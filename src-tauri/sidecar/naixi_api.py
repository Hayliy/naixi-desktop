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
        mcp_count = await asyncio.wait_for(connect_mcp_servers(), timeout=8)
        if mcp_count > 0:
            log.info(f"MCP: {mcp_count} 个服务器已自动连接")
    except asyncio.TimeoutError:
        log.warning("MCP 自动连接超时（跳过）")
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

    # ── 自动化调度器 ──
    async def automation_scheduler():
        """精确到秒的自动化调度器，执行保护 + 有效期检查 + 可配置模型"""
        from desktop_core.storage import (
            automation_get_active, automation_add_run, automation_save, decrypt_config, meta_get
        )
        import aiohttp, re

        # 执行中任务保护（防止重复触发）
        _running: set[str] = set()

        async def _call_llm(prompt: str, model_cfg: dict | None) -> str:
            """调 LLM 并返回回复，支持指定模型"""
            api_key = api_url = model_name = ""
            if model_cfg:
                api_key = model_cfg.get("api_key", "")
                api_url = model_cfg.get("api_url", "")
                model_name = model_cfg.get("model", "")
            if not all([prompt, api_key, api_url]):
                # 降级到默认 provider
                raw = meta_get("desktop_config")
                cfg = json.loads(raw) if raw else {}
                decrypt_config(cfg)
                for pid, pcfg in (cfg.get("api_providers") or {}).items():
                    if pcfg.get("type", "chat") == "chat" and pcfg.get("api_key") and pcfg.get("api_url"):
                        api_key, api_url, model_name = pcfg["api_key"], pcfg["api_url"], pcfg.get("model", "")
                        break
            if not all([prompt, api_key, api_url]):
                return ""
            try:
                headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
                payload = {"model": model_name or "default", "messages": [{"role": "user", "content": prompt}], "max_tokens": 1024}
                async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=30)) as sess:
                    async with sess.post(api_url.rstrip("/") + "/chat/completions", headers=headers, json=payload) as resp:
                        if resp.status == 200:
                            data = await resp.json()
                            return data.get("choices", [{}])[0].get("message", {}).get("content", "")[:200]
            except: pass
            return ""

        def _find_provider_for_model(model_name: str) -> dict | None:
            """根据模型名查找对应的 provider 配置"""
            raw = meta_get("desktop_config")
            if not raw:
                return None
            cfg = json.loads(raw)
            decrypt_config(cfg)
            for pid, pcfg in (cfg.get("api_providers") or {}).items():
                if pcfg.get("model") == model_name or pcfg.get("type", "chat") == "chat":
                    if pcfg.get("api_key") and pcfg.get("api_url"):
                        return pcfg
            return None

        def _save_to_conv(name: str, prompt: str, reply: str):
            try:
                from desktop_core.storage import conv_save_message_sync
                key = f"auto:{''.join(c if c.isalnum() or c in ' _-' else '_' for c in name)[:30]}"
                conv_save_message_sync(key, "user", f"[自动化] {prompt}")
                conv_save_message_sync(key, "assistant", reply or "执行完成")
            except Exception as e:
                log.warning(f"写入自动化对话失败: {e}")

        async def _execute_one(auto: dict):
            """执行单个自动化任务"""
            aid = auto["id"]
            if aid in _running:
                log.info(f"自动化跳过: {auto['name']} 正在执行中")
                return
            _running.add(aid)
            try:
                prompt = auto.get("prompt", "")
                model_name = auto.get("model", "")
                provider = _find_provider_for_model(model_name) if model_name else None
                reply = await _call_llm(prompt, provider)
                automation_add_run(aid, "success", prompt=prompt, reply=reply or "", model_used=model_name or "default")
                _save_to_conv(auto.get("name", "自动化"), prompt, reply)
                log.info(f"自动化执行: {auto['name']} ✅")
                # 一次性任务执行后标记过期
                if auto.get("schedule_type") == "once":
                    auto["status"] = "expired"
                    automation_save(auto)
            except Exception as e:
                automation_add_run(aid, "failed", prompt=auto.get("prompt", ""), error=str(e))
                log.warning(f"自动化执行失败: {auto['name']}: {e}")
            finally:
                _running.discard(aid)

        while True:
            try:
                # 计算下次需要执行的时间（精确调度）
                now_ts = time.time()
                next_due = 60.0  # 默认 60 秒兜底

                active = automation_get_active()
                for auto in active:
                    sched_type = auto.get("schedule_type", "once")
                    if sched_type == "once":
                        scheduled = auto.get("scheduled_at", "").replace("T", " ")
                        if scheduled:
                            try:
                                t = time.mktime(time.strptime(scheduled, "%Y-%m-%d %H:%M"))
                                if t <= now_ts + 1:
                                    # 到点了，立即执行
                                    asyncio.create_task(_execute_one(auto))
                                    next_due = min(next_due, 10.0)
                                else:
                                    next_due = min(next_due, max(1.0, t - now_ts))
                            except:
                                pass
                    elif sched_type == "recurring":
                        rrule = auto.get("rrule", "FREQ=DAILY")
                        parts = {k: v for kv in rrule.split(";") for k, v in [kv.split("=")] if "=" in kv}
                        freq = parts.get("FREQ", "DAILY")
                        interval = int(parts.get("INTERVAL", "1"))
                        last_run = auto.get("last_run", "")
                        if not last_run:
                            # 从未执行过，立即执行
                            asyncio.create_task(_execute_one(auto))
                            next_due = min(next_due, 10.0)
                            continue
                        try:
                            last_ts = time.mktime(time.strptime(last_run, "%Y-%m-%d %H:%M:%S"))
                            diff = now_ts - last_ts
                            period = {"HOURLY": 3600, "DAILY": 86400, "WEEKLY": 604800}.get(freq, 86400) * interval
                            if diff >= period - 1:
                                asyncio.create_task(_execute_one(auto))
                                next_due = min(next_due, 10.0)
                            else:
                                next_due = min(next_due, max(1.0, period - diff))
                        except:
                            asyncio.create_task(_execute_one(auto))
                            next_due = min(next_due, 10.0)

                # 精确 sleep 到下次检查
                await asyncio.sleep(min(next_due, 60.0))
            except Exception as e:
                log.warning(f"自动化调度异常: {e}")
                await asyncio.sleep(30)

    asyncio.create_task(automation_scheduler())

    asyncio.create_task(automation_scheduler())

    while True:
        await asyncio.sleep(3600)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        log.info("桌面端已停止")
    finally:
        _stop_searxng()
