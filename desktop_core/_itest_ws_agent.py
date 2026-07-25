"""ws 反向连入真链路集成测试（真实 aiohttp 服务端 + 真实示例客户端）

不依赖重型 api.py：服务端用真实 WsServerConnector + 真实 ConnectorGuard + 与 live_engine
一致的 transport 映射逻辑挂载最小 aiohttp 应用；客户端直接复用 ws_agent_reverse_example
的 run_once（真实反向连入代码）。覆盖：
  1) 反向连入 -> 引擎列表出现 ws-in 类型（已上台）
  2) 引擎问弹幕 -> 远端回话（双向通信）
  3) 断开 -> 引擎列表移除（热插拔下台）
  4) 刷屏 -> 隔离落 SQLite
  5) 模拟重启（新 Engine 复用同一 SQLite）-> 仍隔离（不洗白）

运行（沙箱/本机均可，需嵌入式 Python 自带 aiohttp）：
    src-tauri/resources/python-embed/python.exe -m desktop_core._itest_ws_agent

前置：引擎侧已配置 live_ws_secret（本测试直接读 storage.meta_get）。
"""

import asyncio
import json
import os
import sys
import tempfile
import sqlite3
import hmac
import logging

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import aiohttp
from aiohttp import web, WSMsgType

from desktop_core.live_bus import (
    WsServerConnector, HttpAgentConnector, WsAgentConnector, ConnectorGuard,
)
from desktop_core.ws_agent_reverse_example import run_once

AGENT = "itest_agent"
PORT = 9846
DB_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                       "data", "naixi_desktop.db")

SECRET = ""  # 在 run() 内从 storage 读取

# 隔离持久化用独立临时 SQLite（不污染生产库），但用真 SQLite 引擎可模拟重启
_tmp = os.path.join(tempfile.gettempdir(), "naixi_itest_quota.db")
if os.path.exists(_tmp):
    os.remove(_tmp)
_tc = sqlite3.connect(_tmp)
_tc.execute("CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT)")
_tc.commit()


def meta_get(k, d=""):
    r = _tc.execute("SELECT value FROM meta WHERE key=?", (k,)).fetchone()
    return r[0] if r else d


def meta_set(k, v):
    _tc.execute("INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)", (k, v))
    _tc.commit()


class _FakeConn:
    def __init__(self, agent_id):
        self.agent_id = agent_id
        self.endpoint = ""
        self.token = ""


class Engine:
    """最小引擎桩：行为对齐 live_engine 的 register/unregister/list_connectors。"""

    def __init__(self):
        self.connectors = []
        self.guard = ConnectorGuard(require_token_for_remote=False,
                                    mem_get=meta_get, mem_set=meta_set)

    def register_connector(self, c):
        self.guard.check_register(c)  # 真实治理：注册前恢复隔离
        self.connectors.append(c)

    def unregister_connector(self, agent_id):
        self.connectors = [c for c in self.connectors
                           if getattr(c, "agent_id", "") != agent_id]

    def list_connectors(self):
        out = []
        for c in self.connectors:
            if isinstance(c, WsServerConnector):
                t = "ws-in"
            elif isinstance(c, HttpAgentConnector):
                t = "http"
            elif isinstance(c, WsAgentConnector):
                t = "ws"
            else:
                t = "local"
            out.append({
                "agent_id": c.agent_id, "name": c.name, "transport": t,
                "builtin": getattr(c, "builtin", False),
                "quarantined": self.guard.is_quarantined(c.agent_id),
            })
        return out


engine = Engine()


async def handler(request):
    if not SECRET:
        return web.Response(status=503, text="未配置 live_ws_secret")
    ws = web.WebSocketResponse(heartbeat=30.0)
    await ws.prepare(request)
    agent_id = name = token = None
    try:
        msg = await ws.receive_json(timeout=15)
        if msg.get("type") != "register":
            await ws.close()
            return ws
        agent_id = msg.get("agent_id")
        name = msg.get("name")
        token = msg.get("token")
        if not agent_id or not name:
            await ws.close()
            return ws
        if not hmac.compare_digest(str(token), str(SECRET)):
            await ws.close()
            return ws
        conn = WsServerConnector(agent_id, name, ws,
                                priority=msg.get("priority", 1), token=token)
        engine.register_connector(conn)
        await ws.send_json({"type": "register_ack", "ok": True})
        async for m in ws:
            if m.type == WSMsgType.TEXT:
                try:
                    d = json.loads(m.data)
                except Exception:
                    continue
                if d.get("type") == "reply":
                    conn.feed_reply(d.get("req_id"), d.get("data"))
                elif d.get("type") == "pong":
                    pass
            elif m.type in (WSMsgType.CLOSE, WSMsgType.CLOSING,
                            WSMsgType.CLOSED, WSMsgType.ERROR):
                break
    finally:
        if agent_id:
            engine.unregister_connector(agent_id)
    return ws


failures = []


def check(c, msg):
    print(("  [PASS] " if c else "  [FAIL] ") + msg)
    if not c:
        failures.append(msg)


async def run():
    global SECRET
    import desktop_core.storage as _storage
    _storage.DB_PATH = DB_PATH
    SECRET = _storage.meta_get("live_ws_secret", "")
    if not SECRET:
        print("  [FAIL] 未配置 live_ws_secret，请先配置后重跑")
        return 1

    app = web.Application()
    app.router.add_get("/api/live/ws_agent", handler)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", PORT)
    await site.start()
    print(f"服务端已起：ws://127.0.0.1:{PORT}/api/live/ws_agent")

    url = f"ws://127.0.0.1:{PORT}/api/live/ws_agent"

    # 1) 客户端连入
    client_task = asyncio.create_task(
        run_once(url, AGENT, "集成测试副播", SECRET, 50))
    await asyncio.sleep(1.5)
    lst = engine.list_connectors()
    check(any(c["agent_id"] == AGENT and c["transport"] == "ws-in" for c in lst),
          "客户端连入后，引擎列表含 ws-in 类型连接器（已上台）")

    # 2) 引擎问 -> 远端答（双向通信）
    conn = next(c for c in engine.connectors if c.agent_id == AGENT)
    resp = await conn.handle_danmaku({"text": "大家好"})
    check(resp is not None and "大家好" in (resp.get("text") or ""),
          f"引擎问弹幕，远端回话成功：{resp}")

    # 3) 断开 -> 下台（热插拔）
    await conn.close()
    await asyncio.sleep(0.4)
    lst2 = engine.list_connectors()
    check(not any(c["agent_id"] == AGENT for c in lst2),
          "客户端断开后，引擎列表已无该连接器（热插拔下台）")
    try:
        await asyncio.wait_for(client_task, timeout=3)
    except asyncio.TimeoutError:
        client_task.cancel()
    check(client_task.done(), "客户端连接任务已退出")

    # 4) 刷屏 -> 隔离落 SQLite
    for _ in range(21):
        engine.guard.allow_emit(AGENT)
    check(engine.guard.is_quarantined(AGENT), "刷屏触发隔离")
    check(meta_get(f"live_q:{AGENT}") != "", "隔离状态已写入 SQLite")

    # 5) 模拟重启：新 Engine 复用同一 SQLite -> 仍隔离
    e2 = Engine()
    e2.guard.check_register(_FakeConn(AGENT))
    check(e2.guard.is_quarantined(AGENT), "重启后隔离仍在（不洗白）")

    _tc.close()
    if os.path.exists(_tmp):
        os.remove(_tmp)
    await runner.cleanup()

    print("")
    if failures:
        print(f"结果：{len(failures)} 项 FAIL")
        for f in failures:
            print(f"  - {f}")
        return 1
    print("结果：全部 PASS")
    return 0


if __name__ == "__main__":
    logging.disable(logging.CRITICAL)
    sys.exit(asyncio.run(run()))
