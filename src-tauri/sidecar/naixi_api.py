"""
奶昔桌面后端 — Tauri sidecar 入口
完全独立自包含，不依赖 QQ 机器人后端的任何文件。
"""
import sys, os, asyncio, logging, subprocess, time
from logging.handlers import RotatingFileHandler

# 日志文件（崩溃时也能查到原因）
LOG_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "logs")
os.makedirs(LOG_DIR, exist_ok=True)
os.makedirs(LOG_DIR, exist_ok=True)
LOG_FILE = os.path.join(LOG_DIR, "naixi_desktop.log")
_handler = RotatingFileHandler(LOG_FILE, maxBytes=5*1024*1024, backupCount=3, encoding="utf-8")
_handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s"))
logging.getLogger().addHandler(_handler)
logging.getLogger().setLevel(logging.INFO)

# 桌面端核心模块路径
DESKTOP_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if DESKTOP_DIR not in sys.path:
    sys.path.insert(0, DESKTOP_DIR)

# 数据库路径
DESKTOP_DATA_DIR = os.path.join(DESKTOP_DIR, "data")
os.makedirs(DESKTOP_DATA_DIR, exist_ok=True)
DESKTOP_DB = os.path.join(DESKTOP_DATA_DIR, "naixi_desktop.db")

# ── 内置 SearXNG ──
SEARXNG_DIR = os.path.join(DESKTOP_DIR, "searxng")
SEARXNG_EXE = os.path.join(SEARXNG_DIR, "SearXNG for Windows.exe")
SEARXNG_PORT = 8899  # 桌面端用 8899，和奶昔后端的 8898 不冲突
_searxng_proc = None


def _start_searxng():
    """启动内置 SearXNG（如果可执行文件存在）"""
    global _searxng_proc
    if not os.path.exists(SEARXNG_EXE):
        log.warning(f"SearXNG 未安装，搜索将使用降级方案")
        return
    try:
        import subprocess as _sp
        startup_kw = {}
        if os.name == "nt":
            startup_kw["creationflags"] = _sp.CREATE_NO_WINDOW
        _searxng_proc = _sp.Popen(
            [SEARXNG_EXE],
            cwd=SEARXNG_DIR,
            stdout=_sp.DEVNULL,
            stderr=_sp.DEVNULL,
            **startup_kw,
        )
        log.info(f"SearXNG 已启动 (PID={_searxng_proc.pid})")
        # 等待端口可用
        for i in range(10):
            time.sleep(0.5)
            try:
                import urllib.request
                urllib.request.urlopen(f"http://127.0.0.1:{SEARXNG_PORT}", timeout=2)
                log.info(f"SearXNG 就绪: http://127.0.0.1:{SEARXNG_PORT}")
                return
            except:
                continue
        log.warning("SearXNG 启动超时")
    except Exception as e:
        log.warning(f"SearXNG 启动失败: {e}")
    _searxng_proc = None


def _stop_searxng():
    """关闭 SearXNG"""
    global _searxng_proc
    if _searxng_proc and _searxng_proc.poll() is None:
        _searxng_proc.terminate()
        try:
            _searxng_proc.wait(timeout=5)
        except:
            _searxng_proc.kill()
        log.info("SearXNG 已停止")

# ── 模块打补丁：让 desktop_core.workflow_engine 使用正确的 storage/config ──
import desktop_core.storage as desktop_storage
import desktop_core.config as desktop_config
desktop_storage.DB_PATH = DESKTOP_DB

# 伪装 core 包，让 workflow_engine 的 `from core import storage` 能正确解析
import types
_core_pkg = types.ModuleType("core")
_core_pkg.__path__ = []  # 标记为包
_core_pkg.__package__ = "core"
sys.modules["core"] = _core_pkg
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

    # 启动内置 SearXNG（如果存在）
    _start_searxng()

    # 自动连接 MCP 服务器（自动补全 npx 路径）
    try:
        # 将 managed Node.js 加入 PATH，让 MCP 子进程能找到 npx
        node_bin = os.path.dirname(sys.executable) if "python" in sys.executable else ""
        node_bin_dir = os.path.dirname(r"C:\Users\21222\.workbuddy\binaries\node\versions\22.22.2\npx")
        if node_bin_dir not in os.environ.get("PATH", ""):
            os.environ["PATH"] = node_bin_dir + os.pathsep + os.environ.get("PATH", "")
        from desktop_core.tools import connect_mcp_servers
        mcp_count = await connect_mcp_servers()
        if mcp_count > 0:
            log.info(f"MCP: {mcp_count} 个服务器已自动连接")
    except Exception as e:
        log.warning(f"MCP 自动连接失败: {e}")

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
    site = web.TCPSite(runner, "127.0.0.1", 9845, reuse_address=True)
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
    finally:
        _stop_searxng()
