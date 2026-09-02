"""
奶昔桌面后端 — Tauri sidecar 入口
完全独立自包含，不依赖 QQ 机器人后端的任何文件。
"""
import sys, os, asyncio, logging, subprocess, time
from logging.handlers import RotatingFileHandler

# 日志文件（崩溃时也能查到原因）
LOG_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "logs")
os.makedirs(LOG_DIR, exist_ok=True)
LOG_FILE = os.path.join(LOG_DIR, "naixi_desktop.log")
_handler = RotatingFileHandler(LOG_FILE, maxBytes=5*1024*1024, backupCount=3, encoding="utf-8")
_handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s"))
logging.getLogger().addHandler(_handler)
logging.getLogger().setLevel(logging.INFO)

# 桌面端核心模块路径：向上查找包含 desktop_core 包的目录（兼容开发态与打包态）
def _find_core_root():
    here = os.path.dirname(os.path.abspath(__file__))
    d = here
    while True:
        if os.path.isdir(os.path.join(d, "desktop_core")):
            return d
        # 打包态：desktop_core 在 resources/ 下（Tauri 资源目录分层结构）
        if os.path.isdir(os.path.join(d, "resources", "desktop_core")):
            return os.path.join(d, "resources")
        parent = os.path.dirname(d)
        if parent == d:
            break
        d = parent
    return here

DESKTOP_DIR = _find_core_root()
if DESKTOP_DIR not in sys.path:
    sys.path.insert(0, DESKTOP_DIR)

# 让 api.py 模块也能正确找到项目根路径
# 关键：必须用 _find_core_root() 算出的 DESKTOP_DIR（开发态=项目根，打包态=resources 目录），
# 不能写死 3 层上级（打包态 3 层上级是安装目录而非 resources，会导致 experts/skills/prompts 找不到）。
os.environ["DESKTOP_DIR"] = DESKTOP_DIR

# 记录入口脚本路径（供重启 API 使用）
sys._naixi_entry = __file__

# 数据库路径
# 开发态修正：_find_core_root 在开发态会先行命中 src-tauri/resources/desktop_core（stage_core
# 同步的代码副本），使 DESKTOP_DIR=src-tauri/resources，从而数据目录变成 resources/data——
# 那是一个全新、几乎为空的库（只有自动创建的裸 bailian/chat，无 Key、无 audio 供应商）。
# 但用户在设置页填的真实配置/密钥实际都落在项目根 data/naixi_desktop.db（含对应的加解密主密钥）。
# 密钥按「每个库各自的主密钥(DPAPI)」加密，跨库拷贝密文无法解密，故必须让后端直接读项目根库。
# 做法：当 DESKTOP_DIR 处于某 resources/ 下时，向上寻找真正含 desktop_core 源码的项目根，
# 把数据目录改为项目根的 data/；打包态（resources 是真实部署目录、上层无 desktop_core）则保持原样。
def _resolve_data_dir(desktop_dir):
    d = desktop_dir
    while d and d != os.path.dirname(d):
        if os.path.isdir(os.path.join(d, "desktop_core")) and os.path.basename(d) != "resources":
            return os.path.join(d, "data")
        d = os.path.dirname(d)
    return os.path.join(desktop_dir, "data")

DESKTOP_DATA_DIR = _resolve_data_dir(DESKTOP_DIR)
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

    # SearXNG 启动已移至 desktop_core.ops_engine._ensure_searxng()
    # （由 api.py on_startup 钩子调用，使用 webapp.py 而非损坏的 exe 壳）
    # 原 _start_searxng() 不再调用（避免启动 0xc000000be 坏 exe 弹窗）

    # 补全 Node.js 目录到 PATH，让后续 on_startup 的 MCP 子进程能找到 npx。
    # （MCP 实际连接统一交给 api.py 的 on_startup 后台任务，避免此处重复 spawn）
    try:
        # 解析优先级：环境变量 NAIXI_NODE_BIN > 系统 PATH 中已有的 npx > 跳过（不硬编码任何用户路径）
        import shutil as _shutil
        node_bin_dir = os.environ.get("NAIXI_NODE_BIN", "").strip()
        if not node_bin_dir:
            _npx = _shutil.which("npx")
            if _npx:
                node_bin_dir = os.path.dirname(_npx)
        if node_bin_dir and node_bin_dir not in os.environ.get("PATH", ""):
            os.environ["PATH"] = node_bin_dir + os.pathsep + os.environ.get("PATH", "")
    except Exception as e:
        log.warning(f"PATH 补全失败: {e}")

    from desktop_core.api import is_trusted_origin

    @web.middleware
    async def cors_middleware(request, handler):
        origin = request.headers.get("Origin", "")
        trusted = is_trusted_origin(origin)
        # 预检请求
        if request.method == "OPTIONS":
            headers = {
                "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
                "Access-Control-Allow-Headers": "Content-Type, Authorization",
            }
            if origin and trusted:
                headers["Access-Control-Allow-Origin"] = origin
                headers["Vary"] = "Origin"
            return web.Response(headers=headers)
        # 拒绝来自非信任浏览器源的跨域请求（防 DNS 重绑定/CSRF）
        if origin and not trusted:
            log.warning(f"拒绝不受信任的跨域请求，来源: {origin}")
            return web.json_response({"error": "来源不被信任"}, status=403)
        try:
            resp = await handler(request)
        except web.HTTPException as e:
            # 未匹配路由(404)等 HTTP 异常响应也需带 CORS 头：
            # 否则 await handler 抛异常导致下面的加头逻辑不执行，浏览器会对 404 报 CORS 拦截，
            # 前端轮询未匹配路由时红色 error 持续累积。HTTPException 本身是 Response 子类，可直接返回。
            resp = e
        # 仅对可信来源回显 Origin（不再使用通配符 *）
        if origin and trusted:
            resp.headers["Access-Control-Allow-Origin"] = origin
            resp.headers["Vary"] = "Origin"
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
        import aiohttp, re, json

        # 执行中任务保护（防止重复触发）
        _running: set[str] = set()

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

        async def _call_llm_with_tools(prompt: str, provider: dict | None) -> str:
            """调用 LLM（支持 Agent 循环 + 工具调用），返回最终回复"""
            api_key = (provider or {}).get("api_key", "")
            api_url = (provider or {}).get("api_url", "")
            model_name = (provider or {}).get("model", "")
            if not all([prompt, api_key, api_url]):
                return ""
            try:
                # 加载工具定义
                from desktop_core.tools import get_auto_definitions, execute
                tools = get_auto_definitions()
                messages = [{"role": "user", "content": prompt}]
                headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
                max_rounds = 5
                for _ in range(max_rounds):
                    payload = {"model": model_name or "default", "messages": messages, "tools": tools, "tool_choice": "auto", "max_tokens": 2048}
                    base_url = api_url.rstrip("/")
                    if not base_url.endswith("/chat/completions"):
                        base_url += "/chat/completions"
                    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=60)) as sess:
                        async with sess.post(base_url, headers=headers, json=payload) as resp:
                            if resp.status != 200:
                                return ""
                            data = await resp.json()
                            msg = data.get("choices", [{}])[0].get("message", {})
                            content = msg.get("content") or ""
                            tool_calls = msg.get("tool_calls")

                    if not tool_calls:
                        return content or "执行完成"

                    # 处理工具调用
                    messages.append(msg)
                    for tc in tool_calls:
                        fid = tc["function"]["name"]
                        try:
                            args = json.loads(tc["function"]["arguments"])
                        except:
                            args = {}
                        result = await execute(fid, args, {"user_id": "auto", "group_id": ""})
                        messages.append({"role": "tool", "tool_call_id": tc["id"], "content": str(result)[:500]})

                return "执行完成（工具调用次数超过限制）"
            except Exception as e:
                log.warning(f"Agent 执行失败: {e}")
                return ""

        async def _execute_one(auto: dict):
            """执行单个自动化任务（Agent 模式 + 耗时统计）"""
            aid = auto["id"]
            if aid in _running:
                log.info(f"自动化跳过: {auto['name']} 正在执行中")
                return
            _running.add(aid)
            start_ts = time.time()
            try:
                prompt = auto.get("prompt", "")
                model_name = auto.get("model", "")
                # 没有指定模型时，用默认 chat provider
                provider = _find_provider_for_model(model_name) if model_name else _find_provider_for_model("")
                reply = await _call_llm_with_tools(prompt, provider)
                duration = int((time.time() - start_ts) * 1000)
                automation_add_run(aid, "success", prompt=prompt, reply=reply or "", model_used=model_name or "default", duration_ms=duration)
                _save_to_conv(auto.get("name", "自动化"), prompt, reply)
                log.info(f"自动化执行: {auto['name']} ✅ ({duration}ms)")
                if auto.get("schedule_type") == "once":
                    auto["status"] = "expired"
                    automation_save(auto)
            except Exception as e:
                duration = int((time.time() - start_ts) * 1000)
                automation_add_run(aid, "failed", prompt=auto.get("prompt", ""), error=str(e), duration_ms=duration)
                log.warning(f"自动化执行失败: {auto['name']}: {e} ({duration}ms)")
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

    while True:
        await asyncio.sleep(3600)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        log.info("桌面端已停止")
    finally:
        _stop_searxng()
