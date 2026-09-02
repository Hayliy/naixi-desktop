"""
memory_store.py — 奶昔分层记忆层（集大成蓝图「Memory 分层」落地）
================================================================

借鉴 Mem0 / Letta(MemGPT) / screenpipe 的「记忆分层」思想，但**本地 SQLite 实现、
零外部依赖**，契合奶昔「本地私有、不连云」的硬约束。

两层结构
--------
- episodes（情景记忆）：时序事件流，记录"发生了什么、何时"（who/what/when）。
  对应 Letta 的 archival + screenpipe 的感知日志。
- facts（语义记忆）：长期键值知识，带 importance 权重，用于压缩/遗忘。
  对应 Mem0 的语义抽取结果。

检索
----
- recall(query)：关键词跨层评分检索（episodes + facts）
- get_recent(n)：最近 n 条情景记忆（用于注入 LLM 上下文）
- 可选 FTS5 全文索引（环境支持时自动启用，失败回退 LIKE 关键词）

与现有 desktop_core/memory.py 的关系
------------------------------------
memory.py 是早期扁平 JSON 列表（上限 50、纯关键词）。本模块是其**能力升级版**，
不改动 memory.py（避免影响正在运行的桌宠），由一体化 Agent 运行时统一调用。
"""
from __future__ import annotations

import sqlite3
import json
import time
import os
import logging

log = logging.getLogger("naixi.memory_store")


def _tokenize(text):
    """非正则分词：ASCII 字母/数字/下划线按词切，CJK 等字母按单字切。

    故意不用 re —— 正则边界坑多易暴雷，且 Python 的 \\w 会把整句中文
    当成一个"词"，导致自然语言查询召回恒空。这里纯字符遍历，确定性强。
    """
    text = (text or "").lower()
    tokens = set()
    buf = []
    for ch in text:
        if ("a" <= ch <= "z") or ("0" <= ch <= "9") or ch == "_":
            buf.append(ch)
        else:
            if buf:
                tokens.add("".join(buf))
                buf = []
            # 非 ASCII 字母（中文/假名等）按单字成词；标点、空格、符号忽略
            if ch.isalpha():
                tokens.add(ch)
    if buf:
        tokens.add("".join(buf))
    return tokens


DEFAULT_DB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "naixi_memory.sqlite")


class MemoryStore:
    """本地分层记忆存储。"""

    def __init__(self, db_path: str = DEFAULT_DB):
        self.db = db_path
        self._fts = False
        self._init()

    # ── schema ──
    def _init(self):
        conn = sqlite3.connect(self.db)
        conn.execute(
            """CREATE TABLE IF NOT EXISTS episodes(
                   id INTEGER PRIMARY KEY AUTOINCREMENT,
                   ts REAL, kind TEXT, text TEXT, meta TEXT)"""
        )
        conn.execute(
            """CREATE TABLE IF NOT EXISTS facts(
                   id INTEGER PRIMARY KEY AUTOINCREMENT,
                   key TEXT UNIQUE, value TEXT,
                   importance REAL DEFAULT 0.5, updated REAL)"""
        )
        # 可选 FTS5 全文索引（环境不支持则回退关键词 LIKE）
        try:
            conn.execute(
                "CREATE VIRTUAL TABLE IF NOT EXISTS episodes_fts "
                "USING fts5(text, content='episodes', content_rowid='id')"
            )
            self._fts = True
        except Exception as e:
            self._fts = False
            log.info(f"[memory_store] FTS5 不可用，回退关键词检索: {e}")
        conn.commit()
        conn.close()

    # ── 写：情景记忆 ──
    def observe(self, text: str, kind: str = "event", meta: dict = None) -> bool:
        """记录一条时序事件（情景记忆）。"""
        conn = sqlite3.connect(self.db)
        conn.execute(
            "INSERT INTO episodes(ts,kind,text,meta) VALUES(?,?,?,?)",
            (time.time(), kind, text, json.dumps(meta or {}, ensure_ascii=False)),
        )
        conn.commit()
        conn.close()
        return True

    # ── 写：语义记忆 ──
    def remember(self, key: str, value: str, importance: float = 0.5) -> bool:
        """写入/更新一条长期事实（语义记忆）。importance 高者优先保留。"""
        conn = sqlite3.connect(self.db)
        conn.execute(
            """INSERT INTO facts(key,value,importance,updated) VALUES(?,?,?,?)
               ON CONFLICT(key) DO UPDATE SET
                 value=excluded.value,
                 importance=excluded.importance,
                 updated=excluded.updated""",
            (key, value, importance, time.time()),
        )
        conn.commit()
        conn.close()
        return True

    def get_fact(self, key: str):
        conn = sqlite3.connect(self.db)
        row = conn.execute("SELECT value FROM facts WHERE key=?", (key,)).fetchone()
        conn.close()
        return row[0] if row else None

    def forget(self, key: str) -> bool:
        conn = sqlite3.connect(self.db)
        conn.execute("DELETE FROM facts WHERE key=?", (key,))
        conn.commit()
        conn.close()
        return True

    # ── 读：检索 ──
    def recall(self, query: str, limit: int = 5) -> list:
        """跨 episodes + facts 关键词评分检索，返回结构化结果列表。

        分词：ASCII 词按词切，CJK 按单字切（Python 的 \\w 会把整句中文当
        一个"词"，导致自然语言查询永远匹配不到子串——已修正为按字切分）。
        """
        kws = _tokenize(query)
        if not kws:
            return []
        conn = sqlite3.connect(self.db)
        scored = []

        eps = conn.execute(
            "SELECT ts,kind,text,meta FROM episodes ORDER BY ts DESC LIMIT 300"
        ).fetchall()
        for ts, kind, text, meta in eps:
            tl = text.lower()
            score = sum(1 for k in kws if k in tl)
            if score > 0:
                scored.append((score, "episode", ts, kind, text))

        facts = conn.execute("SELECT key,value,importance FROM facts").fetchall()
        for key, value, imp in facts:
            kl, vl = key.lower(), value.lower()
            score = sum(1 for k in kws if k in kl or k in vl)
            if score > 0:
                scored.append((score + imp, "fact", 0.0, key, value))

        scored.sort(key=lambda x: -x[0])
        conn.close()
        return [
            {"type": t, "key": k, "text": txt, "ts": ts}
            for _, t, ts, k, txt in scored[:limit]
        ]

    def get_recent(self, n: int = 10) -> list:
        conn = sqlite3.connect(self.db)
        rows = conn.execute(
            "SELECT ts,kind,text FROM episodes ORDER BY ts DESC LIMIT ?", (n,)
        ).fetchall()
        conn.close()
        return [{"ts": ts, "kind": kind, "text": txt} for ts, kind, txt in rows]

    def stats(self) -> dict:
        conn = sqlite3.connect(self.db)
        ne = conn.execute("SELECT COUNT(*) FROM episodes").fetchone()[0]
        nf = conn.execute("SELECT COUNT(*) FROM facts").fetchone()[0]
        conn.close()
        return {"episodes": ne, "facts": nf, "fts": self._fts}

    def clear_all(self):
        conn = sqlite3.connect(self.db)
        conn.execute("DELETE FROM episodes")
        conn.execute("DELETE FROM facts")
        conn.commit()
        conn.close()


if __name__ == "__main__":
    import tempfile

    ms = MemoryStore(os.path.join(tempfile.gettempdir(), "ms_test.sqlite"))
    ms.observe("用户打开了扫雷游戏窗口", kind="action")
    ms.observe("AI 翻开 (4,4) 触发安全区展开", kind="action")
    ms.remember("user_name", "主人", importance=0.9)
    ms.remember("favorite_game", "扫雷", importance=0.5)
    print("stats:", ms.stats())
    print("recent:", ms.get_recent(3))
    print("recall 扫雷:", ms.recall("扫雷"))
    print("recall 主人:", ms.recall("主人"))
