"""多角色直播总线 — LiveBus / AgentConnector / SpeechArbiter / StageCue

设计目标：把"奶昔"从单主播升级为"可挂多个 agent 的舞台"，其他人的 agent
只要实现 AgentConnector 契约即可上台，与奶昔同台互动。

核心组件：
- LiveBus      —— 极简 asyncio 发布/订阅总线，解耦各角色与引擎
- AgentConnector —— 角色契约（基类）：收弹幕/收舞台提示 → 产出发言请求
- SpeechArbiter —— 单麦位仲裁：按优先级分层占麦，避免多角色同时抢话
- StageCue     —— 舞台提示镜像 + 回声防护：一句话说完后广播给其他角色，
                  用 source_id 过滤自己、cue_depth 限深、概率衰减防止无限对喷

全部用普通 dict 作事件载荷，与既有管道（danmaku/scene/tts 队列用 dict）一致，
不引入额外抽象，遵循"最简单方案"。
"""

import asyncio
import logging
import random
import time
from typing import Optional

log = logging.getLogger("live_bus")

# ── 总线 topic ──────────────────────────────────────────────────────────────
TOPIC_DANMAKU = "danmaku"                # 原始弹幕（B站或外部注入）
TOPIC_SPEECH_REQUEST = "speech_request"  # 某角色想发言
TOPIC_STAGE_CUE = "stage_cue"            # 舞台上刚说了一句（供其他角色反应）

# ── 占麦优先级 ──────────────────────────────────────────────────────────────
PRIORITY_HOST = 100      # 主咖（奶昔本体）
PRIORITY_GUEST = 50      # 副播/嘉宾 agent
PRIORITY_LOW = 10        # 低优（自动接话、氛围）

# ── 回声防护参数（D4：也回应其他 agent 舞台提示，但要防无限对喷）──────────────
MAX_CUE_DEPTH = 2                    # 舞台提示最大链深：A→B→A 后停止
CUE_DECAY_PROBS = [0.7, 0.4]        # 第 1 跳 70% 概率反应，第 2 跳 40%，之后 0


# ── 按角色分区的记忆（每个 agent 独立命名空间，落 SQLite meta 表）──────────────

def agent_memory_get(agent_id: str, key: str, default: str = "") -> str:
    """读取某角色的分区记忆。键空间: live_mem:{agent_id}:{key}，互不干扰。"""
    try:
        from desktop_core.storage import meta_get
        return meta_get(f"live_mem:{agent_id}:{key}") or default
    except Exception:
        return default


def agent_memory_set(agent_id: str, key: str, value: str):
    """写入某角色的分区记忆。"""
    try:
        from desktop_core.storage import meta_set
        meta_set(f"live_mem:{agent_id}:{key}", value)
    except Exception as e:
        log.warning(f"[角色记忆] 写入失败 {agent_id}/{key}: {e}")


class LiveBus:
    """极简 asyncio 发布/订阅总线：按 topic 把事件分发到各订阅者的独立队列。"""

    def __init__(self):
        self._subs: dict[str, list[asyncio.Queue]] = {}

    def subscribe(self, topic: str) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue()
        self._subs.setdefault(topic, []).append(q)
        return q

    def unsubscribe(self, topic: str, q: asyncio.Queue):
        lst = self._subs.get(topic)
        if lst and q in lst:
            lst.remove(q)

    async def publish(self, topic: str, event: dict):
        for q in list(self._subs.get(topic, [])):
            try:
                q.put_nowait(event)
            except asyncio.QueueFull:
                pass

    def subscriber_count(self, topic: str) -> int:
        return len(self._subs.get(topic, []))


class AgentConnector:
    """角色连接器契约 —— 其他人的 agent 想上台，继承并实现 handle_* 即可。

    生命周期由引擎驱动：引擎把弹幕 / 舞台提示喂给 handle_danmaku / handle_cue，
    连接器判断"这一条要不要接、接什么"，返回发言。返回值可以是：
      - None            —— 不接
      - str             —— 只有文本（情绪默认"开心"、无动作）
      - dict            —— {"text":..., "emotion":..., "action":...}

    每个连接器有独立 agent_id（用于占麦仲裁、回声过滤、记忆分区）。
    """

    def __init__(self, agent_id: str, name: str, priority: int = PRIORITY_GUEST):
        self.agent_id = agent_id
        self.name = name
        self.priority = priority

    async def handle_danmaku(self, danmaku: dict):
        """收到一条弹幕，决定本角色要不要回应。返回 None / str / dict。"""
        return None

    async def handle_cue(self, cue: dict):
        """收到舞台提示（别的角色刚说了话），决定要不要接话。返回 None / str / dict。

        注意：回声防护（是否该反应、链深）由引擎统一在分发前判定，连接器无需自查。
        """
        return None

    async def close(self):
        """连接器停用时清理资源（外部远程连接器可覆盖）。"""
        return None


def normalize_utterance(ret) -> Optional[dict]:
    """把连接器返回值（None/str/dict）规整为 {text, emotion, action} 或 None。"""
    if not ret:
        return None
    if isinstance(ret, str):
        text = ret.strip()
        return {"text": text, "emotion": "开心", "action": ""} if text else None
    if isinstance(ret, dict):
        text = (ret.get("text") or "").strip()
        if not text:
            return None
        return {"text": text, "emotion": ret.get("emotion", "开心"), "action": ret.get("action", "")}
    return None


class SpeechArbiter:
    """单麦位仲裁 —— 全场同一时刻只有一个角色在说话（D2：优先级分层占麦）。

    规则（用户已拍板，AI 判定实现）：
    - 主咖高优发言 → 可打断（INTERRUPT）正在进行的低优发言
    - 同级 / 低级 → 进 FIFO 队列排队（QUEUE），队列超上限丢弃最旧的低优（DROP）
    - 抢到麦位后置 busy，说完释放
    """

    def __init__(self, queue_cap: int = 8):
        self._busy = False
        self._current: Optional[dict] = None          # 当前占麦发言
        self._pending: list[dict] = []                # 排队发言
        self._queue_cap = queue_cap
        self._lock = asyncio.Lock()

    @property
    def busy(self) -> bool:
        return self._busy

    async def submit(self, req: dict) -> Optional[dict]:
        """提交一个发言请求。返回"应立即播出的请求"或 None（进队列 / 被丢弃）。

        req 形如: {agent_id, name, text, priority, source_id, cue_depth, emotion}
        """
        async with self._lock:
            # 麦位空闲 → 直接占麦
            if not self._busy:
                self._busy = True
                self._current = req
                return req

            # 麦位忙：主咖高优可打断更低优的当前发言
            cur_pri = (self._current or {}).get("priority", PRIORITY_LOW)
            if req.get("priority", PRIORITY_LOW) > cur_pri and req.get("priority", 0) >= PRIORITY_HOST:
                log.info(f"[占麦] {req.get('name')} 打断了 {self._current.get('name') if self._current else '?'}")
                self._current = req
                return req  # 立即改播主咖（引擎负责停掉旧音频）

            # 否则排队（FIFO）
            self._pending.append(req)
            if len(self._pending) > self._queue_cap:
                # 溢出：丢弃队列中最旧的低优发言
                self._drop_oldest_low()
            return None

    def _drop_oldest_low(self):
        for i, r in enumerate(self._pending):
            if r.get("priority", PRIORITY_LOW) <= PRIORITY_LOW:
                dropped = self._pending.pop(i)
                log.info(f"[占麦] 队列溢出，丢弃低优发言: {dropped.get('name')}")
                return
        # 没有低优可丢，丢最旧的
        if self._pending:
            self._pending.pop(0)

    async def release(self) -> Optional[dict]:
        """当前发言结束，释放麦位并取出下一个排队发言。"""
        async with self._lock:
            self._current = None
            if self._pending:
                nxt = self._pending.pop(0)
                self._current = nxt
                self._busy = True
                return nxt
            self._busy = False
            return None

    def clear(self):
        self._busy = False
        self._current = None
        self._pending.clear()

    async def evict(self, agent_id: str):
        """某角色下台时清掉它的麦位占用：丢弃其排队请求；若正占用麦位则把麦位
        顺手交给下一个等待者（或置空闲），避免孤儿发言与麦位卡死。

        与 release 的区别：release 是"当前这句说完了"自然让位；evict 是"这个角色
        被强制拔掉"时的紧急清理，二者都保证麦位最终能继续往前走。
        """
        async with self._lock:
            self._pending = [r for r in self._pending if r.get("agent_id") != agent_id]
            if self._current and self._current.get("agent_id") == agent_id:
                self._current = None
                if self._pending:
                    self._current = self._pending.pop(0)
                    self._busy = True
                else:
                    self._busy = False


def should_react_to_cue(cue: dict) -> bool:
    """回声防护：是否要对一条舞台提示做出反应（D4 概率衰减 + 限深）。

    cue.cue_depth == 0 表示这是"原始弹幕引发的首句"，其衍生反应 depth 递增。
    depth 0→1 用 70%，1→2 用 40%，>=2 直接停，防止两个 agent 无限对喷。
    """
    depth = cue.get("cue_depth", 0)
    if depth >= MAX_CUE_DEPTH:
        return False
    prob = CUE_DECAY_PROBS[depth] if depth < len(CUE_DECAY_PROBS) else 0.0
    return random.random() < prob


class ConnectorGuard:
    """连接器治理（D3：远程连接器是不可信输入面）：注册鉴权 + 每连接器速率限制 + 越限隔离。

    - 注册鉴权：远程连接器（带 endpoint）必须配置 token，否则拒绝上台。
    - 速率限制：滑动窗口内发言次数超上限 → 自动 quarantine（挂起），冷却后自动解除。
    - 信任豁免：主咖(naixi)与操作员(人类副播 human)不受限流影响。

    时钟可注入（测试用），逻辑纯同步，离线可验。
    """

    def __init__(self, require_token_for_remote: bool = True,
                 rate_window: float = 10.0, rate_max: int = 20,
                 quarantine_secs: float = 30.0, trusted_ids: tuple = ("naixi",),
                 clock=None):
        self.require_token_for_remote = require_token_for_remote
        self.rate_window = rate_window
        self.rate_max = rate_max
        self.quarantine_secs = quarantine_secs
        self.trusted_ids = set(trusted_ids)
        self._clock = clock or time.monotonic
        self._counts: dict[str, list] = {}
        self._quarantine: dict[str, float] = {}

    def check_register(self, connector: AgentConnector) -> tuple[bool, str]:
        """注册前校验：远程连接器必须带 token（不可信面）。返回 (ok, 原因)。"""
        if self.require_token_for_remote and getattr(connector, "endpoint", ""):
            if not getattr(connector, "token", ""):
                return False, "远程连接器必须配置 token"
        return True, ""

    def allow_emit(self, agent_id: str) -> bool:
        """发言前检查：信任角色直接放行；隔离中拒绝；否则记一次并判断是否越限。"""
        if agent_id in self.trusted_ids:
            return True
        now = self._clock()
        if agent_id in self._quarantine:
            if now < self._quarantine[agent_id]:
                return False
            del self._quarantine[agent_id]  # 冷却结束，解除隔离
        buf = self._counts.setdefault(agent_id, [])
        buf.append(now)
        cutoff = now - self.rate_window
        self._counts[agent_id] = [t for t in buf if t >= cutoff]
        if len(self._counts[agent_id]) > self.rate_max:
            self._quarantine[agent_id] = now + self.quarantine_secs
            log.warning(f"[治理] 连接器 {agent_id} 触发速率上限，已隔离 {self.quarantine_secs}s")
            return False
        return True

    def is_quarantined(self, agent_id: str) -> bool:
        now = self._clock()
        if agent_id in self._quarantine and now < self._quarantine[agent_id]:
            return True
        if agent_id in self._quarantine:
            del self._quarantine[agent_id]
        return False

    def status(self, agent_id: str) -> dict:
        now = self._clock()
        quarantined = agent_id in self._quarantine and now < self._quarantine[agent_id]
        return {"quarantined": quarantined,
                "emits_in_window": len([t for t in self._counts.get(agent_id, []) if t >= now - self.rate_window])}


class NaixiConnector(AgentConnector):
    """内置"奶昔"角色连接器 —— 复用引擎已有的 _decide_reply 决策大脑。

    这是舞台上的主咖（PRIORITY_HOST）。它不新写决策逻辑，直接调用引擎注入的
    decide_fn（即 LiveEngine._decide_reply(text, user) -> (文本, 情绪, 动作)），
    保证行为与原单主播时代完全一致。
    """

    def __init__(self, decide_fn, name: str = "奶昔"):
        super().__init__(agent_id="naixi", name=name, priority=PRIORITY_HOST)
        self._decide_fn = decide_fn

    async def _decide(self, text: str, user: str):
        try:
            reply, emotion, action = await self._decide_fn(text, user)
            if not reply:
                return None
            return {"text": reply, "emotion": emotion, "action": action}
        except Exception as e:
            log.warning(f"[奶昔连接器] 决策失败: {e}")
            return None

    async def handle_danmaku(self, danmaku: dict):
        return await self._decide(danmaku.get("text", ""), danmaku.get("user", ""))

    async def handle_cue(self, cue: dict):
        # 主咖对别的角色的舞台提示也可能接话（是否反应由引擎已判定）
        return await self._decide(cue.get("text", ""), cue.get("name", "同台"))


class HttpAgentConnector(AgentConnector):
    """通用外部 agent 连接器 —— 通过 HTTP 把弹幕/舞台提示发给别人的 agent 取回复。

    这是"暴露接口连接其他人 agent"的落地形态：对方只要提供一个 HTTP 端点，
    收到 {event, text, user, name} 的 JSON，返回 {"text": "...", "emotion": "...",
    "action": "..."}（或纯文本）即可上台。QQ 机器人只是其中一个实例（配好它的
    地址即可），无需与桌面端共享代码或数据库，符合两项目相互独立的约定。
    """

    def __init__(self, agent_id: str, name: str, endpoint: str, *,
                 priority: int = PRIORITY_GUEST, token: str = "", timeout: float = 12.0,
                 max_retries: int = 2):
        super().__init__(agent_id=agent_id, name=name, priority=priority)
        self.endpoint = endpoint
        self.token = token
        self.timeout = timeout
        self.max_retries = max_retries

    async def _ask(self, event: str, text: str, user: str):
        if not self.endpoint or not text:
            return None
        try:
            import aiohttp
        except Exception as e:
            log.warning(f"[外部角色 {self.name}] aiohttp 不可用: {e}")
            return None
        headers = {"Content-Type": "application/json"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        payload = {"event": event, "text": text, "user": user,
                   "agent_id": self.agent_id, "name": self.name}
        timeout = aiohttp.ClientTimeout(total=self.timeout)
        last_err = None
        for attempt in range(self.max_retries + 1):
            try:
                async with aiohttp.ClientSession() as s:
                    async with s.post(self.endpoint, json=payload, headers=headers,
                                      timeout=timeout) as r:
                        if r.status != 200:
                            # 逻辑不可达（agent 拒绝/未就绪）→ 不重试，直接跳过本轮
                            log.warning(f"[外部角色 {self.name}] HTTP {r.status}，跳过本轮")
                            return None
                        try:
                            data = await r.json()
                        except Exception:
                            raw = (await r.text()).strip()
                            return raw or None
                if isinstance(data, dict):
                    return data.get("text") and data or None
                return str(data).strip() or None
            except (aiohttp.ClientError, asyncio.TimeoutError) as e:
                # 瞬时网络故障（断连/超时）→ 有限重试，避免直播中一次抖动丢整轮
                last_err = e
                if attempt < self.max_retries:
                    log.warning(f"[外部角色 {self.name}] 调用瞬时失败，重试 {attempt+1}/{self.max_retries}: {e}")
                    await asyncio.sleep(min(0.5 * (attempt + 1), 2.0))
                    continue
                break
            except Exception as e:
                # 非网络类异常（解析/编码等）→ 不重试
                log.warning(f"[外部角色 {self.name}] 调用失败: {e}")
                return None
        log.warning(f"[外部角色 {self.name}] 重试耗尽，放弃本轮: {last_err}")
        return None

    async def handle_danmaku(self, danmaku: dict):
        return await self._ask("danmaku", danmaku.get("text", ""), danmaku.get("user", ""))

    async def handle_cue(self, cue: dict):
        return await self._ask("cue", cue.get("text", ""), cue.get("name", "同台"))


class HumanConnector(AgentConnector):
    """人类副播连接器 —— 操作员经引擎 inject_human_speech 手动上麦。

    不自动接弹幕/舞台提示（handle_* 恒返 None），只由人工触发发言。优先级默认
    副播级；操作员若想插话打断，可在注册时调高 priority。受信任，不受限流隔离。
    """

    def __init__(self, agent_id: str = "human", name: str = "人类副播",
                 priority: int = PRIORITY_GUEST):
        super().__init__(agent_id=agent_id, name=name, priority=priority)

    async def handle_danmaku(self, danmaku: dict):
        return None

    async def handle_cue(self, cue: dict):
        return None


class WsAgentConnector(AgentConnector):
    """远程 ws 外部 agent 连接器 —— 经 WebSocket 把事件发给别人的 agent 取回复。

    与 HttpAgentConnector 对称（引擎作为客户端连出去），适合需要双向流式/常驻
    连接的远端角色。连接时把 token 放在 Authorization 头做鉴权；远端拒答(ok=false)
    或网络故障按与 HTTP 版一致的重试/跳过策略处理。
    """

    def __init__(self, agent_id: str, name: str, ws_url: str, *,
                 priority: int = PRIORITY_GUEST, token: str = "", timeout: float = 12.0,
                 max_retries: int = 2):
        super().__init__(agent_id=agent_id, name=name, priority=priority)
        self.endpoint = ws_url            # 复用 endpoint 字段供治理层判定"远程"
        self.ws_url = ws_url
        self.token = token
        self.timeout = timeout
        self.max_retries = max_retries

    async def _ask(self, event: str, text: str, user: str):
        if not self.ws_url or not text:
            return None
        try:
            import aiohttp
        except Exception as e:
            log.warning(f"[ws外部角色 {self.name}] aiohttp 不可用: {e}")
            return None
        payload = {"event": event, "text": text, "user": user,
                   "agent_id": self.agent_id, "name": self.name}
        headers = {"Authorization": f"Bearer {self.token}"} if self.token else {}
        timeout = aiohttp.ClientTimeout(total=self.timeout)
        last_err = None
        for attempt in range(self.max_retries + 1):
            try:
                async with aiohttp.ClientSession() as s:
                    ws = await s.ws_connect(self.ws_url, headers=headers, timeout=timeout)
                    try:
                        await ws.send_json(payload)
                        reply = await ws.receive_json()
                    finally:
                        await ws.close()
                if isinstance(reply, dict):
                    if reply.get("ok") is False:
                        return None  # 远端明确拒答（如未就绪），跳过本轮
                    return reply.get("text") and reply or None
                return str(reply).strip() or None
            except (aiohttp.ClientError, asyncio.TimeoutError) as e:
                last_err = e
                if attempt < self.max_retries:
                    log.warning(f"[ws外部角色 {self.name}] 瞬时故障，重试 {attempt+1}/{self.max_retries}: {e}")
                    await asyncio.sleep(min(0.5 * (attempt + 1), 2.0))
                    continue
                break
            except Exception as e:
                log.warning(f"[ws外部角色 {self.name}] 调用失败: {e}")
                return None
        log.warning(f"[ws外部角色 {self.name}] 重试耗尽，放弃本轮: {last_err}")
        return None

    async def handle_danmaku(self, danmaku: dict):
        return await self._ask("danmaku", danmaku.get("text", ""), danmaku.get("user", ""))

    async def handle_cue(self, cue: dict):
        return await self._ask("cue", cue.get("text", ""), cue.get("name", "同台"))


def make_speech_request(connector: AgentConnector, utt: dict, *,
                        source_id: str = "", cue_depth: int = 0) -> dict:
    """构造标准发言请求事件。utt 为 normalize_utterance 的结果。

    source_id 记录"这句话最初由谁触发"，用于回声过滤（不回应自己引发的链）。
    """
    return {
        "agent_id": connector.agent_id,
        "name": connector.name,
        "text": utt["text"],
        "emotion": utt.get("emotion", "开心"),
        "action": utt.get("action", ""),
        "priority": connector.priority,
        "source_id": source_id or connector.agent_id,
        "cue_depth": cue_depth,
        "ts": time.time(),
    }
