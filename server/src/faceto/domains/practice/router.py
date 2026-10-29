"""practice 域 —— 计划、作答、进度（支撑界面：S3 计划 / S4 刷题）。

★ 核心写路径（§6.3）：
  POST /answers → ① 幂等检查 ② 客观题本地判分 ③ 异步 AI 点评（问答题）④ 202
  作答进度读内存计数（生产 Redis plan:progress:{plan_id}）；
  判分完成发领域事件 answer.graded → profile 域消费更新掌握度。
"""
from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel, Field

from ...core.security import get_current_user, get_owned_resource, rate_limit
from ...core.store import next_id, now
from ...ai.llm import mock_answer_review

router = APIRouter(tags=["practice"])


# ------------------------------------------------------------------ S3 计划

class PlanCreateIn(BaseModel):
    days: int = Field(default=7, ge=1, le=30)


@router.post("/jobs/{job_id}/plans", status_code=201)
async def create_plan(job_id: int, body: PlanCreateIn, request: Request,
                      user: dict = Depends(get_current_user)):
    """同步骨架 + 异步选题（§4.2）。dev 中骨架即完整结构（题库内存直查）。"""
    store = request.app.state.store
    job = get_owned_resource(store.jobs.get(job_id), user["id"], "JOB_NOT_FOUND")
    if job["parse_status"] != "done" or not store.job_points.get(job_id):
        raise HTTPException(409, {"code": "JOB_NOT_PARSED", "message": "岗位画像未就绪，无法生成计划"})

    points = sorted(store.job_points[job_id], key=lambda p: p["weight"], reverse=True)
    pid = next_id()
    store.plans[pid] = {"id": pid, "user_id": user["id"], "job_id": job_id,
                        "days": body.days, "status": "active", "dirty": False, "created_at": now()}

    # 按权重轮转分日：权重高的考点占据每天的核心模块
    items: list[dict] = []
    day_points = _split_days(points, body.days)
    for day_no, pts in enumerate(day_points, start=1):
        for p in pts:
            # 该考点在题库中的可用题量（客观+主观）
            available = [q for q in store.questions.values() if p["point_name"] in q["points"]]
            qcount = max(1, min(len(available), 3 if p["weight"] >= 15 else 2))
            items.append({"id": next_id(), "plan_id": pid, "day_no": day_no,
                          "module": f"第{day_no}天 · {p['point_name']}", "point_name": p["point_name"],
                          "question_count": qcount, "done_count": 0})
    store.plan_items[pid] = items
    return {"plan_id": pid, "days": body.days, "modules": len(items)}


def _split_days(points: list[dict], days: int) -> list[list[dict]]:
    """蛇形分日：权重从高到低往返排列，保证每天既有重点也有补弱。"""
    buckets: list[list[dict]] = [[] for _ in range(days)]
    for i, p in enumerate(points):
        day = i // 2 if i // 2 < days else (i % days)
        buckets[min(day, days - 1)].append(p)
    return [b for b in buckets if b] or [points]


@router.get("/plans/{plan_id}")
async def get_plan(plan_id: int, request: Request, user: dict = Depends(get_current_user)):
    store = request.app.state.store
    plan = get_owned_resource(store.plans.get(plan_id), user["id"], "PLAN_NOT_FOUND")
    items = store.plan_items.get(plan_id, [])
    days = []
    for day_no in sorted({i["day_no"] for i in items}):
        day_items = [i for i in items if i["day_no"] == day_no]
        days.append({"day_no": day_no,
                     "done": sum(i["done_count"] for i in day_items),
                     "total": sum(i["question_count"] for i in day_items),
                     "modules": day_items})
    return {**plan, "day_blocks": days}


@router.get("/plans/{plan_id}/progress")
async def get_progress(plan_id: int, request: Request, user: dict = Depends(get_current_user)):
    """进度直读计数（生产 Redis Hash，不落库查询，§5.3）。"""
    store = request.app.state.store
    get_owned_resource(store.plans.get(plan_id), user["id"], "PLAN_NOT_FOUND")
    items = store.plan_items.get(plan_id, [])
    total = sum(i["question_count"] for i in items)
    done = sum(i["done_count"] for i in items)
    per_day = {}
    for i in items:
        d = per_day.setdefault(i["day_no"], {"done": 0, "total": 0})
        d["done"] += i["done_count"]; d["total"] += i["question_count"]
    return {"plan_id": plan_id, "done": done, "total": total,
            "percent": round(done / total * 100) if total else 0, "per_day": per_day}


# ------------------------------------------------------------------ S4 刷题

@router.get("/plans/{plan_id}/next")
async def next_question(plan_id: int, request: Request, user: dict = Depends(get_current_user)):
    """下一题（含考点溯源信息）：优先返回未完成模块的题目，同模块内轮转。"""
    store = request.app.state.store
    plan = get_owned_resource(store.plans.get(plan_id), user["id"], "PLAN_NOT_FOUND")
    items = store.plan_items.get(plan_id, [])
    pending = [i for i in items if i["done_count"] < i["question_count"]]
    if not pending:
        return {"done": True, "question": None}
    # 优先当天顺序中最靠前的未完成模块
    item = pending[0]
    pool = [q for q in store.questions.values()
            if item["point_name"] in q["points"] and q["status"] == "active"]
    answered_ids = {a["question_id"] for a in store.answers.values()
                    if a["user_id"] == user["id"] and a["plan_id"] == plan_id}
    fresh = [q for q in pool if q["id"] not in answered_ids]
    q = (fresh or pool)[len(answered_ids) % len(pool)] if pool else None
    if not q:
        return {"done": True, "question": None, "reason": "题库覆盖不足"}

    # 复用 question 域的详情组装（跨域只调 service 接口，§3.3）
    from ..question.router import get_question
    detail = await get_question(q["id"], request, job_id=plan["job_id"], user=user)
    return {"done": False, "question": detail,
            "module": item["module"], "point_name": item["point_name"],
            "remaining_in_module": item["question_count"] - item["done_count"]}


class AnswerIn(BaseModel):
    question_id: int
    plan_id: int
    user_answer: Any = None
    self_rating: int = Field(default=3, ge=1, le=5)
    idempotency_key: str = Field(min_length=4, max_length=64)


@router.post("/answers", status_code=202)
async def submit_answer(body: AnswerIn, request: Request,
                        user: dict = Depends(get_current_user),
                        idempotency_key_header: str = Header(None, alias="Idempotency-Key")):
    """★ 核心写路径（§6.3）：幂等 + 客观同步判分 + 主观异步点评。"""
    store = request.app.state.store
    settings = request.app.state.settings
    rate_limit(f"answers:{user['id']}", settings.ANSWER_RATE_PER_MIN)   # §8.1 单用户 30/min

    idem = idempotency_key_header or body.idempotency_key
    key = (user["id"], idem)
    if key in store.answer_idem:                                        # ① 幂等（分片内唯一 §5.7）
        aid = store.answer_idem[key]
        return {"answer_id": aid, "duplicate": True, **_answer_view(store.answers[aid])}

    q = store.questions.get(body.question_id)
    if not q:
        raise HTTPException(404, {"code": "QUESTION_NOT_FOUND", "message": "题目不存在"})
    plan = get_owned_resource(store.plans.get(body.plan_id), user["id"], "PLAN_NOT_FOUND")

    aid = next_id()
    is_correct = None
    correct_answer = analysis = None

    if q["type"] in ("single", "multi"):
        # ② 客观题本地判分（生产也不依赖任何外部调用 —— 核心不等式 §0）
        ua = body.user_answer if isinstance(body.user_answer, list) else (
            [body.user_answer] if body.user_answer is not None else [])
        is_correct = sorted(map(str, ua)) == sorted(map(str, q["answer"] or []))
        correct_answer = q["answer"]
        analysis = q["analysis"]
        ai_status = "skipped"
    else:
        ai_status = "queued" if not settings.degrade["ai_review"] else "degraded"

    answer = {
        "id": aid, "user_id": user["id"], "plan_id": body.plan_id, "question_id": q["id"],
        "question_snapshot": {"stem": q["stem"], "type": q["type"], "points": q["points"]},
        "user_answer": body.user_answer, "is_correct": is_correct, "self_rating": body.self_rating,
        "ai_review": None, "ai_review_status": ai_status,
        "idempotency_key": idem, "created_at": now(),
    }
    store.answers[aid] = answer
    store.answer_idem[key] = aid

    # 进度计数 +1（生产：Redis 计数先行，Kafka 合并落库 <1s 最终一致 §13-#3）
    for item in store.plan_items.get(body.plan_id, []):
        if item["point_name"] in q["points"] and item["done_count"] < item["question_count"]:
            item["done_count"] += 1
            break

    # 领域事件：answer.graded → profile 域消费（跨域写只走事件 §3.3）
    await store.bus.publish("answer.graded", {
        "user_id": user["id"], "question_id": q["id"], "points": q["points"],
        "is_correct": is_correct, "reason": "answer"})

    # ③ 问答题：异步 AI 点评（任务表占位 → 后台执行，对应 Kafka answer.grade）
    task_id = None
    eta = 0
    if ai_status == "queued":
        tid = next_id()
        task_id = tid
        eta = 4

        async def _review(payload: dict) -> dict:
            return mock_answer_review(q, str(body.user_answer or ""))

        store.ai_tasks[tid] = {
            "id": tid, "user_id": user["id"], "task_type": "answer_review",
            "payload": {"answer_id": aid}, "result": None, "status": "queued",
            "model_used": "mock-llm", "tokens_in": len(str(body.user_answer)) // 2,
            "tokens_out": 768, "cost_cents": 2, "attempts": 0, "created_at": now(),
        }
        asyncio.create_task(_run_review(store, tid, aid, settings))

    return {"answer_id": aid, "duplicate": False,
            "is_correct": is_correct, "correct_answer": correct_answer, "analysis": analysis,
            "ai_review_status": ai_status, "task_id": task_id, "eta_seconds": eta}


async def _run_review(store, tid: int, aid: int, settings) -> None:
    task = store.ai_tasks[tid]
    await asyncio.sleep(settings.LLM_REVIEW_DELAY)
    task["status"] = "running"; task["attempts"] += 1
    try:
        ans = store.answers.get(aid)
        if not ans:
            raise RuntimeError("answer gone")
        q = store.questions[ans["question_id"]]
        review = mock_answer_review(q, str(ans["user_answer"] or ""))
        ans["ai_review"] = review
        ans["ai_review_status"] = "done"
        task["result"] = {"score": review["score"]}
        task["status"] = "done"
        await store.bus.publish("answer.graded", {
            "user_id": ans["user_id"], "question_id": ans["question_id"],
            "points": q["points"], "is_correct": None, "reason": "review",
            "score": review["score"]})
    except Exception as exc:
        task["status"] = "failed"; task["result"] = {"error": str(exc)}
        ans = store.answers.get(aid)
        if ans:
            ans["ai_review_status"] = "failed"


@router.get("/answers/{answer_id}/review")
async def get_review(answer_id: int, request: Request, user: dict = Depends(get_current_user)):
    """AI 点评结果；未就绪返回 202 + retry_after（轮询兜底 §6.4）。"""
    store = request.app.state.store
    ans = get_owned_resource(store.answers.get(answer_id), user["id"], "ANSWER_NOT_FOUND")
    if ans["ai_review_status"] in ("done", "degraded", "failed", "skipped"):
        # skipped = 客观题本地判分，本就没有 AI 点评，直接返回终态避免前端空转轮询
        return {"status": ans["ai_review_status"], "review": ans["ai_review"]}
    task = next((t for t in store.ai_tasks.values()
                 if t["task_type"] == "answer_review" and t["payload"].get("answer_id") == answer_id), None)
    retry = 2
    if task:
        pending = sum(1 for t in store.ai_tasks.values()
                      if t["task_type"] == "answer_review" and t["status"] in ("queued", "running"))
        retry = min(max(pending * 2, 1), 30)     # 排队可见化
    return {"status": "queued", "review": None, "retry_after": retry}


def _answer_view(a: dict) -> dict:
    return {"is_correct": a["is_correct"], "ai_review_status": a["ai_review_status"]}
