"""多 Agent 编排 — 主 Agent 拆分子任务并行执行"""
import asyncio, json, logging, time

log = logging.getLogger("orchestrator")

class Orchestrator:
    """将复杂任务拆分为子任务，分发到子 Agent 并行执行"""

    def __init__(self, tool_ctx: dict = None):
        self.tool_ctx = tool_ctx or {}

    async def decompose_and_run(self, task: str, llm_call_fn) -> str:
        """
        1. LLM 分析任务 → 拆分子任务列表
        2. 并行执行子任务
        3. 汇总结果
        """
        # 步骤 1：拆分子任务
        sub_tasks = await self._decompose(task, llm_call_fn)
        if not sub_tasks:
            # 不需要拆分，直接执行
            return None

        log.info(f"[编排] 任务拆分为 {len(sub_tasks)} 个子任务")

        # 步骤 2：并行执行
        results = await asyncio.gather(
            *[self._run_sub_task(st, llm_call_fn) for st in sub_tasks],
            return_exceptions=True
        )

        # 步骤 3：汇总
        summary_parts = [f"## {task}"]
        for i, (st, res) in enumerate(zip(sub_tasks, results)):
            if isinstance(res, Exception):
                summary_parts.append(f"\n### 子任务 {i+1}: {st.get('desc', '')} 失败")
                summary_parts.append(str(res)[:200])
            else:
                summary_parts.append(f"\n### 子任务 {i+1}: {st.get('desc', '')}")
                summary_parts.append(str(res)[:1000])

        return "\n".join(summary_parts)

    async def _decompose(self, task: str, llm_call_fn) -> list:
        """让 LLM 分析任务，返回子任务列表"""
        prompt = (
            f"分析以下任务，如果它包含多个独立可并行执行的子任务，"
            f"拆分为子任务列表（JSON 数组格式）。"
            f"每个子任务包含 desc（描述）和 goal（目标）。"
            f"如果任务很简单不需要拆分，返回空数组 []。\n\n任务：{task}"
        )
        try:
            result = await llm_call_fn([
                {"role": "system", "content": "你是一个任务分解专家。只返回 JSON 数组。"},
                {"role": "user", "content": prompt},
            ])
            # 尝试解析 JSON
            text = result.strip()
            # 找 JSON 块
            import re
            json_match = re.search(r'\[.*?\]', text, re.DOTALL)
            if json_match:
                sub_tasks = json.loads(json_match.group())
                if isinstance(sub_tasks, list) and len(sub_tasks) > 1:
                    return sub_tasks
        except Exception as e:
            log.warning(f"[编排] 分解失败: {e}")
        return []

    async def _run_sub_task(self, sub_task: dict, llm_call_fn) -> str:
        """执行单个子任务"""
        desc = sub_task.get("desc", "")
        goal = sub_task.get("goal", "")
        prompt = f"请完成以下任务：\n{desc}\n目标：{goal}"
        try:
            result = await llm_call_fn([
                {"role": "user", "content": prompt + "\n\n请用工具完成任务，完成后给出总结。"}
            ])
            return str(result)[:2000]
        except Exception as e:
            return f"子任务失败: {str(e)[:200]}"
