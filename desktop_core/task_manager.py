"""任务管理器 — Agent 的任务分解、追踪和错误恢复"""
import json, logging, time

log = logging.getLogger("task")

class Task:
    def __init__(self, task_id, description, steps=None):
        self.id = task_id
        self.description = description
        self.steps = steps or []
        self.status = "pending"  # pending | running | done | failed
        self.current_step = 0
        self.result = ""
        self.created_at = time.time()

    def to_dict(self):
        return {
            "id": self.id,
            "description": self.description[:80],
            "status": self.status,
            "current_step": self.current_step,
            "total_steps": len(self.steps),
            "steps": [{"desc": s.get("desc", "")[:50], "status": s.get("status", "pending")} for s in self.steps],
        }

class TaskManager:
    """任务管理器：分解复杂请求为子任务，追踪进度，错误恢复"""

    def __init__(self, max_concurrent=3):
        self._tasks = {}
        self._max_concurrent = max_concurrent

    def create_task(self, description, steps=None):
        tid = f"task_{int(time.time())}"
        task = Task(tid, description, steps or [])
        self._tasks[tid] = task
        return task

    def update_step(self, task_id, index, status, result=""):
        task = self._tasks.get(task_id)
        if not task:
            return
        if 0 <= index < len(task.steps):
            task.steps[index]["status"] = status
            if result:
                task.steps[index]["result"] = result[:200]
            task.current_step = index

    def get_task(self, task_id):
        return self._tasks.get(task_id)

    def summarize(self):
        """返回所有任务摘要（用于注入 LLM 上下文）"""
        if not self._tasks:
            return ""
        lines = ["【当前任务进度】"]
        for tid, task in self._tasks.items():
            done = sum(1 for s in task.steps if s.get("status") == "done")
            total = len(task.steps)
            lines.append(f"- {task.description[:50]}: {done}/{total} 完成")
        return "\n".join(lines)

# 全局单例
_manager = TaskManager()

def get_manager():
    return _manager
