"""main.py —— 组装：只做 include_router + 中间件挂载（§3.2）。"""
from __future__ import annotations

import asyncio
import atexit
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.staticfiles import StaticFiles

from .core.config import settings
from .core.security import get_current_user, hash_password
from .core.store import Store, seed_store, load_snapshot, save_snapshot
from .core import packs
from .core.tasks import TaskManager
from .domains.user.router import router as user_router
from .domains.job.router import router as job_router
from .domains.question.router import router as question_router
from .domains.practice.router import router as practice_router
from .domains.exp.router import router as exp_router
from .domains.interview.router import router as interview_router
from .domains.profile.router import router as profile_router, make_handler as profile_handler
from .domains.quiz.router import router as quiz_router


async def _flush_loop(store: Store, path: Path, interval: float) -> None:
    """周期落盘：内存仍是权威副本，这里只做「尽量新」的快照。"""
    while True:
        await asyncio.sleep(interval)
        try:
            save_snapshot(store, path)
        except Exception as exc:                       # 落盘失败绝不拖垮主链路
            print(f"[store] 落盘失败：{exc}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    store = app.state.store
    restored = False
    if settings.STORE_PERSIST:
        restored = load_snapshot(store, settings.STORE_PATH)
    seed_store(store, hash_password)                   # 幂等：只补缺失，不打乱已有 ID
    packs.seed_packs()                                 # 刷题中心：内置题库包缺失时写入
    store.heal_after_restore()
    print(f"[store] {'已从快照恢复' if restored else '无快照，使用种子数据'} · "
          f"users={len(store.users)} jobs={len(store.jobs)} questions={len(store.questions)} "
          f"answers={len(store.answers)} → {settings.STORE_PATH if settings.STORE_PERSIST else '（持久化已关闭）'}")

    flusher = None
    if settings.STORE_PERSIST:
        flusher = asyncio.create_task(_flush_loop(store, settings.STORE_PATH, settings.STORE_FLUSH_INTERVAL))
        atexit.register(_shutdown_save, store, settings.STORE_PATH)   # SIGKILL 之外的兜底
    try:
        yield
    finally:
        if flusher:
            flusher.cancel()
        if settings.STORE_PERSIST:
            _shutdown_save(store, settings.STORE_PATH)


def _shutdown_save(store: Store, path: Path) -> None:
    try:
        save_snapshot(store, path)
        print(f"[store] 退出落盘完成 · answers={len(store.answers)} → {path}")
    except Exception as exc:
        print(f"[store] 退出落盘失败：{exc}")


app = FastAPI(title=settings.APP_NAME, version="1.0.0-mvp", lifespan=lifespan)

# ---------------- 应用状态（生产：连接池/客户端注入同一位置） ----------------
app.state.settings = settings
app.state.store = Store()
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
          exp_router, interview_router, profile_router, quiz_router):
    app.include_router(r, prefix=settings.API_PREFIX)

# ---------------- 前端静态资源（五屏 SPA） ----------------
_web_dir = Path(__file__).resolve().parents[2] / "web"


# 刷题独立页：显式注册在 mount 之前，保证 /quiz 不会被 StaticFiles 吞掉
@app.get("/quiz", include_in_schema=False)
async def quiz_page():
    from fastapi.responses import FileResponse
    return FileResponse(_web_dir / "quiz.html", media_type="text/html")


@app.middleware("http")
async def no_cache_static(request: Request, call_next):
    """前端静态资源禁用浏览器缓存（dev 体验）。

    踩过的坑：改完 app.js 刷新页面仍是旧逻辑，排查成本远高于这点性能损耗。
    生产应改为「文件名带内容哈希 + 长期缓存」，届时删除本中间件。
    """
    response = await call_next(request)
    if request.url.path.endswith((".js", ".css", ".html")) or request.url.path == "/":
        response.headers["Cache-Control"] = "no-store, must-revalidate"
    return response


app.mount("/", StaticFiles(directory=str(_web_dir), html=True), name="web")
