"""上下文管理器 — 3 级压缩防止 Token 超限"""
import json, logging, re

log = logging.getLogger("context")

class ContextManager:
    """管理 Agent 对话上下文的长度和压缩"""

    def __init__(self, max_tokens=32000, max_tool_output=3000):
        self.max_tokens = max_tokens
        self.max_tool_output = max_tool_output  # 单条工具输出最大字符数

    def estimate_tokens(self, messages: list) -> int:
        """粗略估算消息列表的总 Token 数（中文约 1.5 char/token，英文约 4 char/token）"""
        total = 0
        for msg in messages:
            content = msg.get("content", "")
            if isinstance(content, str):
                total += len(content) * 1.2  # 混合估算
            elif isinstance(content, list):
                for part in content:
                    if isinstance(part, dict):
                        total += len(str(part.get("text", ""))) * 1.2
            # 系统消息 + 角色开销
            total += 4
        return int(total)

    def compress(self, messages: list) -> list:
        """3 级压缩：修剪 → 截断工具输出 → 折叠"""
        msgs = list(messages)
        while self.estimate_tokens(msgs) > self.max_tokens and len(msgs) > 3:
            compressed = self._compress_pass(msgs)
            if len(compressed) >= len(msgs):
                break  # 无法进一步压缩
            msgs = compressed
        return msgs

    def _compress_pass(self, messages: list) -> list:
        """执行一轮压缩"""
        msgs = list(messages)

        # 1 级：裁剪过长的工具输出
        for i, msg in enumerate(msgs):
            if msg.get("role") == "tool" and len(msg.get("content", "")) > self.max_tool_output:
                content = msg["content"]
                msgs[i] = {**msg, "content": content[:self.max_tool_output] + f"\n...（原始 {len(content)} 字符，已截断）"}

        # 2 级：折叠旧的 tool_use/tool_result 对（保留第一条和最新的几条）
        tool_pairs = []
        i = 0
        while i < len(msgs):
            if msgs[i].get("role") == "assistant" and "tool_calls" in msgs[i]:
                pair_start = i
                i += 1
                while i < len(msgs) and msgs[i].get("role") == "tool":
                    i += 1
                tool_pairs.append((pair_start, i))
            else:
                i += 1

        # 保留最近 3 对工具调用，删除之前的
        if len(tool_pairs) > 3:
            # 保留第一对（可能是上下文关键）和最近 2 对
            keep = {0}  # 第一对（索引在 tool_pairs 中）
            for idx in range(len(tool_pairs) - 2, len(tool_pairs)):
                keep.add(idx)
            to_remove = []
            for idx, (start, end) in enumerate(tool_pairs):
                if idx not in keep:
                    to_remove.extend(range(start, end))
            # 从后往前删（保持索引正确）
            for idx in sorted(to_remove, reverse=True):
                if idx < len(msgs):
                    msgs.pop(idx)

        return msgs

    def should_compress(self, messages: list) -> bool:
        """检查是否需要压缩"""
        return self.estimate_tokens(messages) > self.max_tokens * 0.8
