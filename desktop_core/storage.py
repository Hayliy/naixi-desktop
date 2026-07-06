"""桌面端存储 — 独立 SQLite 封装，不含 QQ 机器人数据表"""
import os, sqlite3, json, logging, base64, subprocess, hashlib

log = logging.getLogger("desktop")

# DB 路径由外层 naixi_api.py 在导入前设置
DB_PATH = ""

# ── API Key 加密 ──
_ENCRYPT_PREFIX = "enc:"
_FERNET_KEY_CACHE = None

def _get_fernet_key() -> bytes:
    """从机器唯一标识派生 Fernet 加密密钥"""
    global _FERNET_KEY_CACHE
    if _FERNET_KEY_CACHE:
        return _FERNET_KEY_CACHE

    try:
        # 取 Windows 机器 UUID（每台机器唯一）
        r = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             "Get-CimInstance -Class Win32_ComputerSystemProduct | Select-Object -ExpandProperty UUID"],
            capture_output=True, text=True, timeout=5
        )
        mid = r.stdout.strip()
    except:
        mid = ""
    
    if not mid or len(mid) < 10:
        # 回退：取 MAC 地址
        try:
            r = subprocess.run(
                ["powershell", "-NoProfile", "-Command",
                 "Get-NetAdapter | Where-Object {$_.Status -eq 'Up'} | Select-Object -First 1 -ExpandProperty MacAddress"],
                capture_output=True, text=True, timeout=5
            )
            mid = r.stdout.strip().replace("-", "")
        except:
            mid = ""

    if not mid or len(mid) < 8:
        # 最终回退
        mid = "NAIXI-DESKTOP-FALLBACK"

    raw_key = hashlib.sha256(f"naixi-v1::{mid}".encode()).digest()
    _FERNET_KEY_CACHE = base64.urlsafe_b64encode(raw_key[:32])
    return _FERNET_KEY_CACHE


def encrypt_api_key(plain: str) -> str:
    """加密 API Key，返回带前缀的密文"""
    if not plain:
        return ""
    try:
        from cryptography.fernet import Fernet
        f = Fernet(_get_fernet_key())
        return _ENCRYPT_PREFIX + f.encrypt(plain.encode()).decode()
    except Exception:
        log.warning("加密 API Key 失败，回退到明文")
        return plain


def decrypt_api_key(cipher: str) -> str:
    """解密 API Key"""
    if not cipher:
        return ""
    if not cipher.startswith(_ENCRYPT_PREFIX):
        return cipher  # 未加密的旧数据，原样返回
    try:
        from cryptography.fernet import Fernet, InvalidToken
        f = Fernet(_get_fernet_key())
        return f.decrypt(cipher[len(_ENCRYPT_PREFIX):].encode()).decode()
    except InvalidToken:
        log.warning("API Key 解密失败（密钥不匹配），返回空")
        return ""
    except Exception as e:
        log.warning(f"API Key 解密异常: {e}")
        return cipher  # 安全回退


def encrypt_config(config: dict) -> dict:
    """对整个配置中的 api_providers 做密钥加密（原地修改）"""
    providers = config.get("api_providers", {})
    for k, v in providers.items():
        if "api_key" in v and v["api_key"]:
            v["api_key"] = encrypt_api_key(v["api_key"])
    return config


def decrypt_config(config: dict) -> dict:
    """对整个配置中的 api_providers 做密钥解密（原地修改）"""
    providers = config.get("api_providers", {})
    for k, v in providers.items():
        if "api_key" in v and v["api_key"]:
            v["api_key"] = decrypt_api_key(v["api_key"])
    return config

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
        """)
        conn.commit()
    finally:
        conn.close()

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
            "SELECT id, role, content, content_blocks, time FROM conv_messages WHERE conv_key=? ORDER BY id ASC",
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
