"""quiz 域 —— 刷题中心：多题库包（pack）的管理与发放。

与 S4 刷题流（plan 驱动）解耦。包数据在磁盘 JSON（core/packs.py），
LLM 导入在 ai/quizgen.py，本路由只做编排与鉴权。
"""
from __future__ import annotations

import time

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from ...core import packs
from ...core.security import get_current_user
from ...ai import quizgen

router = APIRouter(tags=["quiz"])


@router.get("/quiz/packs")
async def list_packs(user: dict = Depends(get_current_user)):
    """题库包列表（刷题中心首页卡片）。进度在客户端 localStorage。"""
    return packs.list_packs()


@router.get("/quiz/packs/{pid}")
async def get_pack(pid: str, user: dict = Depends(get_current_user)):
    p = packs.get_pack(pid)
    if not p:
        raise HTTPException(404, {"code": "PACK_NOT_FOUND", "message": "题库包不存在"})
    return p


@router.delete("/quiz/packs/{pid}")
async def delete_pack(pid: str, user: dict = Depends(get_current_user)):
    try:
        ok = packs.delete_pack(pid)
    except PermissionError as exc:
        raise HTTPException(403, {"code": "PACK_PROTECTED", "message": str(exc)})
    if not ok:
        raise HTTPException(404, {"code": "PACK_NOT_FOUND", "message": "题库包不存在"})
    return {"ok": True}


class ImportIn(BaseModel):
    name: str
    text: str


@router.post("/quiz/packs/import")
async def import_pack(body: ImportIn, user: dict = Depends(get_current_user)):
    """LLM 导入：资料文本 → 题库包（同步等待，客户端展示生成中状态）。"""
    if not quizgen.llm_configured():
        raise HTTPException(501, {
            "code": "LLM_NOT_CONFIGURED",
            "message": "服务端未配置 LLM：设置环境变量 FT_LLM_API_KEY（可选 FT_LLM_BASE_URL / FT_LLM_MODEL）后重启，"
                       "或直接把资料交给 ZCode 助手生成题库包文件放入 server/data/quiz_packs/",
        })
    name = body.name.strip() or f"导入题库 {time.strftime('%m-%d %H:%M')}"
    text = body.text.strip()
    if len(text) < 100:
        raise HTTPException(400, {"code": "MATERIAL_TOO_SHORT", "message": "资料太短（至少 100 字），贴多一点内容再试"})
    try:
        choice, subjective = quizgen.generate_quiz(text)
    except RuntimeError as exc:
        raise HTTPException(502, {"code": "LLM_FAILED", "message": str(exc)})

    pid = f"imp{int(time.time())}"
    pack = {
        "id": pid, "name": name, "desc": "LLM 导入生成 · 建议抽查几题校对答案",
        "source": f"导入资料 {len(text)} 字", "origin": "import-llm", "created_at": time.time(),
        "choice": choice, "subjective": subjective,
    }
    packs.save_pack(pack)
    return {"id": pid, "name": name, "n_choice": len(choice), "n_subjective": len(subjective)}
