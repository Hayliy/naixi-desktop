"""connector_manager 集成测试（真实拉起 naixi_connector 子进程，全链路验证）。

验证点：
  1) 配置 seed / 保存 / 掩码；
  2) start_connector 真正拉起子进程（loopback 适配器常驻）；
  3) 连接器把状态上报给桌面（POST /api/connector/status）；
  4) 经 loopback 端点发一条消息 → 连接器调桌面 Agent(stream) → 回发原样返回；
  5) stop_connector 真杀进程。

用桌面真实 python-embed 跑：import desktop_core.storage 成功 → 写入真实 dev DB；
测试结束会还原 connector_config，不污染开发环境。
"""

import asyncio
import json
import sys

# 确保能 import desktop_core
sys.path.insert(0, r"D:\数据\naixi_desktop")

from aiohttp import web  # noqa: E402

from desktop_core import connector_manager as cm  # noqa: E402


_STATUS_RECEIVED = []


async def _fake_status(request: web.Request):
    try:
        body = await request.json()
    except Exception:
        body = {}
    _STATUS_RECEIVED.append(body)
    return web.json_response({"ok": True})


async def _fake_agent_stream(request: web.Request):
    try:
        body = await request.json()
    except Exception:
        body = {}
    text = (body.get("text") or "")
    resp = web.StreamResponse()
    resp.content_type = "text/event-stream"
    await resp.prepare(request)
    await resp.write(f"event: text-delta\ndata: {json.dumps({'text': 'echo: ' + text}, ensure_ascii=False)}\n\n".encode("utf-8"))
    await resp.write(b"event: finish\ndata: {}\n\n")
    await resp.write_eof()
    return resp


async def _run():
    # 启动假桌面服务器（承接状态上报 + Agent stream）
    app = web.Application()
    app.router.add_post("/api/connector/status", _fake_status)
    app.router.add_post("/api/agent/stream", _fake_agent_stream)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 18899)
    await site.start()

    # 备份原始配置，测试后还原（不污染 dev DB）
    original = cm.get_config()

    try:
        # —— 1) seed / 掩码 ——
        cfg = cm._default_config()
        cfg["desktop"]["base_url"] = "http://127.0.0.1:18899"
        cfg["adapters"]["loopback"]["enabled"] = True
        cfg["adapters"]["feishu"]["enabled"] = False  # 关掉外部网络，纯本地验证
        cm.save_config(cfg)
        masked = cm.get_masked_config()
        assert masked["adapters"]["loopback"]["enabled"] is True, "loopback 应启用"
        print("[OK] 配置保存 + 掩码正确")

        # —— 2) 拉起子进程 ——
        r = await cm.start_connector(force=True)
        assert r.get("pid"), "应返回 pid"
        await asyncio.sleep(2.5)
        assert cm.is_running(), "连接器应处于运行中"
        print(f"[OK] 已拉起连接器子进程 pid={r['pid']}")

        # —— 3) 状态上报 ——
        for _ in range(25):
            if _STATUS_RECEIVED:
                break
            await asyncio.sleep(0.3)
        assert _STATUS_RECEIVED, "连接器应已上报状态到桌面"
        print("[OK] 连接器已向桌面上报连接状态")

        # —— 4) 经 loopback 端点发消息，验证 连接器↔桌面 Agent 全链路 ——
        import aiohttp as _aio

        async with _aio.ClientSession() as s:
            async with s.post(
                "http://127.0.0.1:19876/in",
                json={"text": "你好", "user": "tester"},
                timeout=_aio.ClientTimeout(total=30),
            ) as resp:
                j = await resp.json()
                reply = j.get("reply", "")
        assert "echo: 你好" in reply, f"回发内容异常: {reply!r}"
        print(f"[OK] 全链路打通：loopback → 桌面 Agent → 回发 = {reply!r}")

        # —— 5) 停止 ——
        await cm.stop_connector()
        await asyncio.sleep(1.0)
        assert not cm.is_running(), "停止后不应再运行"
        print("[OK] 已停止连接器子进程")
    finally:
        # 还原开发环境配置
        try:
            cm.save_config(original)
        except Exception as e:
            print(f"[WARN] 还原配置失败: {e}")
        await runner.cleanup()

    print("\n>>> connector_manager_test PASSED")


if __name__ == "__main__":
    asyncio.run(_run())
