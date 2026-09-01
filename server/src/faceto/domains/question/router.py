"""question 域 —— 题库读热点（支撑界面：S4 详情）。CDN+Redis 三级缓存在生产挡 90% 流量。"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request

from ...core.security import get_current_user

router = APIRouter(tags=["question"])


@router.get("/questions/{question_id}")
async def get_question(question_id: int, request: Request,
                       job_id: int = 0, user: dict = Depends(get_current_user)):
    """题目详情 + 双溯源（§4.2）：JD 原句（来自该岗位画像的 jd_evidence）+ 面经出处。"""
    store = request.app.state.store
    q = store.questions.get(question_id)
    if not q or q["status"] != "active":
        raise HTTPException(404, {"code": "QUESTION_NOT_FOUND", "message": "题目不存在"})

    # 溯源①：JD 原句 —— 从用户该岗位的考点证据里找
    jd_evidence: list[str] = []
    if job_id:
        job = store.jobs.get(job_id)
        if job and job["user_id"] == user["id"]:
            for p in store.job_points.get(job_id, []):
                if p["point_name"] in q["points"]:
                    jd_evidence.extend(p.get("jd_evidence") or [])

    # 溯源②：面经出处 —— 题目标注的 exp_ref + 该考点的面经列表
    exp_refs = [d for d in store.exp_docs if set(d["points"]) & set(q["points"])]
    exp_ref = q.get("exp_ref")
    related = [{"id": d["id"], "title": d["title"], "source": d["source"]} for d in exp_refs[:3]]

    return {
        "id": q["id"], "type": q["type"], "stem": q["stem"], "options": q["options"],
        "difficulty": q["difficulty"], "points": q["points"], "chapter": q["chapter"],
        "version": q["version"],
        # 答案与解析不在此返回（提交作答后由 answers 流程返回，防白嫖爬虫）
        "trace": {"jd_evidence": jd_evidence[:3], "exp_ref": exp_ref, "related_exp": related},
    }
