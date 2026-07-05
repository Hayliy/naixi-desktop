"""
奶昔桌面后端 — Tauri sidecar 入口
完全独立自包含，不依赖 QQ 机器人后端的任何文件。
"""
import sys, os, asyncio, logging

# 桌面端核心模块路径
DESKTOP_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if DESKTOP_DIR not in sys.path:
    sys.path.insert(0, DESKTOP_DIR)

# 数据库路径
DESKTOP_DATA_DIR = os.path.join(DESKTOP_DIR, "data")
os.makedirs(DESKTOP_DATA_DIR, exist_ok=True)
DESKTOP_DB = os.path.join(DESKTOP_DATA_DIR, "naixi_desktop.db")

# ── 模块打补丁：让 desktop_core.workflow_engine 使用正确的 storage/config ──
import desktop_core.storage as desktop_storage
import desktop_core.config as desktop_config
desktop_storage.DB_PATH = DESKTOP_DB
sys.modules["core.storage"] = desktop_storage
sys.modules["config"] = desktop_config

# ── 服务启动 ──

logging.basicConfig(level=logging.INFO, format="[%(asctime)s] %(message)s", datefmt="%H:%M:%S")
log = logging.getLogger("桌面端")

async def main():
    from aiohttp import web
    from desktop_core.api import setup_routes

    # 初始化桌面端数据表
    desktop_storage.init_tables()

    @web.middleware
    async def cors_middleware(request, handler):
        if request.method == "OPTIONS":
            return web.Response(headers={
                "Access-Control-Allow-Origin": "*",
                "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
                "Access-Control-Allow-Headers": "Content-Type",
            })
        resp = await handler(request)
        resp.headers["Access-Control-Allow-Origin"] = "*"
        return resp

    app = web.Application(middlewares=[cors_middleware])
    setup_routes(app)

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 9845)
    await site.start()
    log.info(f"桌面端已启动: http://127.0.0.1:9845")
    log.info(f"数据库: {DESKTOP_DB}")

    while True:
        await asyncio.sleep(3600)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        log.info("桌面端已停止")
