"""main.py —— 组装：只做 include_router + 中间件挂载（§3.2）。"""
from __future__ import annotations

from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.staticfiles import StaticFiles

from .core.config import settings
from .core.security import get_current_user
from .core.store import Store, seed_store
from .core.tasks import TaskManager
from .core.security import hash_password
from .domains.user.router import router as user_router
from .domains.job.router import router as job_router
from .domains.question.router import router as question_router
from .domains.practice.router import router as practice_router
from .domains.exp.router import router as exp_router
from .domains.interview.router import router as interview_router
from .domains.profile.router import router as profile_router, make_handler as profile_handler

app = FastAPI(title=settings.APP_NAME, version="1.0.0-mvp")

# ---------------- 应用状态（生产：连接池/客户端注入同一位置） ----------------
app.state.settings = settings
app.state.store = Store()
seed_store(app.state.store, hash_password)
app.state.tasks = TaskManager(app.state.store)

# 领域事件挂接：answer.graded → profile 域掌握度更新（跨域只走事件 §3.3）
app.state.store.bus.subscribe("answer.graded", profile_handler(app.state.store))


# ---------------- 通用任务状态（§4.2：所有 AI 任务统一查询，轮询兜底） ----------------
@app.get(f"{settings.API_PREFIX}/tasks/{{task_id}}")
async def get_task(task_id: int, request: Request, user: dict = Depends(get_current_user)):
    t = app.state.tasks.get(task_id, user["id"])
    if not t:
        raise HTTPException(404, {"code": "TASK_NOT_FOUND", "message": "任务不存在"})
    pending = sum(1 for x in app.state.store.ai_tasks.values()
                  if x["task_type"] == t["task_type"] and x["status"] in ("queued", "running"))
    return {"id": t["id"], "task_type": t["task_type"], "status": t["status"],
            "result": t["result"], "eta_seconds": min(pending * 2, 60)}


@app.get("/api/health")
async def health():
    return {"ok": True, "service": settings.APP_NAME}


# ---------------- 路由挂载 ----------------
for r in (user_router, job_router, question_router, practice_router,
          exp_router, interview_router, profile_router):
    app.include_router(r, prefix=settings.API_PREFIX)

# ---------------- 前端静态资源（五屏 SPA） ----------------
_web_dir = Path(__file__).resolve().parents[2] / "web"
app.mount("/", StaticFiles(directory=str(_web_dir), html=True), name="web")
