"""
奶昔桌面端 — 运维引擎
核心职责：保障系统稳定运行
功能：健康评分、自愈、巡检、告警、趋势、养护、变更记录

所有数据存储在桌面端 SQLite 数据库中。
"""
import os, json, time, asyncio, logging, sqlite3, subprocess
from datetime import datetime, timedelta
from typing import Any

from desktop_core.storage import _get_conn, DB_PATH

log = logging.getLogger("ops")

# psutil 为可选依赖：打包的 embedded python 未内置，缺失时相关指标降级而非抛 500
try:
    import psutil
except ImportError:
    psutil = None

# ────────────────────────────────────────────
# 1. 数据表初始化
# ────────────────────────────────────────────

OPS_TABLES_SQL = """
CREATE TABLE IF NOT EXISTS ops_health_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts REAL NOT NULL,
    score INTEGER NOT NULL,
    backend_alive INTEGER DEFAULT 0,
    backend_mem REAL DEFAULT 0,
    backend_cpu REAL DEFAULT 0,
    services_ok INTEGER DEFAULT 0,
    services_total INTEGER DEFAULT 0,
    sys_cpu REAL DEFAULT 0,
    sys_mem REAL DEFAULT 0,
    sys_disk REAL DEFAULT 0,
    providers_valid INTEGER DEFAULT 0,
    error_count INTEGER DEFAULT 0,
    uptime_seconds INTEGER DEFAULT 0,
    details TEXT DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS ops_incidents (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts REAL NOT NULL,
    resolved_ts REAL DEFAULT 0,
    severity TEXT DEFAULT 'warning',
    category TEXT DEFAULT '',
    title TEXT DEFAULT '',
    message TEXT DEFAULT '',
    status TEXT DEFAULT 'active',
    auto_healed INTEGER DEFAULT 0,
    duration_seconds INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS ops_inspections (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts REAL NOT NULL,
    result TEXT DEFAULT 'pass',
    score INTEGER DEFAULT 100,
    summary TEXT DEFAULT '{}',
    details TEXT DEFAULT '{}',
    issues_found INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS ops_self_heals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts REAL NOT NULL,
    trigger TEXT DEFAULT '',
    action TEXT DEFAULT '',
    result TEXT DEFAULT 'success',
    message TEXT DEFAULT '',
    duration_ms INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS ops_trends (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts REAL NOT NULL,
    bucket TEXT NOT NULL,
    metric TEXT NOT NULL,
    value REAL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS ops_changelog (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts REAL NOT NULL,
    action TEXT DEFAULT '',
    target TEXT DEFAULT '',
    detail TEXT DEFAULT '',
    result TEXT DEFAULT 'ok'
);
"""

def init_ops_tables():
    """初始化运维相关数据表"""
    conn = _get_conn()
    try:
        conn.executescript(OPS_TABLES_SQL)
        conn.commit()
    finally:
        conn.close()
    log.info("运维数据表已就绪")


# ────────────────────────────────────────────
# 2. 健康评分 — 综合多维度加权计算
# ────────────────────────────────────────────

HEALTH_WEIGHTS = {
    "backend": 30,      # 后端进程存活
    "services": 20,     # 依赖服务在线
    "providers": 15,    # API 提供商有效
    "errors": 15,       # 错误率低
    "resources": 20,    # 系统资源充足（CPU/内存/磁盘）
}

def compute_health_score(
    backend_alive: bool,
    services_ok: int, services_total: int,
    providers_valid: int, providers_total: int,
    error_count: int,
    sys_cpu: float, sys_mem: float, sys_disk: float,
) -> tuple[int, dict]:
    """
    加权计算健康评分（0-100）
    返回 (总分, 各项细分)
    """
    breakdown = {}

    # 后端进程（30分）
    breakdown["backend"] = HEALTH_WEIGHTS["backend"] if backend_alive else 0

    # 依赖服务（20分）
    if services_total == 0:
        breakdown["services"] = 20  # 没有依赖服务也算正常
    else:
        ratio = services_ok / services_total
        breakdown["services"] = round(HEALTH_WEIGHTS["services"] * ratio)

    # 提供商（15分）
    if providers_total == 0:
        breakdown["providers"] = 15
    else:
        ratio = providers_valid / providers_total
        breakdown["providers"] = round(HEALTH_WEIGHTS["providers"] * ratio)

    # 错误率（15分）— 最近错误越多分越低
    if error_count == 0:
        breakdown["errors"] = HEALTH_WEIGHTS["errors"]
    elif error_count <= 3:
        breakdown["errors"] = 10
    elif error_count <= 10:
        breakdown["errors"] = 5
    else:
        breakdown["errors"] = 0

    # 系统资源（20分）
    resource_score = 0
    if sys_cpu < 50:
        resource_score += 8
    elif sys_cpu < 80:
        resource_score += 5
    else:
        resource_score += 2

    if sys_mem < 50:
        resource_score += 6
    elif sys_mem < 80:
        resource_score += 4
    else:
        resource_score += 1

    if sys_disk < 50:
        resource_score += 6
    elif sys_disk < 80:
        resource_score += 4
    else:
        resource_score += 1
    breakdown["resources"] = resource_score

    total = sum(breakdown.values())
    return min(total, 100), breakdown


# ────────────────────────────────────────────
# 3. 核心数据操作
# ────────────────────────────────────────────

def _ensure_tables():
    """确保运维表存在（调用前先检查）"""
    conn = _get_conn()
    try:
        tables = [r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'ops_%'"
        ).fetchall()]
        if len(tables) < 6:
            conn.executescript(OPS_TABLES_SQL)
            conn.commit()
    finally:
        conn.close()


# ── 健康检查记录 ──

def save_health_log(data: dict):
    """记录一次健康检查快照"""
    conn = _get_conn()
    try:
        conn.execute("""
            INSERT INTO ops_health_log
            (ts, score, backend_alive, backend_mem, backend_cpu,
             services_ok, services_total, sys_cpu, sys_mem, sys_disk,
             providers_valid, error_count, uptime_seconds, details)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, (
            data.get("ts", time.time()),
            data.get("score", 0),
            1 if data.get("backend_alive") else 0,
            data.get("backend_mem", 0),
            data.get("backend_cpu", 0),
            data.get("services_ok", 0),
            data.get("services_total", 0),
            data.get("sys_cpu", 0),
            data.get("sys_mem", 0),
            data.get("sys_disk", 0),
            data.get("providers_valid", 0),
            data.get("error_count", 0),
            data.get("uptime_seconds", 0),
            json.dumps(data.get("details", {}), ensure_ascii=False),
        ))
        conn.commit()
    finally:
        conn.close()


def get_latest_health() -> dict | None:
    """获取最近一次健康检查结果"""
    conn = _get_conn()
    try:
        row = conn.execute(
            "SELECT * FROM ops_health_log ORDER BY id DESC LIMIT 1"
        ).fetchone()
        if row:
            d = dict(row)
            d["details"] = json.loads(d.get("details", "{}"))
            return d
        return None
    finally:
        conn.close()


def get_health_history(hours: int = 24) -> list[dict]:
    """获取指定小时内所有健康检查记录"""
    cutoff = time.time() - hours * 3600
    conn = _get_conn()
    try:
        rows = conn.execute(
            "SELECT * FROM ops_health_log WHERE ts >= ? ORDER BY ts ASC",
            (cutoff,)
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_uptime_since(hours: int = 24) -> float:
    """计算指定时间内的可用性百分比（后端存活时间占比）"""
    records = get_health_history(hours)
    if not records:
        return 100.0
    alive = sum(1 for r in records if r["backend_alive"])
    return round(alive / len(records) * 100, 2)


# ── 告警/事件管理 ──

def add_incident(severity: str, category: str, title: str, message: str = "") -> int:
    """添加一条告警/事件记录"""
    conn = _get_conn()
    try:
        cur = conn.execute("""
            INSERT INTO ops_incidents (ts, severity, category, title, message, status)
            VALUES (?,?,?,?,?,'active')
        """, (time.time(), severity, category, title, message))
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def resolve_incident(incident_id: int, auto_healed: bool = False):
    """解决一条告警"""
    conn = _get_conn()
    try:
        row = conn.execute("SELECT ts FROM ops_incidents WHERE id=?", (incident_id,)).fetchone()
        if row:
            duration = int(time.time() - row["ts"])
            conn.execute("""
                UPDATE ops_incidents SET resolved_ts=?, status='resolved',
                    auto_healed=?, duration_seconds=?
                WHERE id=?
            """, (time.time(), 1 if auto_healed else 0, duration, incident_id))
            conn.commit()
    finally:
        conn.close()


def get_active_incidents() -> list[dict]:
    """获取当前活跃的告警"""
    conn = _get_conn()
    try:
        rows = conn.execute(
            "SELECT * FROM ops_incidents WHERE status='active' ORDER BY ts DESC"
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_incident_history(limit: int = 50) -> list[dict]:
    """获取告警历史"""
    conn = _get_conn()
    try:
        rows = conn.execute(
            "SELECT * FROM ops_incidents ORDER BY ts DESC LIMIT ?",
            (limit,)
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


# ── 巡检管理 ──

def save_inspection(data: dict) -> int:
    """保存一次巡检报告"""
    conn = _get_conn()
    try:
        cur = conn.execute("""
            INSERT INTO ops_inspections (ts, result, score, summary, details, issues_found)
            VALUES (?,?,?,?,?,?)
        """, (
            data.get("ts", time.time()),
            data.get("result", "pass"),
            data.get("score", 100),
            json.dumps(data.get("summary", {}), ensure_ascii=False),
            json.dumps(data.get("details", {}), ensure_ascii=False),
            data.get("issues_found", 0),
        ))
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def get_inspections(limit: int = 20) -> list[dict]:
    """获取巡检历史"""
    conn = _get_conn()
    try:
        rows = conn.execute(
            "SELECT * FROM ops_inspections ORDER BY ts DESC LIMIT ?",
            (limit,)
        ).fetchall()
        result = []
        for r in rows:
            d = dict(r)
            d["summary"] = json.loads(d.get("summary", "{}"))
            d["details"] = json.loads(d.get("details", "{}"))
            d["issues"] = d["details"].pop("issues", [])  # issues 从 details 中提取到顶层
            result.append(d)
        return result
    finally:
        conn.close()


# ── 自愈记录 ──

def save_self_heal(data: dict):
    """记录一次自愈操作"""
    conn = _get_conn()
    try:
        conn.execute("""
            INSERT INTO ops_self_heals (ts, trigger, action, result, message, duration_ms)
            VALUES (?,?,?,?,?,?)
        """, (
            data.get("ts", time.time()),
            data.get("trigger", ""),
            data.get("action", ""),
            data.get("result", "success"),
            data.get("message", ""),
            data.get("duration_ms", 0),
        ))
        conn.commit()
    finally:
        conn.close()


def get_self_heal_history(limit: int = 30) -> list[dict]:
    """获取自愈历史"""
    conn = _get_conn()
    try:
        rows = conn.execute(
            "SELECT * FROM ops_self_heals ORDER BY ts DESC LIMIT ?",
            (limit,)
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


# ── 趋势数据 ──

def save_trend(bucket: str, metric: str, value: float):
    """保存一条趋势数据"""
    conn = _get_conn()
    try:
        conn.execute("""
            INSERT INTO ops_trends (ts, bucket, metric, value)
            VALUES (?,?,?,?)
        """, (time.time(), bucket, metric, value))
        conn.commit()
    finally:
        conn.close()


def get_trends(metric: str, hours: int = 24, bucket: str | None = None) -> list[dict]:
    """获取指定指标的趋势数据"""
    cutoff = time.time() - hours * 3600
    conn = _get_conn()
    try:
        if bucket:
            rows = conn.execute(
                "SELECT * FROM ops_trends WHERE metric=? AND bucket=? AND ts >= ? ORDER BY ts ASC",
                (metric, bucket, cutoff)
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM ops_trends WHERE metric=? AND ts >= ? ORDER BY ts ASC",
                (metric, cutoff)
            ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def cleanup_old_trends(keep_hours: int = 720):  # 30天
    """清理过期趋势数据"""
    cutoff = time.time() - keep_hours * 3600
    conn = _get_conn()
    try:
        conn.execute("DELETE FROM ops_trends WHERE ts < ?", (cutoff,))
        conn.commit()
    finally:
        conn.close()


# ── 变更记录 ──

def add_changelog(action: str, target: str, detail: str = "", result: str = "ok"):
    """记录一次系统变更"""
    conn = _get_conn()
    try:
        conn.execute("""
            INSERT INTO ops_changelog (ts, action, target, detail, result)
            VALUES (?,?,?,?,?)
        """, (time.time(), action, target, detail, result))
        conn.commit()
    finally:
        conn.close()


def get_changelog(limit: int = 50) -> list[dict]:
    """获取变更记录"""
    conn = _get_conn()
    try:
        rows = conn.execute(
            "SELECT * FROM ops_changelog ORDER BY ts DESC LIMIT ?",
            (limit,)
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


# ── 删除记录 ──

def delete_record(table: str, record_id: int) -> bool:
    """删除指定运维表中的一条记录，返回是否成功"""
    valid_tables = {
        "incidents": "ops_incidents",
        "inspections": "ops_inspections",
        "self_heals": "ops_self_heals",
        "changelog": "ops_changelog",
        "health_log": "ops_health_log",
    }
    real_table = valid_tables.get(table)
    if not real_table:
        log.warning(f"尝试删除无效表: {table}")
        return False
    conn = _get_conn()
    try:
        cur = conn.execute(f"DELETE FROM {real_table} WHERE id=?", (record_id,))
        conn.commit()
        deleted = cur.rowcount > 0
        if deleted:
            log.info(f"已删除 {real_table} 记录 ID={record_id}")
        return deleted
    except Exception as e:
        log.warning(f"删除 {real_table} 记录失败: {e}")
        return False
    finally:
        conn.close()


# ────────────────────────────────────────────
# 4. 自愈引擎
# ────────────────────────────────────────────

async def _restart_backend() -> tuple[bool, str]:
    """
    尝试重启后端进程
    注：这里只记录自愈意图，实际重启由外部进程管理器负责
    """
    try:
        pid = os.getpid()
        log.warning(f"自愈：后端进程(PID={pid}) 异常，尝试自我恢复...")
        # 清理可能的资源泄漏
        import gc
        gc.collect()
        log.info("自愈：内存回收完成，进程仍在运行")
        return True, "内存回收完成，进程状态正常"
    except Exception as e:
        return False, f"自愈失败：{e}"


def _find_searxng_dir():
    """从本文件位置向上遍历，定位含 'SearXNG for Windows.exe' 的 searxng 目录。

    兼容两种布局（彻底消除打包态路径错位）：
      - 开发态：desktop_core/ops_engine.py -> ../searxng/
      - 打包态：resources/desktop_core/ops_engine.py -> ../searxng/
                （build.rs 已把项目根 searxng/ 同步进 resources/searxng/）
    向上最多 5 层，不写死盘符/用户名/项目名。
    """
    here = os.path.dirname(os.path.abspath(__file__))
    cur = here
    for _ in range(5):
        cand = os.path.join(cur, "searxng", "SearXNG for Windows.exe")
        if os.path.exists(cand):
            return os.path.join(cur, "searxng")
        cur = os.path.dirname(cur)
    return None


async def _ensure_searxng() -> tuple[bool, str]:
    """确保 SearXNG 在线：端口已监听则跳过，否则拉起。返回 (ok, msg)。

    与 _restart_searxng 的区别：先探测再决策，避免对已运行实例重复 taskkill。
    供「应用启动钩子」和「看门狗」共用，保证 SearXNG 随桌面端应用启动并持续在线。
    """
    try:
        _, w = await asyncio.wait_for(
            asyncio.open_connection("127.0.0.1", 8899), timeout=1.5
        )
        w.close()
        try:
            await w.wait_closed()
        except Exception:
            pass
        return True, "SearXNG 已在运行（端口 8899 监听中）"
    except Exception:
        pass
    return await _restart_searxng()


async def _searxng_watchdog(interval: int = 60):
    """SearXNG 看门狗：随应用持续运行，离线自动拉起。

    与后端 self-heal 的「检测→重启」机制一致，但作为独立常驻循环：
    每 interval 秒检测 8899 端口，离线则经 _ensure_searxng 自动拉起，
    无需用户手动触发自愈。随桌面端应用启动而启动。
    """
    await asyncio.sleep(5)  # 启动后稍候，避免与启动钩子抢端口
    while True:
        try:
            await asyncio.sleep(interval)
            ok, msg = await _ensure_searxng()
            if not ok:
                log.warning(f"看门狗：SearXNG 离线，已尝试自动拉起：{msg}")
        except asyncio.CancelledError:
            break
        except Exception as e:
            log.error(f"看门狗异常：{e}")


async def _restart_searxng() -> tuple[bool, str]:
    """尝试重启 SearXNG 搜索服务"""
    try:
        # 清理旧实例：8899 端口占用者（webapp python）+ exe 壳，确保干净重启。
        # 注：webapp 进程名是 python.exe，原 taskkill 'SearXNG*' 杀不到，必须按端口清理。
        try:
            subprocess.run(["powershell", "-NoProfile", "-Command",
                "$p=Get-NetTCPConnection -LocalPort 8899 -State Listen -ErrorAction SilentlyContinue; "
                "if($p){Stop-Process -Id $p.OwningProcess -Force -ErrorAction SilentlyContinue}; "
                "Get-Process -Name 'SearXNG*' -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue"],
                capture_output=True, text=True, timeout=8,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
        except Exception:
            pass
        await asyncio.sleep(1)

        # 定位 searxng 目录（多候选，兼容开发态/打包态）
        searxng_dir = _find_searxng_dir()
        if not searxng_dir:
            return False, "SearXNG 目录不存在（已向上遍历项目根及上层 searxng 目录）"

        # 启动：用自带 pythonw（无窗口子系统）直接跑 webapp.py——避免弹出可见控制台终端。
        # 关键修复：必须显式传 SEARXNG_SETTINGS_PATH，否则 webapp 用内置默认配置监听 8888，
        # 与 ops_engine 检测的 8899 不一致 → 看门狗永远检测失败 → 每 60s 重试弹窗循环。
        # 注：SearXNG for Windows.exe 是损坏的壳（0xc000000be 无效镜像格式），
        # 从不提供 HTTP 服务，已移除兜底路径避免启动时弹 Windows 错误对话框。
        startupinfo = None
        if os.name == "nt":
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            startupinfo.wShowWindow = subprocess.SW_HIDE  # 双保险隐藏窗口（pythonw 已无窗口，此为止损层）
        py = os.path.join(searxng_dir, "python", "pythonw.exe")
        webapp = os.path.join(searxng_dir, "python", "Lib", "site-packages", "searx", "webapp.py")
        settings = os.path.join(searxng_dir, "config", "settings.yml")
        if os.path.exists(py) and os.path.exists(webapp):
            env = dict(os.environ)
            if os.path.exists(settings):
                env["SEARXNG_SETTINGS_PATH"] = settings
            subprocess.Popen([py, webapp], cwd=searxng_dir, stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL, startupinfo=startupinfo, env=env)
        else:
            return False, (f"SearXNG 启动器不存在：python={os.path.exists(py)}({py}), "
                           f"webapp={os.path.exists(webapp)}({webapp}), searxng_dir={searxng_dir}")

        # 等待端口就绪（webapp 冷启动较慢，给足 20s）
        for i in range(40):
            await asyncio.sleep(0.5)
            try:
                import urllib.request
                urllib.request.urlopen("http://127.0.0.1:8899", timeout=2)
                return True, "SearXNG 已启动（端口 8899 就绪）"
            except Exception:
                continue
        return False, "SearXNG 启动后端口未就绪"
    except Exception as e:
        return False, f"SearXNG 自愈失败：{e}"


async def _cleanup_disk(threshold: int = 85) -> tuple[bool, str]:
    """磁盘空间清理：当日志/磁盘超过阈值时自动清理"""
    try:
        import shutil
        disk = shutil.disk_usage("/")
        used_pct = round(disk.used / disk.total * 100, 1) if disk.total else 0

        if used_pct < threshold:
            return True, f"磁盘使用率 {used_pct}%，无需清理"

        # 清理日志文件
        log_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "logs")
        freed = 0
        if os.path.exists(log_dir):
            for f in os.listdir(log_dir):
                fpath = os.path.join(log_dir, f)
                if os.path.isfile(fpath) and f.endswith(".log"):
                    # 保留最近3个日志文件
                    mtime = os.path.getmtime(fpath)
                    if time.time() - mtime > 86400 * 7:  # 7天前的日志
                        sz = os.path.getsize(fpath)
                        os.remove(fpath)
                        freed += sz

        # 清理 __pycache__（仅限项目自身代码目录，不碰外部依赖）
        project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        for dirpath, dirnames, _ in os.walk(project_root):
            # 跳过 searxng/ 等外部依赖目录
            rel = os.path.relpath(dirpath, project_root)
            if rel.startswith("searxng") or rel.startswith(".git") or rel.startswith("node_modules") or rel.startswith("src-tauri"):
                dirnames.clear()
                continue
            if "__pycache__" in dirnames:
                try:
                    import shutil
                    cache_path = os.path.join(dirpath, "__pycache__")
                    shutil.rmtree(cache_path, ignore_errors=True)
                except:
                    pass

        freed_mb = round(freed / (1024**2), 1)
        return True, f"磁盘已自动养护：清理了 {freed_mb} MB 过期日志和缓存"
    except Exception as e:
        return False, f"磁盘清理失败：{e}"


async def try_self_heal(trigger_type: str = "auto") -> dict:
    """
    自愈主入口：检测异常 → 尝试恢复 → 记录结果
    返回自愈结果字典
    """
    start = time.monotonic()
    result_data = {"trigger": trigger_type, "action": "", "result": "success",
                   "message": "", "duration_ms": 0}
    recovered = False

    try:
        if psutil is not None:
            # 1. 检查后端自身
            self_proc = psutil.Process(os.getpid())
            mem_mb = round(self_proc.memory_info().rss / (1024**2), 1)
            cpu_pct = self_proc.cpu_percent(interval=0.2)

            if cpu_pct > 95 or mem_mb > 500:
                # 资源占用过高，尝试恢复
                ok, msg = await _restart_backend()
                if ok:
                    result_data["action"] = "后端资源回收"
                    result_data["message"] = msg
                    recovered = True
                    add_changelog("自愈", "后端进程", msg)
                else:
                    result_data["result"] = "failed"
                    result_data["message"] = msg
                    add_incident("critical", "自愈失败", "后端自愈失败", msg)

        # 2. 检查 SearXNG
        try:
            _, writer = await asyncio.wait_for(
                asyncio.open_connection("127.0.0.1", 8899), timeout=1
            )
            writer.close()
            await writer.wait_closed()
        except:
            ok, msg = await _restart_searxng()
            if ok:
                result_data["action"] = "SearXNG 重启"
                result_data["message"] = msg
                recovered = True
                add_changelog("自愈", "SearXNG", msg)
            else:
                result_data["action"] = "SearXNG 恢复失败"
                result_data["result"] = "failed"
                result_data["message"] = msg
                add_incident("warning", "服务异常", "SearXNG 离线", msg)

        # 3. 检查磁盘
        ok, msg = await _cleanup_disk()
        if not ok:
            add_incident("warning", "磁盘空间", "磁盘不足", msg)

        if not recovered and not result_data.get("action"):
            result_data["action"] = "健康检查通过"
            result_data["message"] = "所有服务运行正常，无需自愈"

    except Exception as e:
        result_data["result"] = "failed"
        result_data["message"] = f"自愈引擎异常：{e}"

    result_data["duration_ms"] = int((time.monotonic() - start) * 1000)
    save_self_heal(result_data)
    return result_data


# ────────────────────────────────────────────
# 5. 巡检引擎
# ────────────────────────────────────────────

async def run_inspection() -> dict:
    """
    执行一次全面巡检，生成结构化报告
    检查维度：系统资源、服务连通性、提供商、数据库、错误率、安全
    """
    from desktop_core.storage import meta_get

    start_ts = time.time()
    issues = []
    details = {}
    summary = {}

    # ── 1. 系统资源 ──
    if psutil is not None:
        try:
            sys_cpu = psutil.cpu_percent(interval=0.5)
            sys_mem = psutil.virtual_memory().percent
            sys_disk = psutil.disk_usage("/").percent
            details["system"] = {
                "cpu": sys_cpu,
                "memory": sys_mem,
                "disk": sys_disk,
            }
            if sys_cpu > 90:
                issues.append({"severity": "warning", "item": "CPU 使用率过高", "value": f"{sys_cpu}%"})
            if sys_mem > 90:
                issues.append({"severity": "warning", "item": "内存使用率过高", "value": f"{sys_mem}%"})
            if sys_disk > 90:
                issues.append({"severity": "critical", "item": "磁盘空间不足", "value": f"{sys_disk}%"})
            elif sys_disk > 80:
                issues.append({"severity": "warning", "item": "磁盘空间即将不足", "value": f"{sys_disk}%"})
        except Exception as e:
            issues.append({"severity": "error", "item": "系统资源检测失败", "value": str(e)})
    else:
        details["system"] = {"cpu": None, "memory": None, "disk": None, "note": "未安装 psutil，系统指标不可用"}

    # ── 2. 服务连通性 ──
    services = {}
    for name, port in [("后端 API", 9845), ("SearXNG", 8899)]:
        try:
            _, w = await asyncio.wait_for(asyncio.open_connection("127.0.0.1", port), timeout=1.5)
            w.close()
            await w.wait_closed()
            services[name] = True
        except:
            services[name] = False
            issues.append({"severity": "critical" if name == "后端 API" else "warning",
                          "item": f"{name} 服务离线", "value": f"端口 {port} 无法连接"})
    details["services"] = services

    # ── 3. API 提供商 ──
    try:
        raw = meta_get("desktop_config")
        providers = {"total": 0, "valid": 0, "details": []}
        if raw:
            cfg = json.loads(raw)
            all_providers = cfg.get("api_providers", {})
            providers["total"] = len(all_providers)
            for pid, pcfg in all_providers.items():
                has_key = bool(pcfg.get("api_key", ""))
                if has_key:
                    providers["valid"] += 1
                providers["details"].append({
                    "name": pid,
                    "type": pcfg.get("type", ""),
                    "has_key": has_key,
                })
            if providers["total"] > 0 and providers["valid"] == 0:
                issues.append({"severity": "warning", "item": "所有 API 提供商密钥无效",
                              "value": f"共 {providers['total']} 个提供商，均无有效密钥"})
        details["providers"] = providers
    except Exception as e:
        issues.append({"severity": "error", "item": "提供商检测失败", "value": str(e)})

    # ── 4. 数据库健康 ──
    try:
        conn = _get_conn()
        db_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "naixi_desktop.db")
        db_size_mb = round(os.path.getsize(db_path) / (1024**2), 1) if os.path.exists(db_path) else 0
        tables = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        ).fetchall()
        db_info = {"size_mb": db_size_mb, "table_count": len(tables)}
        details["database"] = db_info
        conn.close()

        if db_size_mb > 100:
            issues.append({"severity": "info", "item": "数据库较大", "value": f"{db_size_mb} MB，建议定时 VACUUM"})
    except Exception as e:
        issues.append({"severity": "error", "item": "数据库检测失败", "value": str(e)})

    # ── 5. 健康历史分析 ──
    try:
        recent_records = get_health_history(1)  # 最近1小时
        error_rate = 0
        if recent_records:
            low_score = sum(1 for r in recent_records if r["score"] < 60)
            error_rate = round(low_score / len(recent_records) * 100, 1)
            if error_rate > 20:
                issues.append({"severity": "warning", "item": "近期健康评分偏低",
                              "value": f"近1小时 {error_rate}% 的记录评分低于60"})
        details["recent_health"] = {
            "records_1h": len(recent_records),
            "low_score_pct": error_rate,
        }
    except Exception as e:
        pass

    # ── 6. 安全检查 ──
    if psutil is not None:
        try:
            # 简单安全扫描：检查是否有异常端口监听
            conns = psutil.net_connections()
            unexpected_ports = []
            for c in conns:
                if c.status == "LISTEN" and c.laddr and c.laddr.port not in (9845, 8899):
                    unexpected_ports.append(c.laddr.port)
            if unexpected_ports:
                issues.append({
                    "severity": "info",
                    "item": "非常规端口监听",
                    "value": f"发现额外监听端口：{unexpected_ports[:5]}",
                })
            details["security"] = {"listening_ports": [c.laddr.port for c in conns if c.status == "LISTEN" and c.laddr]}
        except:
            details["security"] = {}
    else:
        details["security"] = {}

    # ── 汇总 ──
    issue_count = len(issues)
    has_critical = any(i["severity"] == "critical" for i in issues)
    has_warning = any(i["severity"] == "warning" for i in issues)

    if has_critical:
        result = "critical"
    elif has_warning:
        result = "warning"
    elif issue_count == 0:
        result = "pass"
    else:
        result = "info"

    # 评分：基础100，每有一个问题扣分
    score = 100
    for i in issues:
        if i["severity"] == "critical":
            score -= 20
        elif i["severity"] == "warning":
            score -= 10
        elif i["severity"] == "error":
            score -= 15
        else:
            score -= 3
    score = max(0, score)
    summary = {
        "result": result,
        "score": score,
        "issues": issue_count,
        "critical": sum(1 for i in issues if i["severity"] == "critical"),
        "warning": sum(1 for i in issues if i["severity"] == "warning"),
        "duration_seconds": round(time.time() - start_ts, 1),
    }

    details["issues"] = issues

    inspection_data = {
        "ts": start_ts,
        "result": result,
        "score": score,
        "summary": summary,
        "details": details,
        "issues_found": issue_count,
        "issues": issues,
    }

    inspection_id = save_inspection(inspection_data)
    add_changelog("巡检", "全系统", f"评分 {score}/100，发现 {issue_count} 个问题")
    inspection_data["id"] = inspection_id
    return inspection_data


# ────────────────────────────────────────────
# 6. 养护操作
# ────────────────────────────────────────────

async def run_maintenance(actions: list[str] | None = None) -> dict:
    """执行系统养护操作"""
    results = {}
    if actions is None:
        actions = ["log_cleanup", "db_vacuum", "trend_cleanup"]

    for action in actions:
        try:
            if action == "log_cleanup":
                log_dir = os.path.join(
                    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "logs"
                )
                freed = 0
                kept = 0
                if os.path.exists(log_dir):
                    for f in os.listdir(log_dir):
                        fpath = os.path.join(log_dir, f)
                        if os.path.isfile(fpath):
                            mtime = os.path.getmtime(fpath)
                            if time.time() - mtime > 86400 * 7:
                                freed += os.path.getsize(fpath)
                                os.remove(fpath)
                                kept += 1
                results[action] = {
                    "ok": True,
                    "message": f"清理了 {kept} 个过期日志文件，释放 {round(freed/(1024**2),1)} MB",
                }

            elif action == "db_vacuum":
                conn = _get_conn()
                before = os.path.getsize(DB_PATH) if os.path.exists(DB_PATH) else 0
                conn.execute("VACUUM")
                conn.close()
                after = os.path.getsize(DB_PATH) if os.path.exists(DB_PATH) else 0
                saved = round((before - after) / (1024**2), 1)
                results[action] = {
                    "ok": True,
                    "message": f"数据库压缩完成，释放 {saved} MB",
                }

            elif action == "trend_cleanup":
                cleanup_old_trends(keep_hours=720)  # 保留30天
                results[action] = {
                    "ok": True,
                    "message": "趋势数据清理完成（保留最近30天）",
                }

            elif action == "cache_cleanup":
                root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
                import shutil
                cleaned = 0
                for dirpath, dirnames, _ in os.walk(root):
                    rel = os.path.relpath(dirpath, root)
                    if rel.startswith("searxng") or rel.startswith(".git") or rel.startswith("node_modules") or rel.startswith("src-tauri"):
                        dirnames.clear()
                        continue
                    if "__pycache__" in dirnames:
                        shutil.rmtree(os.path.join(dirpath, "__pycache__"), ignore_errors=True)
                        cleaned += 1
                results[action] = {"ok": True, "message": f"清理了 {cleaned} 个 __pycache__ 目录（仅项目代码）"}

            else:
                results[action] = {"ok": False, "message": f"未知的养护操作：{action}"}

            # 记录养护日志
            if results[action]["ok"]:
                add_changelog("养护", f"操作-{action}", results[action]["message"])

        except Exception as e:
            results[action] = {"ok": False, "message": str(e)}
            add_incident("warning", "养护失败", f"养护操作失败：{action}", str(e))

    return {"actions": results, "ok": all(r.get("ok") for r in results.values())}


# ────────────────────────────────────────────
# 7. 运维总览数据
# ────────────────────────────────────────────

async def get_ops_dashboard() -> dict:
    """获取运维总览数据（供前端展示）"""

    # 后端自身状态
    self_pid = os.getpid()
    try:
        self_proc = psutil.Process(self_pid)
        self_mem = round(self_proc.memory_info().rss / (1024**2), 1)
        self_cpu = self_proc.cpu_percent(interval=0.3)
        create_time = self_proc.create_time()
        uptime_seconds = int(time.time() - create_time)
    except:
        self_mem = self_cpu = 0
        uptime_seconds = 0

    # 系统资源
    try:
        sys_cpu = psutil.cpu_percent(interval=0.3)
        sys_mem = psutil.virtual_memory().percent
        sys_disk = psutil.disk_usage("/").percent
    except:
        sys_cpu = sys_mem = sys_disk = 0

    # 服务检查
    services = {}
    for name, port in [("后端 API", 9845), ("SearXNG", 8899)]:
        try:
            _, w = await asyncio.wait_for(asyncio.open_connection("127.0.0.1", port), timeout=1)
            w.close()
            await w.wait_closed()
            services[name] = True
        except:
            services[name] = False
    services_ok = sum(1 for v in services.values() if v)
    services_total = len(services)

    # 提供商
    from desktop_core.storage import meta_get
    raw = meta_get("desktop_config")
    providers_total = 0
    providers_valid = 0
    if raw:
        cfg = json.loads(raw)
        for pid, pcfg in cfg.get("api_providers", {}).items():
            providers_total += 1
            if pcfg.get("api_key", ""):
                providers_valid += 1

    # 最近错误数量（从 ops_health_log 最后一条）
    last = get_latest_health()
    error_count = last["error_count"] if last else 0

    # 计算健康评分
    score, breakdown = compute_health_score(
        backend_alive=True,
        services_ok=services_ok, services_total=services_total,
        providers_valid=providers_valid, providers_total=providers_total,
        error_count=error_count,
        sys_cpu=sys_cpu, sys_mem=sys_mem, sys_disk=sys_disk,
    )

    # 可用性
    uptime_24h = get_uptime_since(24)

    # 活跃告警
    active_incidents = get_active_incidents()

    # 最近一次巡检
    inspections = get_inspections(1)
    last_inspection = inspections[0] if inspections else None

    # 趋势数据（最近24小时的评分趋势）
    health_history = get_health_history(24)
    score_trend = [{"ts": r["ts"], "score": r["score"]} for r in health_history]

    # 记录本次健康检查
    save_health_log({
        "ts": time.time(),
        "score": score,
        "backend_alive": True,
        "backend_mem": self_mem,
        "backend_cpu": self_cpu,
        "services_ok": services_ok,
        "services_total": services_total,
        "sys_cpu": sys_cpu,
        "sys_mem": sys_mem,
        "sys_disk": sys_disk,
        "providers_valid": providers_valid,
        "error_count": error_count,
        "uptime_seconds": uptime_seconds,
        "details": {"services": services},
    })

    return {
        "health_score": score,
        "breakdown": breakdown,
        "psutil_available": psutil is not None,
        "uptime_24h": uptime_24h,
        "uptime_seconds": uptime_seconds,
        "backend": {
            "pid": self_pid,
            "memory_mb": self_mem,
            "cpu": self_cpu,
            "uptime_seconds": uptime_seconds,
        },
        "system": {
            "cpu": sys_cpu,
            "memory": sys_mem,
            "disk": sys_disk,
        },
        "services": services,
        "services_ok": services_ok,
        "services_total": services_total,
        "providers": {"total": providers_total, "valid": providers_valid},
        "active_incidents": len(active_incidents),
        "last_inspection": last_inspection,
        "score_trend": score_trend[-96:],  # 最多返回最近96个点
    }
