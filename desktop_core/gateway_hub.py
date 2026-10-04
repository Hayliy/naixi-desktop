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
        origin = request.headers.get("Origin", "")
        if not _origin_allowed(origin):
            log.warning("[Gateway] 拒绝来源: %s", origin)
            raise web.HTTPForbidden(text="origin not allowed")

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
