"""桌面端存储 — 独立 SQLite 封装，不含 QQ 机器人数据表"""
import os, sqlite3, json, logging, base64, subprocess, hashlib

log = logging.getLogger("desktop")

# DB 路径由外层 naixi_api.py 在导入前设置
DB_PATH = ""

# ── API Key 加密 ──
# 密钥体系（2026-07 加固）：
#   1) 主密钥为随机 32 字节，用 Windows DPAPI（当前用户作用域）保护后存入 meta 表。
#      DPAPI 把密钥绑定到当前 Windows 账户——即使数据库被拷到别的机器/账户也无法解密。
#   2) 旧数据用「机器 UUID 派生」的旧密钥加密，保留旧密钥仅用于向后兼容解密，不再用于新加密。
#   3) encrypt 幂等：已是 enc: 前缀的值不再二次加密（修复历史多层加密 bug）。
#   4) 加密失败绝不回退明文——宁可返回空，也不把密钥以明文落库。
_ENCRYPT_PREFIX = "enc:"
_KEY_MASK = "********"          # 返回给前端的掩码占位符（绝不返回明文）
_MASTER_META_KEY = "_fernet_master_v2"
_FERNET_CACHE = None           # 当前主密钥 Fernet（加解密都用）
_LEGACY_FERNET_CACHE = None    # 旧 UUID 派生密钥 Fernet（仅解密旧数据）


def _machine_uuid() -> str:
    """取机器唯一标识：UUID -> MAC -> 常量（仅用于旧密钥兼容派生）"""
    try:
        r = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             "Get-CimInstance -Class Win32_ComputerSystemProduct | Select-Object -ExpandProperty UUID"],
            capture_output=True, text=True, timeout=5
        )
        mid = r.stdout.strip()
    except Exception:
        mid = ""
    if not mid or len(mid) < 10:
        try:
            r = subprocess.run(
                ["powershell", "-NoProfile", "-Command",
                 "Get-NetAdapter | Where-Object {$_.Status -eq 'Up'} | Select-Object -First 1 -ExpandProperty MacAddress"],
                capture_output=True, text=True, timeout=5
            )
            mid = r.stdout.strip().replace("-", "")
        except Exception:
            mid = ""
    if not mid or len(mid) < 8:
        mid = "NAIXI-DESKTOP-FALLBACK"
    return mid


def _legacy_fernet():
    """旧版机器 UUID 派生密钥（仅用于解密历史数据，保证向后兼容）"""
    global _LEGACY_FERNET_CACHE
    if _LEGACY_FERNET_CACHE is not None:
        return _LEGACY_FERNET_CACHE
    try:
        from cryptography.fernet import Fernet
        raw = hashlib.sha256(f"naixi-v1::{_machine_uuid()}".encode()).digest()
        _LEGACY_FERNET_CACHE = Fernet(base64.urlsafe_b64encode(raw[:32]))
    except Exception:
        _LEGACY_FERNET_CACHE = False
    return _LEGACY_FERNET_CACHE


def _dpapi_protect(data: bytes):
    """用 Windows DPAPI（当前用户作用域）保护数据，失败返回 None"""
    try:
        import ctypes
        from ctypes import wintypes

        class DATA_BLOB(ctypes.Structure):
            _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]

        buf = ctypes.create_string_buffer(data, len(data))
        blob_in = DATA_BLOB(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char)))
        blob_out = DATA_BLOB()
        if not ctypes.windll.crypt32.CryptProtectData(
            ctypes.byref(blob_in), None, None, None, None, 0, ctypes.byref(blob_out)
        ):
            return None
        out = ctypes.string_at(blob_out.pbData, blob_out.cbData)
        ctypes.windll.kernel32.LocalFree(blob_out.pbData)
        return out
    except Exception:
        return None


def _dpapi_unprotect(blob: bytes):
    """用 Windows DPAPI 还原数据，失败返回 None"""
    try:
        import ctypes
        from ctypes import wintypes

        class DATA_BLOB(ctypes.Structure):
            _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]

        buf = ctypes.create_string_buffer(blob, len(blob))
        blob_in = DATA_BLOB(len(blob), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char)))
        blob_out = DATA_BLOB()
        if not ctypes.windll.crypt32.CryptUnprotectData(
            ctypes.byref(blob_in), None, None, None, None, 0, ctypes.byref(blob_out)
        ):
            return None
        out = ctypes.string_at(blob_out.pbData, blob_out.cbData)
        ctypes.windll.kernel32.LocalFree(blob_out.pbData)
        return out
    except Exception:
        return None


def _get_fernet():
    """获取当前主密钥 Fernet 实例。
    优先用 DPAPI 保护的随机主密钥；DPAPI 不可用时回退到旧 UUID 派生密钥（保证不崩）。
    """
    global _FERNET_CACHE
    if _FERNET_CACHE is not None:
        return _FERNET_CACHE
    from cryptography.fernet import Fernet
    try:
        stored = meta_get(_MASTER_META_KEY, "")
        if stored:
            blob = base64.b64decode(stored.encode())
            raw = _dpapi_unprotect(blob)
            if raw and len(raw) == 32:
                _FERNET_CACHE = Fernet(base64.urlsafe_b64encode(raw))
                return _FERNET_CACHE
        # 首次生成随机主密钥并用 DPAPI 保护后落库
        raw = os.urandom(32)
        blob = _dpapi_protect(raw)
        if blob:
            meta_set(_MASTER_META_KEY, base64.b64encode(blob).decode())
            _FERNET_CACHE = Fernet(base64.urlsafe_b64encode(raw))
            log.info("已生成 DPAPI 保护的新主密钥")
            return _FERNET_CACHE
        # DPAPI 不可用：回退旧派生密钥（仍可工作，安全性稍弱）
        log.warning("DPAPI 不可用，回退到机器标识派生密钥")
        legacy = _legacy_fernet()
        if legacy:
            _FERNET_CACHE = legacy
            return _FERNET_CACHE
    except Exception as e:
        log.warning(f"主密钥初始化异常: {e}")
    # 最终兜底：用旧派生密钥
    legacy = _legacy_fernet()
    _FERNET_CACHE = legacy if legacy else False
    return _FERNET_CACHE


def encrypt_api_key(plain: str) -> str:
    """加密 API Key，返回带前缀的密文。幂等：已加密的值原样返回，不二次加密。"""
    if not plain:
        return ""
    if plain.startswith(_ENCRYPT_PREFIX):
        return plain  # 已加密，避免多层加密
    try:
        f = _get_fernet()
        if not f:
            log.warning("加密不可用（无可用密钥），拒绝以明文存储密钥")
            return ""
        return _ENCRYPT_PREFIX + f.encrypt(plain.encode()).decode()
    except Exception as e:
        log.warning(f"加密 API Key 失败: {e}；拒绝以明文存储密钥")
        return ""  # 绝不回退明文


def decrypt_api_key(cipher: str) -> str:
    """解密 API Key。支持历史多层加密（循环剥离）；先试新主密钥，再试旧派生密钥。"""
    if not cipher:
        return ""
    if not cipher.startswith(_ENCRYPT_PREFIX):
        return cipher  # 未加密的旧数据，原样返回
    from cryptography.fernet import InvalidToken
    fernets = [x for x in (_get_fernet(), _legacy_fernet()) if x]
    cur = cipher
    for _ in range(10):  # 最多剥离 10 层，防御历史多层加密
        if not cur.startswith(_ENCRYPT_PREFIX):
            return cur
        token = cur[len(_ENCRYPT_PREFIX):].encode()
        plain = None
        for f in fernets:
            try:
                plain = f.decrypt(token).decode()
                break
            except InvalidToken:
                continue
            except Exception:
                continue
        if plain is None:
            log.warning("API Key 解密失败（无匹配密钥），返回空")
            return ""
        cur = plain
    log.warning("API Key 解密层数异常，返回空")
    return ""


def mask_api_key(cipher_or_plain: str) -> str:
    """把密钥转为掩码占位符，绝不返回明文。有值返回掩码，无值返回空。"""
    return _KEY_MASK if cipher_or_plain else ""


def is_masked_key(value: str) -> bool:
    """判断前端回传的值是否是掩码（含未改动占位符），或为空——两者都应保留原有密钥。"""
    return (not value) or (_KEY_MASK[:4] in value)


def encrypt_config(config: dict) -> dict:
    """对整个配置中的 api_providers 做密钥加密（原地修改，幂等）"""
    providers = config.get("api_providers", {})
    for k, v in providers.items():
        if isinstance(v, dict) and v.get("api_key"):
            v["api_key"] = encrypt_api_key(v["api_key"])
    return config


def decrypt_config(config: dict) -> dict:
    """对整个配置中的 api_providers 做密钥解密（原地修改）"""
    providers = config.get("api_providers", {})
    for k, v in providers.items():
        if isinstance(v, dict) and v.get("api_key"):
            v["api_key"] = decrypt_api_key(v["api_key"])
    return config


def mask_config(config: dict) -> dict:
    """把配置中所有 api_key 替换为掩码占位符，用于安全返回给前端（绝不返回明文）"""
    providers = config.get("api_providers", {})
    for k, v in providers.items():
        if isinstance(v, dict):
            v["api_key"] = mask_api_key(v.get("api_key", ""))
    return config


def merge_preserve_keys(new_config: dict, old_config: dict) -> dict:
    """合并配置时保留旧密钥：前端回传掩码或空 api_key 时，沿用旧的加密密文，避免误删/误覆盖密钥。"""
    new_provs = new_config.get("api_providers", {})
    old_provs = (old_config or {}).get("api_providers", {})
    for k, v in new_provs.items():
        if not isinstance(v, dict):
            continue
        incoming = v.get("api_key", "")
        if is_masked_key(incoming):
            old = old_provs.get(k, {})
            v["api_key"] = old.get("api_key", "") if isinstance(old, dict) else ""
    return new_config

def _get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn

def init_tables():
    """创建桌面端所需的数据表（工作流相关）"""
    conn = _get_conn()
    try:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS workflows (
                id TEXT PRIMARY KEY,
                name TEXT DEFAULT '',
                description TEXT DEFAULT '',
                nodes TEXT DEFAULT '[]',
                edges TEXT DEFAULT '[]',
                dsl TEXT DEFAULT '',
                status TEXT DEFAULT 'draft',
                created_at TEXT DEFAULT (datetime('now')),
                updated_at TEXT DEFAULT (datetime('now'))
            );
            CREATE TABLE IF NOT EXISTS workflow_versions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                workflow_id TEXT NOT NULL,
                version INTEGER DEFAULT 1,
                nodes TEXT DEFAULT '[]',
                edges TEXT DEFAULT '[]',
                status TEXT DEFAULT 'draft',
                created_at TEXT DEFAULT (datetime('now'))
            );
            CREATE TABLE IF NOT EXISTS workflow_runs (
                id TEXT PRIMARY KEY,
                workflow_id TEXT NOT NULL,
                status TEXT DEFAULT 'pending',
                trigger TEXT DEFAULT 'manual',
                input TEXT DEFAULT '{}',
                output TEXT DEFAULT '',
                node_results TEXT DEFAULT '[]',
                variables TEXT DEFAULT '[]',
                started_at TEXT DEFAULT (datetime('now')),
                finished_at TEXT DEFAULT (datetime('now'))
            );
            CREATE TABLE IF NOT EXISTS workflow_templates (
                id TEXT PRIMARY KEY,
                name TEXT DEFAULT '',
                description TEXT DEFAULT '',
                category TEXT DEFAULT '',
                nodes TEXT DEFAULT '[]',
                edges TEXT DEFAULT '[]',
                dsl TEXT DEFAULT '',
                tags TEXT DEFAULT '',
                author TEXT DEFAULT '',
                usage_count INTEGER DEFAULT 0,
                created_at TEXT DEFAULT (datetime('now'))
            );
            CREATE TABLE IF NOT EXISTS meta (
                key TEXT PRIMARY KEY,
                value TEXT DEFAULT ''
            );
            CREATE TABLE IF NOT EXISTS convs (
                key TEXT PRIMARY KEY,
                last_role TEXT DEFAULT '',
                last_msg TEXT DEFAULT '',
                last_time REAL DEFAULT 0,
                msg_count INTEGER DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS conv_messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                conv_key TEXT NOT NULL,
                role TEXT NOT NULL,
                content TEXT DEFAULT '',
                content_blocks TEXT DEFAULT '[]',
                time REAL NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_msg_conv ON conv_messages(conv_key, id);
            CREATE TABLE IF NOT EXISTS avatars (
                seed TEXT PRIMARY KEY,
                url TEXT NOT NULL,
                created_at TEXT DEFAULT (datetime('now'))
            );
            CREATE TABLE IF NOT EXISTS workflow_api_keys (
                workflow_id TEXT PRIMARY KEY,
                api_key TEXT NOT NULL UNIQUE,
                created_at TEXT DEFAULT (datetime('now')),
                enabled INTEGER DEFAULT 1
            );
            CREATE TABLE IF NOT EXISTS workflow_call_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                workflow_id TEXT NOT NULL,
                api_key_id TEXT DEFAULT '',
                status TEXT DEFAULT 'pending',
                input TEXT DEFAULT '{}',
                output TEXT DEFAULT '{}',
                duration_ms INTEGER DEFAULT 0,
                created_at TEXT DEFAULT (datetime('now'))
            );
            CREATE TABLE IF NOT EXISTS workflow_published (
                workflow_id TEXT PRIMARY KEY,
                name TEXT DEFAULT '',
                description TEXT DEFAULT '',
                nodes TEXT DEFAULT '[]',
                edges TEXT DEFAULT '[]',
                dsl TEXT DEFAULT '',
                published_at TEXT DEFAULT (datetime('now'))
            );
            DROP TABLE IF EXISTS automations;
            DROP TABLE IF EXISTS automation_runs;
            CREATE TABLE IF NOT EXISTS naixi_automations (
                id TEXT PRIMARY KEY,
                name TEXT DEFAULT '',
                prompt TEXT DEFAULT '',
                schedule_type TEXT DEFAULT 'once',
                rrule TEXT DEFAULT '',
                scheduled_at TEXT DEFAULT '',
                status TEXT DEFAULT 'active',
                model TEXT DEFAULT '',
                last_run TEXT DEFAULT '',
                valid_from TEXT DEFAULT '',
                valid_until TEXT DEFAULT '',
                created_at TEXT DEFAULT (datetime('now')),
                updated_at TEXT DEFAULT (datetime('now'))
            );
            CREATE TABLE IF NOT EXISTS naixi_automation_runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                automation_id TEXT NOT NULL,
                run_time TEXT DEFAULT (datetime('now')),
                status TEXT DEFAULT 'running',
                prompt TEXT DEFAULT '',
                reply TEXT DEFAULT '',
                error TEXT DEFAULT '',
                model_used TEXT DEFAULT '',
                duration_ms INTEGER DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS hotkeys (
                id TEXT PRIMARY KEY,
                combo TEXT NOT NULL,
                kind TEXT NOT NULL DEFAULT 'motion',
                label TEXT NOT NULL DEFAULT '',
                enabled INTEGER DEFAULT 1,
                created_at TEXT DEFAULT (datetime('now'))
            );
            CREATE UNIQUE INDEX IF NOT EXISTS idx_hotkey_combo ON hotkeys(combo);

            CREATE TABLE IF NOT EXISTS agent_memory (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                agent_id TEXT NOT NULL DEFAULT 'naixi',
                viewer_id TEXT NOT NULL DEFAULT '',
                type TEXT NOT NULL,
                content TEXT NOT NULL,
                importance REAL DEFAULT 1.0,
                ts REAL DEFAULT 0,
                decay REAL DEFAULT 1.0,
                created_at TEXT DEFAULT (datetime('now'))
            );
            CREATE INDEX IF NOT EXISTS idx_agent_memory_av ON agent_memory(agent_id, viewer_id, type, ts);
        """)
        # 为现有表添加 duration_ms 列（如果不存在）
        try:
            conn.execute("ALTER TABLE naixi_automation_runs ADD COLUMN duration_ms INTEGER DEFAULT 0")
        except:
            pass
        # 迁移旧 JSON 数据到新表
        _migrate_naixi_automations()
        conn.commit()
    finally:
        conn.close()
    # 运维数据表
    from desktop_core.ops_engine import init_ops_tables
    init_ops_tables()

# ── 头像缓存 ──

def avatar_get(seed: str) -> str | None:
    """获取缓存的头像 URL"""
    conn = _get_conn()
    try:
        row = conn.execute("SELECT url FROM avatars WHERE seed=?", (seed,)).fetchone()
        return row["url"] if row else None
    finally:
        conn.close()

def avatar_set(seed: str, url: str):
    """缓存头像 URL"""
    conn = _get_conn()
    try:
        conn.execute(
            "INSERT OR REPLACE INTO avatars (seed, url, created_at) VALUES (?, ?, datetime('now'))",
            (seed, url)
        )
        conn.commit()
    finally:
        conn.close()

def avatar_count() -> int:
    """获取已缓存头像总数"""
    conn = _get_conn()
    try:
        row = conn.execute("SELECT COUNT(*) AS cnt FROM avatars").fetchone()
        return row["cnt"] if row else 0
    finally:
        conn.close()

def avatar_list() -> list[dict]:
    """列出所有缓存头像（按创建时间倒序）"""
    conn = _get_conn()
    try:
        rows = conn.execute(
            "SELECT seed, url, created_at FROM avatars ORDER BY created_at DESC"
        ).fetchall()
        return [{"seed": r["seed"], "url": r["url"], "created_at": r["created_at"]} for r in rows]
    finally:
        conn.close()


def avatar_remove_expired():
    """删除已过期的 OSS 头像记录（本地存储的永久有效）"""
    import time, re
    conn = _get_conn()
    try:
        rows = conn.execute("SELECT seed, url FROM avatars").fetchall()
        for r in rows:
            if "Expires=" in r["url"]:
                m = re.search(r"Expires=(\d+)", r["url"])
                if m and int(m.group(1)) < time.time():
                    conn.execute("DELETE FROM avatars WHERE seed = ?", (r["seed"],))
        conn.commit()
    finally:
        conn.close()

def meta_get(key: str, default: str = "") -> str:
    conn = _get_conn()
    try:
        row = conn.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
        return row["value"] if row else default
    finally:
        conn.close()

def meta_set(key: str, value: str):
    conn = _get_conn()
    try:
        conn.execute("INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)", (key, value))
        conn.commit()
    finally:
        conn.close()

# ── 长期记忆层（agent_memory）：替代全局 _scene_history，持久化 + 按观众维度 ──
# 设计：episodic=原始对话/弹幕事件流（可回溯）；profile=从该观众对话中抽取的稳定事实（带重要度/衰减）。
# 按 viewer_id 隔离：空串=通用/主人，否则=某观众 uid —— 直接对症"连弹幕都会忘记"。
def mem_add(agent_id: str, viewer_id: str, mtype: str, content: str,
            importance: float = 1.0, ts: float = None) -> int:
    """写入一条记忆。mtype: 'episodic' | 'profile'"""
    import time as _t
    if ts is None:
        ts = _t.time()
    conn = _get_conn()
    try:
        cur = conn.execute(
            "INSERT INTO agent_memory (agent_id, viewer_id, type, content, importance, ts) "
            "VALUES (?,?,?,?,?,?)",
            (agent_id, viewer_id or "", mtype, content, importance, ts))
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()

def mem_recent(agent_id: str, viewer_id: str = "", limit: int = 30) -> list:
    """取最近事件流（episodic），含通用(空viewer)与该观众，新→旧。"""
    conn = _get_conn()
    try:
        if viewer_id:
            rows = conn.execute(
                "SELECT content, ts FROM agent_memory "
                "WHERE agent_id=? AND type='episodic' AND (viewer_id=? OR viewer_id='') "
                "ORDER BY ts DESC, id DESC LIMIT ?",
                (agent_id, viewer_id, limit)).fetchall()
        else:
            rows = conn.execute(
                "SELECT content, ts FROM agent_memory "
                "WHERE agent_id=? AND type='episodic' ORDER BY ts DESC, id DESC LIMIT ?",
                (agent_id, limit)).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()

def mem_profile_get(agent_id: str, viewer_id: str = "") -> str:
    """聚合该对象(主人/观众)的画像事实，返回可注入 prompt 的文本；无则空串。"""
    conn = _get_conn()
    try:
        rows = conn.execute(
            "SELECT content, importance FROM agent_memory "
            "WHERE agent_id=? AND type='profile' AND viewer_id=? "
            "ORDER BY importance DESC, ts DESC",
            (agent_id, viewer_id or "")).fetchall()
        if not rows:
            return ""
        facts = [r["content"] for r in rows if (r["content"] or "").strip()]
        return "\n".join("- " + f for f in facts)
    finally:
        conn.close()

def mem_profile_set(agent_id: str, viewer_id: str, content: str, importance: float = 1.0):
    """写入/刷新一条画像事实（按 content 去重：同内容刷新重要度/ts，否则新增）。"""
    import time as _t
    conn = _get_conn()
    try:
        existing = conn.execute(
            "SELECT id FROM agent_memory WHERE agent_id=? AND type='profile' "
            "AND viewer_id=? AND content=?",
            (agent_id, viewer_id or "", content)).fetchone()
        if existing:
            conn.execute("UPDATE agent_memory SET importance=?, ts=? WHERE id=?",
                         (importance, _t.time(), existing["id"]))
        else:
            conn.execute(
                "INSERT INTO agent_memory (agent_id, viewer_id, type, content, importance, ts) "
                "VALUES (?,?,?,?,?,?)",
                (agent_id, viewer_id or "", "profile", content, importance, _t.time()))
        conn.commit()
    finally:
        conn.close()

def mem_build_context(agent_id: str, viewer_id: str = "", max_chars: int = 1500) -> str:
    """构建注入 prompt 的长期记忆摘要：画像 + 近期事件流（旧→新）。空则空串。"""
    profile = mem_profile_get(agent_id, viewer_id)
    recent = mem_recent(agent_id, viewer_id, limit=20)
    parts = []
    if profile:
        parts.append("【关于对方，你记得的】\n" + profile)
    if recent:
        lines = [(r.get("content") or "").strip() for r in reversed(recent) if (r.get("content") or "").strip()]
        joined = "\n".join(lines)
        if len(joined) > max_chars:
            joined = joined[-max_chars:]
        parts.append("【近期你们聊过】\n" + joined)
    return "\n\n".join(parts) if parts else ""

def mem_list_objects(agent_id: str) -> list:
    """列出某角色记住的所有对象（主人/观众）：viewer_id、画像条数、事件条数、最近活跃时间。
    用于调试接口，方便肉眼确认「它记住了谁」。空串 viewer 表示主人/通用。"""
    conn = _get_conn()
    try:
        rows = conn.execute(
            "SELECT viewer_id, type, COUNT(*) AS n, MAX(ts) AS last_ts "
            "FROM agent_memory WHERE agent_id=? GROUP BY viewer_id, type",
            (agent_id,)).fetchall()
        agg = {}
        for r in rows:
            vid = r["viewer_id"] or "(主人/通用)"
            a = agg.setdefault(vid, {"viewer_id": r["viewer_id"] or "", "profile": 0, "episodes": 0, "last_ts": 0})
            if r["type"] == "profile":
                a["profile"] = r["n"]
            else:
                a["episodes"] = r["n"]
            a["last_ts"] = max(a["last_ts"], r["last_ts"] or 0)
        return sorted(agg.values(), key=lambda x: x["last_ts"], reverse=True)
    finally:
        conn.close()


def mem_decay():
    """轻量衰减：episodic 超 7 天且重要度<0.5 的降低 decay；decay 过低则删除，避免无限膨胀。"""
    import time as _t
    conn = _get_conn()
    try:
        old_ts = _t.time() - 7 * 24 * 3600
        conn.execute(
            "UPDATE agent_memory SET decay = decay*0.9 "
            "WHERE type='episodic' AND ts<? AND importance<0.5 AND decay>0.2",
            (old_ts,))
        conn.execute("DELETE FROM agent_memory WHERE type='episodic' AND decay<=0.2")
        conn.commit()
    finally:
        conn.close()

# ── 对话历史 ──

def conv_save_message(conv_key: str, role: str, content: str, content_blocks: list = None, msg_time: float = None):
    """保存一条消息到对话"""
    import time as _time
    if msg_time is None:
        msg_time = _time.time()
    conn = _get_conn()
    try:
        conn.execute(
            "INSERT INTO conv_messages (conv_key, role, content, content_blocks, time) VALUES (?, ?, ?, ?, ?)",
            (conv_key, role, content, json.dumps(content_blocks or [], ensure_ascii=False), msg_time)
        )
        # 更新摘要
        prev = conn.execute("SELECT msg_count FROM convs WHERE key=?", (conv_key,)).fetchone()
        count = (prev["msg_count"] if prev else 0) + 1
        conn.execute(
            "INSERT OR REPLACE INTO convs (key, last_role, last_msg, last_time, msg_count) VALUES (?, ?, ?, ?, ?)",
            (conv_key, role, content[:100], msg_time, count)
        )
        conn.commit()
    finally:
        conn.close()

def conv_save_message_sync(conv_key: str, role: str, content: str, content_blocks: list = None, msg_time: float = None):
    """同步版（用于 chat_stream 线程）"""
    import time as _time
    if msg_time is None:
        msg_time = _time.time()
    conn = _get_conn()
    try:
        conn.execute(
            "INSERT INTO conv_messages (conv_key, role, content, content_blocks, time) VALUES (?, ?, ?, ?, ?)",
            (conv_key, role, content, json.dumps(content_blocks or [], ensure_ascii=False), msg_time)
        )
        prev = conn.execute("SELECT msg_count FROM convs WHERE key=?", (conv_key,)).fetchone()
        count = (prev["msg_count"] if prev else 0) + 1
        conn.execute(
            "INSERT OR REPLACE INTO convs (key, last_role, last_msg, last_time, msg_count) VALUES (?, ?, ?, ?, ?)",
            (conv_key, role, content[:100], msg_time, count)
        )
        conn.commit()
    finally:
        conn.close()

def conv_list():
    """获取所有对话摘要，按时间倒序"""
    conn = _get_conn()
    try:
        rows = conn.execute(
            "SELECT key, last_role, last_msg, last_time, msg_count FROM convs ORDER BY last_time DESC"
        ).fetchall()
        return [{
            "key": r["key"],
            "last_role": r["last_role"],
            "last_msg": r["last_msg"],
            "last_time": r["last_time"] or 0,
            "msg_count": r["msg_count"],
        } for r in rows]
    finally:
        conn.close()

def conv_get_messages(conv_key: str):
    """获取某个对话的所有消息"""
    conn = _get_conn()
    try:
        rows = conn.execute(
            "SELECT id, role, content, content_blocks, datetime(time, 'unixepoch', 'localtime') as time FROM conv_messages WHERE conv_key=? ORDER BY id ASC",
            (conv_key,)
        ).fetchall()
        msgs = []
        for r in rows:
            blocks = []
            try:
                blocks = json.loads(r["content_blocks"]) if r["content_blocks"] else []
            except:
                pass
            msgs.append({
                "id": r["id"],
                "role": r["role"],
                "content": r["content"],
                "content_blocks": blocks if blocks else None,
                "time": r["time"] or 0,
            })
        return msgs
    finally:
        conn.close()

def conv_delete_message(conv_key: str, msg_id: int):
    """删除对话中的单条消息，更新对话摘要"""
    conn = _get_conn()
    try:
        # 获取待删除消息
        row = conn.execute("SELECT role, content, time FROM conv_messages WHERE id=? AND conv_key=?", (msg_id, conv_key)).fetchone()
        if not row:
            return False
        # 删除消息
        conn.execute("DELETE FROM conv_messages WHERE id=? AND conv_key=?", (msg_id, conv_key))
        # 更新消息计数
        remaining = conn.execute("SELECT COUNT(*) AS cnt FROM conv_messages WHERE conv_key=?", (conv_key,)).fetchone()
        count = remaining["cnt"] if remaining else 0
        if count == 0:
            conn.execute("DELETE FROM convs WHERE key=?", (conv_key,))
        else:
            # 更新最新消息为最后一条
            last = conn.execute(
                "SELECT role, content, time FROM conv_messages WHERE conv_key=? ORDER BY id DESC LIMIT 1",
                (conv_key,)
            ).fetchone()
            conn.execute(
                "INSERT OR REPLACE INTO convs (key, last_role, last_msg, last_time, msg_count) VALUES (?, ?, ?, ?, ?)",
                (conv_key, last["role"], last["content"][:100], last["time"], count)
            )
        conn.commit()
        return True
    finally:
        conn.close()

def conv_delete(conv_key: str):
    """删除对话及其所有消息"""
    conn = _get_conn()
    try:
        conn.execute("DELETE FROM conv_messages WHERE conv_key=?", (conv_key,))
        conn.execute("DELETE FROM convs WHERE key=?", (conv_key,))
        conn.commit()
    finally:
        conn.close()


# ── 自动化 ──

def _migrate_naixi_automations():
    """从 JSON blob 迁移到 naixi_automations 表（幂等，只执行一次）"""
    raw = meta_get("naixi_automations")
    if not raw:
        return
    conn = _get_conn()
    try:
        existing = conn.execute("SELECT COUNT(*) AS c FROM naixi_automations").fetchone()["c"]
        if existing > 0:
            return  # 已迁移
        items = json.loads(raw)
        for item in items:
            conn.execute(
                """INSERT OR REPLACE INTO naixi_automations 
                   (id, name, prompt, schedule_type, rrule, scheduled_at, status, model, last_run, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (item.get("id", ""), item.get("name", ""), item.get("prompt", ""),
                 item.get("schedule_type", "once"), item.get("rrule", ""),
                 item.get("scheduled_at", ""), item.get("status", "active"),
                 item.get("model", ""), item.get("last_run", ""),
                 item.get("created_at", ""))
            )
            # 迁移历史记录
            for h in item.get("history", []):
                conn.execute(
                    "INSERT INTO naixi_automation_runs (automation_id, run_time, status, reply, model_used) VALUES (?, ?, ?, ?, ?)",
                    (item.get("id", ""), h.get("time", ""), h.get("status", "success"), h.get("result", ""), "")
                )
        conn.commit()
        log.info(f"迁移 {len(items)} 条自动化任务到 SQLite")
    finally:
        conn.close()


def automation_list() -> list[dict]:
    """获取所有自动化任务"""
    conn = _get_conn()
    try:
        rows = conn.execute("SELECT * FROM naixi_automations ORDER BY created_at DESC").fetchall()
        result = []
        for r in rows:
            a = dict(r)
            # 获取执行记录
            runs = conn.execute(
                "SELECT * FROM naixi_automation_runs WHERE automation_id=? ORDER BY id DESC",
                (a["id"],)
            ).fetchall()
            a["history"] = [{"time": rr["run_time"], "status": rr["status"], "result": (rr["reply"] or rr["error"] or "")} for rr in runs]
            result.append(a)
        return result
    finally:
        conn.close()


def automation_save(item: dict):
    """保存/更新自动化任务"""
    conn = _get_conn()
    try:
        conn.execute(
            """INSERT OR REPLACE INTO naixi_automations 
               (id, name, prompt, schedule_type, rrule, scheduled_at, status, model, 
                last_run, valid_from, valid_until, updated_at,
                workflow_id, trigger_type, config, description, last_result)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'),
                       ?, ?, ?, ?, ?)""",
            (item.get("id", ""), item.get("name", ""), item.get("prompt", ""),
             item.get("schedule_type", "once"), item.get("rrule", ""),
             item.get("scheduled_at", ""), item.get("status", "active"),
             item.get("model", ""), item.get("last_run", ""),
             item.get("valid_from", ""), item.get("valid_until", ""),
             item.get("workflow_id", ""), item.get("trigger_type", "schedule"),
             item.get("config", ""), item.get("description", ""),
             item.get("last_result", ""))
        )
        conn.commit()
    finally:
        conn.close()


def automation_toggle(id: str):
    """切换启用/暂停"""
    conn = _get_conn()
    try:
        row = conn.execute("SELECT status FROM naixi_automations WHERE id=?", (id,)).fetchone()
        if not row:
            return
        new_status = "paused" if row["status"] == "active" else "active"
        conn.execute("UPDATE naixi_automations SET status=?, updated_at=datetime('now') WHERE id=?", (new_status, id))
        conn.commit()
    finally:
        conn.close()


def automation_delete(id: str):
    """删除自动化及执行记录"""
    conn = _get_conn()
    try:
        conn.execute("DELETE FROM naixi_automation_runs WHERE automation_id=?", (id,))
        conn.execute("DELETE FROM naixi_automations WHERE id=?", (id,))
        conn.commit()
    finally:
        conn.close()


def automation_delete_run(run_id: int):
    """删除单条执行记录"""
    conn = _get_conn()
    try:
        conn.execute("DELETE FROM naixi_automation_runs WHERE id=?", (run_id,))
        conn.commit()
    finally:
        conn.close()


def workflow_delete_run(run_id: str):
    """删除单条工作流执行记录"""
    conn = _get_conn()
    try:
        conn.execute("DELETE FROM workflow_runs WHERE id=?", (run_id,))
        conn.commit()
    finally:
        conn.close()


def automation_add_run(auto_id: str, status: str, prompt: str = "", reply: str = "", error: str = "", model_used: str = "", duration_ms: int = 0):
    """记录自动化执行"""
    conn = _get_conn()
    try:
        conn.execute(
            "INSERT INTO naixi_automation_runs (automation_id, run_time, status, prompt, reply, error, model_used, duration_ms) VALUES (?, datetime('now', 'localtime'), ?, ?, ?, ?, ?, ?)",
            (auto_id, status, prompt, reply, error, model_used, duration_ms)
        )
        conn.execute("UPDATE naixi_automations SET last_run=datetime('now', 'localtime'), last_result=?, updated_at=datetime('now') WHERE id=?", (status, auto_id))
        conn.commit()
    finally:
        conn.close()


def automation_get(id: str) -> dict | None:
    """获取单个自动化"""
    conn = _get_conn()
    try:
        row = conn.execute("SELECT * FROM naixi_automations WHERE id=?", (id,)).fetchone()
        if not row:
            return None
        a = dict(row)
        runs = conn.execute(
            "SELECT * FROM naixi_automation_runs WHERE automation_id=? ORDER BY id DESC",
            (a["id"],)
        ).fetchall()
        a["history"] = [{"time": rr["run_time"], "status": rr["status"], "result": (rr["reply"] or rr["error"] or "")} for rr in runs]
        return a
    finally:
        conn.close()


def automation_get_active() -> list[dict]:
    """获取所有激活的自动化（含有效期检查）"""
    import time
    now = time.strftime("%Y-%m-%d %H:%M")
    conn = _get_conn()
    try:
        rows = conn.execute(
            "SELECT * FROM naixi_automations WHERE status='active' ORDER BY created_at"
        ).fetchall()
        result = []
        for r in rows:
            a = dict(r)
            # 有效期检查
            vf, vu = a.get("valid_from", ""), a.get("valid_until", "")
            if vf and vf > now:
                continue
            if vu and vu < now:
                continue
            result.append(a)
        return result
    finally:
        conn.close()


# ── VTS 风格全局热键 ──

# 默认种子：VTS 常见用法（语义标签对应 avatarDriver 的 ACTION/EMOTION 关键词）
_HOTKEY_DEFAULTS = [
    ("f1", "expression", "惊讶"),
    ("f2", "expression", "害羞"),
    ("f3", "expression", "生气"),
    ("f4", "motion", "wave"),
    ("f5", "motion", "nod"),
    ("f6", "motion", "think"),
    ("f7", "motion", "shake"),
    ("ctrl+shift+h", "motion", "smile"),
]


def hotkey_seed_defaults():
    """首次启动写入默认热键（幂等：已有数据则跳过）"""
    conn = _get_conn()
    try:
        cnt = conn.execute("SELECT COUNT(*) AS c FROM hotkeys").fetchone()["c"]
        if cnt > 0:
            return
        for combo, kind, label in _HOTKEY_DEFAULTS:
            conn.execute(
                "INSERT OR IGNORE INTO hotkeys (id, combo, kind, label, enabled, created_at) VALUES (?, ?, ?, ?, 1, datetime('now'))",
                (_hotkey_id(combo), combo, kind, label)
            )
        conn.commit()
    finally:
        conn.close()


def _hotkey_id(combo: str) -> str:
    import hashlib
    return "hk_" + hashlib.md5(combo.encode()).hexdigest()[:12]


def hotkey_list() -> list[dict]:
    conn = _get_conn()
    try:
        rows = conn.execute(
            "SELECT id, combo, kind, label, enabled FROM hotkeys ORDER BY created_at"
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def hotkey_save(combo: str, kind: str, label: str, enabled: int = 1) -> dict:
    """新增或更新热键（combo 唯一）。返回最终记录。"""
    combo = (combo or "").strip().lower()
    kind = (kind or "motion").strip().lower()
    label = (label or "").strip()
    if not combo or not label:
        raise ValueError("combo 与 label 不能为空")
    if kind not in ("motion", "expression"):
        kind = "motion"
    hid = _hotkey_id(combo)
    conn = _get_conn()
    try:
        conn.execute(
            "INSERT OR REPLACE INTO hotkeys (id, combo, kind, label, enabled, created_at) VALUES (?, ?, ?, ?, ?, datetime('now'))",
            (hid, combo, kind, label, enabled)
        )
        conn.commit()
        row = conn.execute("SELECT id, combo, kind, label, enabled FROM hotkeys WHERE id=?", (hid,)).fetchone()
        return dict(row)
    finally:
        conn.close()


def hotkey_delete(hid: str):
    conn = _get_conn()
    try:
        conn.execute("DELETE FROM hotkeys WHERE id=?", (hid,))
        conn.commit()
    finally:
        conn.close()


def hotkey_get_active_map() -> dict:
    """返回 combo(小写) -> {kind,label} 的活跃映射，供监听器快速查表。"""
    conn = _get_conn()
    try:
        rows = conn.execute("SELECT combo, kind, label FROM hotkeys WHERE enabled=1").fetchall()
        return {r["combo"].lower(): {"kind": r["kind"], "label": r["label"]} for r in rows}
    finally:
        conn.close()
