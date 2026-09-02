"""跨会话记忆 — SQLite 持久化 + 语义关键词检索"""
import json, logging, time
from desktop_core.storage import meta_get, meta_set

log = logging.getLogger("memory")

class MemoryManager:
    """管理跨会话的记忆存储和召回"""

    MEMORY_KEY = "agent_memory_store"

    def __init__(self, max_entries=50):
        self.max_entries = max_entries
        self._cache = None  # 延迟加载

    def _load(self) -> list:
        if self._cache is not None:
            return self._cache
        raw = meta_get(self.MEMORY_KEY)
        self._cache = json.loads(raw) if raw else []
        return self._cache

    def _save(self, data: list):
        self._cache = data
        # 裁剪到上限
        if len(data) > self.max_entries:
            data = data[-self.max_entries:]
        meta_set(self.MEMORY_KEY, json.dumps(data, ensure_ascii=False))

    def add(self, key: str, content: str, category: str = "general"):
        """添加一条记忆"""
        entries = self._load()
        entry = {
            "key": key,
            "content": content[:500],
            "category": category,
            "time": time.time(),
        }
        entries.append(entry)
        self._save(entries)

    def recall(self, query: str, max_results: int = 5) -> list:
        """关键词检索记忆"""
        entries = self._load()
        if not entries:
            return []
        query_lower = query.lower()
        # 字符遍历分词（等价原 [\w\u4e00-\u9fff]+，避免正则）
        keywords = set()
        _buf = []
        for _ch in query_lower:
            if _ch.isalnum() or _ch == '_' or '\u4e00' <= _ch <= '\u9fff':
                _buf.append(_ch)
            else:
                if _buf:
                    keywords.add(''.join(_buf))
                    _buf = []
        if _buf:
            keywords.add(''.join(_buf))
        scored = []
        for e in entries:
            content_lower = e.get("content", "").lower()
            key_lower = e.get("key", "").lower()
            # 关键词匹配评分
            match_count = sum(1 for kw in keywords if kw in content_lower or kw in key_lower)
            if match_count > 0:
                scored.append((match_count, e))
        scored.sort(key=lambda x: -x[0])
        return [e for _, e in scored[:max_results]]

    def recall_by_key(self, key: str) -> list:
        """按 key 精确召回"""
        entries = self._load()
        return [e for e in entries if e.get("key") == key]

    def get_recent_context(self, max_items: int = 5) -> str:
        """获取近期记忆的摘要文本"""
        entries = self._load()
        if not entries:
            return ""
        recent = entries[-max_items:]
        lines = []
        for e in recent:
            lines.append(f"[{e.get('category')}] {e.get('content', '')[:100]}")
        return "\n".join(lines)

    def clear(self, category: str = None):
        """清除记忆，可指定分类"""
        if category:
            entries = self._load()
            self._save([e for e in entries if e.get("category") != category])
        else:
            self._save([])
