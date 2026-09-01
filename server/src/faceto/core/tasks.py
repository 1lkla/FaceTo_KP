"""异步任务层（§6）：统一 AI 任务表 + 排队可见化。

★ 生产替换点（§6.1/§6.4）：
- submit() 对应「先插任务表占位，再发 Kafka」；
- 后台协程对应 ai_worker 进程（令牌桶并发控制）；
- 任务状态查询 GET /tasks/{id} 是前端轮询兜底，主通道为 SSE。
"""
from __future__ import annotations

import asyncio
import time
from typing import Any, Awaitable, Callable

from .store import Store, next_id, now


class TaskManager:
    def __init__(self, store: Store) -> None:
        self.store = store

    def submit(self, user_id: int, task_type: str, payload: dict,
               runner: Callable[[dict], Awaitable[dict]], delay: float) -> dict:
        """创建任务并异步执行。幂等键 = 业务侧（如 answer_id）在调用前检查。"""
        task_id = next_id()
        task = {
            "id": task_id, "user_id": user_id, "task_type": task_type, "payload": payload,
            "status": "queued", "result": None, "model_used": "mock-llm",
            "tokens_in": 0, "tokens_out": 0, "cost_cents": 0,           # §6.6 成本字段从第一天就有
            "attempts": 0, "created_at": now(),
        }
        self.store.ai_tasks[task_id] = task

        async def _run() -> None:
            await asyncio.sleep(delay)
            task["status"] = "running"
            task["attempts"] += 1
            try:
                task["result"] = await runner(payload)
                task["status"] = "done"
            except Exception as exc:
                task["status"] = "failed"
                task["result"] = {"error": str(exc)}

        asyncio.create_task(_run())
        return task

    def get(self, task_id: int, user_id: int) -> dict | None:
        t = self.store.ai_tasks.get(task_id)
        if not t or t["user_id"] != user_id:
            return None
        return t

    def eta_seconds(self, task_type: str) -> int:
        """排队可见化（§6.4）：按同类任务堆积量估计等待时间。"""
        pending = sum(1 for t in self.store.ai_tasks.values()
                      if t["task_type"] == task_type and t["status"] in ("queued", "running"))
        return min(pending * 2, 60)
