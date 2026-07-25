"""桌面端 API 路由 — 脱敏版，不含任何 QQ 机器人相关功能"""
import json, os, sys, time, logging, asyncio, hmac
from aiohttp import web
from datetime import datetime

# 项目根目录（兼容直接 import 和通过 sidecar 运行）
_DESKTOP_DIR = os.environ.get("DESKTOP_DIR") or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# 权限确认：等待用户批准的高危工具
_PENDING_PERMISSIONS: dict[str, dict] = {}
# 会话级信任：{conv_key: {tool_name, ...}} — 用户勾选"始终允许"后不再对该工具弹出确认
_session_trust: dict[str, set[str]] = {}
# 活跃的 Agent 任务（用于取消）
_active_agent_tasks: dict[str, asyncio.Task] = {}
_agent_cancel_events: dict[str, asyncio.Event] = {}

import subprocess
def _win_hide_kwargs():
    """Windows 下隐藏子进程控制台窗口，避免轮询类接口（系统资源/进程/磁盘）频繁弹窗。"""
    if os.name == "nt":
        si = subprocess.STARTUPINFO()
        si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        si.wShowWindow = subprocess.SW_HIDE
        return {"creationflags": subprocess.CREATE_NO_WINDOW, "startupinfo": si}
    return {}

# ── Windows 原生系统信息采集（ctypes 直接调 API，零子进程，不触发安全软件拦截 powershell 弹窗）──
import ctypes
from ctypes import wintypes, Structure, byref, sizeof

def _win_cpu_times():
    """返回 (idle, kernel, user) 的 64 位 FILETIME 计数值；失败返回 (0,0,0)。"""
    idle = wintypes.FILETIME()
    kernel = wintypes.FILETIME()
    user = wintypes.FILETIME()
    if not ctypes.windll.kernel32.GetSystemTimes(byref(idle), byref(kernel), byref(user)):
        return (0, 0, 0)
    def _ft2ull(ft):
        return (ft.dwHighDateTime << 32) | ft.dwLowDateTime
    return (_ft2ull(idle), _ft2ull(kernel), _ft2ull(user))

def _win_memory():
    """返回 (memory_load_pct, total_bytes, avail_bytes)；失败返回 (0,0,0)。"""
    class MEMORYSTATUSEX(Structure):
        _fields_ = [
            ("dwLength", wintypes.DWORD),
            ("dwMemoryLoad", wintypes.DWORD),
            ("ullTotalPhys", ctypes.c_ulonglong),
            ("ullAvailPhys", ctypes.c_ulonglong),
            ("ullTotalPageFile", ctypes.c_ulonglong),
            ("ullAvailPageFile", ctypes.c_ulonglong),
            ("ullTotalVirtual", ctypes.c_ulonglong),
            ("ullAvailVirtual", ctypes.c_ulonglong),
            ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
        ]
    stat = MEMORYSTATUSEX()
    stat.dwLength = sizeof(MEMORYSTATUSEX)
    if not ctypes.windll.kernel32.GlobalMemoryStatusEx(byref(stat)):
        return (0, 0, 0)
    return (stat.dwMemoryLoad, stat.ullTotalPhys, stat.ullAvailPhys)

def _win_disk(drive):
    """返回 (total_bytes, free_bytes)；失败返回 (0,0)。"""
    free = ctypes.c_ulonglong()
    total = ctypes.c_ulonglong()
    avail = ctypes.c_ulonglong()
    if not ctypes.windll.kernel32.GetDiskFreeSpaceExW(ctypes.c_wchar_p(drive), byref(free), byref(total), byref(avail)):
        return (0, 0)
    return (total.value, free.value)

def _win_list_disks():
    """枚举所有本地固定盘，返回 [{DeviceID, SizeGB, FreeGB, UsedGB}]。"""
    buf = ctypes.create_unicode_buffer(256)
    ctypes.windll.kernel32.GetLogicalDriveStringsW(255, buf)
    drives = [d for d in buf.value.split("\x00") if d]
    out = []
    for d in drives:
        if ctypes.windll.kernel32.GetDriveTypeW(ctypes.c_wchar_p(d)) != 3:  # DRIVE_FIXED = 3
            continue
        total, free = _win_disk(d)
        if total <= 0:
            continue
        out.append({
            "DeviceID": d,
            "SizeGB": round(total / (1024 ** 3), 1),
            "FreeGB": round(free / (1024 ** 3), 1),
            "UsedGB": round((total - free) / (1024 ** 3), 1),
        })
    return out

def _win_proc_ws(pid):
    """查询进程工作集内存（字节），失败返回 0。"""
    h = ctypes.windll.kernel32.OpenProcess(0x0400 | 0x0010, False, pid)  # PROCESS_QUERY_INFORMATION | PROCESS_VM_READ
    if not h:
        return 0
    class PROCESS_MEMORY_COUNTERS(Structure):
        _fields_ = [
            ("cb", wintypes.DWORD),
            ("PageFaultCount", wintypes.DWORD),
            ("PeakWorkingSetSize", ctypes.c_size_t),
            ("WorkingSetSize", ctypes.c_size_t),
            ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
            ("QuotaPagedPoolUsage", ctypes.c_size_t),
            ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
            ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
            ("PagefileUsage", ctypes.c_size_t),
            ("PeakPagefileUsage", ctypes.c_size_t),
            ("PrivateUsage", ctypes.c_size_t),
        ]
    try:
        mc = PROCESS_MEMORY_COUNTERS()
        mc.cb = sizeof(PROCESS_MEMORY_COUNTERS)
        if ctypes.windll.psapi.GetProcessMemoryInfo(h, byref(mc), sizeof(mc)):
            return mc.WorkingSetSize
        return 0
    except Exception:
        return 0
    finally:
        ctypes.windll.kernel32.CloseHandle(h)

def _win_list_processes():
    """枚举 python / node 进程，返回 [{Id, ProcessName, MemMB, CPU, StartTime}]。"""
    TH32CS_SNAPPROCESS = 0x00000002
    class PROCESSENTRY32(Structure):
        _fields_ = [
            ("dwSize", wintypes.DWORD),
            ("cntUsage", wintypes.DWORD),
            ("th32ProcessID", wintypes.DWORD),
            ("th32DefaultHeapID", ctypes.POINTER(ctypes.c_ulong)),
            ("th32ModuleID", wintypes.DWORD),
            ("cntThreads", wintypes.DWORD),
            ("th32ParentProcessID", wintypes.DWORD),
            ("pcPriClassBase", ctypes.c_long),
            ("dwFlags", wintypes.DWORD),
            ("szExeFile", wintypes.CHAR * 260),
        ]
    out = []
    h = ctypes.windll.kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
    if h in (0, -1):
        return out
    try:
        pe = PROCESSENTRY32()
        pe.dwSize = sizeof(PROCESSENTRY32)
        if ctypes.windll.kernel32.Process32First(h, byref(pe)):
            while True:
                name = pe.szExeFile.decode("ascii", "ignore")
                nl = name.lower()
                if "python" in nl or "node" in nl:
                    out.append({
                        "Id": pe.th32ProcessID,
                        "ProcessName": name,
                        "MemMB": round(_win_proc_ws(pe.th32ProcessID) / (1024 ** 2), 1),
                        "CPU": 0.0,
                        "StartTime": "",
                    })
                if not ctypes.windll.kernel32.Process32Next(h, byref(pe)):
                    break
    finally:
        ctypes.windll.kernel32.CloseHandle(h)
    return out

# GPU 查询缓存：避免每次轮询都 spawn nvidia-smi（进程稳固，降低安全软件误报）
_gpu_cache: dict = {"value": None, "ts": 0}

async def _get_gpu_info():
    """查询 NVIDIA GPU 信息，60 秒内复用缓存，避免高频 spawn 子进程。"""
    now = time.time()
    if _gpu_cache["value"] is not None and (now - _gpu_cache["ts"]) < 60:
        return _gpu_cache["value"]
    gpu = {"gpu_util": 0, "gpu_name": "N/A", "gpu_mem_total": 0, "gpu_mem_used": 0}
    try:
        gproc = await asyncio.create_subprocess_exec(
            "nvidia-smi", "--query-gpu=utilization.gpu,name,memory.total,memory.used",
            "--format=csv,noheader,nounits",
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            **_win_hide_kwargs()
        )
        gout, _ = await asyncio.wait_for(gproc.communicate(), timeout=5)
        gl = gout.decode("gbk", errors="ignore").strip().split("\n")[0]
        if gl:
            parts = [x.strip() for x in gl.split(",")]
            if len(parts) >= 4:
                gpu = {
                    "gpu_util": float(parts[0] or 0),
                    "gpu_name": parts[1] or "N/A",
                    "gpu_mem_total": float(parts[2] or 0),
                    "gpu_mem_used": float(parts[3] or 0),
                }
    except Exception:
        pass
    _gpu_cache["value"] = gpu
    _gpu_cache["ts"] = now
    return gpu

# 高危工具列表（执行前需要用户确认）— 以 tools 模块为单一来源，避免两处定义漂移
from desktop_core.tools import HIGH_RISK_TOOLS

# tiktoken 精确估算（可选依赖）
_USE_TIKTOKEN = False
_TIKTOKEN_ENC = None
try:
    import tiktoken as _tk
    _TIKTOKEN_ENC = _tk.get_encoding("cl100k_base")
    _USE_TIKTOKEN = True
except Exception:
    pass

def _estimate_tokens(text: str) -> int:
    """估算文本的 token 数量。优先 tiktoken，降级到字符估算"""
    if not text:
        return 0
    if _USE_TIKTOKEN and _TIKTOKEN_ENC:
        try:
            return len(_TIKTOKEN_ENC.encode(text))
        except Exception:
            pass
    # 降级：中英文混合估算
    cn = sum(1 for c in text if '\u4e00' <= c <= '\u9fff')
    rest = len(text) - cn
    return max(1, int(cn / 1.5 + rest / 3.5))

from desktop_core.context import ContextManager

from desktop_core.storage import meta_get, meta_set, encrypt_config, decrypt_config, decrypt_api_key, mask_config, merge_preserve_keys, conv_list, conv_get_messages, conv_delete, conv_delete_message, conv_save_message_sync as conv_save_message
from desktop_core import tools

log = logging.getLogger("desktop")

# ── 来源信任判定（防跨站/DNS 重绑定攻击本机后端） ──
# 后端只绑定 127.0.0.1，主要威胁是用户浏览器里的恶意网页向 127.0.0.1:9845 发跨域请求。
# 规则：无 Origin（curl/服务端调用）放行；Origin 为 tauri/本机回环则信任；其余外部站点一律拒绝。
def is_trusted_origin(origin: str) -> bool:
    if not origin:
        return True  # 非浏览器请求（无 Origin 头），放行
    try:
        from urllib.parse import urlparse
        u = urlparse(origin)
        host = (u.hostname or "").lower()
        if host in ("tauri.localhost", "ipc.localhost", "localhost", "127.0.0.1", "::1"):
            return True
    except Exception:
        pass
    return False


def cors_origin_header(request):
    """若请求来源可信，返回应回显的 Origin；否则返回 None（不加 CORS 头）"""
    origin = request.headers.get("Origin", "")
    return origin if (origin and is_trusted_origin(origin)) else None


# 延迟导入工作流引擎（从 naixi_py 引用，但 storage/config 已被桌面端覆盖）
_workflow_api = None
def _get_workflow_api():
    global _workflow_api
    if _workflow_api is None:
        from desktop_core.workflow_engine import (
            init_workflow_tables,
            api_list_workflows, api_get_workflow, api_save_workflow,
            api_delete_workflow, api_run_workflow, api_get_runs,
            api_get_node_types, api_export_dsl, api_import_dsl,
            api_publish_workflow, api_list_versions, api_register_webhook,
            api_submit_human_input, api_list_templates, api_use_template,
            api_template_categories, api_get_api_key, api_log_call,
            api_regenerate_api_key, api_list_keys, api_create_key,
            api_update_key, api_delete_key, api_get_usage_stats,
        )
        init_workflow_tables()
        _workflow_api = {
            "list": api_list_workflows,
            "get": api_get_workflow,
            "save": api_save_workflow,
            "delete": api_delete_workflow,
            "run": api_run_workflow,
            "runs": api_get_runs,
            "node_types": api_get_node_types,
            "export": api_export_dsl,
            "import": api_import_dsl,
            "publish": api_publish_workflow,
            "regenerate_key": api_regenerate_api_key,
            "list_keys": api_list_keys,
            "create_key": api_create_key,
            "update_key": api_update_key,
            "delete_key": api_delete_key,
            "usage_stats": api_get_usage_stats,
            "versions": api_list_versions,
            "webhook": api_register_webhook,
            "human_input": api_submit_human_input,
            "templates": api_list_templates,
            "use_template": api_use_template,
            "template_categories": api_template_categories,
            "get_api_key": api_get_api_key,
            "log_call": api_log_call,
        }
    return _workflow_api


# ── 工作流路由 ──

async def api_workflow_list(request):
    wf = _get_workflow_api()
    data = await wf["list"]()
    return web.json_response({"workflows": data, "count": len(data)})

async def api_workflow_get(request):
    wid = request.match_info.get("id", "")
    wf = _get_workflow_api()
    data = await wf["get"](wid)
    if data is None:
        return web.json_response({"error": "工作流不存在"}, status=404)
    return web.json_response(data)

async def api_workflow_save(request):
    try:
        body = await request.json()
    except Exception:
        return web.json_response({"error": "无效的 JSON"}, status=400)
    wf = _get_workflow_api()
    result = await wf["save"](
        body.get("id", f"wf_{int(time.time())}"),
        body.get("name", ""),
        body.get("description", ""),
        body.get("nodes", []),
        body.get("edges", []),
        body.get("dsl", ""),
    )
    return web.json_response(result)

async def api_workflow_delete(request):
    try:
        body = await request.json()
    except Exception:
        return web.json_response({"error": "无效的 JSON"}, status=400)
    wf = _get_workflow_api()
    result = await wf["delete"](body.get("id", ""))
    return web.json_response(result)

async def api_workflow_run(request):
    try:
        body = await request.json()
    except Exception:
        return web.json_response({"error": "无效的 JSON"}, status=400)
    input_data = body.get("input", {})
    if isinstance(input_data, dict):
        silent = input_data.pop("silent_mode", False)
    else:
        silent = False
    wf = _get_workflow_api()
    result = await wf["run"](body.get("id", ""), input_data or {}, silent_mode=silent)
    return web.json_response(result)

async def api_workflow_runs(request):
    wid = request.match_info.get("id", "")
    limit = int(request.query.get("limit", "10"))
    wf = _get_workflow_api()
    data = await wf["runs"](wid, limit)
    return web.json_response({"runs": data, "count": len(data)})


async def api_workflow_delete_run(request):
    """删除单条工作流执行记录"""
    from desktop_core.storage import workflow_delete_run
    body = await request.json()
    workflow_delete_run(body.get("id", ""))
    return web.json_response({"ok": True})


async def api_workflow_node_types(request):
    wf = _get_workflow_api()
    data = await wf["node_types"]()
    return web.json_response(data)

async def api_workflow_export(request):
    wid = request.match_info.get("id", "")
    wf = _get_workflow_api()
    result = await wf["export"](wid)
    return web.json_response(result)

async def api_workflow_import(request):
    try:
        body = await request.json()
    except Exception:
        return web.json_response({"error": "无效的 JSON"}, status=400)
    wf = _get_workflow_api()
    result = await wf["import"](body.get("dsl", ""))
    return web.json_response(result)

async def api_workflow_stream(request):
    try:
        body = await request.json()
    except Exception:
        return web.json_response({"error": "无效的 JSON"}, status=400)
    wid = body.get("id", "")
    input_data = body.get("input", {})
    wf = _get_workflow_api()
    result = await wf["run"](wid, input_data)
    return web.json_response(result)

async def api_workflow_publish(request):
    try:
        body = await request.json()
    except Exception:
        return web.json_response({"error": "无效的 JSON"}, status=400)
    wf = _get_workflow_api()
    result = await wf["publish"](body.get("id", ""))
    return web.json_response(result)

async def api_workflow_regenerate_key(request):
    try:
        body = await request.json()
    except Exception:
        return web.json_response({"error": "无效的 JSON"}, status=400)
    wf = _get_workflow_api()
    result = await wf["regenerate_key"](body.get("id", ""))
    return web.json_response(result)

async def api_workflow_list_keys(request):
    wid = request.match_info.get("id", "")
    wf = _get_workflow_api()
    data = await wf["list_keys"](wid)
    return web.json_response({"keys": data})

async def api_workflow_create_key(request):
    wid = request.match_info.get("id", "")
    try:
        body = await request.json()
    except Exception:
        return web.json_response({"error": "无效的 JSON"}, status=400)
    wf = _get_workflow_api()
    result = await wf["create_key"](wid, body.get("name", "新密钥"))
    return web.json_response(result)

async def api_workflow_update_key(request):
    try:
        body = await request.json()
    except Exception:
        return web.json_response({"error": "无效的 JSON"}, status=400)
    wf = _get_workflow_api()
    result = await wf["update_key"](body.get("id"), body.get("enabled"), body.get("name"), body.get("rate_limit"))
    return web.json_response(result)

async def api_workflow_delete_key(request):
    try:
        body = await request.json()
    except Exception:
        return web.json_response({"error": "无效的 JSON"}, status=400)
    wf = _get_workflow_api()
    result = await wf["delete_key"](body.get("id"))
    return web.json_response(result)

async def api_workflow_usage_stats(request):
    wid = request.match_info.get("id", "")
    days = int(request.query.get("days", "7"))
    wf = _get_workflow_api()
    data = await wf["usage_stats"](wid, days)
    return web.json_response(data)

async def api_workflow_versions(request):
    wid = request.match_info.get("id", "")
    wf = _get_workflow_api()
    data = await wf["versions"](wid)
    return web.json_response({"versions": data})

async def api_workflow_register_webhook(request):
    try:
        body = await request.json()
    except Exception:
        return web.json_response({"error": "无效的 JSON"}, status=400)
    wf = _get_workflow_api()
    result = await wf["webhook"](body.get("id", ""), body.get("endpoint", ""), body.get("method", "POST"))
    return web.json_response(result)

async def api_workflow_human_input(request):
    try:
        body = await request.json()
    except Exception:
        return web.json_response({"error": "无效的 JSON"}, status=400)
    wf = _get_workflow_api()
    result = await wf["human_input"](body.get("pending_key", ""), body.get("value", ""))
    return web.json_response(result)


async def api_webhook_execute(request):
    """通过 webhook 远程触发工作流执行（需 API Key 认证）"""
    wid = request.match_info.get("endpoint", "")
    if not wid:
        return web.json_response({"error": "缺少工作流 ID"}, status=400)
    
    # API Key 认证
    auth_header = request.headers.get("Authorization", "")
    api_key = auth_header.replace("Bearer ", "").strip() if auth_header else request.query.get("api_key", "")
    if not api_key:
        return web.json_response({"error": "缺少 API Key（请通过 Authorization: Bearer xxx 或 ?api_key=xxx 传递）"}, status=401)
    
    wf_api = _get_workflow_api()
    
    # 验证 API Key（使用恒定时间比较，避免计时侧信道）
    stored_key = await wf_api["get_api_key"](wid)
    if not stored_key or not hmac.compare_digest(str(stored_key), str(api_key)):
        return web.json_response({"error": "API Key 无效"}, status=403)
    
    body = {}
    try:
        body = await request.json()
    except Exception:
        pass
    input_data = body.get("input", {}) if isinstance(body, dict) else {}
    
    import time
    start = time.time()
    result = await wf_api["run"](wid, input_data)
    elapsed = int((time.time() - start) * 1000)
    
    # 记录调用日志
    try:
        await wf_api["log_call"](wid, api_key[:8], result.get("status", "unknown"),
                                 json.dumps(input_data, ensure_ascii=False)[:500],
                                 json.dumps(result.get("final_output", {}), ensure_ascii=False)[:500],
                                 elapsed)
    except Exception:
        pass
    
    return web.json_response(result)


# ── 模板路由 ──

async def api_templates_list(request):
    wf = _get_workflow_api()
    data = await wf["templates"](request.query.get("category", ""))
    return web.json_response({"templates": data, "count": len(data)})

async def api_templates_categories(request):
    wf = _get_workflow_api()
    data = await wf["template_categories"]()
    return web.json_response({"categories": data})

async def api_templates_use(request):
    try:
        body = await request.json()
    except Exception:
        return web.json_response({"error": "无效的 JSON"}, status=400)
    wf = _get_workflow_api()
    result = await wf["use_template"](body.get("id", ""))
    if result is None:
        return web.json_response({"error": "模板不存在"}, status=404)
    return web.json_response(result)


# ── 在线模板搜索 ──

async def api_templates_online(request):
    from desktop_core.workflow_engine import api_search_online_templates
    try:
        data = await api_search_online_templates(request)
        return web.json_response(data)
    except Exception as e:
        err_msg = str(e)
        if "rate limit" in err_msg.lower():
            return web.json_response({"error": "GitHub API 频率限制，请稍后重试，或设置 GITHUB_TOKEN 环境变量提高限制"}, status=429)
        return web.json_response({"error": f"搜索失败: {err_msg}"}, status=500)


async def api_test_github_token(request):
    """测试 GitHub Token 是否有效"""
    try:
        body = await request.json()
    except Exception:
        return web.json_response({"error": "无效的请求"}, status=400)
    token = body.get("token", "")
    if not token:
        return web.json_response({"error": "请提供 Token"}, status=400)
    import aiohttp
    async with aiohttp.ClientSession() as s:
        async with s.get("https://api.github.com/rate_limit", headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github.v3+json",
            "User-Agent": "NaixiBot/1.0",
        }) as resp:
            if resp.status == 200:
                data = await resp.json()
                remaining = data.get("rate", {}).get("remaining", 0)
                limit = data.get("rate", {}).get("limit", 5000)
                return web.json_response({"ok": True, "remaining": remaining, "limit": limit})
            else:
                body = await resp.text()
                return web.json_response({"ok": False, "error": f"Token 无效 (HTTP {resp.status})"}, status=400)


async def api_save_github_token(request):
    """加密存储 GitHub Token 到数据库"""
    try:
        body = await request.json()
    except Exception:
        return web.json_response({"error": "无效的请求"}, status=400)
    from desktop_core.storage import encrypt_api_key, meta_set
    token = body.get("token", "")
    encrypted = encrypt_api_key(token) if token else ""
    meta_set("github_token", encrypted)
    return web.json_response({"ok": True})


async def api_get_github_token(request):
    """从数据库读取解密后的 GitHub Token"""
    from desktop_core.storage import decrypt_api_key, meta_get
    encrypted = meta_get("github_token") or ""
    decrypted = decrypt_api_key(encrypted) if encrypted else ""
    return web.json_response({"token": decrypted})


# ── 桌面端状态 ──

async def api_status(request):
    """兼容原 /api/status 格式，返回桌面端可用的默认值"""
    from desktop_core import tools as _tools_mod
    tool_count = len(_tools_mod._registry)
    return web.json_response({
        "version": "0.1.0",
        "trust_total": 0, "trust_level": 0, "trust_rate": 100,
        "knowledge_items": 0, "knowledge_cats": 0,
        "tools": tool_count, "skills": 0,
        "agents": 0, "cases": 0,
        "napcat_connected": False,
        "experiences": 0,
    })

async def api_desktop_status(request):
    return web.json_response({
        "name": "奶昔桌面端",
        "version": "0.1.0",
        "online": True,
    })


async def api_stats(request):
    """奶昔桌面端运维数据：后端自身状态 + 服务 + 数据库 + 提供商"""
    import os as _os, json, time as _time, asyncio
    try:
        import psutil
    except ImportError:
        psutil = None
    from desktop_core.storage import meta_get, _get_conn
    
    self_pid = _os.getpid()
    try:
        self_proc = psutil.Process(self_pid)
        self_mem = round(self_proc.memory_info().rss / (1024**2), 1)
        # 后端 CPU：统计两次轮询间的平均占用，避免空闲进程瞬时采样恒为 0
        ct = self_proc.cpu_times()
        now = _time.time()
        prev = getattr(api_stats, "_cpu_prev", None)
        if prev is None:
            self_cpu = 0.0
        else:
            dw = now - prev["wall"]
            dp = (ct.user + ct.system) - prev["proc"]
            self_cpu = round(max(0.0, min((dp / dw) * 100.0, 100.0)), 1) if dw > 0.01 else 0.0
        api_stats._cpu_prev = {"wall": now, "proc": ct.user + ct.system}
    except:
        self_mem = 0; self_cpu = 0

    conn = _get_conn()
    db_size, db_tables = 0, []
    try:
        db_path = _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "..", "data", "naixi_desktop.db")
        if _os.path.exists(db_path):
            db_size = _os.path.getsize(db_path)
        tables = conn.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name").fetchall()
        for r in tables:
            cnt = conn.execute(f'SELECT COUNT(*) as c FROM "{r[0]}"').fetchone()["c"]
            db_tables.append({"name": r[0], "count": cnt})
        conn.close()
    except:
        pass

    raw = meta_get("desktop_config")
    providers = []
    if raw:
        try:
            cfg = json.loads(raw)
            for pid, pcfg in cfg.get("api_providers", {}).items():
                providers.append({"name": pid, "model": pcfg.get("model",""), "has_key": bool(pcfg.get("api_key","")), "type": pcfg.get("type","chat")})
        except:
            pass

    ports = {"后端API":9845, "SearXNG":8899}
    services = {}
    for name, port in ports.items():
        try:
            _, w = await asyncio.wait_for(asyncio.open_connection("127.0.0.1", port), timeout=1)
            w.close(); await w.wait_closed()
            services[name] = True
        except:
            services[name] = False

    return web.json_response({
        "backend": {"pid": self_pid, "memory_mb": self_mem, "cpu": self_cpu, "version": "0.1.0"},
        "services": services,
        "providers": {"total": len(providers), "with_key": sum(1 for p in providers if p.get("has_key")), "list": providers[:10]},
        "database": {"size_mb": round(db_size/(1024**2),1) if db_size else 0, "tables": db_tables},
    })

async def api_system_resources(request):
    """返回系统资源使用情况（ctypes 直接调 Windows API，零子进程，不触发安全软件拦截）"""
    try:
        # CPU：两次采样 GetSystemTimes 求时间片占用
        idle1, k1, u1 = _win_cpu_times()
        await asyncio.sleep(0.3)
        idle2, k2, u2 = _win_cpu_times()
        sys_total = (k2 - k1) + (u2 - u1)
        sys_idle = idle2 - idle1
        cpu = round((1 - sys_idle / sys_total) * 100, 1) if sys_total > 0 else 0.0
        # 内存
        mem_load, mem_total, mem_avail = _win_memory()
        mem_used_pct = round((1 - mem_avail / mem_total) * 100, 1) if mem_total > 0 else 0.0
        # 系统盘（C:）使用率
        disk_total, disk_free = _win_disk("C:\\")
        disk_used_pct = round((1 - disk_free / disk_total) * 100, 1) if disk_total > 0 else 0.0
        # GPU：走 60 秒缓存的 nvidia-smi 查询（进程稳固，不每轮询都 spawn）
        gpu = await _get_gpu_info()
        return web.json_response({
            "cpu": cpu, "memory": mem_used_pct, "disk": disk_used_pct,
            "gpu_util": gpu["gpu_util"], "gpu_name": gpu["gpu_name"],
            "gpu_mem_total": gpu["gpu_mem_total"], "gpu_mem_used": gpu["gpu_mem_used"],
            "uptime": int(time.time()),
        })
    except Exception as e:
        return web.json_response({
            "cpu": 0, "memory": 0, "disk": 0,
            "gpu_util": 0, "gpu_name": "N/A", "gpu_mem_total": 0, "gpu_mem_used": 0,
            "error": str(e)[:50]
        })


async def api_system_info(request):
    """系统基本信息：主机名、OS、Python 版本、运行时长"""
    import platform, socket, os
    hostname = socket.gethostname()
    os_ver = platform.platform()
    py_ver = platform.python_version()
    pid = os.getpid()
    return web.json_response({
        "hostname": hostname, "os": os_ver, "python": py_ver,
        "pid": pid,
    })


async def api_system_processes(request):
    """当前系统中的 Python 和 Node 进程列表（ctypes Toolhelp 快照，零子进程）"""
    try:
        data = _win_list_processes()
        return web.json_response({"processes": data})
    except Exception as e:
        return web.json_response({"processes": [], "error": str(e)[:50]})


async def api_system_disks(request):
    """磁盘分区详细信息（ctypes 直接查询，零子进程）"""
    try:
        data = _win_list_disks()
        return web.json_response({"disks": data})
    except Exception as e:
        return web.json_response({"disks": [], "error": str(e)[:50]})


async def api_service_health(request):
    """检测各服务端口连通性"""
    import asyncio
    checks = {
        "backend": ("127.0.0.1", 9845),
        "napcat_http": ("127.0.0.1", 3000),
        "napcat_ws": ("127.0.0.1", 3001),
        "ollama": ("127.0.0.1", 11434),
        "searxng": ("127.0.0.1", 8898),
    }
    result = {}
    for name, (host, port) in checks.items():
        try:
            _, writer = await asyncio.wait_for(
                asyncio.open_connection(host, port), timeout=2
            )
            writer.close()
            await writer.wait_closed()
            result[name] = True
        except:
            result[name] = False
    return web.json_response(result)


async def api_database_stats(request):
    """数据库各表记录数"""
    from desktop_core.storage import _get_conn
    try:
        conn = _get_conn()
        rows = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        ).fetchall()
        tables = []
        for r in rows:
            name = r[0]
            count = conn.execute(f"SELECT COUNT(*) as c FROM \"{name}\"").fetchone()["c"]
            tables.append({"name": name, "count": count})
        conn.close()
        return web.json_response({"tables": tables})
    except Exception as e:
        return web.json_response({"error": str(e)}, status=400)


# ── 配置管理（API Key / 平台连接） ──

async def api_desktop_config_get(request):
    # 安全：绝不向前端返回明文密钥，只返回掩码占位符（前端用它判断"已配置"，编辑时留原样即保留）
    raw = meta_get("desktop_config")
    if raw:
        config = json.loads(raw)
        mask_config(config)  # 掩码 api_key，永不返回明文
        return web.json_response(config)
    return web.json_response({"api_providers": {}, "platform_configs": {}})


async def api_desktop_config_set(request):
    try:
        body = await request.json()
        # 合并现有配置，而不是整条替换（防止 curl 测试误覆盖）
        raw = meta_get("desktop_config")
        original = {}
        if raw:
            try:
                original = json.loads(raw)
                existing = original
                # 只合并已知的顶层键
                for key in ("api_providers", "platform_configs", "mcp_servers", "desktop_full_trust", "settings"):
                    if key in body:
                        existing[key] = body[key]
                body = existing
            except Exception:
                original = {}
        # 前端回传掩码/空密钥时，沿用已存的加密密文，避免误删或误覆盖真实密钥
        merge_preserve_keys(body, original)
        encrypt_config(body)  # 幂等加密：只加密新明文密钥，不重复加密已加密值
        meta_set("desktop_config", json.dumps(body, ensure_ascii=False))
        return web.json_response({"ok": True})
    except Exception as e:
        log.warning(f"保存桌面配置失败: {e}")
        return web.json_response({"error": "配置保存失败"}, status=400)


async def api_desktop_restart(request):
    """重启后端（浏览器模式用 REST API 替代 Tauri invoke）"""
    try:
        import subprocess, sys, os
        script = getattr(sys, '_naixi_entry', None) or (sys.argv[0] if sys.argv and os.path.isfile(sys.argv[0]) else None)
        if not script:
            return web.json_response({"error": "无法确定入口脚本路径"}, status=500)
        # 用同样的解释器启动新进程（应答后 1 秒退出当前进程）
        subprocess.Popen(
            [sys.executable, os.path.abspath(script)],
            cwd=os.path.dirname(os.path.abspath(script)),
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
        asyncio.get_event_loop().call_later(1, lambda: os._exit(0))
        return web.json_response({"ok": True, "message": "后端正在重启"})
    except Exception as e:
        log.warning(f"重启后端失败: {e}")
        return web.json_response({"error": "重启失败"}, status=500)


async def api_desktop_paths(request):
    """返回桌面端真实文件路径与存储信息（运行时计算，不硬编码）"""
    import os as _os
    base = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))
    db_path = _os.path.join(base, "data", "naixi_desktop.db")
    logs_dir = _os.path.join(base, "logs")
    models_dir = _os.path.join(base, "models")
    db_size = _os.path.getsize(db_path) if _os.path.exists(db_path) else 0
    keep_days = 7
    raw = meta_get("desktop_config")
    if raw:
        try:
            keep_days = json.loads(raw).get("settings", {}).get("log_keep_days", 7)
        except Exception:
            pass
    return web.json_response({
        "db_path": db_path,
        "db_size_mb": round(db_size / (1024 ** 2), 2) if db_size else 0,
        "logs_dir": logs_dir,
        "models_dir": models_dir,
        "log_keep_days": keep_days,
    })


# ── 默认提示词（基于 GitHub 开源项目最佳实践）──

DEFAULT_PROMPTS = {
    "owner": {
        "label": "日常助手",
        "prompt": (
            "你是一个温柔的 AI 助手，名叫奶昔。\n\n"
            "【角色设定】\n"
            "你是用户的专属助手，温暖、耐心、细心。用友好的语气和用户交流，自称「我」。\n\n"
            "【行为准则】\n"
            "1. 回答简洁直接，不啰嗦不绕弯\n"
            "2. 不知道的事直接说不知道，不要编造\n"
            "3. 需要搜索信息时直接搜索，不要先问用户要不要查\n"
            "4. 给出建议时说明理由，让用户自己做选择\n"
            "5. 涉及代码/技术问题时给出具体示例\n"
            "6. 使用工具完成任务后，用自然语言总结你做了什么、结果如何，不要只返回工具结果\n\n"
            "【禁止行为】\n"
            "- 不要用「你好呀～有什么想聊的吗」等客服式开场\n"
            "- 不要说「我来帮你」「请稍等」等机械句式\n"
            "- 不要每句话都用感叹号或颜文字\n"
            "- 不要主动提及你是 AI 或语言模型\n\n"
            "【对话风格】\n"
            "像朋友一样自然交流，偶尔可以关心用户近况。"
        ),
    },
    "group": {
        "label": "创作模式",
        "prompt": (
            "你是一个创意助手，名叫奶昔。\n\n"
            "【角色设定】\n"
            "你擅长头脑风暴、创意写作、内容生成。思维活跃，想法多样。\n\n"
            "【行为准则】\n"
            "1. 提供多个方案让用户选择\n"
            "2. 在创意方向上大胆提出想法\n"
            "3. 用户给出方向后深入细化\n"
            "4. 涉及事实性内容时先确认再输出\n\n"
            "【对话风格】\n"
            "开放、积极、有想象力。适当使用例子说明想法。"
        ),
    },
    "stranger": {
        "label": "快捷问答",
        "prompt": (
            "你是一个高效的问答助手，名叫奶昔。\n\n"
            "【角色设定】\n"
            "你的核心任务是快速、准确地回答问题。不闲聊，不绕弯子。\n\n"
            "【行为准则】\n"
            "1. 直接回答问题，不要铺垫\n"
            "2. 回答控制在 3-5 句话以内\n"
            "3. 需要搜索时直接搜索并返回结果\n"
            "4. 不知道就说不知道，不要尝试猜测\n"
            "5. 涉及数据/统计时注明来源\n\n"
            "【禁止行为】\n"
            "- 不要反问用户问题\n"
            "- 不要提供未经请求的额外信息\n"
            "- 不要使用表情符号或闲聊语气"
        ),
    },
}


async def api_prompts_get(request):
    """获取所有提示词（数组格式，兼容前端 PromptPanel）"""
    raw = meta_get("desktop_prompts")
    stored = {}
    if raw:
        try: stored = json.loads(raw)
        except: pass

    # 合并默认值
    all_prompts = dict(DEFAULT_PROMPTS)
    for k, v in stored.items():
        if k in all_prompts:
            if isinstance(v, dict):
                all_prompts[k].update(v)
        else:
            all_prompts[k] = v

    # 转成前端需要的数组格式
    prompts_list = []
    for scene, data in all_prompts.items():
        label = data.get("label", scene)
        content = data.get("prompt", data.get("content", ""))
        lines = content.count("\n") + 1 if content else 0
        prompts_list.append({
            "file": scene + ".txt",
            "scene": scene,
            "desc": label,
            "content": content,
            "lines": lines,
            "char_count": len(content),
        })
    return web.json_response({"prompts": prompts_list})

async def api_desktop_prompts_get(request):
    """旧版提示词接口（SetupGuide 使用），返回 {scene: {label, prompt}} 格式"""
    raw = meta_get("desktop_prompts")
    stored = {}
    if raw:
        try: stored = json.loads(raw)
        except: pass
    result = {}
    for scene, data in DEFAULT_PROMPTS.items():
        result[scene] = dict(data)
    for k, v in stored.items():
        if k in result and isinstance(v, dict):
            result[k].update(v)
        elif isinstance(v, dict):
            result[k] = v
    return web.json_response({"prompts": result})


async def api_desktop_prompts_set(request):
    """旧版提示词保存接口（SetupGuide 使用）"""
    try:
        body = await request.json()
        prompts = body.get("prompts", {})
        existing_raw = meta_get("desktop_prompts")
        existing = json.loads(existing_raw) if existing_raw else {}
        existing.update(prompts)
        meta_set("desktop_prompts", json.dumps(existing, ensure_ascii=False))
        return web.json_response({"ok": True})
    except Exception as e:
        return web.json_response({"error": str(e)}, status=400)


async def api_desktop_prompts_reset(request):
    """旧版提示词重置接口（SetupGuide 使用）"""
    try:
        body = await request.json()
        scene = body.get("scene", "")
        if scene in DEFAULT_PROMPTS:
            existing_raw = meta_get("desktop_prompts")
            existing = json.loads(existing_raw) if existing_raw else {}
            existing[scene] = dict(DEFAULT_PROMPTS[scene])
            meta_set("desktop_prompts", json.dumps(existing, ensure_ascii=False))
            return web.json_response({"ok": True, "prompt": DEFAULT_PROMPTS[scene]})
        return web.json_response({"error": "场景不存在"}, status=400)
    except Exception as e:
        return web.json_response({"error": str(e)}, status=400)


async def api_prompts_save(request):
    """保存/创建单个提示词文件"""
    try:
        body = await request.json()
        fname = body.get("file", "")
        content = body.get("content", "")
        if not fname:
            return web.json_response({"error": "缺少文件名"}, status=400)
        scene = fname.replace(".txt", "") if fname.endswith(".txt") else fname

        raw = meta_get("desktop_prompts")
        stored = json.loads(raw) if raw else {}
        # 保留原有标签（预设场景用 DEFAULT_PROMPTS 的 label，不会被覆盖）
        existing_label = None
        if scene in DEFAULT_PROMPTS:
            existing_label = DEFAULT_PROMPTS[scene].get("label", scene)
        elif scene in stored and isinstance(stored[scene], dict):
            existing_label = stored[scene].get("label")
        stored[scene] = {"label": existing_label or scene, "prompt": content}
        meta_set("desktop_prompts", json.dumps(stored, ensure_ascii=False))
        return web.json_response({"ok": True})
    except Exception as e:
        return web.json_response({"error": str(e)}, status=400)


async def api_prompts_delete(request):
    """删除自定义提示词"""
    try:
        body = await request.json()
        fname = body.get("file", "")
        scene = fname.replace(".txt", "") if fname.endswith(".txt") else fname
        raw = meta_get("desktop_prompts")
        stored = json.loads(raw) if raw else {}
        stored.pop(scene, None)
        meta_set("desktop_prompts", json.dumps(stored, ensure_ascii=False))
        return web.json_response({"ok": True})
    except Exception as e:
        return web.json_response({"error": str(e)}, status=400)


def _get_prompt_text(scene: str) -> str:
    """根据场景名获取提示词文本"""
    raw = meta_get("desktop_prompts")
    stored = {}
    if raw:
        try: stored = json.loads(raw)
        except: pass
    if scene in stored:
        data = stored[scene]
        return data.get("prompt", data.get("content", ""))
    if scene in DEFAULT_PROMPTS:
        return DEFAULT_PROMPTS[scene].get("prompt", "")
    return ""


# ── 多类型供应商路由 ──

def _find_provider_by_type(provider_type: str) -> dict | None:
    """从配置中查找指定类型的供应商"""
    raw = meta_get("desktop_config")
    if not raw:
        return None
    try:
        cfg = json.loads(raw)
        for pid, pcfg in cfg.get("api_providers", {}).items():
            if pcfg.get("type", "chat") == provider_type:
                return {"key": pid, **pcfg}
    except:
        pass
    return None


# ── 通用画图函数（提取供头像生成复用） ──

async def _generate_image_from_prompt(prompt: str, size: str = "1024*1024") -> str:
    """调用配置的画图模型生成图片，返回图片 URL（异常时抛出 ValueError）"""
    provider = _find_provider_by_type("image")
    if not provider:
        provider = _find_provider_by_type("chat")
    if not provider:
        raise ValueError("未配置画图/对话模型供应商")

    import aiohttp
    api_url = provider.get("api_url", "").rstrip("/")
    api_key = provider.get("api_key", "")
    model = provider.get("model", "")

    from desktop_core.storage import decrypt_api_key
    decrypted = decrypt_api_key(api_key)
    if decrypted:
        api_key = decrypted

    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    is_dashscope = "dashscope" in api_url or "aliyuncs" in api_url

    if is_dashscope:
        wanx_url = "https://dashscope.aliyuncs.com/api/v1/services/aigc/text2image/image-synthesis"
        headers["x-dashscope-async"] = "enable"
        payload = {
            "model": model or "wanx2.1-t2i-turbo",
            "input": {"prompt": prompt},
            "parameters": {"size": size, "n": 1},
        }
        async with aiohttp.ClientSession(headers=headers) as session:
            async with session.post(wanx_url, json=payload, timeout=aiohttp.ClientTimeout(total=30)) as resp:
                if resp.status != 200:
                    err_text = await resp.text()
                    raise ValueError(f"{model or 'Wanx'} 创建任务失败 {resp.status}: {err_text[:200]}")
                result = await resp.json()
                task_id = result.get("output", {}).get("task_id", "")
                if not task_id:
                    raise ValueError(f"{model or 'Wanx'} 未返回任务 ID: {str(result)[:200]}")

            for attempt in range(30):
                await asyncio.sleep(5)
                async with session.get(f"https://dashscope.aliyuncs.com/api/v1/tasks/{task_id}", timeout=10) as qr:
                    if qr.status != 200:
                        continue
                    qd = await qr.json()
                    status = qd.get("output", {}).get("task_status", "")
                    if status == "SUCCEEDED":
                        results = qd.get("output", {}).get("results", [])
                        if results:
                            return results[0].get("url", "")
                        raise ValueError(f"{model or 'Wanx'} 成功但无结果")
                    elif status in ("FAILED", "CANCELED"):
                        err = qd.get("output", {}).get("failure", "任务失败")
                        raise ValueError(f"{model or 'Wanx'} 生成失败: {err}")

            raise ValueError(f"{model or 'Wanx'} 生成超时")
    else:
        payload = {
            "model": model or "dall-e-3",
            "prompt": prompt,
            "n": 1,
            "size": "1024x1024",
        }
        async with aiohttp.ClientSession(headers=headers) as session:
            async with session.post(api_url, json=payload, timeout=aiohttp.ClientTimeout(total=120)) as resp:
                if resp.status != 200:
                    err_text = await resp.text()
                    raise ValueError(f"API 返回 {resp.status}: {err_text[:200]}")
                result = await resp.json()
                if "data" in result and len(result["data"]) > 0:
                    return result["data"][0].get("url", "")
                if "output" in result:
                    results = result["output"].get("results", [])
                    if results:
                        return results[0].get("url", "")
                raise ValueError(f"无法解析返回结果: {str(result)[:200]}")


async def api_generate_image(request):
    """调用配置的画图模型生成图片"""
    try:
        body = await request.json()
        prompt = body.get("prompt", "")
        if not prompt:
            return web.json_response({"error": "缺少提示词"}, status=400)
        url = await _generate_image_from_prompt(prompt)
        return web.json_response({"ok": True, "url": url})
    except ValueError as e:
        return web.json_response({"error": str(e)}, status=502)
    except Exception as e:
        return web.json_response({"error": str(e)}, status=500)


# ── 头像生成与缓存 ──

ANIME_AVATAR_PROMPT = "二次元猫娘少女风格头像，半身肖像或者是头部肖像，猫耳，可爱萌系，精致插画风，柔和光影"

# 后台生成进度追踪
_generation_task: asyncio.Task | None = None
_generation_total = 0
_generation_completed = 0

async def api_avatar_get(request):
    """获取头像：查缓存 → 未命中则生成 → 返回"""
    seed = request.query.get("seed", "")
    if not seed:
        return web.json_response({"error": "缺少 seed 参数"}, status=400)

    from desktop_core.storage import avatar_get, avatar_set

    # 查缓存
    cached = avatar_get(seed)
    if cached:
        return web.json_response({"ok": True, "url": cached, "cached": True})

    # 检查是否配置了画图模型
    provider = _find_provider_by_type("image")
    if not provider:
        provider = _find_provider_by_type("chat")
    if not provider:
        return web.json_response({"error": "未配置画图模型供应商"}, status=400)

    # 未缓存，生成
    try:
        prompt = f"{ANIME_AVATAR_PROMPT}，风格关键词：{seed}"
        url = await _generate_image_from_prompt(prompt)
        avatar_set(seed, url)
        return web.json_response({"ok": True, "url": url, "cached": False})
    except ValueError as e:
        return web.json_response({"error": str(e)}, status=502)
    except Exception as e:
        return web.json_response({"error": str(e)}, status=500)


async def api_avatar_prefill(request):
    """批量预生成头像（后台异步，不阻塞返回）"""
    global _generation_task, _generation_total, _generation_completed

    if _generation_task is not None and not _generation_task.done():
        return web.json_response({"ok": False, "error": "已有生成任务在进行中"})

    # 检查是否配置了画图模型
    provider = _find_provider_by_type("image")
    if not provider:
        provider = _find_provider_by_type("chat")
    if not provider:
        return web.json_response({"ok": False, "error": "未配置任何画图/对话模型供应商，请先在「模型供应商」中添加"})

    try:
        body = await request.json() if request.can_read_body else {}
    except:
        body = {}
    count = min(int(body.get("count", 20)), 50)
    prompt_prefix = body.get("prompt", ANIME_AVATAR_PROMPT)

    from desktop_core.storage import avatar_count, avatar_remove_expired
    avatar_remove_expired()
    need = max(avatar_count() + 10, count)
    _generation_total = need
    _generation_completed = 0

    async def _fill():
        global _generation_completed
        import aiohttp, os, time, re
        from desktop_core.storage import avatar_get, avatar_set
        # 头像本地存储目录
        avatar_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "avatars")
        os.makedirs(avatar_dir, exist_ok=True)
        for i in range(need):
            seed = f"avatar-{i}"
            existing = avatar_get(seed)
            if existing:
                # 检查是否过期（OSS URL），过期则重新生成
                if "Expires=" in existing:
                    m = re.search(r"Expires=(\d+)", existing)
                    if m and int(m.group(1)) < time.time():
                        existing = None  # 过期，重新生成
            if existing:
                _generation_completed += 1
                continue
            try:
                prompt = f"{prompt_prefix}，风格种子：{seed}"
                url = await _generate_image_from_prompt(prompt)
                # 下载图片到本地
                try:
                    async with aiohttp.ClientSession() as sess:
                        async with sess.get(url, timeout=aiohttp.ClientTimeout(total=30)) as img_resp:
                            if img_resp.status == 200:
                                img_data = await img_resp.read()
                                ext = "png"
                                fpath = os.path.join(avatar_dir, f"{seed}.{ext}")
                                with open(fpath, "wb") as f:
                                    f.write(img_data)
                                local_url = f"/api/avatar/file/{seed}.{ext}"
                                avatar_set(seed, local_url)
                                log.info(f"头像 [{_generation_completed + 1}/{count}] {seed} 已保存到本地")
                            else:
                                raise ValueError(f"下载图片失败: HTTP {img_resp.status}")
                except Exception as dl_err:
                    log.warning(f"下载头像失败，回退 OSS URL: {dl_err}")
                    avatar_set(seed, url)
                _generation_completed += 1
            except Exception as e:
                _generation_completed += 1
                log.warning(f"头像 [{_generation_completed}/{count}] {seed} 生成失败: {e}")
                continue
        log.info(f"头像批量生成完成：共 {count} 个")

    _generation_task = asyncio.create_task(_fill())
    return web.json_response({"ok": True, "message": f"开始后台预生成 {count} 个头像"})


async def api_avatar_gen_status(request):
    """后台生成进度"""
    global _generation_task, _generation_total, _generation_completed
    return web.json_response({
        "running": _generation_task is not None and not _generation_task.done(),
        "completed": _generation_completed,
        "total": _generation_total,
    })


async def api_avatar_list(request):
    """列出所有已缓存头像"""
    from desktop_core.storage import avatar_list
    return web.json_response({"ok": True, "avatars": avatar_list()})


async def api_avatar_stats(request):
    """头像缓存统计"""
    from desktop_core.storage import avatar_count
    return web.json_response({"ok": True, "total": avatar_count()})


async def api_avatar_file(request):
    """提供本地存储的头像文件"""
    import os
    filename = request.match_info.get("filename", "")
    if not filename or ".." in filename or "/" in filename:
        return web.json_response({"error": "无效文件名"}, status=400)
    avatar_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "avatars")
    fpath = os.path.join(avatar_dir, filename)
    if not os.path.exists(fpath):
        return web.json_response({"error": "文件不存在"}, status=404)
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else "png"
    mime = {"png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg", "webp": "image/webp"}.get(ext, "application/octet-stream")
    return web.FileResponse(fpath, headers={"Content-Type": mime})


async def api_generate_video(request):
    """调用配置的视频模型生成视频（支持智谱 CogVideoX 和 OpenAI 兼容格式）"""
    try:
        body = await request.json()
        prompt = body.get("prompt", "")
        if not prompt:
            return web.json_response({"error": "缺少提示词"}, status=400)

        provider = _find_provider_by_type("video")
        if not provider:
            return web.json_response({"error": "未配置视频模型供应商"}, status=400)

        import aiohttp
        api_key = provider.get("api_key", "")
        model = provider.get("model", "cogvideox-flash")

        decrypt_key = decrypt_api_key(api_key)
        if decrypt_key:
            api_key = decrypt_key

        headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}

        # 判断是否智谱
        is_zhipu = "bigmodel" in provider.get("api_url", "")

        if is_zhipu:
            # 智谱 CogVideoX（异步任务模式）
            vurl = "https://open.bigmodel.cn/api/paas/v4/videos/generations"
            payload = {"model": model, "prompt": prompt, "size": "720p", "duration": 5}
            async with aiohttp.ClientSession() as session:
                async with session.post(vurl, json=payload, headers=headers, timeout=aiohttp.ClientTimeout(total=30)) as r:
                    if r.status != 200:
                        err = await r.text()
                        return web.json_response({"error": f"{model} 创建失败 {r.status}: {err[:200]}"}, status=502)
                    result = await r.json()
                    task_id = result.get("id", "")
                    if not task_id:
                        return web.json_response({"error": f"{model} 未返回任务 ID"}, status=502)

                # 轮询结果（最多10分钟）
                for _ in range(100):
                    await asyncio.sleep(6)
                    async with aiohttp.ClientSession() as s2:
                        async with s2.get(f"https://open.bigmodel.cn/api/paas/v4/async-result/{task_id}", headers=headers, timeout=15) as qr:
                            if qr.status == 200:
                                qd = await qr.json()
                                st = qd.get("task_status", "")
                                if st == "SUCCESS":
                                    # CogVideoX 结果在 video_result 字段
                                    vresult = qd.get("video_result", [])
                                    if vresult:
                                        return web.json_response({"ok": True, "url": vresult[0].get("url", "")})
                                    # 旧格式兼容
                                    vurl = qd.get("data", [{}])[0].get("url", "") if qd.get("data") else ""
                                    if vurl:
                                        return web.json_response({"ok": True, "url": vurl})
                                elif st in ("FAILED", "CANCELED"):
                                    return web.json_response({"error": f"{model} 生成失败: {qd.get('failure', '任务取消')}"}, status=502)
                return web.json_response({"error": f"{model} 生成超时"}, status=502)
        else:
            # OpenAI 兼容格式
            api_url = provider.get("api_url", "").rstrip("/")
            payload = {"model": model, "prompt": prompt, "n": 1}
            async with aiohttp.ClientSession(headers=headers) as session:
                async with session.post(api_url, json=payload, timeout=aiohttp.ClientTimeout(total=180)) as resp:
                    if resp.status == 200:
                        result = await resp.json()
                        return web.json_response({"ok": True, "url": str(result)[:100]})
                    err_text = await resp.text()
                    return web.json_response({"error": f"视频 API 返回 {resp.status}: {err_text[:200]}"}, status=502)
    except Exception as e:
        return web.json_response({"error": str(e)}, status=500)


async def api_config_tts_get(request):
    """获取 TTS 朗读模式配置"""
    raw = meta_get("desktop_config")
    mode = "browser"
    voice = "zh-CN-XiaoxiaoNeural"
    if raw:
        try:
            cfg = json.loads(raw)
            mode = cfg.get("tts_mode", "browser")
            voice = cfg.get("tts_voice", "zh-CN-XiaoxiaoNeural")
        except: pass
    return web.json_response({"mode": mode, "voice": voice})

async def api_config_tts_set(request):
    """设置 TTS 朗读模式"""
    try:
        body = await request.json()
        raw = meta_get("desktop_config")
        cfg = json.loads(raw) if raw else {}
        if "mode" in body:
            cfg["tts_mode"] = body["mode"]
        if "voice" in body:
            cfg["tts_voice"] = body["voice"]
        meta_set("desktop_config", json.dumps(cfg, ensure_ascii=False))
        return web.json_response({"ok": True})
    except Exception as e:
        return web.json_response({"error": str(e)}, status=400)


async def api_generate_voice(request):
    """调用配置的语音模型合成语音（支持百炼 CosyVoice 和 OpenAI TTS）"""
    try:
        body = await request.json()
        text = body.get("text", body.get("prompt", ""))
        if not text:
            return web.json_response({"error": "缺少文本"}, status=400)

        provider = _find_provider_by_type("audio")
        if not provider:
            return web.json_response({"error": "未配置语音模型供应商"}, status=400)

        import aiohttp, base64
        api_key = provider.get("api_key", "")
        model = provider.get("model", "cosyvoice-v3-flash")

        decrypt_key = decrypt_api_key(api_key)
        if decrypt_key:
            api_key = decrypt_key

        headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}

        # 判断是否百炼 CosyVoice
        is_dashscope = "dashscope" in provider.get("api_url", "") or "aliyuncs" in provider.get("api_url", "")

        if is_dashscope:
            # 百炼 CosyVoice 格式
            tts_url = "https://dashscope.aliyuncs.com/api/v1/services/audio/tts/SpeechSynthesizer"
            payload = {
                "model": model,
                "input": {"text": text, "voice": "longfeifei_v3", "format": "wav", "sample_rate": 24000},
            }
            async with aiohttp.ClientSession(headers=headers) as session:
                async with session.post(tts_url, json=payload, timeout=aiohttp.ClientTimeout(total=60)) as resp:
                    if resp.status != 200:
                        err = await resp.text()
                        return web.json_response({"error": f"语音 API 返回 {resp.status}: {err[:200]}"}, status=502)
                    result = await resp.json()
                    audio_url = result.get("output", {}).get("audio", {}).get("url", "")
                    if not audio_url:
                        return web.json_response({"error": f"{model} 未返回音频 URL"}, status=502)
                    # 下载音频并返回 base64（OSS URL 不支持 Bearer auth）
                    async with aiohttp.ClientSession() as dl_session:
                        async with dl_session.get(audio_url, timeout=30) as ar:
                            if ar.status != 200:
                                return web.json_response({"error": f"下载音频失败 {ar.status}"}, status=502)
                            audio_data = await ar.read()
                            return web.json_response({
                                "ok": True, "audio": base64.b64encode(audio_data).decode(),
                                "format": "wav"
                            })
        else:
            # OpenAI TTS 格式
            tts_url = api_url.rstrip("/") + "/audio/speech"
            payload = {"model": model, "input": text, "voice": "alloy", "response_format": "wav"}
            async with aiohttp.ClientSession(headers=headers) as session:
                async with session.post(tts_url, json=payload, timeout=aiohttp.ClientTimeout(total=60)) as resp:
                    if resp.status != 200:
                        err = await resp.text()
                        return web.json_response({"error": f"语音 API 返回 {resp.status}: {err[:200]}"}, status=502)
                    audio_data = await resp.read()
                    return web.json_response({
                        "ok": True, "audio": base64.b64encode(audio_data).decode(),
                        "format": "wav"
                    })
    except Exception as e:
        return web.json_response({"error": str(e)}, status=500)


async def api_generate_code(request):
    """调用配置的代码模型生成代码（复用 chat 供应商）"""
    body = await request.json()
    prompt = body.get("prompt", "")
    if not prompt:
        return web.json_response({"error": "缺少提示词"}, status=400)

    provider = _find_provider_by_type("code") or _find_provider_by_type("chat")
    if not provider:
        return web.json_response({"error": "未配置模型供应商"}, status=400)

    api_url = provider.get("api_url", "").rstrip("/")
    api_key = provider.get("api_key", "")
    model = provider.get("model", "")

    decrypt_key = decrypt_api_key(api_key)
    if decrypt_key:
        api_key = decrypt_key

    full_url = api_url if "/chat/completions" in api_url else api_url.rstrip("/") + "/chat/completions"

    import aiohttp
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": "你是一个编程助手。只返回代码，不需要解释。"},
            {"role": "user", "content": prompt},
        ],
    }
    async with aiohttp.ClientSession(headers=headers) as session:
        async with session.post(full_url, json=payload, timeout=aiohttp.ClientTimeout(total=60)) as resp:
            if resp.status != 200:
                return web.json_response({"error": f"API 返回 {resp.status}"}, status=502)
            result = await resp.json()
            code = result.get("choices", [{}])[0].get("message", {}).get("content", "")
            return web.json_response({"ok": True, "code": code, "model": model})


async def api_search(request):
    """内置搜索 — 自包含，不需要任何外部 API Key"""
    try:
        body = await request.json()
        q = body.get("q", body.get("prompt", ""))
        if not q:
            return web.json_response({"error": "缺少搜索关键词"}, status=400)

        import aiohttp, urllib.parse, re

        results = []

        # 方案 1: 本地 SearXNG（桌面端自带 8899 或奶昔后端 8898）
        for port in [8899, 8898]:
            try:
                async with aiohttp.ClientSession() as session:
                    params = {"q": q, "format": "json", "language": "zh-CN"}
                    async with session.get(f"http://127.0.0.1:{port}/search", params=params, timeout=5) as resp:
                        if resp.status == 200:
                            data = await resp.json()
                            for item in data.get("results", []):
                                results.append({
                                    "title": item.get("title", ""),
                                    "url": item.get("url", ""),
                                    "content": item.get("content", ""),
                                })
                            if results:
                                break
            except:
                pass

        # 方案 2: Bing 搜索（不需要 Key，直接请求）
        if not results:
            try:
                bing_url = f"https://www.bing.com/search?q={urllib.parse.quote(q)}&count=10"
                headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"}
                async with aiohttp.ClientSession(headers=headers) as session:
                    async with session.get(bing_url, timeout=8) as resp:
                        if resp.status == 200:
                            html = await resp.text()
                            # 提取 Bing 搜索结果
                            for item in re.finditer(r'<li class="b_algo">.*?<h2><a[^>]*href="([^"]*)"[^>]*>(.*?)</a>', html, re.DOTALL):
                                url = item.group(1)
                                title = re.sub(r'<[^>]+>', '', item.group(2)).strip()
                                results.append({"title": title, "url": url, "content": title})
                                if len(results) >= 8:
                                    break
                            # 如果上面的没匹配到，尝试另一个 Bing 格式
                            if not results:
                                for item in re.finditer(r'<a[^>]*href="(https?://[^"]*)"[^>]*><h2>(.*?)</h2>', html, re.DOTALL):
                                    url = item.group(1)
                                    title = re.sub(r'<[^>]+>', '', item.group(2)).strip()
                                    results.append({"title": title, "url": url, "content": title})
                                    if len(results) >= 8:
                                        break
            except:
                pass

        if results:
            return web.json_response({"ok": True, "results": results[:10], "total": len(results)})
        return web.json_response({"error": "搜索不可用，请确保 SearXNG 已启动或有网络连接"}, status=503)

    except Exception as e:
        err_msg = str(e) or type(e).__name__
        return web.json_response({"error": err_msg}, status=500)


async def api_desktop_test_connection(request):
    """测试 API Key 连通性"""
    try:
        body = await request.json()
        provider = body.get("provider", "")
        api_key = body.get("api_key", "")
        api_url = body.get("api_url", "")

        if not api_key:
            return web.json_response({"ok": False, "error": "API Key 不能为空"})

        import aiohttp
        # 不同提供商的测试端点
        test_urls = {
            "bailian": "https://dashscope.aliyuncs.com/compatible-mode/v1/models",
            "zhipu": "https://open.bigmodel.cn/api/paas/v4/models",
            "agnes": "https://apihub.agnes-ai.com/v1/models",
            "openai": "https://api.openai.com/v1/models",
        }
        # 优先用 api_url 推导 models 端点
        if api_url:
            base = api_url.rstrip("/").replace("/chat/completions", "")
            test_url = f"{base}/models"
        else:
            test_url = test_urls.get(provider, "")
        if not test_url:
            return web.json_response({"ok": False, "error": "无法确定测试端点"})

        async with aiohttp.ClientSession() as session:
            async with session.get(test_url, headers={"Authorization": f"Bearer {api_key}"}, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                if resp.status == 200:
                    return web.json_response({"ok": True})
                else:
                    body_text = await resp.text()
                    return web.json_response({"ok": False, "error": f"HTTP {resp.status}: {body_text[:100]}"})
    except Exception as e:
        return web.json_response({"ok": False, "error": str(e)[:100]})


# ── 平台连接引导 ──

async def api_desktop_list_models(request):
    """调用提供商 API 获取可用模型列表"""
    try:
        body = await request.json()
        api_url = body.get("api_url", "")
        api_key = body.get("api_key", "")
        if not api_url or not api_key:
            return web.json_response({"error": "缺少 api_url 或 api_key"}, status=400)

        # 从 chat/completions URL 推导 models endpoint（去掉 `/chat/completions` 保留版本路径）
        base_url = api_url.rstrip("/").replace("/chat/completions", "")
        models_url = f"{base_url}/models"

        import aiohttp
        headers = {"Authorization": f"Bearer {api_key}"}
        if "dashscope" in api_url:
            headers["X-DashScope-SSE"] = "disable"

        async with aiohttp.ClientSession(headers=headers) as session:
            async with session.get(models_url, timeout=10) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    models = data.get("data", data if isinstance(data, list) else [])
                    # 提取模型 ID 列表
                    ids = []
                    for m in models:
                        mid = m.get("id", m.get("model_id", m.get("name", "")))
                        if mid:
                            ids.append({"id": mid, "owned_by": m.get("owned_by", "")})
                    return web.json_response({"models": ids, "total": len(ids)})
                else:
                    text = await resp.text()
                    return web.json_response({"error": f"API 返回 {resp.status}: {text[:200]}"}, status=502)
    except asyncio.TimeoutError:
        return web.json_response({"error": "请求超时，请检查 API 地址是否正确"}, status=504)
    except Exception as e:
        return web.json_response({"error": str(e)}, status=500)


async def api_desktop_platforms(request):
    import os
    pj_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "platforms.json")
    try:
        with open(pj_path, encoding="utf-8") as f:
            data = json.load(f)
        return web.json_response(data)
    except Exception as e:
        return web.json_response({"error": str(e)}, status=500)


async def api_chat_stream(request):
    """从已保存的配置调用 LLM 并流式返回"""
    try:
        body = await request.json()
        text = body.get("text", "")
        model = body.get("model", "") or "default"
        conv_key = body.get("key", "")
        now_ts = time.time()

        # 读取已保存的配置
        raw = meta_get("desktop_config")
        if not raw:
            return web.json_response({"error": "请先在设置中配置 API Key"}, status=400)
        cfg = json.loads(raw)
        decrypt_config(cfg)  # 解密 api_key
        providers = cfg.get("api_providers", {})

        # 根据 model 找对应的 provider
        provider_id = None
        api_key = ""
        api_url = ""
        for pid, pcfg in providers.items():
            if pcfg.get("model") == model or not provider_id:
                provider_id = pid
                api_key = pcfg.get("api_key", "")
                api_url = pcfg.get("api_url", "")
            if pcfg.get("model") == model:
                break

        if not api_key or not api_url:
            return web.json_response({"error": "未找到匹配的 API 配置"}, status=400)

        # 保存用户消息到对话历史
        if conv_key:
            try: conv_save_message(conv_key, "user", text, msg_time=now_ts)
            except: pass

        # 构造 OpenAI 兼容的流式请求
        import aiohttp
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        # 获取场景和提示词
        scene = body.get("scene", "owner")
        system_prompt = _get_prompt_text(scene)

        # Agent 模式：追加系统操作能力说明
        is_agent = "/agent/" in request.path
        has_system_kw = any(kw in text.lower() for kw in ["打开", "运行", "启动", "执行", "截图", "进程", "系统", "电脑", "安装", "搜索文件", "找文件"])
        if is_agent or has_system_kw:
            system_prompt += (
                "\n\n【系统操作能力】\n"
                "如果用户让你打开程序/游戏，你应该：\n"
                "1. 先调用 find_files 搜索程序的安装位置\n"
                "2. 找到后用 bash(\"start 完整路径\") 启动\n"
                "3. 如果找不到，再告诉用户未安装\n"
                "其他能力：\n"
                "- 打开网址：open_url(\"https://...\")\n"
                "- 查看系统信息：get_system_info()\n"
                "- 截图：screenshot() + analyze_image() 分析\n"
                "- 进程管理：list_processes() / kill_process()\n"
                "- 文件搜索：find_files(\"关键词\")\n"
                "- 系统命令：bash(\"命令\") 可执行任何系统命令（权限需用户确认）\n"
                "注意：优先用工具完成任务，不要只给文字建议。你拥有操控用户电脑的能力。"
            )

        # 构造消息列表
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": text})

        payload = {
            "model": model or "default",
            "messages": messages,
            "stream": True,
        }

        # ── 工具定义（从 tools 模块加载） ──
        TOOLS = tools.get_definitions()
        tool_ctx = {}
        img_p = _find_provider_by_type("image")
        if img_p: tool_ctx["image_provider"] = img_p
        vis_p = _find_provider_by_type("vision")
        if vis_p: tool_ctx["vision_provider"] = vis_p
        raw_cfg = meta_get("desktop_config")
        if raw_cfg:
            try:
                all_p = json.loads(raw_cfg).get("api_providers", {})
                for pid, pcfg in all_p.items():
                    if pcfg.get("type", "chat") == "chat":
                        tool_ctx["chat_provider"] = {"key": pid, **pcfg}
                        break
            except: pass
        # 上下文管理器
        ctx_mgr = ContextManager()
        sse = web.StreamResponse()
        sse.headers["Content-Type"] = "text/event-stream"
        sse.headers["Cache-Control"] = "no-cache"
        sse.headers["Connection"] = "keep-alive"
        _co = cors_origin_header(request)
        if _co:
            sse.headers["Access-Control-Allow-Origin"] = _co
            sse.headers["Vary"] = "Origin"
        await sse.prepare(request)

        full_response = ""
        usage_info = None
        errors_in_round = 0

        # ── 创建任务（存到 SSE 对象上，每次请求独立） ──
        from desktop_core.task_manager import get_manager as get_task_manager
        task_mgr = get_task_manager()
        user_text_preview = text[:120].replace("\n", " ")
        task = task_mgr.create_task(user_text_preview)
        sse._task_id = task.id  # 关键：存在 SSE 对象上，不污染模块级变量
        # 清理旧任务（防止长期积累）
        try: task_mgr.clean_old_tasks(max_age=3600)
        except: pass
        # 清理上一轮 session 的工具发现缓存
        try: tools.clear_discovered()
        except: pass

        # 注册取消事件（供前端终止 Agent 循环）
        cancel_event = asyncio.Event()
        if conv_key:
            _agent_cancel_events[conv_key] = cancel_event

        async def cleanup():
            _agent_cancel_events.pop(conv_key, None)  # 连续错误计数，用于降级

        try:
            # ── Agent 循环 ──
            round_num = 0
            while True:
                round_num += 1
                # 安全上限：防止意外无限循环
                if round_num > 200:
                    log.warning(f"[Agent] 达到安全上限 200 轮，强制结束")
                    break
                # 取消检查
                if cancel_event.is_set():
                    await sse.write(f"event: status\ndata: {json.dumps({'state': 'done', 'text': '已取消'})}\n\n".encode())
                    await sse.write(f"event: finish\ndata: {json.dumps({'usage': usage_info})}\n\n".encode())
                    await sse.write_eof()
                    # 标记任务取消
                    task_mgr.update_task_status(sse._task_id, "failed", "用户取消")
                    return sse
                # ── 任务指引（首轮注入） ──
                if round_num == 0:
                    if any(kw in text.lower() for kw in ["写代码", "开发", "创建项目", "改代码", "修复", "重构", "添加功能", "添功能"]):
                        dev_prompt = (
                            "\n\n【开发任务指引】\n"
                            "1. 先用 list_files 或 grep_search 了解项目结构\n"
                            "2. 用 read_file 读取相关文件了解现有代码\n"
                            "3. 用 edit_file 或 write_file 修改/创建文件\n"
                            "4. 用 run_command 执行构建、测试验证\n"
                            "5. 如果出错，分析错误信息后修复再试"
                        )
                        messages.insert(-1, {"role": "system", "content": dev_prompt})

                # ── 错误恢复：连续失败3次时尝试降级 ──
                if errors_in_round >= 3:
                    fallback_msg = "之前尝试的工具调用失败了。请换一种方式完成任务，或者告诉用户做不到"
                    messages.append({"role": "system", "content": fallback_msg})
                    errors_in_round = 0

                # ── 上下文压缩（超限时自动触发） ──
                if ctx_mgr.should_compress(messages):
                    compressed = ctx_mgr.compress(messages)
                    if len(compressed) < len(messages):
                        log.info(f"[Agent] 上下文压缩: {len(messages)} → {len(compressed)} 条消息")
                        messages = compressed

                # ── 请求 LLM ──
                # 首轮只发 20 核心工具 + MCP，避免 token 爆炸；
                # 后续轮次 LLM 已了解可用能力，发全部工具
                current_tools = tools.get_fast_definitions() if round_num == 0 else TOOLS
                payload = {
                    "model": model,
                    "messages": messages,
                    "tools": current_tools,
                    "tool_choice": "auto",
                    "stream": False,
                }
                async with aiohttp.ClientSession(headers=headers) as session:
                    async with session.post(api_url, json=payload, timeout=aiohttp.ClientTimeout(total=120)) as resp:
                        if resp.status != 200:
                            err = await resp.text()
                            await sse.write(f"event: status\ndata: {json.dumps({'state': 'error', 'text': f'API 返回 {resp.status}'})}\n\n".encode())
                            await sse.write(f"event: finish\ndata: {json.dumps({'usage': None})}\n\n".encode())
                            await sse.write_eof()
                            return sse

                        result = await resp.json()
                        choice = result["choices"][0]
                        msg = choice.get("message", {})
                        finish = choice.get("finish_reason", "")
                        content = msg.get("content", "")
                        tool_calls = msg.get("tool_calls", [])

                # ── Token 用量 ──
                round_input, round_output = 0, 0
                if "usage" in result:
                    u = result["usage"]
                    round_input = u.get("prompt_tokens", u.get("input_tokens", u.get("input", 0)))
                    round_output = u.get("completion_tokens", u.get("output_tokens", u.get("output", 0)))
                if not round_input and not round_output:
                    _est = _estimate_tokens
                    msgs_text = json.dumps([m.get("content", "") for m in messages], ensure_ascii=False)
                    round_input = max(50, _est(msgs_text))
                    round_output = max(10, _est(content)) if content else 20
                if usage_info:
                    usage_info["input"] = (usage_info.get("input", 0) or 0) + round_input
                    usage_info["output"] = (usage_info.get("output", 0) or 0) + round_output
                else:
                    usage_info = {"input": round_input, "output": round_output}

                # ── 保存 assistant 回复 ──
                msg_entry = {"role": "assistant", "content": content}
                if tool_calls:
                    msg_entry["tool_calls"] = tool_calls
                messages.append(msg_entry)

                # ── 处理工具调用（支持并行执行独立工具） ──
                if finish == "tool_calls" and tool_calls:
                    # 给 LLM 发送 tool_use 事件
                    for tc in tool_calls:
                        fn = tc.get("function", {})
                        fn_name = fn.get("name", "")
                        try: fn_args = json.loads(fn.get("arguments", "{}"))
                        except: fn_args = {}
                        await sse.write(f"event: tool_use\ndata: {json.dumps({'name': fn_name, 'args': fn_args, 'id': tc.get('id', '')})}\n\n".encode())

                    # 并行执行：分组执行独立的工具调用
                    # 策略：优先串行（更安全），但如果 LLM 一次返回多个工具，尝试并行
                    parallel_results = {}
                    exec_tasks = []

                    async def _exec_one(tc):
                        fn = tc.get("function", {})
                        fn_name = fn.get("name", "")
                        try: fn_args = json.loads(fn.get("arguments", "{}"))
                        except: fn_args = {}
                        call_id = tc.get("id", "")
                        max_retries = 2

                        # ── 任务步进：添加步骤并标记进行中 ──
                        step_desc = f"{fn_name}({str(fn_args)[:60]})"
                        step_idx = task_mgr.add_step(sse._task_id, step_desc)
                        if step_idx is not None:
                            task_mgr.update_step(sse._task_id, step_idx, "running")

                        for retry in range(max_retries):
                            # 高危工具：权限确认（按信任级别分级）
                            if fn_name in HIGH_RISK_TOOLS:
                                # ── 1. 全局完全信任：跳过所有确认 ──
                                full_trust = meta_get("desktop_full_trust") == "true"
                                if full_trust:
                                    tr = await tools.execute(fn_name, fn_args, {**tool_ctx, "high_risk_approved": True})
                                # ── 2. 会话级信任：该工具已授权，直接执行 ──
                                elif conv_key and fn_name in _session_trust.get(conv_key, set()):
                                    tr = await tools.execute(fn_name, fn_args, {**tool_ctx, "high_risk_approved": True})
                                # ── 3. 需要弹窗确认 ──
                                else:
                                    req_id = call_id or f"perm_{time.time()}"
                                    perm_event = asyncio.Event()
                                    perm_result = {"approved": False, "always_allow": False}
                                    _PENDING_PERMISSIONS[req_id] = {"event": perm_event, "result": perm_result}
                                    await sse.write(f"event: permission_request\ndata: {json.dumps({'id': req_id, 'name': fn_name, 'args': fn_args})}\n\n".encode())
                                    try:
                                        await asyncio.wait_for(perm_event.wait(), timeout=120)
                                    except asyncio.TimeoutError:
                                        if step_idx is not None:
                                            task_mgr.update_step(sse._task_id, step_idx, "failed", "权限确认超时")
                                        return call_id, "⏱ 权限确认超时，已取消"
                                    else:
                                        if perm_result.get("approved"):
                                            tr = await tools.execute(fn_name, fn_args, {**tool_ctx, "high_risk_approved": True})
                                            # 勾选"始终允许"→ 加入会话级信任
                                            if perm_result.get("always_allow") and conv_key:
                                                if conv_key not in _session_trust:
                                                    _session_trust[conv_key] = set()
                                                _session_trust[conv_key].add(fn_name)
                                        else:
                                            if step_idx is not None:
                                                task_mgr.update_step(sse._task_id, step_idx, "failed", "用户拒绝")
                                            tr = "❌ 用户拒绝了操作"
                                    finally:
                                        _PENDING_PERMISSIONS.pop(req_id, None)
                            else:
                                tr = await tools.execute(fn_name, fn_args, tool_ctx)

                            # 错误恢复：失败时重试（最多2次）
                            if tr and ("失败" in tr[:20] or "出错" in tr[:20] or "❌" in tr[:10]):
                                if retry < max_retries - 1:
                                    log.info(f"[Agent] 工具 {fn_name} 失败，重试第 {retry+2} 次")
                                    await asyncio.sleep(1)
                                    continue
                                # 所有重试都失败→标记步骤失败
                                if step_idx is not None:
                                    task_mgr.update_step(sse._task_id, step_idx, "failed", tr[:100])
                            else:
                                # 执行成功
                                if step_idx is not None:
                                    task_mgr.update_step(sse._task_id, step_idx, "done")
                            break
                        return call_id, tr

                    # 几个工具同时跑（并行）
                    if len(tool_calls) > 1:
                        exec_tasks = [_exec_one(tc) for tc in tool_calls]
                        results = await asyncio.gather(*exec_tasks, return_exceptions=True)
                        for r in results:
                            if isinstance(r, Exception):
                                log.warning(f"[Agent] 工具并行执行异常: {r}")
                                continue
                            call_id, result_text = r
                            if call_id:
                                parallel_results[call_id] = result_text
                    else:
                        call_id, result_text = await _exec_one(tool_calls[0])
                        if call_id:
                            parallel_results[call_id] = result_text

                    # 将结果添加到 messages（截断到 800 字符控制 token 消耗）
                    errors_in_round = 0
                    for tc in tool_calls:
                        call_id = tc.get("id", "")
                        tr = parallel_results.get(call_id, "（工具执行失败）")
                        if "失败" in tr[:20] or "出错" in tr[:20]:
                            errors_in_round += 1
                        truncated = tr[:800] + ("" if len(tr) <= 800 else "\n...（结果过长已截断）")
                        await sse.write(f"event: tool_result\ndata: {json.dumps({'tool_call_id': call_id, 'name': tc.get('function', {}).get('name', ''), 'content': tr[:200]})}\n\n".encode())
                        messages.append({"role": "tool", "tool_call_id": call_id, "name": tc.get("function", {}).get("name", ""), "content": truncated})
                    continue

                # ── 文字回复：流式输出 ──
                if content:
                    full_response = content
                    chunk_size = 20
                    for i in range(0, len(content), chunk_size):
                        await sse.write(f"event: text-delta\ndata: {json.dumps({'text': content[i:i + chunk_size]})}\n\n".encode())
                        await asyncio.sleep(0.01)
                # 标记任务完成
                task_mgr.update_task_status(sse._task_id, "done")
                break

            # 保存 AI 回复
            if conv_key and full_response:
                try: conv_save_message(conv_key, "assistant", full_response, msg_time=time.time())
                except: pass

            # ── 所有工具调用完成后汇总（如果没有自动生成回复） ──
            if not content and tool_calls and not cancel_event.is_set():
                try:
                    summary_prompt = "请用中文总结你刚才完成的所有操作和结果，用自然语言告诉用户"
                    messages.append({"role": "user", "content": summary_prompt})
                    pay = {"model": model, "messages": messages, "stream": True}
                    async with aiohttp.ClientSession(headers=headers) as session:
                        async with session.post(api_url, json=pay, timeout=aiohttp.ClientTimeout(total=60)) as resp:
                            if resp.status == 200:
                                async for line in resp.content:
                                    line = line.decode("utf-8", errors="replace").strip()
                                    if line.startswith("data: ") and line != "data: [DONE]":
                                        try:
                                            d = json.loads(line[6:])
                                            txt = (d.get("choices", [{}])[0].get("delta", {}) or {}).get("content", "")
                                            if txt:
                                                full_response = (full_response or "") + txt
                                                await sse.write(f"event: text-delta\ndata: {json.dumps({'text': txt})}\n\n".encode())
                                        except: pass
                except Exception:
                    pass

        except Exception as e:
            await sse.write(f"event: status\ndata: {json.dumps({'state': 'error', 'text': str(e)})}\n\n".encode())
            await sse.write(f"event: finish\ndata: {json.dumps({'usage': usage_info})}\n\n".encode())
            await sse.write_eof()
            # 标记任务失败
            try: task_mgr.update_task_status(sse._task_id, "failed", str(e)[:100])
            except: pass
            return sse
        finally:
            await cleanup()

        await sse.write(f"event: finish\ndata: {json.dumps({'usage': usage_info})}\n\n".encode())
        await sse.write_eof()
        await cleanup()
        return sse

    except Exception as e:
        return web.json_response({"error": str(e)}, status=500)


# ── 对话历史 ──

async def api_conversations_list(request):
    """获取所有对话摘要列表"""
    convs = conv_list()
    return web.json_response({"conversations": convs, "total": len(convs)})


async def api_conversation_get(request):
    """获取某个对话的消息（支持 ?limit= 限制条数，默认 200，auto 对话默认 50）"""
    key = request.match_info.get("key", "")
    if not key:
        return web.json_response({"error": "缺少 key"}, status=400)
    try:
        limit = int(request.query.get("limit", 0))
    except:
        limit = 0
    # auto 对话默认只返回最近 50 条，其他默认 200
    if not limit:
        limit = 50 if key.startswith("auto:") else 200
    msgs = conv_get_messages(key)
    total = len(msgs)
    if limit > 0 and total > limit:
        msgs = msgs[-limit:]
    return web.json_response({"key": key, "messages": msgs, "total": total})


async def api_conversation_delete(request):
    """删除某个对话"""
    body = await request.json()
    key = body.get("key", "")
    if not key:
        return web.json_response({"error": "缺少 key"}, status=400)
    conv_delete(key)
    return web.json_response({"ok": True})


async def api_conversation_message_delete(request):
    """删除对话中的单条消息"""
    body = await request.json()
    key = body.get("key", "")
    msg_id = body.get("msg_id", 0)
    if not key or not msg_id:
        return web.json_response({"error": "缺少 key 或 msg_id"}, status=400)
    ok = conv_delete_message(key, msg_id)
    return web.json_response({"ok": ok})


async def api_providers(request):
    import os
    pj_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "platforms.json")
    try:
        with open(pj_path, encoding="utf-8") as f:
            data = json.load(f)
        return web.json_response(data)
    except Exception as e:
        return web.json_response({"error": str(e)}, status=500)


async def api_providers(request):
    """返回已保存的 API 提供商配置（兼容 Chat 页面的 ProviderSettings）"""
    raw = meta_get("desktop_config")
    providers = []
    if raw:
        try:
            cfg = json.loads(raw)
            for pid, pcfg in cfg.get("api_providers", {}).items():
                providers.append({
                    "id": hash(pid) % 10000,
                    "name": pid,
                    "type": pid,
                    "api_url": pcfg.get("api_url", ""),
                    "has_key": bool(pcfg.get("api_key", "")),
                    "models": [pcfg.get("model", "default")] if pcfg.get("model") else [],
                })
        except:
            pass
    return web.json_response({"providers": providers})
    import os
    pj_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "platforms.json")
    try:
        with open(pj_path, encoding="utf-8") as f:
            data = json.load(f)
        return web.json_response(data)
    except Exception as e:
        return web.json_response({"error": str(e)}, status=500)


# ── 提示词 / 专家 / Skill API ──

def _load_builtin_resource(filename: str) -> list:
    """加载内置资源库 JSON（专家/Skill/提示词），任何异常都返回空列表并写中文日志。

    多路径兜底：优先 _DESKTOP_DIR/data/prompts；再退到当前文件上级的
    resources/data/prompts（应对开发态与打包态单/双层 resources 目录差异），
    确保打包后资源库一定能被找到，而不是静默为空。
    """
    import os, json as _json
    candidates = [
        os.path.join(_DESKTOP_DIR, "data", "prompts", filename),
        os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "prompts", filename),
        os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "resources", "data", "prompts", filename),
    ]
    for fp in candidates:
        try:
            if os.path.exists(fp):
                with open(fp, "r", encoding="utf-8") as f:
                    return _json.load(f)
        except Exception as e:
            logging.getLogger("桌面端").warning(f"读取内置资源库失败（尝试下一个路径）: {fp}: {e}")
    logging.getLogger("桌面端").warning(f"内置资源库未找到: {filename}，返回空列表")
    return []

async def api_prompts_github(request):
    """返回从 GitHub 下载的所有提示词（合并自定义）"""
    try:
        data = _load_builtin_resource("prompts.json")
        data = _load_custom("custom_prompts") + data
        category = request.query.get("category", "")
        search = request.query.get("search", "")
        if category:
            data = [p for p in data if p.get("category") == category]
        if search:
            kw = search.lower()
            data = [p for p in data if kw in p.get("act", "").lower() or kw in p.get("prompt", "").lower()]
        return web.json_response({"prompts": data, "total": len(data)})
    except Exception as e:
        logging.getLogger("桌面端").warning(f"提示词列表接口异常（返回空）: {e}")
        return web.json_response({"prompts": [], "total": 0})

async def api_experts_list(request):
    """返回专家列表（合并自定义）"""
    try:
        data = _load_builtin_resource("experts.json")
        data = _load_custom("custom_experts") + data
        category = request.query.get("category", "")
        search = request.query.get("search", "")
        if category:
            data = [e for e in data if e.get("category") == category]
        if search:
            kw = search.lower()
            data = [e for e in data if kw in e.get("name", "").lower()]
        return web.json_response({"experts": data, "total": len(data)})
    except Exception as e:
        logging.getLogger("桌面端").warning(f"专家列表接口异常（返回空）: {e}")
        return web.json_response({"experts": [], "total": 0})

async def api_skills_list(request):
    """返回 Skill 列表（合并自定义）"""
    try:
        data = _load_builtin_resource("skills.json")
        data = _load_custom("custom_skills") + data
        category = request.query.get("category", "")
        search = request.query.get("search", "")
        if category:
            data = [s for s in data if s.get("category") == category]
        if search:
            kw = search.lower()
            data = [s for s in data if kw in s.get("name", "").lower()]
        return web.json_response({"skills": data, "total": len(data)})
    except Exception as e:
        logging.getLogger("桌面端").warning(f"Skill 列表接口异常（返回空）: {e}")
        return web.json_response({"skills": [], "total": 0})


# ── 自定义 CRUD ──

def _load_custom(meta_key: str) -> list:
    """从 meta 表加载自定义数据。

    任何异常（meta 表尚未建、数据库被锁、路径不对、JSON 损坏）都吞掉并返回空列表，
    绝不向上抛出——否则会连累 experts/skills/prompts 端点整体 500、资源库空白。
    """
    try:
        from desktop_core.storage import meta_get
        raw = meta_get(meta_key)
    except Exception as e:
        logging.getLogger("桌面端").warning(f"读取自定义数据失败（已忽略）: {meta_key}: {e}")
        return []
    if raw:
        try:
            return json.loads(raw)
        except Exception:
            pass
    return []

def _save_custom(meta_key: str, items: list):
    """保存自定义数据到 meta 表"""
    from desktop_core.storage import meta_set
    meta_set(meta_key, json.dumps(items, ensure_ascii=False))

async def api_custom_list(request):
    """列出某类型的自定义资源"""
    meta_key = request.query.get("type", "")
    if meta_key not in ("custom_prompts", "custom_experts", "custom_skills"):
        return web.json_response({"items": [], "total": 0})
    return web.json_response({"items": _load_custom(meta_key), "total": 0})

async def api_custom_save(request):
    """保存自定义资源（添加/编辑）"""
    try:
        body = await request.json()
        meta_key = body.get("type", "")
        if meta_key not in ("custom_prompts", "custom_experts", "custom_skills"):
            return web.json_response({"error": "无效的类型"}, status=400)
        item = body.get("item", {})
        items = _load_custom(meta_key)
        idx = body.get("index", -1)
        if idx >= 0 and idx < len(items):
            items[idx] = item
        else:
            items.insert(0, item)  # 新添加的放最前面
        _save_custom(meta_key, items)
        return web.json_response({"ok": True, "total": len(items)})
    except Exception as e:
        return web.json_response({"error": str(e)}, status=400)

async def api_custom_delete(request):
    """删除自定义资源"""
    try:
        body = await request.json()
        meta_key = body.get("type", "")
        if meta_key not in ("custom_prompts", "custom_experts", "custom_skills"):
            return web.json_response({"error": "无效的类型"}, status=400)
        idx = body.get("index", -1)
        items = _load_custom(meta_key)
        if 0 <= idx < len(items):
            items.pop(idx)
            _save_custom(meta_key, items)
        return web.json_response({"ok": True})
    except Exception as e:
        return web.json_response({"error": str(e)}, status=400)


# ── 知识库 API ──

async def api_knowledge_list(request):
    """列出所有知识条目"""
    from desktop_core.storage import meta_get, meta_set
    try:
        raw = meta_get("knowledge_base")
        items = json.loads(raw) if raw else []
        import time
        # 确保每个条目有 id（兼容旧数据）
        changed = False
        for i, item in enumerate(items):
            if not item.get("id"):
                items[i]["id"] = f"k_{int(time.time())}_{i}"
                changed = True
        if changed:
            meta_set("knowledge_base", json.dumps(items, ensure_ascii=False))
        cat = request.query.get("category", "")
        if cat:
            items = [i for i in items if i.get("category", "") == cat]
        # 统计分类
        from collections import Counter
        cats = Counter(i.get("category", "未分类") for i in items)
        categories = [{"name": k, "count": v} for k, v in cats.most_common()]
        return web.json_response({"items": items, "categories": categories, "total": len(items)})
    except Exception as e:
        return web.json_response({"error": str(e)}, status=400)


async def api_knowledge_summary(request):
    """知识库汇总（分类统计 + 总数）"""
    from desktop_core.storage import meta_get
    try:
        raw = meta_get("knowledge_base")
        items = json.loads(raw) if raw else []
        from collections import Counter
        cats = Counter(i.get("category", "未分类") for i in items)
        return web.json_response({
            "total": len(items),
            "categories": [{"name": k, "count": v} for k, v in cats.most_common()],
        })
    except Exception as e:
        return web.json_response({"error": str(e)}, status=400)


async def api_knowledge_add(request):
    """添加知识条目"""
    from desktop_core.storage import meta_get, meta_set
    try:
        body = await request.json()
        title = body.get("title", "").strip()
        content = body.get("content", "").strip()
        category = body.get("category", "默认").strip()
        if not title:
            return web.json_response({"error": "标题不能为空"}, status=400)
        raw = meta_get("knowledge_base")
        try: items = json.loads(raw) if raw else []
        except: items = []
        import time
        items.append({
            "id": f"k_{int(time.time())}_{len(items)}",
            "title": title,
            "content": content,
            "category": category,
            "created_at": time.strftime("%Y-%m-%d %H:%M:%S")
        })
        meta_set("knowledge_base", json.dumps(items, ensure_ascii=False))
        return web.json_response({"ok": True, "total": len(items)})
    except Exception as e:
        return web.json_response({"error": str(e)}, status=400)


async def api_knowledge_delete(request):
    """删除知识条目"""
    from desktop_core.storage import meta_get, meta_set
    try:
        body = await request.json()
        kid = body.get("id", "")
        raw = meta_get("knowledge_base")
        try: items = json.loads(raw) if raw else []
        except: items = []
        items = [i for i in items if i.get("id") != kid]
        meta_set("knowledge_base", json.dumps(items, ensure_ascii=False))
        return web.json_response({"ok": True, "total": len(items)})
    except Exception as e:
        return web.json_response({"error": str(e)}, status=400)


async def api_knowledge_search(request):
    """搜索知识条目"""
    from desktop_core.storage import meta_get
    try:
        body = await request.json()
        query = body.get("query", "").strip().lower()
        if not query:
            return web.json_response({"items": [], "total": 0})
        raw = meta_get("knowledge_base")
        try: items = json.loads(raw) if raw else []
        except: items = []
        results = [i for i in items if query in i.get("title", "").lower() or query in i.get("content", "").lower()]
        return web.json_response({"items": results[:10], "total": len(results)})
    except Exception as e:
        return web.json_response({"error": str(e)}, status=400)


async def api_knowledge_update(request):
    """更新知识条目"""
    from desktop_core.storage import meta_get, meta_set
    try:
        body = await request.json()
        kid = body.get("id", "")
        raw = meta_get("knowledge_base")
        try: items = json.loads(raw) if raw else []
        except: items = []
        for i, item in enumerate(items):
            if item.get("id") == kid:
                if body.get("title"): items[i]["title"] = body["title"].strip()
                if "content" in body: items[i]["content"] = body.get("content", "").strip()
                if body.get("category"): items[i]["category"] = body["category"].strip()
                import time
                items[i]["updated_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
                meta_set("knowledge_base", json.dumps(items, ensure_ascii=False))
                return web.json_response({"ok": True})
        return web.json_response({"error": "条目不存在"}, status=404)
    except Exception as e:
        return web.json_response({"error": str(e)}, status=400)


async def api_knowledge_import_url(request):
    """从 URL 导入内容到知识库"""
    from desktop_core.storage import meta_get, meta_set
    import aiohttp
    try:
        body = await request.json()
        url = body.get("url", "").strip()
        category = body.get("category", "网页导入").strip()
        if not url:
            return web.json_response({"error": "URL 不能为空"}, status=400)
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                if resp.status != 200:
                    return web.json_response({"error": f"请求失败: HTTP {resp.status}"}, status=400)
                html = await resp.text()
        import re
        title = url.split("/")[-1][:60] or "网页导入"
        m = re.search(r'<title>(.*?)</title>', html, re.IGNORECASE | re.DOTALL)
        if m:
            title = m.group(1).strip()[:60]
        # 去标签取纯文本
        text = re.sub(r'<[^>]+>', ' ', html)
        text = re.sub(r'\s+', ' ', text).strip()[:2000]
        if not text:
            text = "(无法提取内容)"
        raw = meta_get("knowledge_base")
        items = json.loads(raw) if raw else []
        import time
        items.append({
            "id": f"k_{int(time.time())}_{len(items)}",
            "title": title,
            "content": text,
            "category": category,
            "source_url": url,
            "created_at": time.strftime("%Y-%m-%d %H:%M:%S")
        })
        meta_set("knowledge_base", json.dumps(items, ensure_ascii=False))
        return web.json_response({"ok": True, "title": title, "total": len(items)})
    except Exception as e:
        return web.json_response({"error": f"导入失败: {str(e)[:100]}"}, status=400)


async def api_knowledge_import_github(request):
    """从 GitHub 仓库导入 markdown 文件作为知识条目"""
    import aiohttp, time, os
    try:
        body = await request.json()
        repo = body.get("repo", "").strip()
        branch = body.get("branch", "main").strip()
        path = body.get("path", "").strip()
        if not repo:
            return web.json_response({"error": "请填写仓库地址（如 owner/repo）"}, status=400)

        token = ""
        encrypted = meta_get("github_token") or ""
        if encrypted:
            from desktop_core.storage import decrypt_api_key
            try: token = decrypt_api_key(encrypted)
            except: pass
        if not token:
            token = os.environ.get("GITHUB_TOKEN", "")

        headers = {"Accept": "application/vnd.github.v3+json"}
        if token:
            headers["Authorization"] = f"Bearer {token}"

        api_url = f"https://api.github.com/repos/{repo}/contents/{path}"
        if branch:
            api_url += f"?ref={branch}"

        async with aiohttp.ClientSession(headers=headers) as sess:
            async with sess.get(api_url) as resp:
                if resp.status == 403:
                    return web.json_response({"error": "GitHub API 频率限制，请设置 Token"}, status=429)
                if resp.status == 404:
                    return web.json_response({"error": "仓库或路径不存在"}, status=404)
                if resp.status != 200:
                    return web.json_response({"error": f"GitHub API 返回 {resp.status}"}, status=resp.status)
                items = await resp.json()

        if not isinstance(items, list):
            items = [items]

        md_files = [f for f in items if f.get("type") == "file" and f["name"].endswith((".md", ".mdx"))]
        if not md_files:
            return web.json_response({"error": "该路径下没有找到 markdown 文件"}, status=404)

        raw = meta_get("knowledge_base")
        kb = json.loads(raw) if raw else []
        imported = 0
        errors = []

        async with aiohttp.ClientSession(headers=headers) as sess:
            for f in md_files:
                try:
                    async with sess.get(f["download_url"]) as resp:
                        if resp.status != 200:
                            errors.append(f["name"]); continue
                        content = await resp.text()
                    kb.append({
                        "id": f"k_{int(time.time())}_{len(kb)}",
                        "title": f["name"].replace(".md", "").replace(".mdx", ""),
                        "content": content[:5000],
                        "category": "github",
                        "source_url": f["html_url"],
                        "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                    })
                    imported += 1
                except:
                    errors.append(f["name"])

        meta_set("knowledge_base", json.dumps(kb, ensure_ascii=False))
        msg = f"成功导入 {imported} 个文件"
        if errors:
            msg += f"，{len(errors)} 个失败"
        return web.json_response({"ok": True, "imported": imported, "total": len(kb), "message": msg})
    except Exception as e:
        return web.json_response({"error": f"导入失败: {str(e)[:200]}"}, status=400)


# ── 记忆 API（Hermes 风格：FTS 搜索 + 统计 + 分类）──

async def api_memory_stats(request):
    """记忆统计：总数、按对话类型分组、最近活动"""
    from desktop_core.storage import _get_conn
    try:
        conn = _get_conn()
        # 总消息数
        total = conn.execute("SELECT COUNT(*) as c FROM conv_messages").fetchone()["c"]
        # 对话数
        conv_count = conn.execute("SELECT COUNT(*) as c FROM convs").fetchone()["c"]
        # 按类型分组（auto: 自动化 / test: 测试 / 其他）
        type_rows = conn.execute(
            """SELECT 
                CASE 
                    WHEN conv_key LIKE 'auto:%' THEN '自动'
                    WHEN conv_key LIKE 'test%' THEN '测试'
                    ELSE '对话'
                END as type,
                COUNT(*) as cnt 
               FROM conv_messages GROUP BY type ORDER BY cnt DESC"""
        ).fetchall()
        categories = [{"name": r["type"], "count": r["cnt"]} for r in type_rows]
        # 最近 7 天活跃
        recent = conn.execute(
            "SELECT COUNT(*) as c FROM conv_messages WHERE time >= datetime('now', '-7 days', 'localtime')"
        ).fetchone()["c"]
        # 最近记忆片段（最新 5 条消息）
        recent_rows = conn.execute(
            "SELECT conv_key, role, content, datetime(time, 'unixepoch', 'localtime') as time FROM conv_messages ORDER BY id DESC LIMIT 5"
        ).fetchall()
        recent_items = []
        for r in recent_rows:
            recent_items.append({
                "conv": r["conv_key"],
                "role": r["role"],
                "content": r["content"][:100] if r["content"] else "",
                "time": r["time"],
            })
        conn.close()
        return web.json_response({
            "total": total,
            "conversations": conv_count,
            "recent_7d": recent,
            "categories": categories,
            "recent": recent_items,
        })
    except Exception as e:
        return web.json_response({"error": str(e)}, status=400)


async def api_memory_search(request):
    """搜索记忆（对话内容 FTS）"""
    from desktop_core.storage import _get_conn
    try:
        body = await request.json()
        query = body.get("query", "").strip().lower()
        conv_filter = body.get("conv", "")
        page = max(1, int(body.get("page", 1)))
        limit = min(50, max(1, int(body.get("limit", 20))))
        if not query:
            return web.json_response({"items": [], "total": 0})
        
        conn = _get_conn()
        where = "WHERE LOWER(content) LIKE ?"
        params = [f"%{query}%"]
        if conv_filter:
            where += " AND conv_key = ?"
            params.append(conv_filter)
        
        total = conn.execute(f"SELECT COUNT(*) as c FROM conv_messages {where}", params).fetchone()["c"]
        offset = (page - 1) * limit
        rows = conn.execute(
            f"SELECT id, conv_key, role, content, datetime(time, 'unixepoch', 'localtime') as time FROM conv_messages {where} ORDER BY id DESC LIMIT ? OFFSET ?",
            params + [limit, offset]
        ).fetchall()
        conn.close()
        items = []
        for r in rows:
            items.append({
                "id": r["id"],
                "conv": r["conv_key"],
                "role": r["role"],
                "content": (r["content"] or "")[:300],
                "time": r["time"],
            })
        return web.json_response({"items": items, "total": total, "page": page})
    except Exception as e:
        return web.json_response({"error": str(e)}, status=400)


async def api_memory_categories(request):
    """记忆分类列表（对话列表作为分类）"""
    from desktop_core.storage import _get_conn
    try:
        conn = _get_conn()
        rows = conn.execute(
            "SELECT key, last_msg, msg_count, last_time FROM convs ORDER BY last_time DESC"
        ).fetchall()
        conn.close()
        categories = []
        for r in rows:
            categories.append({
                "key": r["key"],
                "label": r["key"][:30],
                "count": r["msg_count"] or 0,
                "last_msg": (r["last_msg"] or "")[:60],
                "last_time": r["last_time"] or "",
            })
        return web.json_response({"categories": categories, "total": len(categories)})
    except Exception as e:
        return web.json_response({"error": str(e)}, status=400)

async def api_automations_list(request):
    """列出所有自动化任务"""
    from desktop_core.storage import automation_list
    return web.json_response({"automations": automation_list()})


async def api_automations_save(request):
    """创建或更新自动化任务"""
    import time
    from desktop_core.storage import automation_save
    body = await request.json()
    now = time.strftime("%Y-%m-%d %H:%M:%S")
    item = {
        "id": body.get("id") or f"auto_{int(time.time())}",
        "name": body.get("name", ""),
        "prompt": body.get("prompt", ""),
        "schedule_type": body.get("schedule_type", "recurring"),
        "rrule": body.get("rrule", ""),
        "scheduled_at": body.get("scheduled_at", ""),
        "status": "active",
        "model": body.get("model", ""),
        "valid_from": body.get("valid_from", ""),
        "valid_until": body.get("valid_until", ""),
        "last_run": "",
        "created_at": now,
        "workflow_id": body.get("workflow_id", ""),
        "trigger_type": body.get("trigger_type", "schedule"),
        "config": body.get("config", ""),
        "description": body.get("description", ""),
        "last_result": "",
    }
    automation_save(item)
    return web.json_response({"ok": True, "id": item["id"]})


async def api_automations_toggle(request):
    """启用/暂停自动化"""
    from desktop_core.storage import automation_toggle
    body = await request.json()
    automation_toggle(body.get("id", ""))
    return web.json_response({"ok": True})


async def api_automations_delete(request):
    """删除自动化"""
    from desktop_core.storage import automation_delete
    body = await request.json()
    automation_delete(body.get("id", ""))
    return web.json_response({"ok": True})


async def api_automations_run(request):
    """立即执行自动化（Agent 模式 + 耗时统计）"""
    from desktop_core.storage import automation_get, automation_add_run
    import time, aiohttp, json
    body = await request.json()
    auto = automation_get(body.get("id", ""))
    if not auto:
        return web.json_response({"error": "未找到该自动化"}, status=404)

    start_ts = time.time()
    prompt = auto.get("prompt", "")
    workflow_id = auto.get("workflow_id", "")
    reply = ""
    model_used = ""
    
    # 工作流型：直接标记成功（无需 LLM 执行）
    if workflow_id and not prompt:
        duration = int((time.time() - start_ts) * 1000)
        automation_add_run(auto["id"], "success", prompt=f"[触发工作流] {auto.get('name', '')}", 
                          reply="", duration_ms=duration)
        return web.json_response({"ok": True, "result": "已触发工作流", "conv_key": "", "messages": []})
    
    if prompt:
        try:
            from desktop_core.storage import meta_get, decrypt_config
            from desktop_core.tools import get_auto_definitions, execute
            raw_cfg = meta_get("desktop_config")
            cfg = json.loads(raw_cfg) if raw_cfg else {}
            decrypt_config(cfg)
            providers = cfg.get("api_providers", {})
            model_name = auto.get("model", "")
            api_key = api_url = ""
            for pid, pcfg in providers.items():
                if model_name and pcfg.get("model") == model_name:
                    api_key, api_url, model_used = pcfg.get("api_key", ""), pcfg.get("api_url", ""), pcfg.get("model", "")
                    break
                elif pcfg.get("type", "chat") == "chat" and pcfg.get("api_key") and pcfg.get("api_url"):
                    api_key, api_url, model_used = pcfg.get("api_key", ""), pcfg.get("api_url", ""), pcfg.get("model", "")
                    break
            if api_key and api_url:
                # 修复 URL：避免重复 append /chat/completions
                base_url = api_url.rstrip("/")
                if not base_url.endswith("/chat/completions"):
                    base_url += "/chat/completions"
                # Agent 循环
                tools = get_auto_definitions()
                messages = [{"role": "user", "content": prompt}]
                headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
                for _ in range(5):
                    payload = {"model": model_used or "default", "messages": messages, "tools": tools, "tool_choice": "auto", "max_tokens": 2048}
                    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=60)) as sess:
                        async with sess.post(base_url, headers=headers, json=payload) as resp:
                            if resp.status == 200:
                                data = await resp.json()
                                msg = data.get("choices", [{}])[0].get("message", {})
                                reply = msg.get("content") or ""
                                tc = msg.get("tool_calls")
                                if not tc:
                                    break
                                messages.append(msg)
                                for t in tc:
                                    try: args = json.loads(t["function"]["arguments"])
                                    except: args = {}
                                    r = await execute(t["function"]["name"], args, {"user_id": "manual", "group_id": ""})
                                    messages.append({"role": "tool", "tool_call_id": t["id"], "content": str(r)[:500]})
                            else:
                                err_text = await resp.text()
                                log.warning(f"手动执行 LLM {resp.status}: {err_text[:200]}")
                                if not reply:  # 首次失败尝试无工具的请求
                                    payload2 = {"model": model_used or "default", "messages": [{"role": "user", "content": prompt}], "max_tokens": 1024}
                                    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=30)) as s2:
                                        async with s2.post(base_url, headers=headers, json=payload2) as r2:
                                            if r2.status == 200:
                                                d2 = await r2.json()
                                                reply = d2.get("choices", [{}])[0].get("message", {}).get("content", "")
                                break
        except Exception as e:
            log.warning(f"手动执行 LLM 失败: {e}")

    duration = int((time.time() - start_ts) * 1000)
    automation_add_run(auto["id"], "success" if reply else "failed", prompt=prompt, reply=reply, model_used=model_used, duration_ms=duration)
    conv_key = ""
    conv_messages: list[dict] = []
    if prompt:
        from desktop_core.storage import conv_save_message_sync, conv_get_messages
        conv_key = f"auto:{''.join(c if c.isalnum() or c in ' _-' else '_' for c in auto.get('name', '自动化'))[:30]}"
        conv_save_message_sync(conv_key, "user", f"[自动化] {prompt}")
        conv_save_message_sync(conv_key, "assistant", reply or "执行完成")
        conv_messages = conv_get_messages(conv_key)
    result = f"手动执行: {reply[:200]}" if reply else f"执行失败"
    return web.json_response({"ok": True, "result": result, "conv_key": conv_key, "messages": conv_messages})


async def api_automations_delete_run(request):
    """删除单条执行记录"""
    from desktop_core.storage import automation_delete_run
    body = await request.json()
    automation_delete_run(body.get("id", 0))
    return web.json_response({"ok": True})


async def api_automations_trigger(request):
    """外部触发自动化执行（webhook）"""
    from desktop_core.storage import automation_get, automation_add_run
    import time, aiohttp
    body = await request.json() if request.can_read_body else {}
    auto_id = body.get("id", "") or request.query.get("id", "")
    if not auto_id:
        return web.json_response({"error": "缺少自动化 id"}, status=400)
    auto = automation_get(auto_id)
    if not auto:
        return web.json_response({"error": "未找到该自动化"}, status=404)
    if auto.get("status") != "active":
        return web.json_response({"error": "自动化已暂停"}, status=400)

    start_ts = time.time()
    prompt = auto.get("prompt", "")
    reply = ""
    model_used = ""
    try:
        from desktop_core.storage import meta_get, decrypt_config
        raw_cfg = meta_get("desktop_config")
        cfg = json.loads(raw_cfg) if raw_cfg else {}
        decrypt_config(cfg)
        model_name = auto.get("model", "")
        api_key = api_url = ""
        for pid, pcfg in (cfg.get("api_providers") or {}).items():
            if model_name and pcfg.get("model") == model_name:
                api_key, api_url, model_used = pcfg.get("api_key", ""), pcfg.get("api_url", ""), pcfg.get("model", "")
                break
            elif pcfg.get("type", "chat") == "chat" and pcfg.get("api_key") and pcfg.get("api_url"):
                api_key, api_url, model_used = pcfg.get("api_key", ""), pcfg.get("api_url", ""), pcfg.get("model", "")
                break
        if api_key and api_url and prompt:
            base_url = api_url.rstrip("/")
            if not base_url.endswith("/chat/completions"):
                base_url += "/chat/completions"
            headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
            payload = {"model": model_used or "default", "messages": [{"role": "user", "content": prompt}], "max_tokens": 1024}
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=30)) as sess:
                async with sess.post(base_url, headers=headers, json=payload) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        reply = data.get("choices", [{}])[0].get("message", {}).get("content", "")
    except Exception as e:
        log.warning(f"外部触发执行 LLM 失败: {e}")

    duration = int((time.time() - start_ts) * 1000)
    automation_add_run(auto_id, "success" if reply else "failed", prompt=prompt, reply=reply, model_used=model_used, duration_ms=duration)
    if prompt:
        from desktop_core.storage import conv_save_message_sync
        conv_key = f"auto:{''.join(c if c.isalnum() or c in ' _-' else '_' for c in auto.get('name', '自动化'))[:30]}"
        conv_save_message_sync(conv_key, "user", f"[自动化] {prompt}")
        conv_save_message_sync(conv_key, "assistant", reply or "执行完成")
    return web.json_response({"ok": True, "result": f"已触发: {auto.get('name', '')}", "reply": reply[:200] if reply else ""})


# ── 运维 API ──

async def api_ops_dashboard(request):
    """运维总览：健康评分、可用性、活跃告警、趋势"""
    from desktop_core.ops_engine import get_ops_dashboard
    try:
        data = await get_ops_dashboard()
        return web.json_response(data)
    except Exception as e:
        log.error(f"运维总览失败：{e}")
        return web.json_response({"error": str(e)}, status=500)


async def api_ops_inspect(request):
    """触发一次全面巡检"""
    from desktop_core.ops_engine import run_inspection
    try:
        data = await run_inspection()
        return web.json_response(data)
    except Exception as e:
        log.error(f"巡检失败：{e}")
        return web.json_response({"error": str(e)}, status=500)


async def api_ops_inspections(request):
    """获取巡检历史"""
    from desktop_core.ops_engine import get_inspections
    try:
        limit = int(request.query.get("limit", 20))
        data = get_inspections(limit)
        return web.json_response({"inspections": data})
    except Exception as e:
        return web.json_response({"error": str(e)}, status=500)


async def api_ops_self_heal(request):
    """尝试自愈"""
    from desktop_core.ops_engine import try_self_heal
    try:
        data = await try_self_heal(trigger_type="manual")
        return web.json_response(data)
    except Exception as e:
        log.error(f"自愈失败：{e}")
        return web.json_response({"error": str(e)}, status=500)


async def api_ops_self_heals(request):
    """获取自愈历史"""
    from desktop_core.ops_engine import get_self_heal_history
    try:
        limit = int(request.query.get("limit", 30))
        data = get_self_heal_history(limit)
        return web.json_response({"heals": data})
    except Exception as e:
        return web.json_response({"error": str(e)}, status=500)


async def api_ops_incidents(request):
    """获取告警/事件列表"""
    from desktop_core.ops_engine import get_active_incidents, get_incident_history
    try:
        active = get_active_incidents()
        history = get_incident_history(50)
        return web.json_response({"active": active, "history": history})
    except Exception as e:
        return web.json_response({"error": str(e)}, status=500)


async def api_ops_maintenance(request):
    """执行养护操作"""
    from desktop_core.ops_engine import run_maintenance
    try:
        body = await request.json()
        actions = body.get("actions", None)
        result = await run_maintenance(actions)
        return web.json_response(result)
    except Exception as e:
        return web.json_response({"error": str(e)}, status=500)


async def api_ops_changelog(request):
    """获取变更记录"""
    from desktop_core.ops_engine import get_changelog
    try:
        limit = int(request.query.get("limit", 50))
        data = get_changelog(limit)
        return web.json_response({"changelog": data})
    except Exception as e:
        return web.json_response({"error": str(e)}, status=500)


async def api_ops_health_history(request):
    """获取健康评分历史趋势"""
    from desktop_core.ops_engine import get_health_history, get_uptime_since
    try:
        hours = int(request.query.get("hours", 24))
        data = get_health_history(hours)
        uptime = get_uptime_since(hours)
        return web.json_response({"records": data, "uptime": uptime})
    except Exception as e:
        return web.json_response({"error": str(e)}, status=500)


async def api_ops_trends(request):
    """获取趋势数据"""
    from desktop_core.ops_engine import get_trends
    try:
        metric = request.query.get("metric", "health_score")
        hours = int(request.query.get("hours", 24))
        bucket = request.query.get("bucket", None)
        data = get_trends(metric, hours, bucket)
        return web.json_response({"trends": data})
    except Exception as e:
        return web.json_response({"error": str(e)}, status=500)


async def api_ops_delete(request):
    """删除运维记录"""
    from desktop_core.ops_engine import delete_record
    try:
        body = await request.json()
        table = body.get("table", "")
        record_id = body.get("id", 0)
        if not table or not record_id:
            return web.json_response({"error": "缺少 table 或 id 参数"}, status=400)
        ok = delete_record(table, record_id)
        return web.json_response({"ok": ok})
    except Exception as e:
        return web.json_response({"error": str(e)}, status=500)


# ── 路由注册 ──

def setup_routes(app):
    # 兼容原 /api/status（让前端不再显示"连接中"）
    app.router.add_get("/api/status", api_status)
    # 桌面状态
    app.router.add_get("/api/desktop/status", api_desktop_status)
    app.router.add_get("/api/desktop_status", api_desktop_status)  # 前端下划线路径别名
    # 系统资源（整机 CPU/内存/磁盘/GPU）——补注册漏掉的路由，修复仪表盘系统资源恒为 0% 问题
    app.router.add_get("/api/system/resources", api_system_resources)
    app.router.add_get("/api/system/info", api_system_info)
    app.router.add_get("/api/system/processes", api_system_processes)
    app.router.add_get("/api/desktop/config", api_desktop_config_get)
    app.router.add_post("/api/desktop/config", api_desktop_config_set)
    app.router.add_get("/api/desktop/paths", api_desktop_paths)
    app.router.add_post("/api/desktop/restart", api_desktop_restart)
    app.router.add_post("/api/desktop/test-connection", api_desktop_test_connection)
    app.router.add_post("/api/desktop/models", api_desktop_list_models)
    app.router.add_get("/api/stats", api_stats)
    app.router.add_get("/api/desktop/platforms", api_desktop_platforms)
    app.router.add_get("/api/database/stats", api_database_stats)
    app.router.add_post("/api/chat/stream", api_chat_stream)
    app.router.add_post("/api/agent/stream", api_chat_stream)
    app.router.add_get("/api/providers", api_providers)

    # 对话历史
    app.router.add_get("/api/conversations", api_conversations_list)
    app.router.add_get("/api/conversation/{key}", api_conversation_get)
    app.router.add_post("/api/conversation/delete", api_conversation_delete)
    app.router.add_post("/api/conversation/message/delete", api_conversation_message_delete)

    # 多类型供应商路由（画图/视频/语音/代码/搜索）
    app.router.add_post("/api/generate_image", api_generate_image)
    app.router.add_post("/api/generate_video", api_generate_video)
    app.router.add_post("/api/generate_voice", api_generate_voice)
    app.router.add_get("/api/config/tts", api_config_tts_get)
    app.router.add_post("/api/config/tts", api_config_tts_set)
    app.router.add_post("/api/generate_code", api_generate_code)
    app.router.add_post("/api/search", api_search)

    # 头像生成与缓存
    app.router.add_get("/api/avatar/get", api_avatar_get)
    app.router.add_post("/api/avatar/prefill", api_avatar_prefill)
    app.router.add_get("/api/avatar/gen-status", api_avatar_gen_status)
    app.router.add_get("/api/avatar/list", api_avatar_list)
    app.router.add_get("/api/avatar/stats", api_avatar_stats)
    app.router.add_get("/api/avatar/file/{filename}", api_avatar_file)

    # 提示词管理（新版，PromptPanel 使用）
    app.router.add_get("/api/prompts", api_prompts_get)
    app.router.add_post("/api/prompts/save", api_prompts_save)
    app.router.add_post("/api/prompts/delete", api_prompts_delete)

    # 提示词管理（旧版，SetupGuide 使用）
    app.router.add_get("/api/desktop/prompts", api_desktop_prompts_get)
    app.router.add_get("/api/github/prompts", api_prompts_github)
    app.router.add_get("/api/github/experts", api_experts_list)
    app.router.add_get("/api/github/skills", api_skills_list)
    app.router.add_get("/api/custom/list", api_custom_list)
    app.router.add_post("/api/custom/save", api_custom_save)
    app.router.add_post("/api/custom/delete", api_custom_delete)
    app.router.add_post("/api/desktop/prompts", api_desktop_prompts_set)
    app.router.add_post("/api/desktop/prompts/reset", api_desktop_prompts_reset)

    # 知识库
    app.router.add_get("/api/knowledge/list", api_knowledge_list)
    app.router.add_get("/api/knowledge/summary", api_knowledge_summary)
    app.router.add_post("/api/knowledge/add", api_knowledge_add)
    app.router.add_post("/api/knowledge/delete", api_knowledge_delete)
    app.router.add_post("/api/knowledge/search", api_knowledge_search)
    app.router.add_post("/api/knowledge/import-github", api_knowledge_import_github)
    app.router.add_post("/api/knowledge/update", api_knowledge_update)
    app.router.add_post("/api/knowledge/import-url", api_knowledge_import_url)

    # 记忆（对话内容检索）
    app.router.add_get("/api/memory/stats", api_memory_stats)
    app.router.add_post("/api/memory/search", api_memory_search)
    app.router.add_get("/api/memory/categories", api_memory_categories)

    # 自动化
    app.router.add_get("/api/automations", api_automations_list)
    app.router.add_post("/api/automations/save", api_automations_save)
    app.router.add_post("/api/automations/toggle", api_automations_toggle)
    app.router.add_post("/api/automations/delete", api_automations_delete)
    app.router.add_post("/api/automations/run", api_automations_run)
    app.router.add_post("/api/automations/delete-run", api_automations_delete_run)
    app.router.add_post("/api/automations/trigger", api_automations_trigger)
    app.router.add_get("/api/automations/trigger", api_automations_trigger)  # GET 也支持（webhook 兼容）

    # 运维管理
    app.router.add_get("/api/ops/dashboard", api_ops_dashboard)
    app.router.add_post("/api/ops/inspect", api_ops_inspect)
    app.router.add_get("/api/ops/inspections", api_ops_inspections)
    app.router.add_post("/api/ops/self-heal", api_ops_self_heal)
    app.router.add_get("/api/ops/self-heals", api_ops_self_heals)
    app.router.add_get("/api/ops/incidents", api_ops_incidents)
    app.router.add_post("/api/ops/maintenance", api_ops_maintenance)
    app.router.add_get("/api/ops/changelog", api_ops_changelog)
    app.router.add_get("/api/ops/health-history", api_ops_health_history)
    app.router.add_get("/api/ops/trends", api_ops_trends)
    app.router.add_post("/api/ops/delete", api_ops_delete)

    # 工作流
    app.router.add_get("/api/workflows", api_workflow_list)
    app.router.add_get("/api/workflows/{id}", api_workflow_get)
    app.router.add_post("/api/workflows/save", api_workflow_save)
    app.router.add_post("/api/workflows/delete", api_workflow_delete)
    app.router.add_post("/api/workflows/run", api_workflow_run)
    app.router.add_get("/api/workflows/{id}/runs", api_workflow_runs)
    app.router.add_post("/api/workflows/delete-run", api_workflow_delete_run)
    app.router.add_get("/api/workflow/node-types", api_workflow_node_types)
    app.router.add_get("/api/workflows/{id}/export", api_workflow_export)
    app.router.add_post("/api/workflows/import", api_workflow_import)
    app.router.add_post("/api/workflows/publish", api_workflow_publish)
    app.router.add_post("/api/workflows/regenerate-key", api_workflow_regenerate_key)
    app.router.add_get("/api/workflows/{id}/keys", api_workflow_list_keys)
    app.router.add_post("/api/workflows/{id}/keys/create", api_workflow_create_key)
    app.router.add_post("/api/workflows/keys/update", api_workflow_update_key)
    app.router.add_post("/api/workflows/keys/delete", api_workflow_delete_key)
    app.router.add_get("/api/workflows/{id}/usage", api_workflow_usage_stats)
    app.router.add_get("/api/workflows/{id}/versions", api_workflow_versions)
    app.router.add_post("/api/workflows/webhook", api_workflow_register_webhook)
    app.router.add_post("/api/workflows/human-input", api_workflow_human_input)
    app.router.add_post("/api/webhook/{endpoint}", api_webhook_execute)

    # 模板
    app.router.add_get("/api/workflow/templates", api_templates_list)
    app.router.add_get("/api/workflow/templates/categories", api_templates_categories)
    app.router.add_post("/api/workflow/templates/use", api_templates_use)
    app.router.add_get("/api/workflow/templates/online", api_templates_online)
    app.router.add_post("/api/workflow/templates/test-token", api_test_github_token)
    app.router.add_post("/api/workflow/templates/save-token", api_save_github_token)
    app.router.add_get("/api/workflow/templates/get-token", api_get_github_token)

    # MCP 管理
    app.router.add_get("/api/mcp/servers", api_mcp_list)
    app.router.add_post("/api/mcp/servers", api_mcp_save)
    app.router.add_post("/api/mcp/connect", api_mcp_connect)
    app.router.add_post("/api/mcp/disconnect", api_mcp_disconnect)
    app.router.add_post("/api/mcp/test", api_mcp_test)
    app.router.add_post("/api/platform/test", api_platform_test)

    # 直播管理
    app.router.add_get("/api/live/status", api_live_status)
    app.router.add_post("/api/live/start", api_live_start)
    app.router.add_post("/api/live/stop", api_live_stop)
    app.router.add_get("/api/live/danmaku", api_live_danmaku)
    app.router.add_post("/api/live/connect", api_live_connect)
    app.router.add_post("/api/live/disconnect", api_live_disconnect)
    app.router.add_post("/api/live/test-tts", api_live_test_tts)
    app.router.add_post("/api/live/start-stream", api_live_start_stream)
    app.router.add_post("/api/live/stop-stream", api_live_stop_stream)
    app.router.add_route("GET", "/api/live/config", api_live_config)
    app.router.add_route("POST", "/api/live/config", api_live_config)
    app.router.add_post("/api/live/save-config", api_live_save_config)
    app.router.add_get("/api/live/audio-devices", api_live_audio_devices)
    app.router.add_get("/api/live/live2d-stream", api_live2d_stream)
    app.router.add_post("/api/live/pet-start", api_live_pet_start)
    app.router.add_post("/api/live/pet-stop", api_live_pet_stop)
    app.router.add_post("/api/live/chat-test", api_live_chat_test)
    app.router.add_get("/api/live/models", api_live_models)
    app.router.add_post("/api/live/models/delete", api_live_models_delete)
    app.router.add_post("/api/live/models/import", api_live_models_import)
    app.router.add_get("/api/live2d-model/{path:.*}", api_live2d_model)
    app.router.add_get("/api/live2d-model-list", api_live2d_model_list)
    app.router.add_get("/api/live/connectors", api_live_connectors)
    app.router.add_post("/api/live/connectors/register", api_live_connector_register)
    app.router.add_post("/api/live/connectors/unregister", api_live_connector_unregister)
    app.router.add_post("/api/live/human_speak", api_live_human_speak)
    app.router.add_get("/api/live/ws_agent", api_live_ws_agent)
    app.router.add_get("/api/live/connect_credentials", api_live_connect_credentials)

    # 启动时连接 MCP 服务器
    app.on_startup.append(_on_startup_mcp)

    # 工具权限确认
    app.router.add_get("/api/tools", api_tools_list)
    app.router.add_post("/api/tool/permit", api_tool_permit)
    app.router.add_get("/api/config/trust", api_config_trust)
    app.router.add_post("/api/config/trust", api_config_trust)

    # 任务管理
    app.router.add_get("/api/tasks", api_tasks_list)
    app.router.add_post("/api/tasks/clear", api_tasks_clear)

    # 取消 Agent
    app.router.add_post("/api/chat/cancel", api_cancel_chat)

    # 日志
    app.router.add_get("/api/logs", api_logs)


# ── 任务管理 API ──

async def api_tasks_list(request):
    """获取当前所有任务列表"""
    from desktop_core.task_manager import get_manager
    mgr = get_manager()
    tasks = [mgr.get_task(tid).to_dict() for tid in list(mgr._tasks.keys())[-10:] if mgr.get_task(tid)]
    return web.json_response({"tasks": tasks})


async def api_tasks_clear(request):
    """清除已完成的任务"""
    from desktop_core.task_manager import get_manager
    mgr = get_manager()
    to_del = [tid for tid, t in list(mgr._tasks.items()) if t.status in ("done", "failed")]
    for tid in to_del:
        del mgr._tasks[tid]
    return web.json_response({"ok": True, "cleared": len(to_del)})


# ── 取消 Agent 执行 ──

async def api_cancel_chat(request):
    """取消正在进行的 Agent 对话"""
    try:
        body = await request.json()
        conv_key = body.get("key", "")
        if conv_key and conv_key in _agent_cancel_events:
            _agent_cancel_events[conv_key].set()
            return web.json_response({"ok": True, "cancelled": conv_key})
        for ev in _agent_cancel_events.values():
            ev.set()
        return web.json_response({"ok": True, "cancelled": "all"})
    except Exception as e:
        return web.json_response({"error": str(e)}, status=400)


async def _on_startup_mcp(app):
    """应用启动时自动连接 MCP 服务器"""
    try:
        from desktop_core import tools
        count = await tools.connect_mcp_servers()
        if count > 0:
            log.info(f"[MCP] 已连接 {count} 个 MCP 服务器")
    except Exception as e:
        log.warning(f"[MCP] 启动连接失败: {e}")


# ── 直播管理 API ──

async def api_live_status(request):
    """直播引擎状态"""
    from desktop_core.live_engine import engine
    return web.json_response(engine.status)

async def api_live_connect(request):
    """连接 B站"""
    from desktop_core.live_engine import engine
    engine._load_config()  # 从数据库加载配置
    body = await request.json() if request.can_read_body else {}
    if body.get("access_key_id") and "****" not in str(body.get("access_key_id","")):
        engine._access_key_id = body["access_key_id"]
    if body.get("access_key_secret") and "****" not in str(body.get("access_key_secret","")):
        engine._access_key_secret = body["access_key_secret"]
    if body.get("app_id") and "****" not in str(body.get("app_id","")):
        engine._app_id = body["app_id"]
    if body.get("code") and "****" not in str(body.get("code","")):
        engine._code = body["code"]
    if body.get("room_id"):
        engine._room_id = body["room_id"]
    engine._bili_config_saved = bool(engine._access_key_id and engine._access_key_secret and engine._app_id and engine._code)
    ok = await engine.connect_bilibili()
    return web.json_response({"ok": ok, "status": engine.status})

async def api_live_disconnect(request):
    """断开 B站"""
    from desktop_core.live_engine import engine
    await engine.disconnect_bilibili()
    return web.json_response({"ok": True, "status": engine.status})

async def api_live_start(request):
    """启动直播引擎"""
    from desktop_core.live_engine import engine
    engine._load_config()  # 先从数据库加载已保存的配置
    body = await request.json() if request.can_read_body else {}
    # 防止前端把遮罩后的密钥（如 RtGe****）传回来覆盖真实密钥
    if body.get("access_key_id") and "****" not in str(body.get("access_key_id","")):
        engine._access_key_id = body["access_key_id"]
    if body.get("access_key_secret") and "****" not in str(body.get("access_key_secret","")):
        engine._access_key_secret = body["access_key_secret"]
    if body.get("app_id") and "****" not in str(body.get("app_id","")):
        engine._app_id = body["app_id"]
    if body.get("code") and "****" not in str(body.get("code","")):
        engine._code = body["code"]
    if body.get("room_id"): engine._room_id = body["room_id"]
    if body.get("rtmp_url"): engine._rtmp_url = body["rtmp_url"]
    if body.get("dashscope_api_key") and "****" not in str(body.get("dashscope_api_key","")):
        engine._dashscope_api_key = body["dashscope_api_key"]
    engine.save_config()
    ok = await engine.start()
    return web.json_response({"ok": ok, "status": engine.status})

async def api_live_stop(request):
    """停止直播引擎"""
    from desktop_core.live_engine import engine
    await engine.stop()
    return web.json_response({"ok": True, "status": engine.status})

async def api_live_danmaku(request):
    """获取弹幕列表"""
    from desktop_core.live_engine import engine
    return web.json_response({"danmaku": engine.danmaku_list})

async def api_live_test_tts(request):
    """测试 TTS API Key 是否可用"""
    from desktop_core.live_engine import engine
    engine._load_config()
    err = await engine.test_tts()
    return web.json_response({"ok": not err, "error": err or ""})

async def api_live_connectors(request):
    """列出当前在台的角色（奶昔 + 已接入的外部 agent）"""
    from desktop_core.live_engine import engine
    return web.json_response({"connectors": engine.list_connectors()})

async def api_live_connector_register(request):
    """接入一个外部 agent 角色。支持两种传输：

    - type=http（默认）：远程 HTTP 端点，QQ 机器人配好地址即可上台
    - type=ws：远程 WebSocket 端点（常驻双向连接）

    body: {agent_id, name, endpoint, type?, priority?, token?}
    远程连接器必须带 token，否则注册被治理层拒绝。
    """
    from desktop_core.live_engine import engine
    body = await request.json() if request.can_read_body else {}
    agent_id = (body.get("agent_id") or "").strip()
    name = (body.get("name") or "").strip()
    endpoint = (body.get("endpoint") or "").strip()
    if not agent_id or not name or not endpoint:
        return web.json_response({"ok": False, "error": "缺少 agent_id / name / endpoint"}, status=400)
    ctype = (body.get("type") or "http").lower()
    priority = int(body.get("priority", 50))
    token = body.get("token", "")
    if ctype == "ws":
        ok = engine.register_ws_connector(agent_id, name, endpoint, priority=priority, token=token)
    else:
        ok = engine.register_http_connector(agent_id, name, endpoint, priority=priority, token=token)
    if not ok:
        return web.json_response({"ok": False, "error": "注册被拒（远程连接器需配置 token，或参数非法）"}, status=400)
    return web.json_response({"ok": ok, "connectors": engine.list_connectors()})


async def api_live_human_speak(request):
    """人类副播上麦：操作员在副播面板输入后调用，把一句话当作人类角色发言投到麦位。

    body: {agent_id?, text, emotion?, action?}
    """
    from desktop_core.live_engine import engine
    body = await request.json() if request.can_read_body else {}
    text = (body.get("text") or "").strip()
    if not text:
        return web.json_response({"ok": False, "error": "缺少 text"}, status=400)
    agent_id = (body.get("agent_id") or "human").strip()
    ok = await engine.inject_human_speech(
        agent_id, text,
        emotion=body.get("emotion", "开心"),
        action=body.get("action", ""),
    )
    return web.json_response({"ok": ok, "connectors": engine.list_connectors()})

async def api_live_connector_unregister(request):
    """让一个外部角色下台。body: {agent_id}"""
    from desktop_core.live_engine import engine
    body = await request.json() if request.can_read_body else {}
    agent_id = (body.get("agent_id") or "").strip()
    ok = await engine.unregister_connector(agent_id)
    return web.json_response({"ok": ok, "connectors": engine.list_connectors()})


def _live_ws_secret() -> str:
    """服务端反向连入的鉴权密钥：优先读 SQLite meta(live_ws_secret)，兜底环境变量。
    未配置返回空串（handler 据此安全拒绝所有反向连接）。"""
    try:
        from desktop_core import storage
        s = storage.meta_get("live_ws_secret", "")
        if s:
            return s
    except Exception:
        pass
    return os.environ.get("NAIXI_LIVE_WS_SECRET", "")


async def api_live_connect_credentials(request):
    """生成/读取接入外部 agent 的凭证，便于前端一键获取（免手填 endpoint/token）。

    返回 agent_id/name/type/endpoint(本机)/lan_endpoint(局域网)/token(live_ws_secret)/
    sample(复制即用的外部 agent Python 连接示例)。
    live_ws_secret 缺失时自动生成并落库，启用反向连入。
    """
    from desktop_core import storage
    import secrets
    secret = storage.meta_get("live_ws_secret", "")
    if not secret:
        secret = secrets.token_hex(16)
        storage.meta_set("live_ws_secret", secret)
    lan_ip = "127.0.0.1"
    try:
        import socket
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        lan_ip = s.getsockname()[0]
        s.close()
    except Exception:
        pass
    ws_endpoint = "ws://127.0.0.1:9845/api/live/ws_agent"
    lan_ws_endpoint = "ws://{}:9845/api/live/ws_agent".format(lan_ip)
    agent_id = "ext_agent"
    name = "外部角色"
    sample = (
        "# 外部 agent 连接示例（Python，需安装 websocket-client：pip install websocket-client）\n"
        "import websocket, json\n\n"
        "WS_URL = \"{}\"\n"
        "SECRET = \"{}\"\n"
        "AGENT_ID = \"{}\"\n"
        "NAME = \"{}\"\n\n"
        "ws = websocket.create_connection(WS_URL)\n"
        "ws.send(json.dumps({{\"type\":\"register\",\"agent_id\":AGENT_ID,\"name\":NAME,\"token\":SECRET,\"priority\":50}}))\n"
        "print(ws.recv())  # 应收到 register_ack ok:true\n\n"
        "while True:\n"
        "    msg = json.loads(ws.recv())\n"
        "    if msg.get(\"type\") == \"request\":\n"
        "        # 引擎下发的 danmaku/cue 请求，回一句话即可上台发言\n"
        "        ws.send(json.dumps({{\"type\":\"reply\",\"req_id\":msg[\"req_id\"],\"data\":{{\"text\":\"我是外部角色，收到啦\",\"emotion\":\"开心\",\"action\":\"\"}}}}))\n"
    ).format(ws_endpoint, secret, agent_id, name)
    return web.json_response({
        "ok": True,
        "agent_id": agent_id,
        "name": name,
        "type": "ws",
        "endpoint": ws_endpoint,
        "lan_endpoint": lan_ws_endpoint,
        "token": secret,
        "sample": sample,
    })


async def api_live_ws_agent(request):
    """ws 服务端热插拔端点 —— 远端 agent 主动"反向连入"引擎（引擎作为 ws 服务端）。

    握手协议（全 JSON 文本帧）：
      1) 客户端连上后先发注册帧：
         {"type":"register","agent_id":"...","name":"...","token":"...","priority":50}
      2) 引擎校验：token 必须与服务端密钥一致（constant-time 比较）；agent_id/name 必填。
         通过则动态注册为 WsServerConnector 上台，回 {"type":"register_ack","ok":true}；
         失败回 {"type":"register_ack","ok":false,"error":"..."} 并关闭。
      3) 之后引擎按需下发请求帧：{"type":"request","kind":"danmaku|cue","req_id":"...","data":{...}}
         客户端处理后回复：{"type":"reply","req_id":"...","data":{"text","emotion","action"}}
         不想接话则回 data:null 或 {"ok":false}。
      4) 断开（客户端关闭 / 网络异常）即自动注销下台，实现真正热插拔。
    """
    from desktop_core.live_engine import engine
    from desktop_core.live_bus import WsServerConnector, PRIORITY_GUEST

    ws = web.WebSocketResponse(heartbeat=30.0)
    await ws.prepare(request)

    # ── 握手：等首帧 register ──
    agent_id = ""
    conn = None
    try:
        first = await ws.receive(timeout=15.0)
        if first.type != web.WSMsgType.TEXT:
            await ws.send_json({"type": "register_ack", "ok": False, "error": "首帧必须为文本 register"})
            await ws.close()
            return ws
        reg = json.loads(first.data)
        if (reg.get("type") or "") != "register":
            await ws.send_json({"type": "register_ack", "ok": False, "error": "首帧类型必须为 register"})
            await ws.close()
            return ws
        agent_id = (reg.get("agent_id") or "").strip()
        name = (reg.get("name") or "").strip()
        token = reg.get("token") or ""
        priority = int(reg.get("priority", PRIORITY_GUEST))
        if not agent_id or not name:
            await ws.send_json({"type": "register_ack", "ok": False, "error": "缺少 agent_id / name"})
            await ws.close()
            return ws
        # 鉴权：反向连入是不可信面，token 必须与服务端密钥一致
        secret = _live_ws_secret()
        if not secret:
            await ws.send_json({"type": "register_ack", "ok": False,
                                "error": "服务端未配置反向连入密钥(live_ws_secret)，已拒绝"})
            await ws.close()
            return ws
        if not token or not hmac.compare_digest(str(token), str(secret)):
            log.warning(f"[ws服务端] 反向连入鉴权失败: {agent_id}")
            await ws.send_json({"type": "register_ack", "ok": False, "error": "token 校验失败"})
            await ws.close()
            return ws
        # 动态注册上台（token 传给连接器以过治理层"远程需 token"校验）
        conn = WsServerConnector(agent_id, name, ws, priority=priority, token=token)
        ok = engine.register_connector(conn)
        if not ok:
            await ws.send_json({"type": "register_ack", "ok": False,
                                "error": "注册被拒（可能被限流隔离或参数非法）"})
            await ws.close()
            return ws
        await ws.send_json({"type": "register_ack", "ok": True})
        log.info(f"[ws服务端] 远端角色反向连入并上台: {name}({agent_id})")

        # ── 读循环：把远端回复喂回对应请求的 Future ──
        async for msg in ws:
            if msg.type == web.WSMsgType.TEXT:
                try:
                    m = json.loads(msg.data)
                except Exception:
                    continue
                mtype = m.get("type") or ""
                if mtype == "reply":
                    req_id = m.get("req_id") or ""
                    if req_id:
                        conn.feed_reply(req_id, m.get("data"))
                elif mtype == "ping":
                    try:
                        await ws.send_json({"type": "pong"})
                    except Exception:
                        break
            elif msg.type in (web.WSMsgType.CLOSE, web.WSMsgType.CLOSING,
                              web.WSMsgType.CLOSED, web.WSMsgType.ERROR):
                break
    except asyncio.TimeoutError:
        try:
            await ws.send_json({"type": "register_ack", "ok": False, "error": "握手超时"})
        except Exception:
            pass
    except Exception as e:
        log.warning(f"[ws服务端] 连接异常: {e}")
    finally:
        # 断开即注销下台，实现热插拔
        if agent_id:
            try:
                await engine.unregister_connector(agent_id)
            except Exception:
                pass
            log.info(f"[ws服务端] 远端角色已断开下台: {agent_id}")
    return ws

async def api_live_start_stream(request):
    """启动 RTMP 推流"""
    from desktop_core.live_engine import engine
    body = await request.json() if request.can_read_body else {}
    rtmp_url = body.get("rtmp_url", "") or engine._rtmp_url
    ok = await engine.start_stream(rtmp_url)
    return web.json_response({"ok": ok, "status": engine.status})

async def api_live_stop_stream(request):
    """停止 RTMP 推流"""
    from desktop_core.live_engine import engine
    await engine.stop_stream()
    return web.json_response({"ok": True, "status": engine.status})

async def api_live_config(request):
    """获取/保存直播配置"""
    from desktop_core.live_engine import engine
    engine._load_config()
    if request.method == "GET":
        mp = engine._model_path
        # 未手动设置时自动发现第一个模型
        if not mp:
            try:
                for base_dir in (
                    os.path.join(_DESKTOP_DIR, "data", "models"),
                    os.path.join(_DESKTOP_DIR, "godot_renderer", "models"),
                ):
                    if not os.path.exists(base_dir):
                        continue
                    for entry in sorted(os.listdir(base_dir)):
                        d = os.path.join(base_dir, entry)
                        if not os.path.isdir(d):
                            continue
                        for f in os.listdir(d):
                            if f.endswith(".model3.json"):
                                mp = os.path.join(d, f)
                                break
                        if mp:
                            break
                    if mp:
                        break
            except:
                pass
        return web.json_response({
            "access_key_id": engine._access_key_id,
            "access_key_secret": engine._access_key_secret[:4]+"****" if engine._access_key_secret else "",
            "app_id": engine._app_id,
            "code": engine._code,
            "room_id": engine._room_id,
            "rtmp_url": engine._rtmp_url,
            "dashscope_api_key": engine._dashscope_api_key[:4]+"****" if engine._dashscope_api_key else "",
            "live_prompt": engine._live_prompt,
            "audio_out_device": engine._audio_out_device,
            "audio_in_device": engine._audio_in_device,
            "model_path": mp,
            "render_mode": engine._render_mode,
            "tts_engine": engine._tts_engine,
        })
    body = await request.json()
    ok = engine.save_config(**body)
    return web.json_response({"ok": ok})

async def api_live_save_config(request):
    """保存直播配置"""
    from desktop_core.live_engine import engine
    body = await request.json()
    ok = engine.save_config(**body)
    return web.json_response({"ok": ok})

async def api_live_audio_devices(request):
    """列出系统音频设备"""
    from desktop_core.live_engine import engine
    return web.json_response(engine.list_audio_devices())

async def api_live2d_stream(request):
    """WebSocket: 双向通信通道——推送参数 + 接收聊天"""
    from desktop_core.live_engine import engine
    ws = web.WebSocketResponse()
    await ws.prepare(request)
    engine._live2d_ws = ws
    try:
        async for msg in ws:
            if msg.type == web.WSMsgType.CLOSED:
                break
            if msg.type == web.WSMsgType.TEXT:
                try:
                    data = json.loads(msg.data)
                    if data.get("type") == "chat":
                        text = data.get("text", "")
                        reply, emotion, action = await engine._decide_reply(text, "测试")
                        if not reply:
                            reply = "嗯嗯～"
                            emotion = "开心"
                        # 情绪→动作降级（LLM 未输出动作标签时用）
                        if not action:
                            emo_to_action = {"开心":"smile","欢迎":"wave","惊讶":"surprised",
                                             "害羞":"shy","悲伤":"sad","生气":"angry","卖萌":"tilt"}
                            action = emo_to_action.get(emotion, "")
                        mg, mi = engine._action_to_motion(action)
                        await ws.send_json({
                            "type": "speak",
                            "text": reply,
                            "emotion": emotion,
                            "action": action,
                            "motion_group": mg,
                            "motion_index": mi,
                            "mouth": [0.5]*5,
                            "frame_ms": 80,
                        })
                        # 同时触发 TTS 语音播放
                        try:
                            audio = await engine._synthesize(reply)
                            if audio:
                                engine.play_audio(audio)
                        except:
                            pass
                except:
                    pass
    finally:
        if engine._live2d_ws is ws:
            engine._live2d_ws = None
    return ws

async def api_live_pet_start(request):
    """启动桌宠（PySide6 独立窗口）"""
    from desktop_core.live_engine import engine
    body = await request.json() if request.body_exists else {}
    ok = engine._start_pet(body.get("model_path", ""))
    return web.json_response({"ok": ok})

async def api_live_pet_stop(request):
    """停止桌宠"""
    from desktop_core.live_engine import engine
    engine._stop_pet()
    return web.json_response({"ok": True})

async def api_live_chat_test(request):
    """LLM 测试：发送文本 → 返回回复+情绪"""
    from desktop_core.live_engine import engine
    body = await request.json()
    text = body.get("text", "")
    if not text:
        return web.json_response({"error": "no text"}, status=400)
    try:
        reply, emotion, action = await engine._decide_reply(text, "测试")
    except Exception as e:
        return web.json_response({"error": str(e), "reply": None, "emotion": "开心", "action": ""}, status=500)
    if not reply:
        return web.json_response({"reply": "LLM 未配置或规则未匹配", "emotion": "无奈", "action": ""}, status=200)
    if not action:
        emo_to_action = {"开心":"smile","欢迎":"wave","惊讶":"surprised","害羞":"shy","悲伤":"sad","生气":"angry","卖萌":"tilt"}
        action = emo_to_action.get(emotion, "")
    mg, mi = engine._action_to_motion(action)
    result = {"reply": reply, "emotion": emotion, "action": action}
    if engine._live2d_ws and not engine._live2d_ws.closed:
        try:
            await engine._live2d_ws.send_json({
                "type": "speak",
                "text": reply,
                "emotion": emotion,
                "action": action,
                "motion_group": mg,
                "motion_index": mi,
                "mouth": [0.5, 0.8, 0.5, 0.3, 0.0],
                "frame_ms": 80,
            })
        except:
            pass
    # 触发 TTS 语音播放
    try:
        audio = await engine._synthesize(reply)
        if audio:
            engine.play_audio(audio)
    except:
        pass
    return web.json_response(result)

async def api_live_models(request):
    """列出 data/models/ 目录中的模型"""
    models_dir = os.path.join(_DESKTOP_DIR, "data", "models")
    models = []
    if os.path.exists(models_dir):
        for entry in os.listdir(models_dir):
            d = os.path.join(models_dir, entry)
            if not os.path.isdir(d):
                continue
            for f in os.listdir(d):
                if f.endswith(".model3.json"):
                    models.append({"name": entry, "file": f, "path": os.path.join(d, f)})
                    break
    return web.json_response({"models": models})

async def api_live_models_delete(request):
    """删除 data/models/ 中的模型目录"""
    from desktop_core.live_engine import engine
    body = await request.json()
    name = body.get("name", "")
    if not name:
        return web.json_response({"error": "no name"}, status=400)
    target = os.path.join(_DESKTOP_DIR, "data", "models", name)
    if not os.path.exists(target):
        return web.json_response({"error": "not found"}, status=404)
    import shutil
    shutil.rmtree(target)
    return web.json_response({"ok": True})


async def api_live_models_import(request):
    """导入模型文件到 data/models/"""
    models_dir = os.path.join(_DESKTOP_DIR, "data", "models")
    os.makedirs(models_dir, exist_ok=True)
    try:
        reader = await request.multipart()
        field = await reader.next()
        if not field or field.name != "file":
            return web.json_response({"error": "缺少 file 字段"}, status=400)
        filename = field.filename or "model.model3.json"
        content = await field.read()
        # 判断文件类型
        is_vrm = filename.lower().endswith(".vrm")
        is_model3 = filename.lower().endswith(".model3.json")
        if not is_vrm and not is_model3:
            return web.json_response({"error": "仅支持 .model3.json 或 .vrm 文件"}, status=400)
        # 模型目录名：去后缀 → 去重名 → 创建
        base_name = os.path.splitext(filename)[0]
        if base_name.endswith(".model3"):
            base_name = base_name[:-7]  # 去掉 .model3 后缀
        target_dir = os.path.join(models_dir, base_name)
        suffix = 1
        while os.path.exists(target_dir):
            target_dir = os.path.join(models_dir, f"{base_name}_{suffix}")
            suffix += 1
        os.makedirs(target_dir, exist_ok=True)
        # 保存文件
        dest = os.path.join(target_dir, filename)
        with open(dest, "wb") as f:
            f.write(content)
        # 返回模型路径
        model_path = os.path.join(target_dir, filename) if is_model3 else target_dir
        log.info(f"模型已导入: {dest}")
        return web.json_response({"ok": True, "path": model_path, "name": base_name})
    except Exception as e:
        log.warning(f"模型导入失败: {e}")
        return web.json_response({"error": "导入失败"}, status=500)

async def api_live2d_model(request):
    """代理 Live2D 模型文件（递归搜索本地 VTube Studio / data/models 目录）"""
    sub_path = request.match_info.get("path", "")
    if not sub_path or ".." in sub_path:
        return web.json_response({"error": "invalid path"}, status=400)
    search_roots = [
        os.path.join(_DESKTOP_DIR, "data", "models"),
        r"D:\Program Files\Steam\steamapps\common\VTube Studio\VTube Studio_Data\StreamingAssets\Live2DModels",
    ]
    # 递归查找文件（处理 model3.json / 纹理 / 物理 / moc3 等）
    for base in search_roots:
        if not os.path.exists(base):
            continue
        for root, _, files in os.walk(base):
            if sub_path in files:
                return _model_response(os.path.join(root, sub_path))
    return web.json_response({"error": "not found: " + sub_path}, status=404)

def _model_response(fp: str):
    ext = os.path.splitext(fp)[1].lower()
    mime = {"png": "image/png", "json": "application/json", "moc3": "application/octet-stream",
            "physics3": "application/json", "exp3": "application/json", "cdi3": "application/json"}.get(ext, "application/octet-stream")
    # CORS 头由中间件按来源信任度统一注入，此处不再硬编码通配符 *
    return web.FileResponse(fp, headers={"Content-Type": mime})

async def api_live2d_model_list(request):
    """列出可用的 Live2D 模型（扫描 VTube Studio 和本地目录）"""
    search_roots = [
        os.path.join(_DESKTOP_DIR, "data", "models"),
        r"D:\Program Files\Steam\steamapps\common\VTube Studio\VTube Studio_Data\StreamingAssets\Live2DModels",
    ]
    models = []
    seen = set()
    for base in search_roots:
        if not os.path.exists(base):
            continue
        for entry in os.listdir(base):
            model_dir = os.path.join(base, entry)
            if not os.path.isdir(model_dir):
                continue
            # 查找 model3.json（支持直接以目录名下划线格式）
            for f in os.listdir(model_dir):
                if f.endswith(".model3.json") and f not in seen:
                    seen.add(f)
                    models.append({
                        "name": entry,
                        "modelFile": f,
                        "path": os.path.join(model_dir, f),
                    })
                    break
    return web.json_response({"models": models})

# ── MCP 管理 API ──

async def api_mcp_list(request):
    """列出已配置的 MCP 服务器"""
    raw = meta_get("desktop_config")
    if not raw:
        return web.json_response({"servers": {}})
    try:
        cfg = json.loads(raw)
        servers = cfg.get("mcp_servers", {})
        return web.json_response({"servers": servers})
    except:
        return web.json_response({"servers": {}})

async def api_mcp_save(request):
    """保存 MCP 服务器配置"""
    try:
        body = await request.json()
        servers = body.get("servers", {})
        raw = meta_get("desktop_config")
        cfg = json.loads(raw) if raw else {}
        cfg["mcp_servers"] = servers
        meta_set("desktop_config", json.dumps(cfg, ensure_ascii=False))
        return web.json_response({"ok": True, "count": len(servers)})
    except Exception as e:
        return web.json_response({"error": str(e)}, status=400)

async def api_mcp_connect(request):
    """连接所有 MCP 服务器并刷新工具列表"""
    try:
        from desktop_core import tools
        await tools.connect_mcp_servers()
        # 刷新工具注册表
        TOOLS = tools.get_definitions()
        return web.json_response({"ok": True, "tool_count": len(TOOLS)})
    except Exception as e:
        return web.json_response({"error": str(e)}, status=500)

async def api_mcp_disconnect(request):
    """断开 MCP 连接"""
    try:
        from desktop_core.mcp_client import MCPManager
        mgr = tools.get_mcp_manager() if hasattr(tools, 'get_mcp_manager') else None
        if mgr:
            await mgr.disconnect_all()
        return web.json_response({"ok": True})
    except Exception as e:
        return web.json_response({"error": str(e)}, status=500)


async def api_mcp_test(request):
    """测试单个 MCP 服务器连接"""
    try:
        body = await request.json()
        name = body.get("name", "")
        if not name:
            return web.json_response({"ok": False, "error": "缺少服务器名称"})
        from desktop_core.mcp_client import MCPServer
        from desktop_core.storage import meta_get
        import json
        raw = meta_get("desktop_config")
        srv_cfg = {}
        if raw:
            cfg = json.loads(raw)
            srv_cfg = cfg.get("mcp_servers", {}).get(name, {})
        if not srv_cfg.get("command"):
            return web.json_response({"ok": False, "error": f"未找到服务器「{name}」的配置"})
        server = MCPServer(name, srv_cfg["command"], srv_cfg.get("args", []), srv_cfg.get("env", {}))
        ok = await server.connect()
        tool_names = [t.get("name", "") for t in server._tools]
        await server.disconnect()
        if ok:
            return web.json_response({"ok": True, "tools": tool_names})
        return web.json_response({"ok": False, "error": "连接失败（初始化超时或无响应）"})
    except Exception as e:
        return web.json_response({"ok": False, "error": str(e)[:200]})


async def api_platform_test(request):
    """测试平台连接（HTTP 端点 ping）"""
    try:
        body = await request.json()
        url = body.get("url", "")
        if not url:
            return web.json_response({"ok": False, "error": "缺少测试地址"})
        import aiohttp
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=8)) as sess:
            async with sess.get(url) as resp:
                if resp.status < 500:
                    return web.json_response({"ok": True, "status": resp.status})
                return web.json_response({"ok": False, "error": f"HTTP {resp.status}"})
    except asyncio.TimeoutError:
        return web.json_response({"ok": False, "error": "连接超时（8秒）"})
    except Exception as e:
        return web.json_response({"ok": False, "error": str(e)[:100]})


async def api_tools_list(request):
    """列出所有可用工具（含分类和参数信息）"""
    from desktop_core import tools as _tools_mod
    cat = request.query.get("category", "")
    try:
        registry = _tools_mod._registry
        tools_list = []
        cat_counts = {}
        for name, t in registry.items():
            if cat and t.get("category", "") != cat:
                continue
            params = t.get("parameters", {})
            props = params.get("properties", {})
            required = params.get("required", [])
            param_details = []
            for pname, pinfo in props.items():
                param_details.append({
                    "name": pname,
                    "type": pinfo.get("type", "string"),
                    "description": pinfo.get("description", ""),
                    "required": pname in required,
                })
            tools_list.append({
                "name": name,
                "description": t.get("description", ""),
                "category": t.get("category", "core"),
                "has_params": bool(props),
                "param_count": len(props),
                "params": param_details,
                "required_params": required,
            })
            c = t.get("category", "core")
            cat_counts[c] = cat_counts.get(c, 0) + 1
        tools_list.sort(key=lambda x: (x["category"], x["name"]))
        return web.json_response({
            "tools": tools_list,
            "count": len(tools_list),
            "categories": [{"name": k, "count": v} for k, v in sorted(cat_counts.items())],
        })
    except Exception as e:
        return web.json_response({"error": str(e)}, status=400)


async def api_tool_permit(request):
    """用户批准或拒绝高危工具的执行"""
    try:
        body = await request.json()
        req_id = body.get("id", "")
        approved = body.get("approved", False)
        always_allow = body.get("always_allow", False)
        if req_id in _PENDING_PERMISSIONS:
            info = _PENDING_PERMISSIONS[req_id]
            info["result"]["approved"] = approved
            info["result"]["always_allow"] = always_allow
            info["event"].set()
            return web.json_response({"ok": True, "approved": approved})
        return web.json_response({"error": "请求不存在或已超时"}, status=404)
    except Exception as e:
        return web.json_response({"error": str(e)}, status=400)


async def api_config_trust(request):
    """获取/设置完全信任模式"""
    if request.method == "GET":
        val = meta_get("desktop_full_trust")
        return web.json_response({"full_trust": val == "true"})
    try:
        body = await request.json()
        enabled = body.get("full_trust", False)
        meta_set("desktop_full_trust", "true" if enabled else "false")
        return web.json_response({"ok": True, "full_trust": enabled})
    except Exception as e:
        return web.json_response({"error": str(e)}, status=400)


async def api_logs(request):
    """返回后端日志文件内容（过滤掉 HTTP 访问日志）"""
    # 优先从已挂载的 RotatingFileHandler 取得真实日志路径（与后端写日志处完全一致，
    # 不受 api.py 在不同形态下的加载位置影响）
    log_path = None
    for h in logging.getLogger().handlers:
        bf = getattr(h, "baseFilename", None)
        if bf and bf.endswith("naixi_desktop.log"):
            log_path = bf
            break
    if not log_path:
        log_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "logs", "naixi_desktop.log")
    try:
        with open(log_path, "r", encoding="utf-8") as f:
            lines = f.readlines()
        # 过滤掉 aiohttp.access 行（HTTP 请求日志），只保留应用日志
        app_lines = [l for l in lines if 'aiohttp.access' not in l]
        # 如果应用日志太少，回退到全部日志
        if len(app_lines) < 10:
            app_lines = lines
        last_lines = app_lines[-200:]
        return web.Response(text="".join(last_lines), content_type="text/plain", charset="utf-8")
    except FileNotFoundError:
        return web.Response(text="日志文件不存在", content_type="text/plain", charset="utf-8", status=404)
    except Exception as e:
        return web.Response(text=f"读取日志失败: {e}", content_type="text/plain", charset="utf-8", status=500)
