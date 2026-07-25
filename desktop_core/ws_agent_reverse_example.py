"""远端 agent 反向连入奶昔引擎的示例客户端（ws 服务端热插拔）。

演示：远端 agent 主动连到引擎的 GET /api/live/ws_agent（引擎作为 ws 服务端），
握手鉴权通过后自动"上台"；之后响应引擎下发的弹幕 / 舞台提示请求；断开即"下台"，
实现真正的热插拔（远端上下线不需改引擎配置、不需引擎重启）。

运行（用奶昔自带的嵌入式 Python，已含 aiohttp）：
  src-tauri/resources/python-embed/python.exe desktop_core/ws_agent_reverse_example.py

环境变量：
  NAIXI_ENGINE_WS       反向连入端点，默认 ws://127.0.0.1:9845/api/live/ws_agent
  NAIXI_AGENT_ID        角色 id，默认 example_agent
  NAIXI_AGENT_NAME      显示名，默认 示例副播
  NAIXI_AGENT_PRIORITY  占麦优先级（数值越大越优先），默认 50
  NAIXI_LIVE_WS_SECRET  反向连入密钥（必须与引擎侧 live_ws_secret 一致），必填

注意：真实 agent 请自行实现 build_reply 里的模型 / 业务逻辑，并做好节流——
引擎 ConnectorGuard 会对短时间高频发言做限流隔离（且隔离状态已持久化，重启仍隔离）。
"""
import asyncio
import json
import logging
import os
import signal

import aiohttp

log = logging.getLogger("ws_agent_example")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s", datefmt="%H:%M:%S")


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default)


async def run_once(url: str, agent_id: str, name: str, token: str, priority: int) -> bool:
    """单次连接生命周期：注册握手 -> 处理引擎请求 -> 直到断开。返回是否成功上台。"""
    async with aiohttp.ClientSession() as session:
        async with session.ws_connect(url, heartbeat=20.0) as ws:
            # 1) 注册握手（首帧必须是 register）
            await ws.send_json({
                "type": "register",
                "agent_id": agent_id,
                "name": name,
                "token": token,
                "priority": priority,
            })

            registered = False
            # 2) 读循环
            async for msg in ws:
                if msg.type == aiohttp.WSMsgType.TEXT:
                    try:
                        m = json.loads(msg.data)
                    except Exception:
                        continue
                    mtype = m.get("type") or ""
                    if mtype == "register_ack":
                        if m.get("ok"):
                            registered = True
                            log.info("注册成功，已上台：%s(%s)", name, agent_id)
                        else:
                            log.error("注册被拒：%s", m.get("error", ""))
                            return False
                    elif mtype == "request":
                        # 引擎问：这条弹幕 / 舞台提示接不接？
                        kind = m.get("kind")
                        req_id = m.get("req_id")
                        data = m.get("data") or {}
                        text = (data.get("text") or "").strip()
                        log.info("[请求 %s] %s: %s", kind, req_id, text[:40])
                        reply = build_reply(kind, data)
                        if reply is None:
                            # 不接话：明确告诉引擎放弃本轮
                            await ws.send_json({"type": "reply", "req_id": req_id, "data": {"ok": False}})
                        else:
                            await ws.send_json({"type": "reply", "req_id": req_id, "data": reply})
                    elif mtype == "ping":
                        # 应用层心跳：服务端发 ping，客户端回 pong
                        await ws.send_json({"type": "pong"})
                elif msg.type in (aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.CLOSE,
                                  aiohttp.WSMsgType.ERROR):
                    break
            return registered


def build_reply(kind: str, data: dict):
    """按请求类型生成回复。

    返回 {text, emotion, action} 表示接话；返回 None 表示不接话。
    真实 agent 请把这里的示例逻辑换成你自己的模型 / 业务。
    """
    text = (data.get("text") or "").strip()
    if not text:
        return None
    if kind == "danmaku":
        # 示例：把观众弹幕原样复述（真实 agent 这里换成你自己的生成逻辑）
        return {"text": f"刚才有人说到：{text}", "emotion": "开心", "action": ""}
    if kind == "cue":
        # 舞台提示：其他角色说了什么，问你要不要接话
        return {"text": f"我接一句：{text}", "emotion": "普通", "action": ""}
    return None


async def main():
    url = _env("NAIXI_ENGINE_WS", "ws://127.0.0.1:9845/api/live/ws_agent")
    agent_id = _env("NAIXI_AGENT_ID", "example_agent")
    name = _env("NAIXI_AGENT_NAME", "示例副播")
    token = _env("NAIXI_LIVE_WS_SECRET", "")
    priority = int(_env("NAIXI_AGENT_PRIORITY", "50"))

    if not token:
        log.error("缺少 NAIXI_LIVE_WS_SECRET（反向连入密钥），无法连入。"
                  "请先在引擎侧配置 live_ws_secret（或设环境变量 NAIXI_LIVE_WS_SECRET）。")
        return

    stop = asyncio.Event()
    loop = asyncio.get_event_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop.set)
        except (NotImplementedError, ValueError):
            pass

    backoff = 1
    while not stop.is_set():
        try:
            log.info("连接引擎：%s", url)
            ok = await run_once(url, agent_id, name, token, priority)
        except Exception as e:  # 网络抖动 / 引擎未起，自动重连
            log.warning("连接异常：%s", e)
            ok = None
        # 注册被拒（密钥错 / 被限流隔离）则放慢重连；成功过则快速重连
        backoff = 1 if ok is not False else min(backoff * 2, 30)
        if stop.is_set():
            break
        log.info("%d 秒后重连…", backoff)
        try:
            await asyncio.wait_for(stop.wait(), timeout=backoff)
        except asyncio.TimeoutError:
            pass
    log.info("已退出。")


if __name__ == "__main__":
    asyncio.run(main())
