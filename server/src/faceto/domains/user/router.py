"""user 域 —— 注册登录、会话（支撑界面：全局）。"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from ...core.security import (create_token, get_current_user, hash_password,
                              verify_password, rate_limit, client_ip)
from ...core.store import next_id, now

router = APIRouter(prefix="/auth", tags=["auth"])


class RegisterIn(BaseModel):
    email: str = Field(min_length=3, max_length=120)
    password: str = Field(min_length=6, max_length=64)
    name: str = Field(default="", max_length=30)


class LoginIn(BaseModel):
    email: str
    password: str


@router.post("/register", status_code=201)
async def register(body: RegisterIn, request: Request):
    store = request.app.state.store
    if any(u["email"] == body.email for u in store.users.values()):
        raise HTTPException(409, {"code": "AUTH_EMAIL_EXISTS", "message": "邮箱已被注册"})
    uid = next_id()
    store.users[uid] = {"id": uid, "email": body.email,
                        "name": body.name or body.email.split("@")[0],
                        "password": hash_password(body.password), "created_at": now()}
    return _tokens(uid)


@router.post("/login")
async def login(body: LoginIn, request: Request):
    store = request.app.state.store
    rate_limit(f"login:{client_ip(request)}", 30)           # §7.2 登录限流（防撞库，IP 维度）
    user = next((u for u in store.users.values() if u["email"] == body.email), None)
    if not user or not verify_password(body.password, user["password"]):
        raise HTTPException(401, {"code": "AUTH_BAD_CREDENTIALS", "message": "邮箱或密码错误"})
    return _tokens(user["id"])


@router.get("/me")
async def me(user: dict = Depends(get_current_user)):
    return {"id": user["id"], "email": user["email"], "name": user["name"]}


def _tokens(uid: int) -> dict:
    """access(短) + refresh(长)。生产 refresh 走 HttpOnly Cookie + 轮转 + Redis 撤销列表（§7.1）。"""
    return {"access_token": create_token(uid, "access"),
            "refresh_token": create_token(uid, "refresh", 30 * 24 * 3600),
            "token_type": "bearer"}
