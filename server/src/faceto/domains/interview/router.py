"""interview 域 —— 模拟面试、SSE 流式（支撑界面：S5）。

★ SSE 设计（§4.3）：
- event: token | point_eval | done | error，心跳 :ping 每 15s；
- 会话状态存 store（生产存 Redis sse:state:{session_id}，Pod 漂移可恢复）；
- 单用户并发 SSE 连接上限 3（§7.6，M1 简化为同会话重复连接拒绝）。
"""
from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from ...core.security import get_current_user, get_owned_resource
from ...core.store import next_id, now
from ...ai.llm import (mock_interview_first, mock_interview_question,
                       mock_followup, mock_eval)

router = APIRouter(tags=["interview"])

MAX_TURNS = 5


class InterviewCreateIn(BaseModel):
    job_id: int


@router.post("/interviews", status_code=201)
async def create_interview(body: InterviewCreateIn, request: Request,
                           user: dict = Depends(get_current_user)):
    settings = request.app.state.settings
    if settings.degrade["interview"]:                    # §8.3 降级：停止新建
        raise HTTPException(503, {"code": "INTERVIEW_DEGRADED", "message": "模拟面试排队中，请稍后再试"})
    store = request.app.state.store
    job = get_owned_resource(store.jobs.get(body.job_id), user["id"], "JOB_NOT_FOUND")
    points = [p["point_name"] for p in store.job_points.get(body.job_id, [])]
    if not points:
        raise HTTPException(409, {"code": "JOB_NOT_PARSED", "message": "岗位画像未就绪"})

    iid = next_id()
    store.interviews[iid] = {
        "id": iid, "user_id": user["id"], "job_id": body.job_id, "status": "active",
        "point_checklist": points[:6], "turn_count": 0,
        "started_at": now(), "ended_at": None,
    }
    store.interview_turns[iid] = []
    return {"interview_id": iid, "max_turns": MAX_TURNS,
            "point_checklist": points[:6]}


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


async def _stream_tokens(text: str, interval: float):
    """按 token 流式吐字（生产为 LLM 逐 token 推送）。中文按 2 字符切。"""
    for i in range(0, len(text), 2):
        yield text[i:i + 2]
        await asyncio.sleep(interval)


@router.get("/interviews/{interview_id}/stream")
async def interview_stream(interview_id: int, request: Request,
                           user: dict = Depends(get_current_user)):
    store = request.app.state.store
    sess = get_owned_resource(store.interviews.get(interview_id), user["id"], "INTERVIEW_NOT_FOUND")
    settings = request.app.state.settings
    turn_no = sess["turn_count"]

    async def gen():
        try:
            if turn_no == 0:
                # 开场白 + 第一题
                async for tok in _stream_tokens(mock_interview_first(sess["point_checklist"]),
                                                settings.LLM_TOKEN_INTERVAL):
                    yield _sse("token", {"t": tok})
            else:
                async for tok in _stream_tokens(mock_interview_question(sess["point_checklist"], turn_no),
                                                settings.LLM_TOKEN_INTERVAL):
                    yield _sse("token", {"t": tok})
            yield _sse("done", {"turn": turn_no, "awaiting": "answer"})
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            yield _sse("error", {"message": str(exc)})

    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache",
                                      "X-Accel-Buffering": "no"})   # §4.3 关闭网关缓冲


class TurnIn(BaseModel):
    answer: str = Field(min_length=1, max_length=4000)


@router.post("/interviews/{interview_id}/turns")
async def submit_turn(interview_id: int, body: TurnIn, request: Request,
                      user: dict = Depends(get_current_user)):
    """提交一轮回答 → SSE 流返回：追问 + 实时考点评估事件。"""
    store = request.app.state.store
    settings = request.app.state.settings
    sess = get_owned_resource(store.interviews.get(interview_id), user["id"], "INTERVIEW_NOT_FOUND")
    if sess["status"] != "active":
        raise HTTPException(409, {"code": "INTERVIEW_CLOSED", "message": "会话已结束"})
    turn_no = sess["turn_count"] + 1
    point = sess["point_checklist"][(turn_no - 1) % len(sess["point_checklist"])]
    eval_result = mock_eval(body.answer, point)

    store.interview_turns[interview_id].append({
        "id": next_id(), "session_id": interview_id, "turn_no": turn_no, "role": "user",
        "content": body.answer, "point_tags": [point], "score": eval_result["score"], "created_at": now(),
    })

    async def gen():
        try:
            # ① 实时考点评估（point_eval 事件）
            yield _sse("point_eval", {"turn": turn_no, **eval_result})
            # ② 面试官回应：评价 + 追问（token 流）
            reply = (f"（评估：{eval_result['level']} {eval_result['score']} 分）"
                     f"{eval_result['comment']}")
            async for tok in _stream_tokens(reply, settings.LLM_TOKEN_INTERVAL):
                yield _sse("token", {"t": tok})
            if turn_no >= MAX_TURNS:
                closing = "好的，今天的面试就到这里。稍后可在报告中查看各考点评估，辛苦了。"
                async for tok in _stream_tokens(closing, settings.LLM_TOKEN_INTERVAL):
                    yield _sse("token", {"t": tok})
                sess["status"] = "ending"
                sess["turn_count"] = turn_no
                yield _sse("done", {"turn": turn_no, "finished": True})
            else:
                follow = mock_followup(turn_no)
                async for tok in _stream_tokens(follow, settings.LLM_TOKEN_INTERVAL):
                    yield _sse("token", {"t": tok})
                sess["turn_count"] = turn_no
                yield _sse("done", {"turn": turn_no, "finished": False, "awaiting": "answer"})
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            yield _sse("error", {"message": str(exc)})

    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@router.get("/interviews/{interview_id}/report")
async def get_report(interview_id: int, request: Request,
                     user: dict = Depends(get_current_user)):
    """会话报告（会话结束后生成）。"""
    store = request.app.state.store
    sess = get_owned_resource(store.interviews.get(interview_id), user["id"], "INTERVIEW_NOT_FOUND")
    turns = store.interview_turns.get(interview_id, [])
    if not turns:
        return {"status": "pending", "report": None, "retry_after": 1}

    by_point: dict[str, list[int]] = {}
    for t in turns:
        for p in t["point_tags"]:
            by_point.setdefault(p, []).append(t["score"])
    overall = round(sum(sum(v) for v in by_point.values()) /
                    sum(len(v) for v in by_point.values())) if by_point else 0
    detail = [{"point_name": p, "avg_score": round(sum(v) / len(v)),
               "turns": len(v)} for p, v in by_point.items()]
    weak = sorted(detail, key=lambda d: d["avg_score"])[:3]
    # 掌握度回流（领域事件 → profile 域，§2 画像评估服务）
    for d in detail:
        await store.bus.publish("answer.graded", {
            "user_id": user["id"], "question_id": 0, "points": [d["point_name"]],
            "is_correct": None, "reason": "interview", "score": d["avg_score"]})
    sess["status"] = "done"
    sess["ended_at"] = now()
    return {"status": "done", "overall": overall, "points": detail,
            "weak_points": [w["point_name"] for w in weak],
            "turns": [{"turn_no": t["turn_no"], "point": t["point_tags"][0],
                       "score": t["score"]} for t in turns]}
