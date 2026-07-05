"""桌面端存储 — 独立 SQLite 封装，不含 QQ 机器人数据表"""
import os, sqlite3, json, logging

log = logging.getLogger("desktop")

# DB 路径由外层 naixi_api.py 在导入前设置
DB_PATH = ""

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
        """)
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
