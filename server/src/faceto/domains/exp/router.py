"""exp 域 —— 面经检索（支撑界面：S3 面经栏 / S4 溯源）。

生产为 ES 全文 + ik 分词（§5.5），独立降级开关 degrade.exp（§8.3）；
M1-dev 用内存关键词过滤 + 游标分页（禁 offset 深翻页，§4.1）。
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request

from ...core.security import get_current_user

router = APIRouter(tags=["exp"])

PAGE_SIZE = 5


@router.get("/exp")
async def search_exp(request: Request, point_id: str = "", cursor: int = 0,
                     keyword: str = "", user: dict = Depends(get_current_user)):
    settings = request.app.state.settings
    if settings.degrade["exp"]:        # §8.3 降级：隐藏入口/静态精选
        return {"items": [], "next_cursor": None, "degraded": True}

    store = request.app.state.store
    docs = store.exp_docs
    if point_id:
        docs = [d for d in docs if point_id in d["points"]]
    if keyword:
        kw = keyword.lower()
        docs = [d for d in docs if kw in d["title"].lower() or kw in d["content"].lower()
                or any(kw in p.lower() for p in d["points"])]

    docs = sorted(docs, key=lambda d: d["published_at"], reverse=True)
    window = docs[cursor:cursor + PAGE_SIZE]
    next_cursor = cursor + PAGE_SIZE if cursor + PAGE_SIZE < len(docs) else None
    return {"items": [{"id": d["id"], "title": d["title"], "source": d["source"],
                       "content": d["content"], "points": d["points"],
                       "published_at": d["published_at"]} for d in window],
            "next_cursor": next_cursor, "total": len(docs)}
