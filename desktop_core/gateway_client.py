"""出站网关拨号：主动连入其他奶昔设备（对端作为 server），补齐「跨设备接入」仅有被动接收的短板。

设计要点：
  - 与 GatewayHub（WS 服务端）对称：本模块是 WS 客户端，拨号到对端的 /ws/gateway，
    走同一套 hello/welcome/subscribe/ping/invoke 协议 —— 对端会把它当成一条普通入站 peer。
  - 连接后本端即可「调用对端能力」（对端 _invoke 仅放行 read 级，与入站 peer 一致），
    对端也会在它的 peer 列表里看到本端；本端在「已连接对端」里以「我主动接入」标注。
  - token 走 URL ?token=xxx（与对端 _client_token 解析一致）；provider 用本端 HUB.provider，
    对端是独立 hub 实例，不会与本端自身冲突。
  - 自动重连：断线后按退避间隔重试（auto_connect=True 时），保证对端重启/网络抖动后自愈。
  - 配置持久化到 data/gateway_remotes.json：label / url / token / auto_connect，重启后端不丢。
"""
import asyncio
import json
import logging
import os
import time
from typing import Optional

log = logging.getLogger("gateway.client")

_REMOTES_FILE: Optional[str] = None
_REMOTES: dict[str, "RemotePeer"] = {}

PROVIDER = "desktop-9845"  # 与 gateway_hub.HUB.provider 对齐；对端是独立实例，不会冲突


def _humanize_error(e: Exception) -> str:
    """把底层异常翻译成用户能看懂的中文。

    铁则：不把 `WSServerHandshakeError: 401, message='Invalid response status'`
    这种英文异常直接摆到界面上 —— 用户看不懂，也不知道该改哪里。
    """
    name = type(e).__name__
    txt = str(e)
    code = ""
    try:
        import aiohttp
        if isinstance(e, aiohttp.WSServerHandshakeError):
            code = str(getattr(e, "status", "") or "")
    except Exception:
        pass
    if not code:
        import re as _re
        m = _re.search(r"\b(401|403|404|500|502|503)\b", txt)
        code = m.group(1) if m else ""
    if code == "401":
        return "口令不对（对方拒绝了连接，请核对「开放接入」里的连接口令）"
    if code == "403":
        return "对方没有开启「允许其他设备连接」"
    if code == "404":
        return "地址不对：该端口上没有互联服务（确认对方端口，通常是 18400）"
    if name in ("ClientConnectorError", "ClientConnectorDNSError"):
        return "连不上对方：地址或端口不通（检查 IP、端口，以及对方防火墙）"
    if name in ("ServerTimeoutError", "ConnectionTimeoutError", "TimeoutError", "asyncio.TimeoutError"):
        return "连接超时：对方没有响应"
    if name in ("ClientConnectorCertificateError", "ClientConnectorSSLError"):
        return "对方的证书不受信任（wss 需要有效证书）"
    if code:
        return f"对方拒绝连接（HTTP {code}）"
    return f"连接失败：{txt[:80]}"


def _remotes_path() -> str:
    global _REMOTES_FILE
    if _REMOTES_FILE is None:
        # 与其它模块同源：走 config.DATA_DIR（<core>/../data），保证落盘位置一致，
        # 不额外造一个没人管的目录。取不到就退回相对 desktop_core 的 data。
        try:
            from desktop_core import config as _cfg
            base = _cfg.DATA_DIR
        except Exception:
            base = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data")
        _REMOTES_FILE = os.path.abspath(os.path.join(base, "gateway_remotes.json"))
    return _REMOTES_FILE


def _load_store() -> list:
    try:
        if os.path.exists(_remotes_path()):
            with open(_remotes_path(), "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, list):
                    return data
    except Exception as e:
        log.warning("[GatewayClient] 读取远端列表失败: %s", e)
    return []


def _save_store() -> None:
    try:
        os.makedirs(os.path.dirname(_remotes_path()), exist_ok=True)
        with open(_remotes_path(), "w", encoding="utf-8") as f:
            json.dump([
                {"label": r.label, "url": r.url, "token": r.token, "auto_connect": r.auto_connect}
                for r in _REMOTES.values()
            ], f, ensure_ascii=False, indent=2)
    except Exception as e:
        log.warning("[GatewayClient] 保存远端列表失败: %s", e)


class RemotePeer:
    """单个出站对端连接（异步管理）。"""

    def __init__(self, label: str, url: str, token: str, auto_connect: bool = True):
        self.label = label
        self.url = url
        self.token = token
        self.auto_connect = auto_connect
        self.ws = None
        self.state = "disconnected"  # disconnected | connecting | connected
        self.error = ""
        self.remote_caps: list = []
        self.remote_peers: list = []
        self.last_seen = 0.0
        self._task: Optional[asyncio.Task] = None
        self._req_id = 0
        self._pending: dict[str, asyncio.Future] = {}

    def to_dict(self) -> dict:
        return {
            "label": self.label,
            "url": self.url,
            "state": self.state,
            "error": self.error,
            "auto_connect": self.auto_connect,
            "capabilities": self.remote_caps,
            "peer_count": len(self.remote_peers),
            "last_seen": self.last_seen,
        }

    async def _send(self, msg: dict) -> None:
        if self.ws is not None and not self.ws.closed:
            try:
                await self.ws.send_str(json.dumps(msg, ensure_ascii=False))
            except Exception as e:
                log.debug("[GatewayClient] 发送失败 %s: %s", self.label, e)

    def _next_id(self) -> str:
        self._req_id += 1
        return f"c{self._req_id}"

    def _fail_pending(self, reason: str) -> None:
        """断线时让所有在飞的调用立刻失败，而不是让调用方一直等到超时。"""
        for rid, fut in list(self._pending.items()):
            if not fut.done():
                fut.set_result({"ok": False, "error": reason})
        self._pending.clear()

    async def invoke(self, capability: str, params: dict | None = None, timeout: float = 20.0):
        """调用对端某条能力，等待 result。返回对端回包的 data/error。"""
        rid = self._next_id()
        fut: asyncio.Future = asyncio.get_running_loop().create_future()
        self._pending[rid] = fut
        await self._send({"type": "invoke", "capability": capability, "id": rid,
                          "params": params or {}})
        try:
            return await asyncio.wait_for(fut, timeout=timeout)
        except asyncio.TimeoutError:
            self._pending.pop(rid, None)
            return {"ok": False, "error": "调用超时（对端无响应）"}

    async def _handle(self, data: dict) -> None:
        t = (data.get("type") or "").strip()
        if t == "welcome":
            self.remote_caps = data.get("capabilities") or []
            self.remote_peers = data.get("peers") or []
            self.last_seen = time.time()
            log.info("[GatewayClient] %s 已连入，对方能力 %d 条", self.label, len(self.remote_caps))
        elif t == "result":
            rid = str(data.get("id") or "")
            fut = self._pending.pop(rid, None)
            if fut is not None and not fut.done():
                fut.set_result(data)
        elif t == "pong":
            self.last_seen = time.time()
        elif t == "event":
            self.last_seen = time.time()
            # 对端广播（如任务完成）：暂仅刷新心跳，前端可后续扩展订阅展示
        elif t == "subscribed":
            self.last_seen = time.time()

    async def _run(self) -> None:
        backoff = 2
        while True:
            if not self.auto_connect and self.state == "disconnected":
                await asyncio.sleep(3600)
                continue
            self.state = "connecting"
            try:
                import aiohttp
                from desktop_core import gateway_hub as _gh
                sep = "?" if "?" not in self.url else "&"
                conn_url = (f"{self.url}{sep}provider={_gh.HUB.provider}"
                           f"&token={self.token}" if self.token else f"{self.url}{sep}provider={_gh.HUB.provider}")
                async with aiohttp.ClientSession() as session:
                    async with session.ws_connect(conn_url, timeout=aiohttp.ClientTimeout(total=15)) as ws:
                        self.ws = ws
                        self.state = "connected"
                        self.error = ""
                        backoff = 2
                        await self._send({"type": "hello", "provider": _gh.HUB.provider,
                                         "remote": "desktop"})
                        async for msg in ws:
                            if msg.type == aiohttp.WSMsgType.TEXT:
                                try:
                                    data = json.loads(msg.data)
                                except Exception:
                                    continue
                                await self._handle(data)
                            elif msg.type in (aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.ERROR):
                                break
                # 正常退出循环（对端关闭）也要让在飞调用立刻失败
                self._fail_pending("连接已断开")
            except Exception as e:
                self.state = "disconnected"
                self.error = _humanize_error(e)
                self.ws = None
                self._fail_pending(self.error)
                log.warning("[GatewayClient] %s 连接失败/中断: %s", self.label, e)
            # 断线退避重连（2s 起，封顶 30s）
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 30)

    def start(self) -> None:
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._run())

    async def stop(self) -> None:
        self.auto_connect = False
        if self.ws is not None and not self.ws.closed:
            try:
                await self.ws.close()
            except Exception:
                pass
        if self._task is not None and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except Exception:
                pass
        self._task = None
        self.ws = None
        self.state = "disconnected"


def list_remotes() -> list:
    return [r.to_dict() for r in _REMOTES.values()]


def add_remote(label: str, url: str, token: str, auto_connect: bool = True) -> dict:
    """新增/更新一个出站对端并立即拨号。返回当前全量列表。"""
    label = (label or "").strip()
    url = (url or "").strip()
    token = (token or "").strip()
    if not label:
        return {"ok": False, "error": "名称不能为空"}
    if not url.lower().startswith(("ws://", "wss://")):
        return {"ok": False, "error": "对端地址必须以 ws:// 或 wss:// 开头"}
    if _REMOTES.get(label) is not None:
        # 同名：先停旧连接再重建
        asyncio.create_task(_REMOTES[label].stop())
        _REMOTES.pop(label, None)
    rp = RemotePeer(label=label, url=url, token=token, auto_connect=auto_connect)
    _REMOTES[label] = rp
    rp.start()
    _save_store()
    return {"ok": True, "remotes": list_remotes()}


def remove_remote(label: str) -> dict:
    rp = _REMOTES.pop(label, None)
    if rp is not None:
        asyncio.create_task(rp.stop())
        _save_store()
        return {"ok": True, "remotes": list_remotes()}
    return {"ok": False, "error": f"未找到对端: {label}"}


def init_remotes() -> None:
    """后端启动时调用：载入持久化配置并自动拨号 auto_connect 的项。"""
    for item in _load_store():
        label = item.get("label")
        if not label:
            continue
        rp = RemotePeer(
            label=label,
            url=item.get("url", ""),
            token=item.get("token", ""),
            auto_connect=bool(item.get("auto_connect", True)),
        )
        _REMOTES[label] = rp
        if rp.auto_connect and rp.url:
            rp.start()
    log.info("[GatewayClient] 已载入 %d 个出站对端", len(_REMOTES))
