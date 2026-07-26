"""虚拟主播引擎 — 完整直播管道
架构：danmaku → scene → tts → avatar → stream (5 Agent asyncio.Queue 串联)
"""

import asyncio, hashlib, hmac, json, logging, os, re, subprocess, sys, tempfile, time
from datetime import datetime
from typing import Optional
import aiohttp
from aiohttp import WSMsgType

from desktop_core.live_bus import (
    LiveBus, SpeechArbiter, AgentConnector, NaixiConnector, HttpAgentConnector,
    WsAgentConnector, WsServerConnector, HumanConnector, ConnectorGuard,
    make_speech_request, normalize_utterance, should_react_to_cue,
    PRIORITY_HOST, PRIORITY_GUEST,
)

DEFAULT_LIVE_PROMPT = """你是奶昔，一个虚拟主播。你正在B站直播，以下是你的设定：

性格：可爱、活泼、有点傲娇。语气自然口语化，像在和朋友聊天。
回复要求：简短（30字以内），偶尔带一点点语气词，不要说教或长篇大论。
互动规则：
- 观众发弹幕→根据内容自然回应
- 有人送礼物→感谢
- 有人进入直播间→简单欢迎
- 被问到敏感/不知道的问题→诚实说不知道，转移话题
- 保持直播氛围轻松愉快

注意：不要说"感谢xxx的弹幕"这种机械的回复，直接回应内容本身。"""

log = logging.getLogger("live_engine")

# ── 常量 ──────────────────────────────────────────────────────────────────

OPEN_LIVE_API = "https://api-live.bilibili.com"
HEARTBEAT_INTERVAL = 20       # B站心跳间隔（秒）
QUEUE_TIMEOUT = 2             # 队列等待超时（秒）
MAX_DANMAKU = 200             # 弹幕缓存上限
STREAM_WIDTH = 1280
STREAM_HEIGHT = 720
STREAM_FPS = 15
PCM_RATE = 44100             # 推流音频采样率（Hz）
PCM_CHANNELS = 1             # 推流音频声道数（单声道）
PCM_CHUNK_MS = 100           # 音频喂帧粒度（毫秒），用于实时节流
DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
AVATARS_DIR = os.path.join(DATA_DIR, "avatars")

AGENT_DEFS = [
    {"id": "danmaku", "name": "弹幕监听",  "desc": "B站开放平台 WebSocket 弹幕接收"},
    {"id": "scene",   "name": "场景决策",  "desc": "LLM 弹幕→互动策略生成"},
    {"id": "tts",     "name": "语音合成",  "desc": "CosyVoice / Edge-TTS 语音生成"},
    {"id": "avatar",  "name": "虚拟角色",  "desc": "Live2D 立绘渲染与口型同步"},
    {"id": "stream",  "name": "推流输出",  "desc": "ffmpeg 音视频合成 RTMP 推流"},
]

# ── 工具函数 ──────────────────────────────────────────────────────────────

def _fmt_size(b):
    return f"{b/1024/1024:.1f}MB" if b >= 1048576 else f"{b/1024:.1f}KB" if b >= 1024 else f"{b}B"

def _fmt_time(ts):
    return datetime.fromtimestamp(ts).strftime("%H:%M:%S")


class LiveEngine:
    """虚拟主播引擎 — 完整 5 Agent 管道"""

    def __init__(self):
        # 状态
        self._running = False
        self._start_time = 0.0
        self._access_key_id = ""
        self._access_key_secret = ""
        self._app_id = ""
        self._room_id = ""
        self._code = ""
        self._rtmp_url = ""
        self._game_id = ""
        self._dashscope_api_key = ""
        self._bili_config_saved = False

        # B站连接
        self._connected = False
        self._ws = None
        self._ws_session = None
        self._ws_task: Optional[asyncio.Task] = None
        self._hb_task: Optional[asyncio.Task] = None

        # Agent 状态: stopped/ready/running/error
        self._agent_status: dict[str, str] = {a["id"]: "stopped" for a in AGENT_DEFS}
        self._agent_tasks: dict[str, asyncio.Task] = {}
        self._agent_errors: list[str] = []

        # Agent 管道队列
        self._danmaku_queue: asyncio.Queue = asyncio.Queue()
        self._scene_queue: asyncio.Queue = asyncio.Queue()
        self._tts_queue: asyncio.Queue = asyncio.Queue()
        self._avatar_queue: asyncio.Queue = asyncio.Queue()

        # 数据
        self._danmaku_cache: list[dict] = []
        self._last_error = ""
        self._ffmpeg_proc = None                       # 单常驻推流 ffmpeg（asyncio 子进程）
        self._stream_running = False                    # 常驻推流循环开关
        self._pcm_queue: asyncio.Queue = asyncio.Queue()  # 待播 PCM 段队列
        self._audio_pump_task: Optional[asyncio.Task] = None  # 实时喂音任务
        self._subtitle_file = ""                        # drawtext 字幕文件（reload=1 防注入）
        self._current_text = ""
        self._current_emotion = "开心"
        self._audio_playlist: list[str] = []
        # VTube Studio 连接
        self._vts_ws: Optional[aiohttp.ClientWebSocketResponse] = None
        self._vts_authenticated: bool = False
        self._vts_host: str = "127.0.0.1"
        self._vts_port: int = 8001
        self._vts_expressions: list = []   # VTS 自省到的表情文件名列表
        self._vts_motions: list = []       # VTS 自省到的动作热键名列表
        self._vts_req_seq: int = 0          # VTS 请求自增序号（requestID）
        self._vts_models: dict = {}         # modelID -> modelName（VTS 已加载模型）
        self._vts_current_model: str = ""   # 当前激活模型 GUID（用于 model_id 未绑定时回退）
        self._model_bindings: dict = {}     # agent_id -> modelID（持久化，重启后恢复绑定）
        # 桌宠 WebSocket（前端 Live2D 窗口）
        self._live2d_ws: Optional[aiohttp.WebSocketResponse] = None
        # 桌宠子进程（PySide6 独立窗口）
        self._pet_proc: Optional[subprocess.Popen] = None
        # 场景历史（全部保留，过长时压缩）
        self._scene_history: list[dict] = []
        self._live_prompt: str = DEFAULT_LIVE_PROMPT
        # 高并发防护
        self._last_process_time: float = 0.0      # 上次处理弹幕时间
        self._process_interval: float = 2.0        # 最小处理间隔（秒）
        self._danmaku_batch: list[dict] = []       # 批量缓冲
        # LLM 聊天配置缓存
        self._chat_cfg: dict = {}
        self._chat_cfg_ts: float = 0
        # 音频设备
        self._audio_out_device: str = ""  # 输出设备名称（VB-Cable 或默认）
        self._audio_in_device: str = ""   # 输入设备名称
        # 桌宠配置（前端 SettingsPet 读写）
        self._model_path: str = ""
        self._render_mode: str = "live2d"
        self._tts_engine: str = "cosyvoice"
        self._sd_available: bool = False
        try:
            import sounddevice
            self._sd_available = True
        except:
            pass

        # 多角色舞台：总线 + 麦位仲裁 + 角色连接器注册表（Lumi_Nox 多角色整合）
        self._bus = LiveBus()
        self._arbiter = SpeechArbiter()
        # 隔离状态持久化到 SQLite meta（按 agent_id 单行），重启/重连的刷屏 agent 仍在隔离期
        self._guard = ConnectorGuard(
            trusted_ids=("naixi", "human"),
            mem_get=self._guard_mem_get, mem_set=self._guard_mem_set,
        )
        self._connectors: dict[str, AgentConnector] = {}
        self._load_model_bindings()
        self._register_builtin_connectors()

    @staticmethod
    def _guard_mem_get(key: str) -> str:
        """治理层隔离状态读取（默认落 SQLite meta；storage 不可用时静默降级为无持久化）。"""
        try:
            from desktop_core import storage
            return storage.meta_get(key, "")
        except Exception:
            return ""

    @staticmethod
    def _guard_mem_set(key: str, value: str):
        """治理层隔离状态写入（默认落 SQLite meta；storage 不可用时静默降级）。"""
        try:
            from desktop_core import storage
            storage.meta_set(key, value)
        except Exception:
            pass

    # ── 多角色连接器 ────────────────────────────────────────────────────────

    def _register_builtin_connectors(self):
        """注册内置角色：奶昔本体（主咖）+ 人类副播（操作员手动上麦的槽位）。"""
        naixi = NaixiConnector(self._decide_reply)
        human = HumanConnector("human", "人类副播")
        self._apply_model_binding(naixi)
        self._apply_model_binding(human)
        self._connectors["naixi"] = naixi
        self._connectors["human"] = human

    # ── 模型绑定持久化（按 VTS 模型 GUID 隔离，重启后恢复）──
    def _load_model_bindings(self):
        """从 SQLite meta 读取角色→模型绑定（live_model_bindings）。"""
        try:
            from desktop_core.storage import meta_get
            raw = meta_get("live_model_bindings", "")
            if raw:
                self._model_bindings = json.loads(raw) or {}
        except Exception:
            self._model_bindings = {}

    def _save_model_bindings(self):
        """把角色→模型绑定落库（live_model_bindings）。"""
        try:
            from desktop_core.storage import meta_set
            meta_set("live_model_bindings", json.dumps(self._model_bindings or {}))
        except Exception:
            pass

    def _apply_model_binding(self, connector: AgentConnector):
        """把持久化绑定应用到连接器（若该 agent_id 已存绑定）。"""
        mid = self._model_bindings.get(connector.agent_id)
        if mid:
            connector.model_id = mid

    def register_connector(self, connector: AgentConnector) -> bool:
        """注册一个外部角色连接器（其他人的 agent 上台）。同名 agent_id 覆盖。

        注册前经治理层校验：远程连接器必须带 token（不可信面），否则拒绝上台。
        """
        if not getattr(connector, "agent_id", ""):
            return False
        ok_reg, reason = self._guard.check_register(connector)
        if not ok_reg:
            log.warning(f"[舞台] 注册被拒 {connector.name}({connector.agent_id}): {reason}")
            return False
        self._apply_model_binding(connector)
        self._connectors[connector.agent_id] = connector
        log.info(f"[舞台] 角色已上台: {connector.name}({connector.agent_id}) 优先级={connector.priority}"
                 f" 模型={connector.model_id or '当前模型'}")
        return True

    async def unregister_connector(self, agent_id: str) -> bool:
        """让一个外部角色下台。内置奶昔不可下台。"""
        if agent_id == "naixi":
            return False
        c = self._connectors.pop(agent_id, None)
        if c:
            try: await c.close()
            except: pass
            # 干净释放该角色占用的麦位：丢弃其排队请求，若正占麦则把麦位顺给下一等待者
            try:
                model_key = getattr(c, "model_id", None) or "__current__"
                await self._arbiter.evict(model_key, agent_id)
            except Exception as e:
                log.warning(f"[舞台] 下台时清理麦位失败: {e}")
            log.info(f"[舞台] 角色已下台: {agent_id}")
            return True
        return False

    def register_http_connector(self, agent_id: str, name: str, endpoint: str,
                                priority: int = PRIORITY_GUEST, token: str = "",
                                model_id: Optional[str] = None) -> bool:
        """便捷注册一个 HTTP 外部角色（QQ 机器人等）。供 API 调用。"""
        if not agent_id or not name or not endpoint:
            return False
        conn = HttpAgentConnector(agent_id, name, endpoint, priority=priority, token=token, model_id=model_id)
        if model_id:
            self._model_bindings[agent_id] = model_id
            self._save_model_bindings()
        return self.register_connector(conn)

    def register_ws_connector(self, agent_id: str, name: str, ws_url: str,
                              priority: int = PRIORITY_GUEST, token: str = "",
                              model_id: Optional[str] = None) -> bool:
        """便捷注册一个远程 ws 外部角色（常驻双向连接的远端 agent）。供 API 调用。"""
        if not agent_id or not name or not ws_url:
            return False
        conn = WsAgentConnector(agent_id, name, ws_url, priority=priority, token=token, model_id=model_id)
        if model_id:
            self._model_bindings[agent_id] = model_id
            self._save_model_bindings()
        return self.register_connector(conn)

    async def inject_human_speech(self, agent_id: str, text: str,
                                  emotion: str = "开心", action: str = "") -> bool:
        """人类副播上麦：把一个人工输入当作某人类连接器角色的发言，直接占麦。

        操作员在副播面板输入后调用。受信任，不受限流隔离。返回是否成功投放。
        """
        connector = self._connectors.get(agent_id)
        if not connector or not isinstance(connector, HumanConnector):
            return False
        text = (text or "").strip()
        if not text:
            return False
        utt = {"text": text, "emotion": emotion, "action": action}
        await self._emit(connector, utt, source_id=agent_id, cue_depth=0)
        return True

    def list_connectors(self) -> list:
        """列出当前在台的角色（供前端/API 展示），含传输方式与治理状态。"""
        out = []
        for c in self._connectors.values():
            item = {"agent_id": c.agent_id, "name": c.name, "priority": c.priority,
                    "builtin": c.agent_id in ("naixi", "human"),
                    "transport": "ws-in" if isinstance(c, WsServerConnector)
                                 else "http" if isinstance(c, HttpAgentConnector)
                                 else "ws" if isinstance(c, WsAgentConnector)
                                 else "local",
                    "model_id": getattr(c, "model_id", None) or "",
                    "human_controlled": getattr(c, "human_controlled", False)}
            if getattr(c, "endpoint", ""):
                item["endpoint"] = c.endpoint
            g = self._guard.status(c.agent_id)
            item["quarantined"] = g["quarantined"]
            item["emits_in_window"] = g["emits_in_window"]
            out.append(item)
        return out

    def list_vts_models(self) -> dict:
        """返回 VTS 已加载模型（modelID->name）与当前模型，供前端绑定下拉。"""
        return {"models": self._vts_models, "current": self._vts_current_model}

    async def bind_connector_model(self, agent_id: str, model_id: Optional[str]) -> bool:
        """把某角色绑定到指定 VTS 模型（model_id 为空串/None 表示用当前模型），持久化。

        真人独占模型：仅记录绑定用于冲突提示，奶昔不会写入该模型。
        """
        connector = self._connectors.get(agent_id)
        if not connector:
            return False
        mid = (model_id or "").strip() or None
        connector.model_id = mid
        if mid:
            self._model_bindings[agent_id] = mid
        else:
            self._model_bindings.pop(agent_id, None)
        self._save_model_bindings()
        log.info(f"[舞台] 角色 {agent_id} 绑定模型: {mid or '（当前模型）'}")
        return True

    async def _enqueue_speak(self, req: dict):
        """把仲裁通过的发言请求投入既有语音管道（_scene_queue），携带角色元数据。"""
        await self._scene_queue.put({
            "type": "speak",
            "text": req.get("text", ""),
            "emotion": req.get("emotion", "开心"),
            "action": req.get("action", ""),
            "agent_id": req.get("agent_id", "naixi"),
            "name": req.get("name", "奶昔"),
            "source_id": req.get("source_id", req.get("agent_id", "naixi")),
            "cue_depth": req.get("cue_depth", 0),
            "model_key": req.get("model_key", "__current__"),
            "human_controlled": req.get("human_controlled", False),
        })

    async def _emit(self, connector: AgentConnector, utt: dict, *, source_id: str = "", cue_depth: int = 0):
        """一个角色产出一句发言 → 占麦仲裁 → 抢到则入语音管道，否则排队/丢弃。

        真人独占模型(human_controlled)：奶昔不合成/不写 VTS，仅把这句当作舞台提示
        广播给其它角色，让其它 agent 能在各自的模型上接话（真人自己在真机/真模型上说话）。
        """
        req = make_speech_request(connector, utt, source_id=source_id, cue_depth=cue_depth)
        if getattr(connector, "human_controlled", False):
            await self._broadcast_human_cue(req)
            return
        model_key = req.get("model_key", "__current__")
        admitted = await self._arbiter.submit(model_key, req)
        if admitted:
            await self._enqueue_speak(admitted)

    async def _broadcast_human_cue(self, req: dict):
        """真人发言：仅广播舞台提示供其它角色接话，不占麦/不合成/不写 VTS。"""
        cue = {
            "name": req.get("name", "人类副播"),
            "text": req.get("text", ""),
            "source_id": req.get("source_id", req.get("agent_id", "human")),
            "agent_id": req.get("agent_id", "human"),
            "cue_depth": req.get("cue_depth", 0) + 1,
        }
        try:
            await self._broadcast_cue(cue)
        except Exception as e:
            log.warning(f"[舞台] 广播真人提示失败: {e}")

    def _match_mention(self, text: str):
        """解析 @路由：弹幕含 @角色名/agent_id 时只投给该角色。返回 (目标连接器, 去掉@后的文本)。"""
        if not text or "@" not in text:
            return None, text
        for connector in self._connectors.values():
            for tag in (connector.name, connector.agent_id):
                if tag and f"@{tag}" in text:
                    cleaned = text.replace(f"@{tag}", "").strip()
                    return connector, cleaned
        return None, text

    async def _dispatch_danmaku(self, danmaku: dict):
        """把一条（或一批）弹幕分发给在台角色。含 @路由 则定向，否则全体判断是否接。"""
        target, cleaned = self._match_mention(danmaku.get("text", ""))
        if target is not None:
            danmaku = {**danmaku, "text": cleaned}
            targets = [target]
        else:
            targets = list(self._connectors.values())
        for connector in targets:
            if not self._guard.allow_emit(connector.agent_id):
                log.warning(f"[舞台] {connector.name} 被限流隔离，跳过本轮弹幕")
                continue
            try:
                utt = normalize_utterance(await connector.handle_danmaku(danmaku))
            except Exception as e:
                log.warning(f"[舞台] {connector.name} 处理弹幕异常: {e}")
                utt = None
            if utt:
                await self._emit(connector, utt, source_id=connector.agent_id, cue_depth=0)

    async def _broadcast_cue(self, cue: dict):
        """一句话说完后，广播舞台提示给"其他"角色（D4 回声防护：过滤自己+限深+概率衰减）。"""
        if not should_react_to_cue(cue):
            return
        for connector in list(self._connectors.values()):
            if connector.agent_id == cue.get("source_id"):
                continue  # 不回应自己引发的链
            if not self._guard.allow_emit(connector.agent_id):
                continue  # 限流隔离中，本轮不接话
            try:
                utt = normalize_utterance(await connector.handle_cue(cue))
            except Exception as e:
                log.warning(f"[舞台] {connector.name} 处理舞台提示异常: {e}")
                utt = None
            if utt:
                # 反应句继承 source_id（仍算同一条链），链深 +1
                await self._emit(connector, utt, source_id=cue.get("source_id", ""), cue_depth=cue.get("cue_depth", 1))

    async def _after_speak(self, action: dict, spoken: bool):
        """一句发言处理完：广播舞台提示给其他角色，并释放麦位、放行下一句。"""
        # 只有真正说出口的话才广播为舞台提示（合成失败的不算"说过"）
        if spoken:
            cue = {
                "name": action.get("name", "奶昔"),
                "text": action.get("text", ""),
                "source_id": action.get("source_id", action.get("agent_id", "naixi")),
                "agent_id": action.get("agent_id", "naixi"),
                "cue_depth": action.get("cue_depth", 0) + 1,
            }
            try:
                await self._broadcast_cue(cue)
            except Exception as e:
                log.warning(f"[舞台] 广播舞台提示失败: {e}")
        # 释放麦位，取出下一句排队发言（按模型各自独立）
        try:
            model_key = action.get("model_key", "__current__")
            nxt = await self._arbiter.release(model_key)
            if nxt:
                await self._enqueue_speak(nxt)
        except Exception as e:
            log.warning(f"[舞台] 释放麦位失败: {e}")

    # ── 状态快照 ──────────────────────────────────────────────────────────

    @property
    def status(self) -> dict:
        elapsed = time.time() - self._start_time if self._start_time else 0
        danmaku_rate = round(len(self._danmaku_cache) / max(elapsed, 1), 1) if elapsed > 0 else 0
        return {
            "running": self._running,
            "connected": self._connected,
            "streaming": self._ffmpeg_proc is not None and self._ffmpeg_proc.returncode is None,
            "room_id": self._room_id,
            "game_id": self._game_id,
            "agents": {a["id"]: {"name": a["name"], "desc": a["desc"],
                       "status": self._agent_status.get(a["id"], "stopped")} for a in AGENT_DEFS},
            "danmaku_count": len(self._danmaku_cache),
            "danmaku_rate": danmaku_rate,
            "uptime": round(elapsed),
            "start_time": self._start_time,
            "last_error": self._last_error,
            "vts_connected": self._vts_ws is not None and not self._vts_ws.closed,
            "vts_models": self._vts_models,
            "vts_current_model": self._vts_current_model,
            "pet_running": self._pet_proc is not None and self._pet_proc.poll() is None,
            "errors": self._agent_errors[-10:],
        }

    @property
    def danmaku_list(self) -> list[dict]:
        return list(self._danmaku_cache)

    # ── 配置持久化 ────────────────────────────────────────────────────────

    def _load_config(self):
        """从 SQLite 加载直播配置"""
        try:
            from desktop_core.storage import meta_get
            raw = meta_get("live_config")
            if raw:
                cfg = json.loads(raw)
                self._access_key_id = cfg.get("access_key_id", "")
                self._access_key_secret = cfg.get("access_key_secret", "")
                self._app_id = cfg.get("app_id", "")
                self._code = cfg.get("code", "")
                self._room_id = cfg.get("room_id", "")
                self._rtmp_url = cfg.get("rtmp_url", "")
                self._dashscope_api_key = cfg.get("dashscope_api_key", "")
                self._live_prompt = cfg.get("live_prompt") or DEFAULT_LIVE_PROMPT
                self._audio_out_device = cfg.get("audio_out_device", "")
                self._audio_in_device = cfg.get("audio_in_device", "")
                self._model_path = cfg.get("model_path", "")
                self._render_mode = cfg.get("render_mode", "live2d")
                self._tts_engine = cfg.get("tts_engine", "cosyvoice")
                self._bili_config_saved = bool(self._access_key_id and self._access_key_secret)
        except: pass

    def save_config(self, **kwargs) -> bool:
        """保存直播配置到 SQLite（自动合并旧配置，防止部分更新覆盖）"""
        try:
            # 先从 DB 加载已有配置作为基础
            base = {}
            try:
                from desktop_core.storage import meta_get
                raw = meta_get("live_config")
                if raw:
                    base = json.loads(raw)
            except:
                pass

            # 防止前端把遮罩后的密钥传回来覆盖真实密钥
            def _real(v, cur):
                if v is None or (isinstance(v, str) and "****" in v):
                    return cur
                return v

            cfg = {
                "access_key_id": _real(kwargs.get("access_key_id"), base.get("access_key_id", self._access_key_id)),
                "access_key_secret": _real(kwargs.get("access_key_secret"), base.get("access_key_secret", self._access_key_secret)),
                "app_id": (kwargs.get("app_id") if (kwargs.get("app_id") and str(kwargs.get("app_id")).isdigit() and "****" not in str(kwargs.get("app_id"))) else base.get("app_id", self._app_id)),
                "room_id": kwargs.get("room_id", base.get("room_id", self._room_id)),
                "code": _real(kwargs.get("code"), base.get("code", self._code)),
                "rtmp_url": kwargs.get("rtmp_url", base.get("rtmp_url", self._rtmp_url)),
                "dashscope_api_key": _real(kwargs.get("dashscope_api_key"), base.get("dashscope_api_key", self._dashscope_api_key)),
                "live_prompt": kwargs.get("live_prompt", base.get("live_prompt", self._live_prompt)),
                "audio_out_device": kwargs.get("audio_out_device", base.get("audio_out_device", self._audio_out_device)),
                "audio_in_device": kwargs.get("audio_in_device", base.get("audio_in_device", self._audio_in_device)),
                "model_path": kwargs.get("model_path", base.get("model_path", self._model_path)),
                "render_mode": kwargs.get("render_mode", base.get("render_mode", self._render_mode)),
                "tts_engine": kwargs.get("tts_engine", base.get("tts_engine", self._tts_engine)),
            }
            from desktop_core.storage import meta_set
            meta_set("live_config", json.dumps(cfg))
            self._access_key_id = cfg["access_key_id"]
            self._access_key_secret = cfg["access_key_secret"]
            self._app_id = cfg["app_id"]
            self._room_id = cfg["room_id"]
            self._rtmp_url = cfg["rtmp_url"]
            self._dashscope_api_key = cfg["dashscope_api_key"]
            self._live_prompt = cfg["live_prompt"]
            self._audio_out_device = cfg.get("audio_out_device", "")
            self._audio_in_device = cfg.get("audio_in_device", "")
            self._model_path = cfg["model_path"]
            self._render_mode = cfg["render_mode"]
            self._tts_engine = cfg["tts_engine"]
            self._bili_config_saved = bool(self._access_key_id and self._access_key_secret)
            log.info("[直播] 配置已保存")
            return True
        except Exception as e:
            self._last_error = f"配置保存失败: {e}"
            return False

    # ═══════════════════════════════════════════════════════════════════════
    # 生命周期
    # ═══════════════════════════════════════════════════════════════════════

    def dict(self, **kwargs) -> bool:
        ...

    async def _close_old_session(self):
        """关闭上次残留的 B站 session（从数据库读取 game_id）"""
        try:
            from desktop_core.storage import meta_get
            old_id = meta_get("live_game_id")
            if not old_id or not self._access_key_id or not self._access_key_secret:
                return
            import aiohttp
            from uuid import uuid4
            end_body = json.dumps({"game_id": old_id, "app_id": int(self._app_id)}, separators=(",", ":"))
            md5 = self._bili_md5(end_body)
            ts, nonce = str(int(time.time())), uuid4().hex[:16]
            hdrs = {"Content-Type":"application/json","Accept":"application/json",
                "X-Bili-Timestamp":ts,"X-Bili-Signature-Method":"HMAC-SHA256",
                "X-Bili-Signature-Nonce":nonce,"X-Bili-Signature-Version":"1.0","X-Bili-AccessKeyId":self._access_key_id,
                "X-Bili-Content-MD5":md5}
            hdrs["Authorization"] = self._bili_sign(self._access_key_secret, hdrs, md5)
            async with aiohttp.ClientSession() as session:
                async with session.post("https://live-open.biliapi.com/v2/app/end", data=end_body, headers=hdrs, timeout=5) as r:
                    if r.status == 200:
                        log.info(f"[直播] 已关闭旧 session: {old_id[:16]}...")
            from desktop_core.storage import meta_set
            meta_set("live_game_id", "")
        except:
            pass

    async def start(self) -> bool:
        """启动直播引擎 — 配置加载 + Agent 启动 + 自动连接"""
        self._load_config()
        # 检查 B站 配置
        if not self._bili_config_saved:
            self._last_error = "B站 开放平台配置不完整（需 App ID + Token）"
            return False

        self._running = True
        self._start_time = time.time()
        self._last_error = ""
        self._agent_errors.clear()

        # 启动所有 Agent
        await self._start_agent("danmaku", self._agent_danmaku)
        await self._start_agent("scene", self._agent_scene)
        await self._start_agent("tts", self._agent_tts)
        await self._start_agent("avatar", self._agent_avatar)
        await self._start_agent("stream", self._agent_stream)

        # 尝试连接 VTube Studio（非阻塞，失败不影响直播）
        asyncio.create_task(self._vts_connect())

        # 先关闭上次残留的 session（防止"同一房间启动数量超过配置上限"）
        await self._close_old_session()

        # 自动连接 B站（失败则等 5 秒重试一次）
        for attempt in range(2):
            ok = await self.connect_bilibili()
            if ok:
                break
            if attempt == 0:
                log.info("[直播] 首次连接失败，等 5 秒重试...")
                await asyncio.sleep(5)
        if not ok:
            log.warning(f"[直播] B站 连接失败: {self._last_error}")

        log.info("[直播] 引擎已启动")
        return True

    async def stop(self):
        """停止所有 Agent 和连接，保存统计数据"""
        self._running = False
        await self.disconnect_bilibili()
        await self._vts_disconnect()
        self._stop_pet()
        await self._stop_ffmpeg()
        # 清空占麦仲裁状态，避免上一场残留 busy 卡住下一场
        try: self._arbiter.clear()
        except: pass
        for aid in list(self._agent_tasks.keys()):
            t = self._agent_tasks.pop(aid, None)
            if t and not t.done():
                t.cancel()
                try: await t
                except: pass
            self._agent_status[aid] = "stopped"
        # 保存统计数据
        if self._start_time:
            self._save_stats()
        self._start_time = 0
        log.info("[直播] 引擎已停止")

    def _save_stats(self):
        """保存本次直播统计数据到 SQLite"""
        elapsed = time.time() - self._start_time
        try:
            from desktop_core.storage import meta_set
            stats = {
                "uptime": round(elapsed),
                "danmaku": len(self._danmaku_cache),
                "errors": len(self._agent_errors),
                "last_run": time.strftime("%Y-%m-%d %H:%M:%S"),
                "room_id": self._room_id,
            }
            from desktop_core.storage import meta_get
            old = meta_get("live_stats")
            if old:
                try:
                    all_stats = json.loads(old)
                except: all_stats = []
            else:
                all_stats = []
            all_stats.append(stats)
            all_stats = all_stats[-30:]  # 保留最近 30 条
            meta_set("live_stats", json.dumps(all_stats))
            log.info(f"[直播] 统计数据已保存: {elapsed:.0f}s, {len(self._danmaku_cache)} 条弹幕")
        except Exception as e:
            log.warning(f"[直播] 统计保存失败: {e}")

    async def _start_agent(self, agent_id: str, coro_func):
        """启动一个 Agent 协程"""
        if agent_id in self._agent_tasks and not self._agent_tasks[agent_id].done():
            self._agent_tasks[agent_id].cancel()
        self._agent_status[agent_id] = "ready"
        task = asyncio.create_task(self._agent_wrapper(agent_id, coro_func()))
        self._agent_tasks[agent_id] = task

    async def _agent_wrapper(self, agent_id: str, coro):
        """Agent 包装器：捕获异常、自愈重启"""
        self._agent_status[agent_id] = "running"
        retries = 0
        while self._running and retries < 3:
            try:
                await coro
                break  # 正常退出
            except asyncio.CancelledError:
                break
            except Exception as e:
                retries += 1
                err = f"[{agent_id}] 异常(第{retries}次): {e}"
                self._agent_errors.append(err)
                self._last_error = err
                log.warning(f"[直播] {err}")
                if retries < 3:
                    await asyncio.sleep(retries * 3)
                    self._agent_status[agent_id] = "running"
                    # 重新创建协程
                    coro = self._restart_agent(agent_id)
                else:
                    self._agent_status[agent_id] = "error"
        if self._running and self._agent_status.get(agent_id) != "error":
            self._agent_status[agent_id] = "stopped"

    def _restart_agent(self, agent_id: str):
        """根据 agent_id 返回新的协程"""
        m = {"danmaku": self._agent_danmaku, "scene": self._agent_scene,
             "tts": self._agent_tts, "avatar": self._agent_avatar, "stream": self._agent_stream}
        return m.get(agent_id, self._agent_danmaku)()

    # ═══════════════════════════════════════════════════════════════════════
    # B站 Open Live API v2 连接（参考：github.com/VTB-LINK/bianka）
    # ═══════════════════════════════════════════════════════════════════════

    @staticmethod
    def _bili_md5(s: str) -> str:
        return hashlib.md5(s.encode()).hexdigest()

    @staticmethod
    def _bili_sign(secret: str, headers: dict, body_md5: str) -> str:
        """B站 Open Live API v2 签名
        X-Bili-* header 按小写 key 排序后 key:value\n 格式，HMAC-SHA256
        """
        # 构建小写 headers 映射
        lower_headers = {k.lower(): v for k, v in headers.items() if k.lower().startswith("x-bili-")}
        keys = sorted(lower_headers.keys())
        raw = "\n".join(f"{k}:{lower_headers[k]}" for k in keys)
        return hmac.new(secret.encode(), raw.encode(), hashlib.sha256).hexdigest()

    async def connect_bilibili(self) -> bool:
        """连接 B站 弹幕 WebSocket — Open Live API v2"""
        if self._connected:
            return True
        if not all([self._access_key_id, self._access_key_secret, self._app_id, self._code]):
            self._last_error = "B站 配置不完整（需 App ID + AccessKey ID + Secret + 主播身份码）"
            return False

        # 先关掉之前可能残留的 session
        await self._close_old_session()
        # 取消上一轮残留的心跳/读取任务，避免重连时任务泄漏（旧实现直接覆盖 task 引用）
        await self._cancel_bili_tasks()

        try:
            import aiohttp
            from uuid import uuid4

            api_host = "https://live-open.biliapi.com"
            body = json.dumps({"code": self._code, "app_id": int(self._app_id)}, separators=(",", ":"))
            body_md5 = self._bili_md5(body)
            ts = str(int(time.time()))
            nonce = uuid4().hex[:16]
            headers = {
                "Content-Type": "application/json",
                "Accept": "application/json",
                "X-Bili-Timestamp": ts,
                "X-Bili-Signature-Method": "HMAC-SHA256",
                "X-Bili-Signature-Nonce": nonce,
                "X-Bili-Signature-Version": "1.0",
                "X-Bili-AccessKeyId": self._access_key_id,
                "X-Bili-Content-MD5": body_md5,
            }
            headers["Authorization"] = self._bili_sign(self._access_key_secret, headers, body_md5)

            async with aiohttp.ClientSession() as session:
                async with session.post(f"{api_host}/v2/app/start", data=body, headers=headers, timeout=10) as r:
                    if r.status != 200:
                        txt = await r.text()
                        log.warning(f"[直播] B站 API {r.status}: {txt[:300]}")
                        self._last_error = f"B站 API {r.status}: {txt[:200]}"
                        return False
                    resp = await r.json()
                if resp.get("code") != 0:
                    msg = resp.get('message', '')
                    log.warning(f"[直播] B站 返回错误: code={resp.get('code')} msg={msg}")
                    self._last_error = f"B站 start 失败: {msg}"
                    # 如果 B站 说"超过配置上限"，等5秒清理旧 session 重试一次
                    if "超过配置上限" in msg:
                        log.info("[直播] 等待 5 秒后重试...")
                        await asyncio.sleep(5)
                        await self._close_old_session()
                        return False  # 让调用方可以检查 last_error 后重试
                    return False
                info = resp["data"]
                self._game_id = info["game_info"]["game_id"]
                # 保存 game_id 到数据库，下次启动时先关旧 session
                try:
                    from desktop_core.storage import meta_set
                    meta_set("live_game_id", self._game_id)
                except: pass
                auth_body_str = info["websocket_info"]["auth_body"]
                wss_links = info["websocket_info"]["wss_link"]

            # 心跳
            self._hb_task = asyncio.create_task(self._heartbeat_loop())

            # 连接 WS（B站二进制协议包: op=7认证, ver=0原始数据）
            auth_body = json.loads(auth_body_str) if isinstance(auth_body_str, str) else auth_body_str
            auth_str = json.dumps(auth_body, separators=(",", ":"))
            ws_session = aiohttp.ClientSession()
            try:
                wss_url = wss_links[0]
                ws = await ws_session.ws_connect(wss_url, heartbeat=30)
                self._ws = ws
                # 发送认证协议包（二进制, op=7, ver=0）
                await ws.send_bytes(self._build_ws_packet(7, auth_str.encode(), 0))
                self._connected = True
                self._ws_session = ws_session
                log.info(f"[直播] 已连接到 B站 直播间")
                self._ws_task = asyncio.create_task(self._ws_read_loop(ws))
            except:
                await ws_session.close()
                raise
            self._connected = True
            return True
        except Exception as e:
            self._last_error = f"B站连接失败: {e}"
            log.warning(f"[直播] {self._last_error}")
            return False

    async def _on_bili_json(self, raw: str):
        """处理 B站 WS JSON 消息（兼容新旧协议）"""
        try:
            data = json.loads(raw)
            cmd = data.get("cmd", "")
            is_v2 = cmd.startswith("LIVE_OPEN_PLATFORM_")

            if cmd in ("DANMU_MSG", "LIVE_OPEN_PLATFORM_DM"):
                if is_v2:
                    d = data.get("data", {})
                    txt, uid, uname = d.get("msg", ""), d.get("uid", 0), d.get("uname", "")
                else:
                    info = data["info"]
                    txt, uid, uname = info[1], info[2][0], info[2][1]
                self._cache_danmaku(uname, txt)
                await self._danmaku_queue.put({"type": "danmaku", "uid": uid, "user": uname, "text": txt, "time": time.time()})

            elif cmd in ("SEND_GIFT", "LIVE_OPEN_PLATFORM_SEND_GIFT"):
                d = data.get("data", data)
                uname = d.get("uname", "") or (data.get("data", {}) if is_v2 else {}).get("uname", "")
                gift = d.get("gift_name", "") or d.get("giftName", "")
                num = d.get("num", 1) or d.get("gift_num", 1)
                action = d.get("action", "赠送")
                if uname:
                    txt = f"{uname}{action}{gift}x{num}"
                    self._cache_danmaku(uname, f"[礼物]{gift}x{num}")
                    await self._danmaku_queue.put({"type": "gift", "user": uname, "text": txt, "gift": gift, "num": num, "time": time.time()})

            elif cmd in ("LIVE_OPEN_PLATFORM_GUARD", "GUARD_BUY"):
                d = data.get("data", data)
                uname = d.get("uname", "") or data.get("data", {}).get("uname", "")
                guard = d.get("guard_level", "") or d.get("gift_name", "")
                if uname:
                    txt = f"感谢{uname}上舰！"
                    await self._danmaku_queue.put({"type": "guard", "user": uname, "text": txt, "time": time.time()})

            elif cmd in ("INTERACT_WORD", "LIVE_OPEN_PLATFORM_LIVE_ROOM_ENTER"):
                d = data.get("data", data)
                uname = d.get("uname", "") or data.get("data", {}).get("uname", "")
                if uname:
                    await self._danmaku_queue.put({"type": "enter", "user": uname, "text": f"{uname}进入直播间", "time": time.time()})

            elif cmd in ("LIKE", "LIVE_OPEN_PLATFORM_LIKE"):
                d = data.get("data", data)
                uname = d.get("uname", "") or data.get("data", {}).get("uname", "")
                if uname:
                    await self._danmaku_queue.put({"type": "like", "user": uname, "text": f"{uname}点了赞", "time": time.time()})

            # 新增事件处理
            elif cmd in ("LIVE_OPEN_PLATFORM_SUPER_CHAT", "SUPER_CHAT"):
                # 醒目留言/SC
                d = data.get("data", data)
                uname = d.get("uname", "") or d.get("user", {}).get("uname", "")
                msg = d.get("message", "") or d.get("msg", "")
                rmb = d.get("rmb", 0) or d.get("price", 0)
                if uname:
                    txt = f"SC({rmb}元) {uname}: {msg}"
                    self._cache_danmaku(uname, f"[SC]{msg}")
                    await self._danmaku_queue.put({"type": "super_chat", "user": uname, "text": txt, "rmb": rmb, "time": time.time()})

            elif cmd == "LIVE_OPEN_PLATFORM_SUPER_CHAT_DEL":
                # SC 被删除
                log.info(f"[直播] SC 被删除: {data.get('data', {}).get('messageIds', '')}")

            elif cmd in ("LIVE_OPEN_PLATFORM_LIVE",):
                # 开播通知
                d = data.get("data", {})
                log.info(f"[直播] 直播已开始: room={d.get('roomId','')} title={d.get('title','')}")

            elif cmd in ("LIVE_OPEN_PLATFORM_LIVE_OFF",):
                # 下播通知
                d = data.get("data", {})
                log.info(f"[直播] 直播已结束: room={d.get('roomId','')}")

            elif cmd in ("LIVE_OPEN_PLATFORM_GAME_START",):
                # 场次开始
                d = data.get("data", {})
                log.info(f"[直播] 场次开始: game={d.get('gameId','')}")

            elif cmd in ("LIVE_OPEN_PLATFORM_GAME_END", "LIVE_OPEN_PLATFORM_INTERACTION_END"):
                # 场次结束 / 交互结束
                log.info(f"[直播] 场次/交互结束")

        except Exception as e:
            log.warning(f"[直播] 消息解析异常: {e}")

    async def _on_bili_binary(self, raw: bytes):
        """处理 B站 WS 二进制包"""
        try:
            if len(raw) < 16:
                return
            import struct, zlib
            
            # 可能一个 frame 包含多个包，循环解析
            offset = 0
            while offset + 16 <= len(raw):
                total_len = struct.unpack(">I", raw[offset:offset+4])[0]
                header_len = struct.unpack(">H", raw[offset+4:offset+6])[0]
                ver = struct.unpack(">H", raw[offset+6:offset+8])[0]
                op = struct.unpack(">I", raw[offset+8:offset+12])[0]
                
                if total_len < header_len or total_len > len(raw) - offset:
                    break
                
                body = raw[offset+header_len:offset+total_len]
                
                # 对 op=5（消息数据）或 op=8（认证回复）处理
                if op in (5, 8):
                    # 尝试解压
                    try:
                        body = zlib.decompress(body)
                    except:
                        pass
                    
                    text = body.decode("utf-8", errors="replace")
                    for line in text.split("\0"):
                        line = line.strip()
                        if line:
                            await self._on_bili_json(line)
                
                offset += total_len
        except:
            pass

    @staticmethod
    def _build_ws_packet(op: int, body: bytes, ver: int = 0) -> bytes:
        """构建 B站 WS 二进制协议包（官方文档: 大端对齐）
        ver=0 原始数据, ver=2 zlib压缩"""
        import struct
        header_len = 16
        total_len = header_len + len(body)
        return struct.pack(">IHHII", total_len, header_len, ver, op, 1) + body

    async def _ws_read_loop(self, ws):
        """WS 消息读取循环（后台任务），断开后自动重连"""
        try:
            async for msg in ws:
                if msg.type == WSMsgType.TEXT:
                    log.info(f"[直播] WS TEXT: {msg.data[:200]}")
                    await self._on_bili_json(msg.data)
                elif msg.type == WSMsgType.BINARY:
                    log.info(f"[直播] WS BINARY: {len(msg.data)}B")
                    await self._on_bili_binary(msg.data)
                elif msg.type == WSMsgType.CLOSED:
                    break
        except Exception as e:
            log.warning(f"[直播] WS 读取异常: {e}")
        finally:
            self._connected = False
            log.info("[直播] WS 连接已断开")
            # 自动重连（引擎仍在运行）
            if self._running:
                log.info("[直播] 尝试自动重连...")
                asyncio.create_task(self._auto_reconnect())

    async def _auto_reconnect(self):
        """自动重连 B站，最多 3 次"""
        for i in range(3):
            await asyncio.sleep(5 * (i + 1))
            if not self._running or self._connected:
                return
            log.info(f"[直播] 重连第 {i+1} 次...")
            self._load_config()
            ok = await self.connect_bilibili()
            if ok:
                log.info("[直播] 重连成功")
                return
        log.warning("[直播] 自动重连失败")

    async def _cancel_bili_tasks(self):
        """取消 B站 心跳/读取后台任务（重连与断开共用，避免 task 泄漏）。"""
        if self._ws_task and not self._ws_task.done():
            self._ws_task.cancel()
            try: await self._ws_task
            except: pass
        self._ws_task = None
        if self._hb_task and not self._hb_task.done():
            self._hb_task.cancel()
            try: await self._hb_task
            except: pass
        self._hb_task = None

    async def disconnect_bilibili(self):
        """断开 B站 连接"""
        self._connected = False
        await self._cancel_bili_tasks()
        if self._ws:
            try: await self._ws.close()
            except: pass
            self._ws = None
        if self._ws_session:
            try: await self._ws_session.close()
            except: pass
            self._ws_session = None
        # 调用 /v2/app/end 关闭场次
        if self._game_id and self._app_id:
            try:
                import aiohttp
                from uuid import uuid4
                end_body = json.dumps({"game_id": self._game_id, "app_id": int(self._app_id)}, separators=(",", ":"))
                md5 = self._bili_md5(end_body)
                ts, nonce = str(int(time.time())), uuid4().hex[:16]
                hdrs = {"Content-Type":"application/json","Accept":"application/json",
                    "X-Bili-Timestamp":ts,"X-Bili-Signature-Method":"HMAC-SHA256",
                    "X-Bili-Signature-Nonce":nonce,"X-Bili-Signature-Version":"1.0","X-Bili-AccessKeyId":self._access_key_id,
                    "X-Bili-Content-MD5":md5}
                hdrs["Authorization"] = self._bili_sign(self._access_key_secret, hdrs, md5)
                async with aiohttp.ClientSession() as session:
                    await session.post("https://live-open.biliapi.com/v2/app/end", data=end_body, headers=hdrs, timeout=5)
            except: pass
        self._game_id = ""
        # 清理数据库中的 game_id
        try:
            from desktop_core.storage import meta_set
            meta_set("live_game_id", "")
        except: pass
        log.info("[直播] 已断开 B站 连接")

    async def _heartbeat_loop(self):
        """B站 心跳：HTTP 项目心跳(20s) + WS 协议心跳(30s)"""
        ws_hb_count = 0
        while self._running and self._game_id:
            await asyncio.sleep(20)

            # WS 协议心跳（op=2，每 30s 一次，但配合 20s 周期每 2 次发一次）
            ws_hb_count += 1
            if ws_hb_count % 2 == 1 and self._ws and not self._ws.closed:
                try:
                    await self._ws.send_bytes(self._build_ws_packet(2, b"", 0))
                except:
                    pass

            # HTTP 项目心跳（保持 game 存活）
            try:
                import aiohttp
                from uuid import uuid4
                hb = json.dumps({"game_id": self._game_id}, separators=(",", ":"))
                md5 = self._bili_md5(hb)
                ts, nonce = str(int(time.time())), uuid4().hex[:16]
                hdrs = {"Content-Type":"application/json","Accept":"application/json",
                    "X-Bili-Timestamp":ts,"X-Bili-Signature-Method":"HMAC-SHA256",
                    "X-Bili-Signature-Nonce":nonce,"X-Bili-Signature-Version":"1.0","X-Bili-AccessKeyId":self._access_key_id,
                    "X-Bili-Content-MD5":md5}
                hdrs["Authorization"] = self._bili_sign(self._access_key_secret, hdrs, md5)
                async with aiohttp.ClientSession() as session:
                    async with session.post("https://live-open.biliapi.com/v2/app/heartbeat", data=hb, headers=hdrs, timeout=5) as r:
                        if r.status != 200:
                            log.warning(f"[直播] 心跳失败: {r.status}")
            except Exception as e:
                log.warning(f"[直播] 心跳异常: {e}")

    def _cache_danmaku(self, user: str, text: str):
        self._danmaku_cache.append({"user": user, "text": text[:200], "time": time.time(), "time_str": _fmt_time(time.time())})
        if len(self._danmaku_cache) > MAX_DANMAKU:
            self._danmaku_cache = self._danmaku_cache[-MAX_DANMAKU:]

    # ── LLM 直播互动 ──────────────────────────────────────────────────────

    def _resolve_chat_config(self) -> dict:
        """获取聊天LLM配置（对话页的 chat 供应商）"""
        now = time.time()
        if self._chat_cfg and now - self._chat_cfg_ts < 60:
            return self._chat_cfg
        cfg = {"api_key": "", "api_url": "", "model": ""}
        try:
            from desktop_core.storage import meta_get, decrypt_config
            raw = meta_get("desktop_config")
            if raw:
                dc = json.loads(raw)
                decrypt_config(dc)
                for pid, pcfg in dc.get("api_providers", {}).items():
                    if pcfg.get("type", "chat") in ("chat", "default"):
                        cfg = {"api_key": pcfg.get("api_key", ""), "api_url": pcfg.get("api_url", ""), "model": pcfg.get("model", "")}
                        break
        except:
            pass
        self._chat_cfg = cfg
        self._chat_cfg_ts = now
        return cfg

    async def _call_llm(self, prompt: str) -> Optional[str]:
        """调用配置的聊天 LLM，返回回复文本"""
        cfg = self._resolve_chat_config()
        if not cfg["api_key"] or not cfg["api_url"]:
            return None
        try:
            from aiohttp import ClientSession
            import json as _json
            is_dashscope = "dashscope" in cfg["api_url"] or ("aliyuncs" in cfg["api_url"] and "compatible-mode" not in cfg["api_url"])
            messages = [{"role": "system", "content": self._live_prompt}]
            # 构造上下文：全部历史，超长时压缩
            ctx = list(self._scene_history)
            total_chars = sum(len(h.get("content","")) for h in ctx)
            if total_chars > 4000:
                # 压缩旧消息：保留最近 20 条，前面的合并为一段摘要
                recent = ctx[-20:]
                old = ctx[:-20]
                summary = "前面聊了: " + " | ".join(
                    h["content"].replace("的弹幕","").strip()[:60]
                    for h in old[-10:] if h["role"] == "user"
                )
                if len(summary) > 500:
                    summary = summary[:500] + "..."
                ctx = [{"role": "system", "content": f"[历史摘要] {summary}"}] + recent
            for h in ctx:
                messages.append({"role": h["role"], "content": h["content"]})
            messages.append({"role": "user", "content": prompt})

            if is_dashscope:
                url = cfg["api_url"].rstrip("chat/completions").rstrip("/") + "/chat/completions"
            else:
                url = cfg["api_url"].rstrip("/") + ("/chat/completions" if "/chat/completions" not in cfg["api_url"] else "")
            headers = {"Authorization": f"Bearer {cfg['api_key']}", "Content-Type": "application/json"}
            payload = {"model": cfg["model"] or "qwen-plus", "messages": messages,
                       "max_tokens": 100, "temperature": 0.8}

            async with ClientSession() as s:
                async with s.post(url, json=payload, headers=headers, timeout=10) as r:
                    if r.status != 200:
                        return None
                    data = await r.json()
                    reply = data.get("choices", [{}])[0].get("message", {}).get("content", "")
                    if reply:
                        # 记录到上下文（不限量，_call_llm 内部会压缩）
                        self._scene_history.append({"role": "user", "content": prompt})
                        self._scene_history.append({"role": "assistant", "content": reply})
                        return reply.strip()
        except:
            pass
        return None

    # 动作标签 → Live2D motion 映射（通用）
    _ACTION_MOTION_MAP = {
        "wave": ("TapBody", 0), "bye": ("TapBody", 0),
        "nod": ("TapHead", 0), "think": ("TapHead", 0),
        "surprise": ("TapBody", 0), "shake": ("TapHead", 0),
        "kime": ("TapBody", 0), "sing": ("TapBody", 0),
        "angry": ("TapBody", 0), "cry": ("TapBody", 0),
        "smile": ("TapBody", 0), "sad": ("TapBody", 0),
    }
    _ACTION_NAMES = list(_ACTION_MOTION_MAP.keys())

    async def _decide_reply(self, text: str, user: str) -> tuple:
        """弹幕回复：LLM → 规则降级。返回 (回复文本, 情绪, 动作标签)"""
        llm_reply = await self._call_llm(
            f"[弹幕] {user}: {text[:100]}\n"
            "请用以下格式回复:\n"
            "[情绪] 回复内容 [动作标签]\n"
            "可用情绪: 开心、欢迎、惊讶、悲伤、害羞、生气、卖萌\n"
            f"可用动作标签: {' '.join(f'[{a}]' for a in self._ACTION_NAMES)}\n"
        )
        if llm_reply:
            return self._parse_reply(llm_reply)
        t = text.lower().strip()
        # (条件, 回复模板, 情绪, 动作)
        rules = [
            (lambda t: any(k in t for k in ["你好","hi","hello","在吗"]), f"欢迎{user}来到直播间～", "欢迎", "wave"),
            (lambda t: any(k in t for k in ["谢谢","感谢","thx"]), f"谢谢{user}的支持！", "开心", "smile"),
            (lambda t: any(k in t for k in ["666","哈哈","笑死","好活"]), f"嘻嘻～{user}开心就好！", "开心", "smile"),
            (lambda t: any(k in t for k in ["主播","奶昔","老婆","可爱"]), f"被{user}夸了，好害羞", "害羞", "wave"),
        ]
        for cond, reply, emotion, action in rules:
            if cond(t):
                return (reply, emotion, action)
        return (None, "开心", "")

    def _parse_reply(self, raw: str) -> tuple:
        """解析 LLM 回复中的情绪标记和动作标签。返回 (文本, 情绪, 动作)"""
        emotion = "开心"
        action = ""
        text = raw.strip()
        # 提取情绪 [情绪]
        if text.startswith("[") and "]" in text[:10]:
            bracket_end = text.index("]")
            emotion = text[1:bracket_end].strip()
            text = text[bracket_end+1:].strip()
        # 提取动作标签 [动作]（可能在末尾）
        import re
        for a in self._ACTION_NAMES:
            pat = re.compile(r'\[' + re.escape(a) + r'\]', re.IGNORECASE)
            m = pat.search(text)
            if m:
                action = a
                text = pat.sub('', text).strip()
                break
        valid_emo = {"开心","欢迎","惊讶","悲伤","害羞","生气","卖萌","无奈"}
        if emotion not in valid_emo:
            emotion = "开心"
        return (text, emotion, action)

    def _action_to_motion(self, action: str) -> tuple:
        """动作标签 → (motion_group, motion_index)"""
        return self._ACTION_MOTION_MAP.get(action, ("", -1))

    async def _agent_danmaku(self):
        """弹幕 Agent — B站 WS 回调本身已驱动，此协程保持运行"""
        while self._running:
            await asyncio.sleep(1)

    # ═══════════════════════════════════════════════════════════════════════
    # Agent: 场景决策（LLM 或规则）
    # ═══════════════════════════════════════════════════════════════════════

    async def _agent_scene(self):
        """场景 Agent — 弹幕/礼物/进入 → LLM → 回复（含高并发削峰）"""
        while self._running:
            try:
                msg = await asyncio.wait_for(self._danmaku_queue.get(), timeout=QUEUE_TIMEOUT)
            except asyncio.TimeoutError:
                # 超时：处理积压的批量缓冲
                if self._danmaku_batch:
                    await self._process_batch()
                continue

            msg_type = msg.get("type", "")

            # 高优：礼物/上舰/SC/进入 → 奶昔主咖立即回应（走占麦仲裁，主咖高优可插队）
            if msg_type in ("gift", "guard", "super_chat", "enter"):
                if msg_type in ("gift", "guard"):
                    reply = f"感谢{msg['user']}的{'礼物' if msg_type=='gift' else '大航海'}！"
                elif msg_type == "super_chat":
                    reply = f"感谢{msg['user']}的醒目留言！"
                else:
                    reply = f"欢迎{msg['user']}进入直播间～"
                emotion = "开心" if msg_type in ("gift", "guard") else "欢迎"
                naixi = self._connectors.get("naixi")
                if naixi:
                    await self._emit(naixi, {"text": reply, "emotion": emotion, "action": "wave"},
                                     source_id="naixi", cue_depth=0)
                continue

            # 弹幕：削峰 + 批量
            if msg_type != "danmaku" or not msg.get("text"):
                continue

            now = time.time()

            # 如果距离上次处理不足间隔，加入批量缓冲
            if now - self._last_process_time < self._process_interval:
                self._danmaku_batch.append(msg)
                if len(self._danmaku_batch) > 20:  # 缓冲上限，太多就丢最早的
                    self._danmaku_batch.pop(0)
                continue

            # 到了处理窗口：合并缓冲+当前弹幕
            batch = list(self._danmaku_batch)
            batch.append(msg)
            self._danmaku_batch.clear()
            self._last_process_time = now

            danmaku = self._build_danmaku_event(batch)
            await self._dispatch_danmaku(danmaku)

    def _build_danmaku_event(self, batch: list) -> dict:
        """把一批弹幕合成一个分发事件：太多时采样 + 高频词统计。"""
        if len(batch) > 5:
            from collections import Counter
            words = []
            for b in batch:
                words.extend(b.get("text", "")[:20])
            top_words = Counter(words).most_common(3)
            samples = batch[:3]
            summary = f"（共{len(batch)}条弹幕，高频词:{' '.join(w for w,_ in top_words)}）"
            text = summary + "\n".join(f"[弹幕] {b['user']}: {b['text'][:60]}" for b in samples)
        else:
            text = "\n".join(f"[弹幕] {b['user']}: {b['text'][:60]}" for b in batch)
        return {"type": "danmaku", "user": "", "text": text, "batch": batch}

    async def _process_batch(self):
        """处理积压的批量缓冲（超时触发）"""
        batch = list(self._danmaku_batch)
        self._danmaku_batch.clear()
        if not batch:
            return
        danmaku = self._build_danmaku_event(batch)
        await self._dispatch_danmaku(danmaku)

    # ── 音频设备管理（sounddevice + VB-Cable） ──────────────────────────

    def list_audio_devices(self) -> dict:
        """列出所有音频设备，标记输入/输出/VB-Cable"""
        result = {"outputs": [], "inputs": [], "vb_cable": None, "available": self._sd_available}
        if not self._sd_available:
            return result
        try:
            import sounddevice as sd
            for i, d in enumerate(sd.query_devices()):
                info = {"index": i, "name": d["name"], "channels": d["max_output_channels"] if d["max_output_channels"] > 0 else d["max_input_channels"]}
                if "VB" in d["name"] or "Cable" in d["name"]:
                    result["vb_cable"] = info
                if d["max_output_channels"] > 0:
                    result["outputs"].append(info)
                if d["max_input_channels"] > 0:
                    result["inputs"].append(info)
        except:
            pass
        return result

    def _get_audio_devices(self) -> tuple:
        """获取实际使用的输出/输入设备ID"""
        out_id, in_id = None, None
        if not self._sd_available:
            return out_id, in_id
        try:
            import sounddevice as sd
            devices = sd.query_devices()
            # 输出：仅当明确配置了输出设备才指定，否则用系统默认
            if self._audio_out_device:
                for i, d in enumerate(devices):
                    if self._audio_out_device in d["name"] and d["max_output_channels"] > 0:
                        out_id = i
                        break
            if out_id is None:
                out_id = sd.default.device[1]  # 系统默认输出
            # 输入：仅当明确配置了输入设备才指定，否则用系统默认
            if self._audio_in_device:
                for i, d in enumerate(devices):
                    if self._audio_in_device in d["name"] and d["max_input_channels"] > 0:
                        in_id = i
                        break
            if in_id is None:
                in_id = sd.default.device[0]  # 系统默认输入
        except:
            pass
        return out_id, in_id

    def play_audio(self, audio_bytes: bytes, sample_rate: int = 24000):
        """播放音频 bytes 到输出设备（用 ffmpeg 统一转 WAV）"""
        if not self._sd_available or not audio_bytes:
            return
        try:
            import sounddevice as sd
            import numpy as np
            import threading, io, wave, subprocess, tempfile, os

            # 写临时文件，用 ffmpeg 转成标准 WAV（支持任何输入格式）
            tmp_in = os.path.join(tempfile.gettempdir(), f"play_in_{int(time.time()*1000)}")
            tmp_out = os.path.join(tempfile.gettempdir(), f"play_out_{int(time.time()*1000)}.wav")
            with open(tmp_in, "wb") as f:
                f.write(audio_bytes)
            subprocess.run(
                ["ffmpeg", "-y", "-i", tmp_in, "-ar", "24000", "-ac", "1",
                 "-sample_fmt", "s16", "-f", "wav", tmp_out],
                capture_output=True, timeout=10
            )
            try: os.remove(tmp_in)
            except: pass

            if not os.path.exists(tmp_out):
                return

            with wave.open(tmp_out, 'rb') as wf:
                frames = wf.readframes(wf.getnframes())
                data = np.frombuffer(frames, dtype=np.int16)
                rate = wf.getframerate()
            try: os.remove(tmp_out)
            except: pass

            out_id, _ = self._get_audio_devices()
            if hasattr(self, '_play_thread') and self._play_thread and self._play_thread.is_alive():
                self._play_thread.join(timeout=3)
            self._play_thread = threading.Thread(
                target=lambda: (sd.wait(), sd.play(data, rate, device=out_id), sd.wait()),
                daemon=True
            )
            self._play_thread.start()
        except:
            pass

    # ── VTube Studio 控制（WebSocket API） ───────────────────────────────

    async def _vts_connect(self):
        """连接 VTube Studio WebSocket API（含认证 + 自省表情/动作列表）"""
        import aiohttp
        if self._vts_ws and not self._vts_ws.closed:
            return True
        try:
            ws = await aiohttp.ClientSession().ws_connect(f"ws://{self._vts_host}:{self._vts_port}", heartbeat=10)
            self._vts_ws = ws
            # 完整认证握手：先取临时 token，再带 token 认证（VTS 1.0 标准流程）
            token = ""
            try:
                await self._vts_request("AuthenticationTokenRequest",
                                        {"pluginName": "奶昔直播", "pluginDeveloper": "Naixi"})
                resp = json.loads(await asyncio.wait_for(ws.receive_str(), timeout=5))
                token = resp.get("data", {}).get("authenticationToken", "")
            except Exception as e:
                log.info(f"[VTS] 获取临时 token 失败（尝试无 token 认证）: {e}")
            await self._vts_request("AuthenticationRequest",
                                    {"pluginName": "奶昔直播", "pluginDeveloper": "Naixi", "authenticationToken": token})
            resp = json.loads(await asyncio.wait_for(ws.receive_str(), timeout=5))
            if resp.get("data", {}).get("authenticated"):
                self._vts_authenticated = True
                log.info("[VTS] 已连接并认证")
            else:
                log.info("[VTS] 已连接（未认证，需在 VTS 中点击确认授权）")
            # 自省可用表情/动作列表，供情绪/动作模糊匹配
            await self._vts_introspect()
            # 枚举已加载模型（按 modelID 精准路由，避免串模型冲突）
            await self._vts_enumerate_models()
            # 启动后台读取循环，消费 VTS 响应，避免未读消息堆积
            asyncio.create_task(self._vts_read_loop())
            return True
        except Exception as e:
            log.warning(f"[VTS] 连接失败: {e}")
            return False

    async def _vts_request(self, message_type: str, data: dict):
        """向 VTS 发送一条请求（不等待响应，由后台读取循环消费）"""
        if not self._vts_ws or self._vts_ws.closed:
            return
        try:
            self._vts_req_seq += 1
            req = json.dumps({
                "apiName": "VTubeStudioPublicAPI", "apiVersion": "1.0",
                "requestID": f"naixi_{self._vts_req_seq}", "messageType": message_type, "data": data
            })
            await self._vts_ws.send_str(req)
        except Exception as e:
            log.info(f"[VTS] 发送 {message_type} 失败: {e}")

    async def _vts_read_loop(self):
        """后台消费 VTS 响应，避免未读消息堆积导致连接异常"""
        try:
            while self._vts_ws and not self._vts_ws.closed:
                msg = await self._vts_ws.receive()
                if msg.type in (aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.ERROR):
                    break
        except Exception:
            pass
        self._vts_authenticated = False
        log.info("[VTS] 读取循环结束，连接已断开")

    async def _vts_introspect(self):
        """自省 VTS 模型可用表情(ExpressionStateRequest)/动作热键(HotkeysInCurrentModelRequest)"""
        self._vts_expressions = []
        self._vts_motions = []
        # 1) 表情列表
        try:
            await self._vts_request("ExpressionStateRequest", {})
            resp = json.loads(await asyncio.wait_for(self._vts_ws.receive_str(), timeout=5))
            exprs = resp.get("data", {}).get("expressions", []) or []
            # 每个表情含 file（完整文件名，如 xxx.exp3.json）与 name
            self._vts_expressions = [e.get("file", e.get("name", "")) for e in exprs if isinstance(e, dict)]
        except Exception as e:
            log.info(f"[VTS] 读取表情列表失败: {e}")
        # 2) 动作热键（type=TriggerAnimation 的热键即为可触发的动作）
        try:
            await self._vts_request("HotkeysInCurrentModelRequest", {})
            resp = json.loads(await asyncio.wait_for(self._vts_ws.receive_str(), timeout=5))
            hotkeys = resp.get("data", {}).get("availableHotkeys", []) or []
            self._vts_motions = [
                h.get("name", "") for h in hotkeys
                if isinstance(h, dict) and h.get("type") == "TriggerAnimation" and h.get("name")
            ]
        except Exception as e:
            log.info(f"[VTS] 读取动作热键失败: {e}")
        if self._vts_expressions or self._vts_motions:
            log.info(f"[VTS] 自省完成：表情 {len(self._vts_expressions)} 个，动作热键 {len(self._vts_motions)} 个")

    async def _vts_enumerate_models(self):
        """枚举 VTS 已加载模型（AvailableModelsRequest）+ 当前模型（CurrentModelRequest），
        供多角色舞台按 modelID 精准路由，避免指令误打到其他模型造成冲突。"""
        self._vts_models = {}
        self._vts_current_model = ""
        try:
            await self._vts_request("AvailableModelsRequest", {})
            resp = json.loads(await asyncio.wait_for(self._vts_ws.receive_str(), timeout=5))
            models = (resp.get("data", {}) or {}).get("availableModels", []) or []
            self._vts_models = {m.get("modelID"): m.get("modelName", "") for m in models if m.get("modelID")}
        except Exception as e:
            log.info(f"[VTS] 枚举模型失败: {e}")
        try:
            await self._vts_request("CurrentModelRequest", {})
            resp = json.loads(await asyncio.wait_for(self._vts_ws.receive_str(), timeout=5))
            self._vts_current_model = (resp.get("data", {}) or {}).get("modelID", "")
        except Exception as e:
            log.info(f"[VTS] 读取当前模型失败: {e}")
        if self._vts_models:
            log.info(f"[VTS] 已枚举模型 {len(self._vts_models)} 个，当前模型: {self._vts_current_model or '未识别'}")

    # 情绪/动作关键词 → VTS 表情/动作文件名子串（中英对照，覆盖常见命名）
    _VTS_EMOTION_MAP = {
        "开心": ["happy", "joy", "smile"],
        "欢迎": ["welcome", "hello", "wave", "happy"],
        "惊讶": ["surprise", "shock"],
        "悲伤": ["sad", "cry", "tear"],
        "害羞": ["shy", "blush", "embarrass"],
        "生气": ["angry", "mad", "rage"],
        "卖萌": ["joy", "cute", "love", "happy"],
        "无奈": ["neutral", "tired", "sigh"],
    }
    _VTS_ACTION_MAP = {
        "wave": ["wave"], "bye": ["bye", "wave"], "nod": ["nod", "bow"],
        "think": ["think", "ponder"], "surprise": ["surprise"],
        "shake": ["shake", "no"], "kime": ["kime", "pose"], "sing": ["sing", "song"],
        "angry": ["angry"], "cry": ["cry", "tear"], "smile": ["smile", "happy"],
        "sad": ["sad"],
    }

    def _vts_match(self, keyword: str, candidates: list) -> str:
        """在候选文件名（VTS 表情/动作）中按关键词模糊匹配，命中返回文件名"""
        if not keyword or not candidates:
            return ""
        subs = self._VTS_EMOTION_MAP.get(keyword) or self._VTS_ACTION_MAP.get(keyword) or [keyword.lower()]
        for sub in subs:
            sub = sub.lower()
            for c in candidates:
                cname = c if isinstance(c, str) else str(c)
                if sub in cname.lower():
                    return c
        return ""

    async def _vts_send_expression(self, emotion: str, model_id: Optional[str] = None):
        """按情绪触发 VTS 表情（ExpressionActivationRequest，active=true）。model_id 指定目标模型。"""
        if not self._vts_ws or self._vts_ws.closed or not self._vts_authenticated:
            return
        name = self._vts_match(emotion, self._vts_expressions)
        if not name:
            return
        data = {"expressionFile": name, "fadeTime": 0.5, "active": True}
        if model_id:
            data["modelID"] = model_id
        try:
            await self._vts_request("ExpressionActivationRequest", data)
            log.info(f"[VTS] 表情触发: {emotion} → {name}" + (f" 模型={model_id}" if model_id else ""))
        except Exception as e:
            log.info(f"[VTS] 表情触发失败: {e}")

    async def _vts_send_motion(self, action: str, model_id: Optional[str] = None):
        """按动作标签触发 VTS 动作（HotkeyTriggerRequest，匹配 TriggerAnimation 热键名）。model_id 指定目标模型。"""
        if not self._vts_ws or self._vts_ws.closed or not self._vts_authenticated:
            return
        name = self._vts_match(action, self._vts_motions)
        if not name:
            return
        try:
            # VTS 允许直接用热键名称（不区分大小写）作为 hotkeyID 触发
            data = {"hotkeyID": name}
            if model_id:
                data["modelID"] = model_id
            await self._vts_request("HotkeyTriggerRequest", data)
            log.info(f"[VTS] 动作触发: {action} → 热键[{name}]" + (f" 模型={model_id}" if model_id else ""))
        except Exception as e:
            log.info(f"[VTS] 动作触发失败: {e}")

    async def _vts_disconnect(self):
        """断开 VTube Studio 连接"""
        if self._vts_ws:
            try: await self._vts_ws.close()
            except: pass
            self._vts_ws = None
            self._vts_authenticated = False

    async def _vts_send_parameters(self, params: dict, model_id: Optional[str] = None):
        """发送参数到 VTube Studio（如 MouthOpen, FaceAngleX 等）。model_id 指定目标模型。"""
        if not self._vts_ws or self._vts_ws.closed:
            return
        try:
            data = {"parameterValues": [{"id": k, "value": v} for k, v in params.items()]}
            if model_id:
                data["modelID"] = model_id
            req = json.dumps({
                "apiName": "VTubeStudioPublicAPI", "apiVersion": "1.0",
                "messageType": "InjectParameterDataRequest",
                "data": data,
            })
            await self._vts_ws.send_str(req)
        except:
            pass

    def _audio_to_mouth_data(self, audio_bytes: bytes, frame_ms: int = 80) -> list[float]:
        """分析音频 bytes 生成 MouthOpen 值序列（0.0~1.0）。

        支持 WAV 与压缩格式（如 Edge-TTS 输出的 MP3）：非 WAV 时先用 ffmpeg
        转码为标准 WAV 再解析，避免口型序列退化为 [0.0]（此前 MP3 直读 wave
        模块会抛 "file does not start with RIFF id"，导致口型全平）。
        """
        import numpy as np, io, wave, subprocess, tempfile, os

        def _parse(wav_bytes: bytes):
            with io.BytesIO(wav_bytes) as buf:
                with wave.open(buf, 'rb') as wf:
                    frames = wf.readframes(wf.getnframes())
                    data = np.frombuffer(frames, dtype=np.int16).astype(np.float32)
                    rate = wf.getframerate()
            return data, rate

        pcm = None
        rate = None
        try:
            pcm, rate = _parse(audio_bytes)
        except Exception:
            # 非 WAV（如 Edge-TTS 的 MP3）：ffmpeg 转码为 WAV 后解析
            try:
                tmp_in = os.path.join(tempfile.gettempdir(), f"mouth_in_{int(time.time() * 1000)}")
                tmp_out = os.path.join(tempfile.gettempdir(), f"mouth_out_{int(time.time() * 1000)}.wav")
                with open(tmp_in, "wb") as f:
                    f.write(audio_bytes)
                subprocess.run(
                    ["ffmpeg", "-y", "-i", tmp_in, "-ar", "24000", "-ac", "1",
                     "-sample_fmt", "s16", "-f", "wav", tmp_out],
                    capture_output=True, timeout=10,
                )
                if os.path.exists(tmp_out):
                    with open(tmp_out, "rb") as f:
                        pcm, rate = _parse(f.read())
                try:
                    os.remove(tmp_in)
                except Exception:
                    pass
                try:
                    os.remove(tmp_out)
                except Exception:
                    pass
            except Exception:
                return [0.0]
        if pcm is None or rate is None:
            return [0.0]
        frame_size = int(rate * frame_ms / 1000)
        mouth_values = []
        for i in range(0, len(pcm), frame_size):
            chunk = pcm[i:i + frame_size]
            if len(chunk) == 0:
                break
            rms = float(np.sqrt(np.mean(chunk ** 2)))
            # 映射到 0.0~1.0（阈值 500~8000）
            mouth = min(1.0, max(0.0, (rms - 500) / 8000))
            mouth_values.append(mouth)
        return mouth_values if mouth_values else [0.0]

    async def _vts_speak(self, audio_bytes: bytes, text: str = "", emotion: str = "",
                         action: str = "", model_id: Optional[str] = None, human_controlled: bool = False):
        """TTS 音频播放 + 口型同步（VTS + 桌宠双通道）。

        model_id: 绑定的 VTS 模型 GUID；真人模型(human_controlled)完全由真人操控，
        奶昔不写入任何 VTS 数据（口型/表情/动作），直接返回。
        """
        # 真人独占模型：奶昔不写入 VTS（真人自己在真机上操控），仅做桌宠内渲（若有）
        if human_controlled:
            log.info(f"[VTS] 真人模型({model_id or 'human'})由真人独占，奶昔跳过所有 VTS 写入")
            return
        mouth_data = self._audio_to_mouth_data(audio_bytes)
        if not mouth_data:
            return
        self.play_audio(audio_bytes)
        if self._live2d_ws and not self._live2d_ws.closed:
            try:
                await self._live2d_ws.send_json({
                    "type": "speak", "mouth": mouth_data,
                    "frame_ms": 80, "text": text, "emotion": emotion, "action": action,
                    "model_id": model_id or "",
                })
            except:
                pass
        # VTS 表情/动作触发（与桌宠内渲共用同一份 emotion/action）
        if emotion:
            await self._vts_send_expression(emotion, model_id)
        if action:
            await self._vts_send_motion(action, model_id)
        # 逐帧发送口型参数到 VTube Studio（80ms/帧，按 model_id 精准投递）
        frame_interval = 0.08
        for mouth in mouth_data:
            if not self._running:
                break
            await self._vts_send_parameters({"MouthOpen": mouth}, model_id)
            await asyncio.sleep(frame_interval)

    # ═══════════════════════════════════════════════════════════════════════
    # Agent: TTS 语音合成
    # ═══════════════════════════════════════════════════════════════════════

    async def _agent_tts(self):
        """TTS Agent — 文本 → 语音合成 → 播放 + 推流"""
        while self._running:
            try:
                action = await asyncio.wait_for(self._scene_queue.get(), timeout=QUEUE_TIMEOUT)
            except asyncio.TimeoutError:
                continue

            if action.get("type") != "speak":
                continue

            text = action.get("text", "")
            if not text:
                continue

            spoken = False
            try:
                audio_bytes = await self._synthesize(text)
                if audio_bytes:
                    connector = self._connectors.get(action.get("agent_id", "naixi"))
                    model_id = getattr(connector, "model_id", None) if connector else None
                    human_controlled = getattr(connector, "human_controlled", False) if connector else False
                    await self._vts_speak(audio_bytes, text, action.get("emotion", "开心"),
                                          action.get("action", ""), model_id, human_controlled)
                    tmp = os.path.join(tempfile.gettempdir(), f"live_push_{int(time.time()*1000)}.wav")
                    try:
                        with open(tmp, "wb") as f:
                            f.write(audio_bytes)
                    except:
                        tmp = ""
                    await self._tts_queue.put({
                        "type": "audio", "audio_path": tmp, "text": text,
                        "emotion": action.get("emotion", "开心")
                    })
                    spoken = True
            finally:
                # 无论合成成功与否都必须释放麦位，否则占麦仲裁会永久卡死
                await self._after_speak(action, spoken)

    def _resolve_tts_config(self) -> dict:
        """解析 TTS 配置（api_key/api_url/model），优先对话页audio供应商"""
        cfg = {"api_key": "", "api_url": "https://dashscope.aliyuncs.com/api/v1/services/aigc/text2audio/cosyvoice", "model": "cosyvoice-v3-flash"}
        try:
            from desktop_core.storage import meta_get, decrypt_api_key
            raw = meta_get("desktop_config")
            if raw:
                dc = json.loads(raw)
                for pid, pcfg in dc.get("api_providers", {}).items():
                    if pcfg.get("type", "chat") == "audio":
                        raw_key = pcfg.get("api_key", "")
                        if raw_key.startswith("enc:"):
                            try:
                                cfg["api_key"] = decrypt_api_key(raw_key)
                            except:
                                cfg["api_key"] = raw_key
                        else:
                            cfg["api_key"] = raw_key
                        if pcfg.get("api_url"):
                            cfg["api_url"] = pcfg["api_url"]
                        if pcfg.get("model"):
                            cfg["model"] = pcfg["model"]
                        return cfg
        except:
            pass
        if not cfg["api_key"]:
            cfg["api_key"] = self._dashscope_api_key
        if not cfg["api_key"]:
            cfg["api_key"] = os.environ.get("DASHSCOPE_API_KEY", "")
        return cfg

    async def _cosyvoice_request(self, text: str, timeout: int = 30) -> Optional[bytes]:
        """调用 TTS，返回音频 bytes（内存流式，不存文件）"""
        tts = self._resolve_tts_config()
        if not tts["api_key"]:
            return None
        is_dashscope = "dashscope" in tts["api_url"] or "aliyuncs" in tts["api_url"]
        try:
            if is_dashscope:
                # 百炼 WebSocket 流式合成（返回完整音频字节，无临时文件）
                import dashscope
                from dashscope.audio.tts_v2 import SpeechSynthesizer
                dashscope.api_key = tts["api_key"]
                voice = os.environ.get("COSYVOICE_VOICE", "longfeifei_v3")
                # SpeechSynthesizer 是同步的，放线程池跑
                def _sync_synth():
                    synth = SpeechSynthesizer(model=tts["model"], voice=voice)
                    return synth.call(text)
                loop = asyncio.get_event_loop()
                audio = await loop.run_in_executor(None, _sync_synth)
                return audio if audio else None
            else:
                # OpenAI 兼容模式：HTTP 直接返回音频字节
                from aiohttp import ClientSession
                headers = {"Authorization": f"Bearer {tts['api_key']}", "Content-Type": "application/json"}
                url = tts["api_url"].rstrip("/") + "/audio/speech"
                payload = {"model": tts["model"], "input": text, "voice": "alloy", "response_format": "wav"}
                async with ClientSession() as s:
                    async with s.post(url, json=payload, headers=headers, timeout=timeout) as r:
                        if r.status == 200:
                            return await r.read()
        except:
            pass
        return None

    async def test_tts(self) -> str:
        """测试 TTS 配置是否可用"""
        tts = self._resolve_tts_config()
        if not tts["api_key"]:
            return "未配置 API Key"
        is_dashscope = "dashscope" in tts["api_url"] or "aliyuncs" in tts["api_url"]
        try:
            from aiohttp import ClientSession
            headers = {"Authorization": f"Bearer {tts['api_key']}", "Content-Type": "application/json"}
            if is_dashscope:
                url = "https://dashscope.aliyuncs.com/api/v1/services/audio/tts/SpeechSynthesizer"
                payload = {"model": tts["model"], "input": {"text": "测试", "voice": "longfeifei_v3", "format": "wav", "sample_rate": 24000}}
            else:
                url = tts["api_url"].rstrip("/") + "/audio/speech"
                payload = {"model": tts["model"], "input": "测试", "voice": "alloy", "response_format": "wav"}
            async with ClientSession() as s:
                async with s.post(url, json=payload, headers=headers, timeout=10) as r:
                    if r.status == 200:
                        return ""
                    txt = (await r.text())[:100]
                    return f"API 返回 {r.status}: {txt}"
        except Exception as e:
            return f"请求失败: {e}"

    async def _synthesize(self, text: str) -> Optional[bytes]:
        """语音合成 — 对话页audio供应商 → 直播页配置 → Edge-TTS，返回音频 bytes"""
        # 尝试 CosyVoice（百炼 WebSocket 流式，直接返回 bytes）
        data = await self._cosyvoice_request(text)
        if data:
            return data
        # 降级 Edge-TTS（仍需临时文件，返回后清理）
        tmp = os.path.join(tempfile.gettempdir(), f"live_tts_{int(time.time()*1000)}.mp3")
        try:
            import edge_tts
            communicate = edge_tts.Communicate(text, "zh-CN-XiaoxiaoNeural")
            await communicate.save(tmp)
            with open(tmp, "rb") as f:
                data = f.read()
            try: os.remove(tmp)
            except: pass
            return data
        except Exception:
            return None

    # ═══════════════════════════════════════════════════════════════════════
    # Agent: 虚拟角色（画面生成）
    # ═══════════════════════════════════════════════════════════════════════

    async def _agent_avatar(self):
        """形象 Agent — 文字+表情 → 画面帧元数据"""
        while self._running:
            try:
                action = await asyncio.wait_for(self._tts_queue.get(), timeout=QUEUE_TIMEOUT)
            except asyncio.TimeoutError:
                continue

            if action.get("type") == "audio":
                text = action.get("text", "")
                emotion = action.get("emotion", "开心")
                self._current_text = text
                self._current_emotion = emotion
                await self._avatar_queue.put({
                    "type": "frame_meta",
                    "text": text,
                    "emotion": emotion,
                })

    # ═══════════════════════════════════════════════════════════════════════
    # Agent: RTMP 推流
    # ═══════════════════════════════════════════════════════════════════════

    async def _agent_stream(self):
        """推流 Agent — 帧元数据 → ffmpeg 画面合成 → RTMP"""
        while self._running:
            try:
                meta = await asyncio.wait_for(self._avatar_queue.get(), timeout=QUEUE_TIMEOUT)
            except asyncio.TimeoutError:
                continue

            if meta.get("type") != "frame_meta":
                continue

            text = meta.get("text", "")
            audio_path = meta.get("audio_path", "")
            log.info(f"[推流] 推送语音 ({len(text)}字): {text[:30]}...")
            if self._rtmp_url and audio_path and os.path.exists(audio_path):
                await self._composite_and_push(audio_path, text)
                # 用完删除临时文件
                try: os.remove(audio_path)
                except: pass

    async def _composite_and_push(self, audio_path: str, text: str):
        """把一句语音送进常驻推流：更新字幕文件 + 解码 PCM 入播放队列。

        不再每句新开 ffmpeg（旧实现每句一进程 + -shortest 会导致每句掉线、
        双进程抢同一 RTMP 地址）。字幕改走 textfile + reload=1，彻底避免把
        弹幕文本直接拼进 filter 字符串带来的注入风险。
        """
        # 确保常驻推流已在运行（未开则按需拉起）
        if not (self._ffmpeg_proc and self._ffmpeg_proc.returncode is None):
            ok = await self.start_stream()
            if not ok:
                log.warning(f"[推流] 常驻推流未就绪，丢弃本句: {text[:20]}")
                return
        # 更新字幕（写文件，drawtext reload=1 会自动读取，避免注入）
        self._set_subtitle(text)
        # 解码音频为 raw PCM 并入队，由 _audio_pump_loop 实时喂给 ffmpeg
        pcm = await self._decode_to_pcm(audio_path)
        if pcm:
            await self._pcm_queue.put(pcm)
            log.info(f"[推流] 已入队语音 {_fmt_size(len(pcm))}: {text[:20]}")

    async def _decode_to_pcm(self, audio_path: str) -> bytes:
        """用一次性 ffmpeg 把任意音频文件解码为 s16le 单声道 raw PCM。"""
        try:
            proc = await asyncio.create_subprocess_exec(
                "ffmpeg", "-y", "-i", audio_path,
                "-f", "s16le", "-ar", str(PCM_RATE), "-ac", str(PCM_CHANNELS), "pipe:1",
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
            )
            pcm, _ = await proc.communicate()
            return pcm or b""
        except FileNotFoundError:
            log.warning("[推流] ffmpeg 未安装，无法解码音频")
            return b""
        except Exception as e:
            log.warning(f"[推流] 音频解码失败: {e}")
            return b""

    def _ensure_subtitle_file(self):
        """确保字幕文件存在（drawtext reload=1 要求文件常在，空文件写一个空格占位）。"""
        if not self._subtitle_file:
            self._subtitle_file = os.path.join(tempfile.gettempdir(), "naixi_live_subtitle.txt")
        if not os.path.exists(self._subtitle_file):
            try:
                with open(self._subtitle_file, "w", encoding="utf-8") as f:
                    f.write(" ")
            except Exception as e:
                log.warning(f"[推流] 创建字幕文件失败: {e}")

    def _set_subtitle(self, text: str):
        """更新字幕文件内容（限长 60 字，纯文件写入，天然免疫 filter 注入）。"""
        self._ensure_subtitle_file()
        try:
            safe = (text or " ")[:60] or " "
            with open(self._subtitle_file, "w", encoding="utf-8") as f:
                f.write(safe)
        except Exception as e:
            log.warning(f"[推流] 更新字幕失败: {e}")

    def _subtitle_filter(self) -> str:
        """构造 drawtext filter：从字幕文件读，Windows 路径按 ffmpeg 规则转义。"""
        esc = self._subtitle_file.replace("\\", "/").replace(":", "\\:")
        return (
            f"drawtext=textfile='{esc}':reload=1:fontcolor=white:fontsize=24:"
            f"x=(w-text_w)/2:y=h-80:box=1:boxcolor=black@0.4:boxborderw=8"
        )

    async def _audio_pump_loop(self):
        """实时向常驻 ffmpeg 的 stdin 喂 PCM：有语音喂语音，空闲喂静音。

        以 PCM_CHUNK_MS 为粒度按真实时间节流，避免一次性灌爆缓冲；空闲时持续
        喂静音帧，保证音频流不断（否则观众端会卡顿/断流）。
        """
        chunk_samples = PCM_RATE * PCM_CHUNK_MS // 1000
        chunk_bytes = chunk_samples * 2 * PCM_CHANNELS      # s16le = 2 字节/采样
        silence = b"\x00" * chunk_bytes
        interval = PCM_CHUNK_MS / 1000.0
        current = b""
        while self._stream_running and self._ffmpeg_proc and self._ffmpeg_proc.returncode is None:
            t0 = time.monotonic()
            if not current:
                try:
                    current = self._pcm_queue.get_nowait()
                except asyncio.QueueEmpty:
                    current = b""
            if current:
                chunk = current[:chunk_bytes]
                current = current[chunk_bytes:]
                if len(chunk) < chunk_bytes:
                    chunk = chunk + silence[len(chunk):]
            else:
                chunk = silence
            try:
                self._ffmpeg_proc.stdin.write(chunk)
                await self._ffmpeg_proc.stdin.drain()
            except Exception as e:
                log.warning(f"[推流] 写入音频流失败，停止喂音: {e}")
                break
            dt = time.monotonic() - t0
            if dt < interval:
                await asyncio.sleep(interval - dt)

    async def start_stream(self, rtmp_url: str = "") -> bool:
        """启动单常驻推流：一个 ffmpeg 全程在线，画面 + 字幕(reload) + stdin 音频。

        画面用 lavfi 无限背景，字幕从 textfile 每帧 reload，音频从 stdin 管道喂
        （由 _audio_pump_loop 持续供给，空闲静音垫底）。全程只有这一个 ffmpeg
        进程，杜绝旧实现每句新开进程 + 双进程抢 RTMP 导致的掉线。
        """
        if rtmp_url:
            self._rtmp_url = rtmp_url
            self.save_config(rtmp_url=rtmp_url)
        if not self._rtmp_url:
            self._last_error = "未配置 RTMP 地址"
            return False
        if self._ffmpeg_proc and self._ffmpeg_proc.returncode is None:
            return True
        self._ensure_subtitle_file()
        self._set_subtitle(" ")
        try:
            self._ffmpeg_proc = await asyncio.create_subprocess_exec(
                "ffmpeg", "-y",
                "-f", "lavfi", "-i", f"color=c=0x1a1a2e:s={STREAM_WIDTH}x{STREAM_HEIGHT}:r={STREAM_FPS}",
                "-f", "s16le", "-ar", str(PCM_RATE), "-ac", str(PCM_CHANNELS), "-i", "pipe:0",
                "-vf", self._subtitle_filter(),
                "-c:v", "libx264", "-preset", "ultrafast", "-tune", "zerolatency",
                "-pix_fmt", "yuv420p", "-g", str(STREAM_FPS * 2), "-b:v", "2000k",
                "-c:a", "aac", "-b:a", "128k",
                "-f", "flv", self._rtmp_url,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            self._stream_running = True
            # 启动实时喂音循环（有语音喂语音，空闲喂静音）
            self._audio_pump_task = asyncio.create_task(self._audio_pump_loop())
            log.info("[直播] 单常驻推流已启动")
            return True
        except FileNotFoundError:
            self._last_error = "ffmpeg 未安装"
            return False
        except Exception as e:
            self._last_error = f"推流启动失败: {e}"
            return False

    async def stop_stream(self):
        """停止推流"""
        await self._stop_ffmpeg()

    async def _stop_ffmpeg(self):
        """停止常驻推流：先停喂音循环，关 stdin，再优雅结束 ffmpeg。"""
        self._stream_running = False
        # 停止喂音任务
        if self._audio_pump_task:
            self._audio_pump_task.cancel()
            try:
                await self._audio_pump_task
            except: pass
            self._audio_pump_task = None
        # 清空待播队列
        try:
            while True:
                self._pcm_queue.get_nowait()
        except asyncio.QueueEmpty:
            pass
        if self._ffmpeg_proc:
            try:
                if self._ffmpeg_proc.stdin:
                    try:
                        self._ffmpeg_proc.stdin.close()
                    except: pass
                self._ffmpeg_proc.terminate()
                await asyncio.sleep(0.5)
                if self._ffmpeg_proc.returncode is None:
                    self._ffmpeg_proc.kill()
            except: pass
            self._ffmpeg_proc = None
            log.info("[直播] 推流已停止")

    def _start_pet(self, model_path: str = ""):
        """启动桌宠子进程（PySide6 独立窗口）"""
        if self._pet_proc and self._pet_proc.poll() is None:
            log.info("[桌宠] 已在运行")
            return True
        try:
            sidecar = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src-tauri", "sidecar")
            pet_script = os.path.join(sidecar, "pet_window.py")
            if not os.path.exists(pet_script):
                # 也可能是和桌面端代码放在一起
                pet_script = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "desktop_core", "pet_window.py")
            args = [sys.executable, "-B", pet_script]
            if model_path:
                args.append(model_path)
            self._pet_proc = subprocess.Popen(args)
            log.info(f"[桌宠] 已启动: {' '.join(args[-2:])}")
            return True
        except Exception as e:
            log.warning(f"[桌宠] 启动失败: {e}")
            return False

    def _stop_pet(self):
        """停止桌宠子进程"""
        if self._pet_proc and self._pet_proc.poll() is None:
            try:
                self._pet_proc.terminate()
                self._pet_proc.wait(timeout=3)
            except:
                try: self._pet_proc.kill()
                except: pass
            self._pet_proc = None
            log.info("[桌宠] 已停止")


# 全局单例
engine = LiveEngine()
engine._load_config()  # 启动时从数据库加载配置
