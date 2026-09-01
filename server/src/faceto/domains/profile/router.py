"""profile 域 —— 掌握度计算、匹配度、弱项（支撑界面：S2 画像 / S5 报告回流）。

事件溯源（§5.2 mastery_events）：消费 answer.graded 事件累积，
掌握度表可由事件全量重算。
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from ...core.security import get_current_user
from ...core.store import next_id, now

router = APIRouter(prefix="/profile", tags=["profile"])

# 掌握度模型（M1 简化版）：


# 掌握度模型（M1 简化版）：
#   客观题：delta = correct ? +1 : -0.4；AI 点评：delta = score/100 - 0.5
#   score = 50 + 50 * tanh(累积 delta / 3) —— 收敛于 [0,100]，防单题抖动
def make_handler(store):
    async def handler(event: dict) -> None:
        uid = event["user_id"]
        points = event.get("points") or []
        correct = event.get("is_correct")
        reason = event.get("reason")
        score = event.get("score")

        for p in points:
            if correct is not None:
                delta = 1.0 if correct else -0.4
            elif score is not None:
                delta = score / 100 - 0.5
            else:
                continue
            m = store.mastery.setdefault(uid, {}).setdefault(
                p, {"answered": 0, "correct": 0, "delta_sum": 0.0, "score": 50, "updated_at": now()})
            m["answered"] += 1
            if correct:
                m["correct"] += 1
            m["delta_sum"] += delta
            import math
            m["score"] = round(50 + 50 * math.tanh(m["delta_sum"] / 3))
            m["updated_at"] = now()
            # mastery_event 落档（生产写分区表）
            _ = next_id()
    return handler


@router.get("/mastery")
async def get_mastery(request: Request, job_id: int = 0, user: dict = Depends(get_current_user)):
    """岗位维度掌握度视图：S2 雷达/弱项数据源。"""
    store = request.app.state.store
    m = store.mastery.get(user["id"], {})
    points = store.job_points.get(job_id, [])
    out = [{"point_name": p["point_name"], "weight": p["weight"],
            "mastery": m.get(p["point_name"], {}).get("score"),
            "answered": m.get(p["point_name"], {}).get("answered", 0)} for p in points]
    known = [x for x in out if x["mastery"] is not None]
    match = round(sum(x["weight"] * x["mastery"] for x in known) / sum(p["weight"] for p in points)) \
        if known and points else None
    weak = sorted(known, key=lambda x: x["mastery"])[:3]
    return {"points": out, "match_score": match,
            "weak_points": [{"point_name": w["point_name"], "mastery": w["mastery"]} for w in weak]}
