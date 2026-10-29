"""鉴权（§7）：JWT 签发校验 + PBKDF2 口令 + FastAPI 依赖注入。

- access token 无状态校验（生产在网关 Lua 层验签，不打到业务）；
- 密码生产应换 argon2id，M1-dev 用 stdlib PBKDF2 等价实现；
- 越权检查统一在 get_owned_resource 依赖里做（§7.5），禁止散落手工比对。
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import time
from typing import Any, Optional

from fastapi import Depends, Header, HTTPException, Request

from .config import settings

# ---------------------------------------------------------------- 口令


def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 60_000)
    return f"pbkdf2${salt}${dk.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        _, salt, hexdk = stored.split("$")
    except ValueError:
        return False
    dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 60_000)
    return hmac.compare_digest(dk.hex(), hexdk)


# ---------------------------------------------------------------- JWT（HS256，stdlib 实现）


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _b64url_decode(s: str) -> bytes:
    pad = "=" * (-len(s) % 4)
    return base64.urlsafe_b64decode(s + pad)


def create_token(user_id: int, scope: str = "access", ttl: Optional[int] = None) -> str:
    header = _b64url(json.dumps({"alg": "HS256", "typ": "JWT"}).encode())
    payload = {
        "sub": str(user_id),
        "scope": scope,
        "iss": settings.JWT_ISSUER,
        "iat": int(time.time()),
        "exp": int(time.time()) + (ttl or settings.ACCESS_TOKEN_TTL),
    }
    body = _b64url(json.dumps(payload).encode())
    sig = _b64url(hmac.new(settings.JWT_SECRET.encode(), f"{header}.{body}".encode(), hashlib.sha256).digest())
    return f"{header}.{body}.{sig}"


def decode_token(token: str, scope: str = "access") -> dict[str, Any]:
    try:
        header, body, sig = token.split(".")
    except ValueError:
        raise HTTPException(401, "AUTH_TOKEN_MALFORMED")
    expect = _b64url(hmac.new(settings.JWT_SECRET.encode(), f"{header}.{body}".encode(), hashlib.sha256).digest())
    if not hmac.compare_digest(sig, expect):
        raise HTTPException(401, "AUTH_TOKEN_INVALID")
    payload = json.loads(_b64url_decode(body))
    if payload.get("exp", 0) < time.time():
        raise HTTPException(401, "AUTH_TOKEN_EXPIRED")
    if payload.get("scope") != scope:
        raise HTTPException(401, "AUTH_TOKEN_SCOPE")
    return payload


# ---------------------------------------------------------------- 依赖注入


def get_current_user(request: Request, authorization: Optional[str] = Header(None)) -> "dict":
    """请求上下文注入当前用户（store 中的用户记录）。

    SSE 的 EventSource 无法携带 Authorization 头，允许 ?token= 查询参数兜底
    （生产走网关签发的短时效一次性票据，这里 dev 简化复用 access token）。
    """
    token = None
    if authorization and authorization.startswith("Bearer "):
        token = authorization[7:]
    elif "token" in request.query_params:
        token = request.query_params["token"]
    if not token:
        raise HTTPException(401, "AUTH_REQUIRED")
    payload = decode_token(token)
    user = request.app.state.store.users.get(int(payload["sub"]))
    if not user:
        raise HTTPException(401, "AUTH_USER_GONE")
    return user


def get_optional_user(request: Request, authorization: Optional[str] = Header(None)) -> Optional[dict]:
    if not authorization or not authorization.startswith("Bearer "):
        return None
    try:
        payload = decode_token(authorization[7:])
    except HTTPException:
        return None
    return request.app.state.store.users.get(int(payload["sub"]))


def get_owned_resource(resource: Optional[dict], owner_id: int, code: str) -> dict:
    """§7.5 越权统一检查：所有资源接口强制 owner == current_user。"""
    if resource is None:
        raise HTTPException(404, code)
    if resource.get("user_id") != owner_id:
        raise HTTPException(403, f"{code}_FORBIDDEN")
    return resource


# ---------------------------------------------------------------- 应用级限流（§8.1 兜底，内存实现）

_rate_buckets: dict[str, list[float]] = {}


def rate_limit(key: str, limit_per_min: int) -> None:
    now = time.time()
    window = [t for t in _rate_buckets.get(key, []) if now - t < 60]
    if len(window) >= limit_per_min:
        raise HTTPException(429, {"code": "AUTH_RATE_LIMITED", "retry_after": 60})
    window.append(now)
    _rate_buckets[key] = window


def client_ip(request: Request) -> str:
    fwd = request.headers.get("x-forwarded-for")
    return fwd.split(",")[0].strip() if fwd else (request.client.host if request.client else "unknown")
