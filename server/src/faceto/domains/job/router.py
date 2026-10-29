"""job 域 —— JD 管理、考点权重、画像（支撑界面：S1 导入 / S2 画像）。

写路径走异步任务（§4.2）：POST /jobs → 202 {job_id}，解析完成后画像可查。
"""
from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from ...core.security import get_current_user, get_owned_resource
from ...core.store import next_id, now
from ...core.mastery import compute_match
from ...ai.llm import mock_jd_parse

router = APIRouter(tags=["job"])


class JobCreateIn(BaseModel):
    source: str = Field(pattern="^(text|url|image)$")
    payload: str = Field(min_length=10, max_length=20000)
    title: str = Field(default="", max_length=60)


def _parse_job_text(payload: str) -> tuple[str, str]:
    """url/image 入口在生产的处理：抓取/OCR。M1-dev 直接把 payload 当文本。"""
    if payload.startswith("http"):
        return payload, "（链接内容抓取：M1-dev 直接按原文处理）" + payload
    return payload, ""


async def _run_jd_parse(store, job_id: int, jd_text: str) -> dict:
    """生产：ai_worker 消费 jd.parse topic。dev：模拟 LLM 解析延迟。"""
    points = mock_jd_parse(jd_text)["points"]
    store.job_points[job_id] = points
    store.jobs[job_id]["parse_status"] = "done"
    return {"points": len(points)}


# ------------------------------------------------------------------ S1 导入

@router.post("/jobs", status_code=202)
async def create_job(body: JobCreateIn, request: Request, user: dict = Depends(get_current_user)):
    store = request.app.state.store
    settings = request.app.state.settings
    if settings.degrade["jd_parse"]:                       # §8.3 降级：JD 解析
        raise HTTPException(503, {"code": "JOB_PARSE_DEGRADED", "message": "JD 解析服务繁忙，请稍后再试"})

    jd_text, note = _parse_job_text(body.payload)
    jid = next_id()
    store.jobs[jid] = {
        "id": jid, "user_id": user["id"],
        "title": body.title or _guess_title(jd_text), "company": _guess_company(jd_text),
        "source_type": body.source, "raw_text": jd_text + note,
        "parse_status": "pending", "ocr_status": "done" if body.source != "image" else "pending",
        "cos_key": None, "created_at": now(),
    }
    store.job_points[jid] = []

    # 异步解析（任务表占位 + 后台执行，对应 Kafka jd.parse）
    tid = next_id()
    store.ai_tasks[tid] = task = {
        "id": tid, "user_id": user["id"], "task_type": "jd_parse",
        "payload": {"job_id": jid}, "result": None, "status": "queued",
        "model_used": "mock-llm", "tokens_in": len(jd_text) // 2, "tokens_out": 512,
        "cost_cents": 3, "attempts": 0, "created_at": now(),
    }
    asyncio.create_task(_delayed_parse(store, jid, jd_text, task, settings))
    return {"job_id": jid, "task_id": task["id"], "status": "pending"}


async def _delayed_parse(store, jid, jd_text, task, settings):
    await asyncio.sleep(settings.LLM_JD_PARSE_DELAY)
    task["status"] = "running"; task["attempts"] += 1
    try:
        task["result"] = await _run_jd_parse(store, jid, jd_text)
        task["status"] = "done"
    except Exception as exc:
        task["status"] = "failed"; task["result"] = {"error": str(exc)}


@router.get("/jobs")
async def list_jobs(request: Request, user: dict = Depends(get_current_user)):
    store = request.app.state.store
    jobs = [j for j in store.jobs.values() if j["user_id"] == user["id"]]
    jobs.sort(key=lambda j: j["created_at"], reverse=True)
    return [{"id": j["id"], "title": j["title"], "company": j["company"],
             "parse_status": j["parse_status"], "created_at": j["created_at"],
             "point_count": len(store.job_points.get(j["id"], []))} for j in jobs]


@router.get("/jobs/{job_id}")
async def get_job(job_id: int, request: Request, user: dict = Depends(get_current_user)):
    store = request.app.state.store
    job = get_owned_resource(store.jobs.get(job_id), user["id"], "JOB_NOT_FOUND")
    points = store.job_points.get(job_id, [])
    # 匹配度/覆盖度统一走 core 共享实现，与 profile 域同源（§3.3：core 提供纯函数，域间不互调）
    r = compute_match(points, store.mastery.get(user["id"], {}))
    return {**job, "point_count": len(points),
            "match_score": r["match_score"],                      # 权重 × 掌握度加权
            "coverage": r["coverage"],                            # 已练考点权重占比
            "covered_points": len(r["known"])}                    # 已练考点个数


@router.post("/jobs/{job_id}/reparse", status_code=202)
async def reparse(job_id: int, request: Request, user: dict = Depends(get_current_user)):
    from ...core.security import rate_limit
    rate_limit(f"reparse:{user['id']}", 5)
    store = request.app.state.store
    job = get_owned_resource(store.jobs.get(job_id), user["id"], "JOB_NOT_FOUND")
    job["parse_status"] = "pending"
    task = {
        "id": next_id(), "user_id": user["id"], "task_type": "jd_parse",
        "payload": {"job_id": job_id}, "result": None, "status": "queued",
        "model_used": "mock-llm", "tokens_in": 0, "tokens_out": 0, "cost_cents": 0,
        "attempts": 0, "created_at": now(),
    }
    store.ai_tasks[task["id"]] = task
    asyncio.create_task(
        _delayed_parse(store, job_id, job["raw_text"], task, request.app.state.settings))
    return {"job_id": job_id, "task_id": task["id"], "status": "pending"}


# ------------------------------------------------------------------ S2 画像（读为主，可缓存）

@router.get("/jobs/{job_id}/points")
async def get_points(job_id: int, request: Request, user: dict = Depends(get_current_user)):
    store = request.app.state.store
    get_owned_resource(store.jobs.get(job_id), user["id"], "JOB_NOT_FOUND")
    mastery = store.mastery.get(user["id"], {})
    out = []
    for p in store.job_points.get(job_id, []):
        m = mastery.get(p["point_name"])
        out.append({**p, "mastery": m["score"] if m else None,
                    "answered": m["answered"] if m else 0})
    return out


class PointsUpdateIn(BaseModel):
    points: list[dict]   # [{point_name, weight}]


@router.put("/jobs/{job_id}/points")
async def update_points(job_id: int, body: PointsUpdateIn, request: Request,
                        user: dict = Depends(get_current_user)):
    """用户手工调权重（触发既有计划重排——生产发事件，dev 标记计划 dirty）。"""
    store = request.app.state.store
    get_owned_resource(store.jobs.get(job_id), user["id"], "JOB_NOT_FOUND")
    changes = {p["point_name"]: p["weight"] for p in body.points}
    changed = 0
    for p in store.job_points.get(job_id, []):
        if p["point_name"] in changes and p["weight"] != changes[p["point_name"]]:
            p["weight"] = max(1, min(100, int(changes[p["point_name"]])))
            p["source"] = "user"
            changed += 1
    # 既有计划标记待重排（异步重排在生产由 practice 域消费事件完成）
    for plan in store.plans.values():
        if plan["job_id"] == job_id and plan["user_id"] == user["id"]:
            plan["dirty"] = True
    return {"updated": changed}


# ------------------------------------------------------------------ utils

def _guess_title(text: str) -> str:
    for line in text.splitlines():
        line = line.strip()
        if line:
            return line[:40]
    return "未命名岗位"


def _guess_company(text: str) -> str:
    import re
    m = re.search(r"(公司|企业)[:：\s]*([^\s，,。；;]{2,20})", text)
    return m.group(2) if m else "未识别"
