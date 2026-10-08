"""Gateway 控制平面 —— WebSocket Mesh（18400）

架构依据（业界 OpenClaw / Moltbot / Panther 三家同款分层）：
    Channel Adapter  ←→  Gateway（控制平面）  ←→  Agent
本模块实现 Gateway 的 WS 部分。**边界约定（重要）**：

    · WS 只做：订阅 / 事件通知 / 探活 / 能力清单推送    —— 有连接无状态，不会死锁
    · 能力**调用**走同步 HTTP（带超时，天然防死锁）    —— 见 capabilities 端点

为什么这样切：双向往返若都走 WS，A 调 B → B 回调 A → A 再调 B 会无限回环。
HTTP 自带超时与状态码，天然切断回环。业界 MessageBus 同样是这个逻辑。

协议（JSON 文本帧，msg.type 区分）：
    → hello      {"type":"hello","provider":"qq-naixi","capabilities":[...]}
    ← welcome    {"type":"welcome","peers":[...],"capabilities":[...]}
    → subscribe  {"type":"subscribe","topics":["capability","task","event"]}
    → invoke     {"type":"invoke","id":"...","capability":"...","args":{...}}
    ← result     {"type":"result","id":"...","ok":true/false,"data":...}
    → ping       {"type":"ping"}
    ← pong{"type":"pong"}

安全：
    · 绑 127.0.0.1，且做来源校验（拒绝浏览器 Origin，防 DNS 重绑定）
    · invoke 只放行 trust=read 的能力；write/dangerous 一律拒绝并要求确认流程
    · 未知 capability id 直接报错，不做模糊匹配（避免误调）
"""

import asyncio
import json
import logging
import os
import time
from urllib.parse import urlparse

from aiohttp import WSMsgType, web

log = logging.getLogger("gateway")

# 控制平面端口。刻意与业务端口（9845/9847）分开：业务停掉不影响 Mesh 探活。
# 可用环境变量 GATEWAY_WS_PORT 覆盖：Windows 上端口频繁跑批/重连时可能撞 TIME_WAIT
# （实测 10048 且 netstat查不到进程，属正常现象，等 1~2 分钟或换端口即可）。
WS_PORT = int(os.environ.get("GATEWAY_WS_PORT", "18400"))
WS_PATH = "/ws/gateway"
PEER_TIMEOUT = 45.0# 超过此时间没收到任何帧则判定掉线

# topic → 是否允许订阅（白名单，防订阅到不该收的东西）
ALLOWED_TOPICS = ("capability", "task", "event", "log")

# ── 跨机互联（mesh）配置 ─────────────────────────────────────────
# 设计目标：**普通人点一下开关就能跨机联**，硬核用户仍可用环境变量全覆盖。
#   · WS 默认监听 0.0.0.0，但是否「允许远程」由 mesh 开关 + token 在**认证层**拦截
#     （本机连接永远免 token —— 保证本机 bot↔桌面 自连不受开关影响）。
#   · token 由系统自动生成并持久化，用户**无需理解** NAIXI_GATEWAY_TOKENS 是什么。
# 环境变量（GATEWAY_WS_HOST / NAIXI_GATEWAY_TOKENS）仍优先，供硬核/无 GUI 场景覆盖。
import json as _json

WS_HOST = os.environ.get("GATEWAY_WS_HOST", "0.0.0.0")


def _writable_dir() -> str:
    """mesh 配置目录：优先项目 data/（与库同源），不可写则退回用户目录（安装态只读时）。"""
    import tempfile
    cands = [
        os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data"),
        os.path.join(os.environ.get("APPDATA") or tempfile.gettempdir(), "奶昔", "data"),
    ]
    for d in cands:
        try:
            os.makedirs(d, exist_ok=True)
            if os.access(d, os.W_OK):
                return d
        except Exception:
            continue
    return tempfile.gettempdir()


MESH_FILE = os.path.join(_writable_dir(), "gateway_mesh.json")

# 运行时状态（由 _reload_runtime 更新）
MESH_ENABLED = False
MESH_TOKEN = ""
TOKENS: dict[str, set[str]] = {}


def _load_mesh_file() -> dict:
    try:
        with open(MESH_FILE, "r", encoding="utf-8") as f:
            return _json.load(f)
    except Exception:
        return {}


def _save_mesh_file(d: dict) -> bool:
    try:
        with open(MESH_FILE, "w", encoding="utf-8") as f:
            _json.dump(d, f, ensure_ascii=False, indent=2)
        return True
    except Exception as e:
        log.warning("[Gateway] mesh 配置保存失败: %s", e)
        return False


def _parse_tokens(raw: str) -> dict:
    out: dict[str, set[str]] = {}
    for item in (raw or "").split(";"):
        item = item.strip()
        if not item or ":" not in item:
            continue
        tok, scopes = item.split(":", 1)
        tok = tok.strip()
        if tok:
            out[tok] = {s.strip() for s in scopes.split(",") if s.strip()} or {"*"}
    return out


def _reload_runtime() -> None:
    """重算 TOKENS / MESH_ENABLED / MESH_TOKEN。env 优先于 mesh 文件。"""
    global TOKENS, MESH_ENABLED, MESH_TOKEN
    env_raw = os.environ.get("NAIXI_GATEWAY_TOKENS", "").strip()
    if env_raw:
        # 硬核模式：直接用 env 的 token 串，并视为已开启远程
        TOKENS = _parse_tokens(env_raw)
        MESH_ENABLED = True
        MESH_TOKEN = next(iter(TOKENS), "")
    else:
        cfg = _load_mesh_file()
        MESH_ENABLED = bool(cfg.get("enabled"))
        MESH_TOKEN = str(cfg.get("token") or "").strip()
        TOKENS = _parse_tokens(f"{MESH_TOKEN}:*") if (MESH_ENABLED and MESH_TOKEN) else {}


def get_mesh_state() -> dict:
    """给 API/UI 用：当前开关 + 展示用 token（token 仅本机 owner 可见，见 API 层）。"""
    return {"enabled": MESH_ENABLED, "token": MESH_TOKEN, "host": WS_HOST}


def set_mesh(enabled: bool) -> dict:
    """开/关跨机互联。开启时若无 token 则自动生成一个（用户无需自拟）。"""
    global MESH_ENABLED, MESH_TOKEN
    cfg = _load_mesh_file()
    if enabled:
        MESH_TOKEN = MESH_TOKEN or _gen_token()
        cfg = {"enabled": True, "token": MESH_TOKEN}
    else:
        MESH_TOKEN = ""
        cfg = {"enabled": False, "token": ""}
    _save_mesh_file(cfg)
    _reload_runtime()
    return get_mesh_state()


def _gen_token() -> str:
    import secrets
    import string
    # 去掉了 0/O/1/l 等易混字符，方便手打/口述
    alphabet = string.ascii_letters.replace("O", "").replace("o", "").replace("l", "") + "23456789"
    return "".join(secrets.choice(alphabet) for _ in range(10))


def regenerate_token() -> dict:
    """强制换一个连接口令（旧口令立即失效）。

    用途：口令已经泄露 / 已分享给不再信任的设备 / 单纯想换一个新的。
    未开启跨机互联时不做任何事（避免关着也在后台转 token）。
    """
    global MESH_TOKEN
    if not MESH_ENABLED:
        return get_mesh_state()
    MESH_TOKEN = _gen_token()
    _save_mesh_file({"enabled": True, "token": MESH_TOKEN})
    _reload_runtime()
    log.info("[Gateway] 连接口令已重新生成")
    return get_mesh_state()


def set_custom_token(tok: str) -> dict:
    """高级档：用户**自己指定**连接口令（而不是用随机生成的）。

    校验规则（拒绝弱口令是硬核档的责任）：
      · 长度 >= 8（低于 8 暴力猜解成本太低）
      · 至少包含字母与数字各一个（纯字母/纯数字都易被字典命中）
    不通过时抛 ValueError，由 API 层转 400 提示用户。
    """
    global MESH_TOKEN
    tok = (tok or "").strip()
    if len(tok) < 8:
        raise ValueError("口令至少 8 位")
    has_alpha = any(c.isalpha() for c in tok)
    has_digit = any(c.isdigit() for c in tok)
    if not (has_alpha and has_digit):
        raise ValueError("口令需同时包含字母和数字")
    MESH_TOKEN = tok
    _save_mesh_file({"enabled": MESH_ENABLED, "token": MESH_TOKEN})
    _reload_runtime()
    log.info("[Gateway] 连接口令已由用户自定义")
    return get_mesh_state()


_reload_runtime()


def _client_token(request) -> str:
    """取对端 token：优先 URL ?token=xxx（WS 客户端常用），其次 Authorization: Bearer。"""
    t = request.query.get("token") or request.query.get("access_token") or ""
    if t:
        return t.strip()
    auth = request.headers.get("Authorization", "") or ""
    if auth.lower().startswith("bearer "):
        return auth[7:].strip()
    return ""


def _is_local(request) -> bool:
    """是否来自本机回环（本机 bot↔桌面自连走这里，永远免 token）。"""
    return (request.remote or "") in ("127.0.0.1", "::1", "localhost", "")


def _token_valid(request) -> bool:
    """token 是否有效（必须命中已配置 token）。"""
    return bool(TOKENS) and _client_token(request) in TOKENS


def _origin_allowed(origin: str) -> bool:
    """来源校验。规则与桌面端 9845 后端一致（见 api.py is_trusted_origin）：
    无 Origin（curl/服务端/WS 客户端）放行；仅信任本机回环与 Tauri。"""
    if not origin:
        return True
    try:
        host = (urlparse(origin).hostname or "").lower()
        if host in ("tauri.localhost", "ipc.localhost", "localhost", "127.0.0.1", "::1"):
            return True
    except Exception:
        pass
    return False


class GatewayHub:
    """连接中枢：管理所有对端连接、订阅关系、事件广播。

    同一provider 重复连接时顶掉旧连接（对端重启后自愈，不必手动清理）。
    """

    def __init__(self, provider: str = "desktop-9845"):
        self.provider = provider
        self._peers: dict[str, dict] = {}   # provider -> {ws, subs:set, last_seen, remote}

    # ── 连接生命周期 ──
    def attach(self, provider: str, ws: web.WebSocketResponse, remote: str = "") -> None:
        old = self._peers.get(provider)
        if old and old.get("ws") is not None and not old["ws"].closed:
            log.info("[Gateway] %s 重复连接，顶掉旧连接", provider)
            try:
                asyncio.create_task(old["ws"].close(code=4000, message=b"replaced by new connection"))
            except Exception:
                pass
        self._peers[provider] = {"ws": ws, "subs": set(), "last_seen": time.time(), "remote": remote}
        log.info("[Gateway] 对端接入: %s (共 %d 个)", provider, len(self._peers))

    def detach(self, provider: str) -> None:
        if self._peers.pop(provider, None) is not None:
            log.info("[Gateway] 对端断开: %s (剩 %d 个)", provider, len(self._peers))

    def touch(self, provider: str) -> None:
        p = self._peers.get(provider)
        if p:
            p["last_seen"] = time.time()

    @property
    def peer_count(self) -> int:
        return len(self._peers)

    def peer_list(self) -> list:
        out = []
        for name, p in self._peers.items():
            out.append({
                "provider": name,
                "remote": p.get("remote", ""),
                "subs": sorted(p.get("subs") or []),
                "idle_s": round(time.time() - p.get("last_seen", time.time()), 1),
            })
        return out

    # ── 事件广播（供桌面端主动推给对端，如"任务完成"）──
    async def broadcast(self, topic: str, payload: dict) -> int:
        """推给所有订阅了该 topic 的对端。返回成功条数。"""
        if topic not in ALLOWED_TOPICS:
            log.warning("[Gateway] 拒绝广播到未知 topic: %s", topic)
            return 0
        msg = json.dumps({"type": "event", "topic": topic,
                          "ts": time.time(), "payload": payload}, ensure_ascii=False)
        n = 0
        dead = []
        for name, p in list(self._peers.items()):
            if topic not in (p.get("subs") or set()):
                continue
            try:
                await p["ws"].send_str(msg)
                n += 1
            except Exception as e:
                log.debug("[Gateway] 推送 %s 失败: %s", name, e)
                dead.append(name)
        for name in dead:
            self.detach(name)
        return n

    # ── 请求处理 ──
    async def handle(self, request: web.Request) -> web.WebSocketResponse:
        # ── 认证 ──
        # 本机（bot↔桌面自连）：**永远免 token** —— 保证开/关「跨机互联」开关
        #   都不影响本机互联；无 token 时仍做 Origin 校验，防浏览器 DNS 重绑定
        #   （本机恶意网页打本机 WS 端口）。
        # 远程：必须「跨机开关已开 + token 正确」，否则一律拒绝（fail-closed）。
        is_local = _is_local(request)
        if _token_valid(request):
            pass                                    # 带正确 token：直接放行
        elif is_local:
            origin = request.headers.get("Origin", "")
            if not _origin_allowed(origin):
                log.warning("[Gateway] 拒绝来源(本机): %s", origin)
                raise web.HTTPForbidden(text="origin not allowed")
        else:
            if not MESH_ENABLED:
                log.warning("[Gateway] 拒绝远程：跨机互联未开启 (peer=%s)", request.remote)
                raise web.HTTPForbidden(text="mesh not enabled")
            log.warning("[Gateway] 拒绝远程：token 缺失/无效 (peer=%s)", request.remote)
            raise web.HTTPUnauthorized(text="invalid or missing token")

        ws = web.WebSocketResponse(heartbeat=25.0)
        await ws.prepare(request)
        # 初始 peer 标识：优先取URL 查询参数（?provider=xxx），
        # 否则退到对端 IP。真正的 provider 以 hello 帧里的为准（见 _dispatch）。
        peer = request.query.get("provider") or request.remote or "unknown"

        try:
            async for msg in ws:
                if msg.type == WSMsgType.ERROR:
                    log.warning("[Gateway] WS 错误 %s: %s", peer, ws.exception())
                    break
                if msg.type != WSMsgType.TEXT:
                    continue
                self.touch(peer)
                try:
                    data = json.loads(msg.data)
                except Exception:
                    await ws.send_str(json.dumps({"type": "error", "error": "invalid json"}))
                    continue
                # hello 帧带provider 时用它替换 URL 推导出的临时标识
                if (data.get("type") or "") == "hello" and data.get("provider"):
                    declared = str(data["provider"]).strip()
                    if declared and declared != peer:
                        # 先摘掉旧的临时条目，再以声明的 provider 重新登记
                        self.detach(peer)
                        peer = declared
                        self.attach(peer, ws, data.get("remote", ""))
                await self._dispatch(ws, peer, data)
        finally:
            self.detach(peer)
        return ws

    async def _dispatch(self, ws: web.WebSocketResponse, peer: str, data: dict) -> None:
        t = (data.get("type") or "").strip()

        if t == "hello":
            self.attach(peer, ws, data.get("remote", ""))
            # 对端可能没走 attach（首帧就是 hello 之外的类型），这里补一次
            if peer not in self._peers:
                self.attach(peer, ws, data.get("remote", ""))
            else:
                self._peers[peer]["ws"] = ws
            caps = self._local_capabilities()
            await ws.send_str(json.dumps({
                "type": "welcome", "provider": self.provider,
                "peers": self.peer_list(), "capabilities": caps, "ts": time.time(),
            }, ensure_ascii=False))

        elif t == "subscribe":
            topics = [x for x in (data.get("topics") or []) if x in ALLOWED_TOPICS]
            p = self._peers.get(peer)
            if p is not None:
                p["subs"] = set(topics)
            await ws.send_str(json.dumps({"type": "subscribed", "topics": topics}))

        elif t == "ping":
            await ws.send_str(json.dumps({"type": "pong", "ts": time.time()}))

        elif t == "invoke":
            await self._invoke(ws, peer, data)

        else:
            await ws.send_str(json.dumps({"type": "error", "error": f"未知消息类型: {t}"}))

    async def _invoke(self, ws: web.WebSocketResponse, peer: str, data: dict) -> None:
        """被调方执行能力。**只放行 read 类**——写操作必须等requires_confirm 流程。"""
        cid = (data.get("capability") or "").strip()
        rid = data.get("id") or ""
        caps = {c["id"]: c for c in self._local_capabilities()}
        cap = caps.get(cid)
        if not cap:
            await ws.send_str(json.dumps({"type": "result", "id": rid, "ok": False,
                                          "error": f"未知能力: {cid}"}))
            return
        if cap.get("trust") != "read":
            await ws.send_str(json.dumps({
                "type": "result", "id": rid, "ok": False,
                "error": f"能力 {cid} 为 {cap.get('trust')} 级，需人工确认后才可执行",
                "requires_confirm": True}))
            return
        try:
            from desktop_core import storage as _st
            rows = _st.capability_list(provider=self.provider)
            target = next((r for r in rows if r["id"] == cid), None)
            if target and target.get("endpoint"):
                import aiohttp
                async with aiohttp.ClientSession() as s:
                    async with s.get(f"http://127.0.0.1:9845{target['endpoint']}",
                                     timeout=aiohttp.ClientTimeout(total=15)) as r:
                        payload = await r.json(content_type=None)
                await ws.send_str(json.dumps({"type": "result", "id": rid, "ok": True,
                                              "data": payload}, ensure_ascii=False))
                return
        except Exception as e:
            await ws.send_str(json.dumps({"type": "result", "id": rid, "ok": False,
                                          "error": f"{type(e).__name__}: {e}"}))

    def _local_capabilities(self) -> list:
        try:
            from desktop_core import storage as _st
            if not _st.DB_PATH:
                import os
                _st.DB_PATH = os.path.join(
                    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                    "data", "naixi_desktop.db")
            return _st.capability_list(provider=self.provider)
        except Exception as e:
            log.debug("[Gateway] 读本地能力失败: %s", e)
            return []


# 全局单例
HUB = GatewayHub()


async def handle_ws(request: web.Request) -> web.WebSocketResponse:
    return await HUB.handle(request)


def register_routes(app: web.Application) -> None:
    app.router.add_get(WS_PATH, handle_ws)
    app.router.add_get("/api/gateway/peers", lambda r: web.json_response(
        {"ok": True, "peers": HUB.peer_list(), "count": HUB.peer_count}))
