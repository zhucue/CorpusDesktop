import hashlib
import os
import secrets
import threading
import time
from datetime import UTC, datetime, timedelta
from typing import Annotated
from uuid import UUID

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from fastapi import APIRouter, Depends, Query, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from services.api.access import MANAGE, human_only, require_project
from services.api.db import get_db
from services.api.errors import ApiError
from services.api.models import AgentToken, LoginSession, User
from services.api.views import user_view

router = APIRouter(prefix="/api/auth")
COOKIE = "corpus_session"
SESSION_DAYS = 14
HASHER = PasswordHasher()
DUMMY_HASH = HASHER.hash(secrets.token_urlsafe(16))
SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}
# while must_change_password is set, only these paths answer (contracts/p7.md §五)
PASSWORD_CHANGE_PATHS = {"/api/auth/me", "/api/auth/password", "/api/auth/logout"}

Db = Annotated[Session, Depends(get_db)]


def normalize_email(value: str) -> str:
    value = value.strip().lower()
    local, _, domain = value.partition("@")
    if not local or "." not in domain or len(value) > 254 or " " in value:
        raise ValueError("邮箱格式不正确")
    return value


def allowed_origins():
    return {o.strip() for o in os.environ["PUBLIC_ORIGIN"].split(",") if o.strip()}


def bearer(request: Request) -> str | None:
    scheme, _, token = request.headers.get("authorization", "").partition(" ")
    return (token.strip() or None) if scheme.lower() == "bearer" else None


def origin_rejected(request: Request) -> bool:
    """Cookie requests need a known Origin (CSRF); bearer-token requests carry no cookie and are exempt."""
    return (
        request.method not in SAFE_METHODS
        and bearer(request) is None
        and request.headers.get("origin") not in allowed_origins()
    )


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def revoke(db, user_id, keep_session: str | None = None):
    """Drop the user's login sessions (except keep_session, a token hash) and all agent tokens."""
    q = delete(LoginSession).where(LoginSession.user_id == user_id)
    if keep_session:
        q = q.where(LoginSession.token_hash != keep_session)
    db.execute(q)
    db.execute(delete(AgentToken).where(AgentToken.user_id == user_id))


def _active(request: Request, user: User | None, missing: str) -> User:
    if user is None:
        raise ApiError(401, "AUTH_REQUIRED", missing)
    if user.disabled_at is not None:
        raise ApiError(401, "ACCOUNT_DISABLED", "账号已停用，请联系管理员")
    if user.must_change_password and request.url.path not in PASSWORD_CHANGE_PATHS:
        raise ApiError(403, "PASSWORD_CHANGE_REQUIRED", "请先修改密码")
    return user


def current_user(request: Request, db: Db) -> User:
    """Cookie session, or `Authorization: Bearer <agent token>`: the token's user, limited to its project
    (user.token_project_id, enforced in services.api.access). Disabled accounts are rejected; accounts
    with a temporary password only reach PASSWORD_CHANGE_PATHS."""
    if (raw := bearer(request)) is not None:
        entry = db.get(AgentToken, token_hash(raw))
        if not entry or entry.expires_at <= datetime.now(UTC):
            raise ApiError(401, "AUTH_REQUIRED", "令牌无效或已过期")
        user = _active(request, db.get(User, entry.user_id), "令牌无效或已过期")
        user.token_project_id = entry.project_id
        return user
    token = request.cookies.get(COOKIE)
    entry = db.get(LoginSession, token_hash(token)) if token else None
    if not entry or entry.expires_at <= datetime.now(UTC):
        raise ApiError(401, "AUTH_REQUIRED", "请先登录")
    return _active(request, db.get(User, entry.user_id), "请先登录")


CurrentUser = Annotated[User, Depends(current_user)]


class LoginInput(BaseModel):
    email: str = Field(max_length=254)
    password: str = Field(min_length=1, max_length=1024)


def _login_failed(db, request, email, reason):
    from services.api.audit import record  # audit imports this module

    record(
        db,
        None,
        "login_failed",
        "user",
        None,
        None,
        detail={"email": email[:254], "reason": reason},
        request=request,
    )
    db.commit()


@router.post("/login")
def login(body: LoginInput, request: Request, response: Response, db: Db):
    from services.api.audit import record

    email = body.email.strip().lower()
    user = db.scalar(select(User).where(User.email == email))
    try:
        HASHER.verify(user.password_hash if user else DUMMY_HASH, body.password)
    except (VerificationError, InvalidHashError):
        user = None
    if not user:
        _login_failed(db, request, email, "invalid_credentials")
        raise ApiError(401, "INVALID_CREDENTIALS", "邮箱或密码错误")
    if user.disabled_at is not None:
        _login_failed(db, request, email, "account_disabled")
        raise ApiError(403, "ACCOUNT_DISABLED", "账号已停用，请联系管理员")
    user.last_login_at = datetime.now(UTC)
    record(db, user, "login", "user", user.id, user.email, request=request)
    token = secrets.token_urlsafe(32)
    db.add(
        LoginSession(
            token_hash=token_hash(token),
            user_id=user.id,
            expires_at=datetime.now(UTC) + timedelta(days=SESSION_DAYS),
        )
    )
    db.execute(
        delete(LoginSession).where(
            LoginSession.user_id == user.id,
            LoginSession.expires_at <= datetime.now(UTC),
        )
    )
    db.commit()
    secure = all(o.startswith("https://") for o in allowed_origins())
    response.set_cookie(
        COOKIE,
        token,
        max_age=SESSION_DAYS * 86400,
        httponly=True,
        samesite="lax",
        secure=secure,
        path="/",
    )
    return me_view(user)


@router.post("/logout", status_code=204)
def logout(request: Request, db: Db):
    token = request.cookies.get(COOKIE)
    if token:
        db.execute(
            delete(LoginSession).where(LoginSession.token_hash == token_hash(token))
        )
        db.commit()
    response = Response(status_code=204)
    response.delete_cookie(COOKIE, path="/")
    return response


def me_view(user):
    return {**user_view(user), "must_change_password": user.must_change_password}


@router.get("/me")
def me(user: CurrentUser):
    return me_view(user)


def check_password_length(value: str):
    if not 12 <= len(value) <= 1024:
        raise ApiError(422, "VALIDATION_ERROR", "新密码长度须为 12 到 1024 位")


class PasswordInput(BaseModel):
    old_password: str = Field(min_length=1, max_length=1024)
    new_password: str = Field(max_length=1024)


@router.post("/password")
def change_password(body: PasswordInput, request: Request, user: CurrentUser, db: Db):
    """Browser session only. Keeps the current session; other sessions and agent tokens are revoked.
    nginx rate-limits this path in the login zone, so old-password guessing is throttled like login."""
    if bearer(request) is not None:
        raise ApiError(403, "FORBIDDEN", "权限不足")
    try:
        HASHER.verify(user.password_hash, body.old_password)
    except (VerificationError, InvalidHashError):
        raise ApiError(400, "WRONG_PASSWORD", "原密码不正确")
    check_password_length(body.new_password)
    if body.new_password == body.old_password:
        raise ApiError(422, "VALIDATION_ERROR", "新密码不能与原密码相同")
    from services.api.audit import record

    user.password_hash = HASHER.hash(body.new_password)
    user.must_change_password = False
    revoke(db, user.id, keep_session=token_hash(request.cookies[COOKIE]))
    record(db, user, "password_change", "user", user.id, user.email, request=request)
    db.commit()
    return me_view(user)


users_router = APIRouter(prefix="/api/users")

LOOKUPS_PER_MINUTE = 20
_lookups: dict = {}  # user id → recent lookup times (one api process: uvicorn without workers)
_lookups_lock = threading.Lock()


def _rate_limit(user_id):
    now = time.monotonic()
    with _lookups_lock:
        recent = [t for t in _lookups.get(user_id, ()) if now - t < 60]
        if len(recent) >= LOOKUPS_PER_MINUTE:
            _lookups[user_id] = recent
            raise ApiError(429, "RATE_LIMITED", "查找过于频繁，请一分钟后再试")
        recent.append(now)
        _lookups[user_id] = recent


@users_router.get("")
def find_user(
    email: Annotated[str, Query(max_length=254)],
    project_id: UUID,
    user: CurrentUser,
    db: Db,
):
    """Adding a member (contracts/p11.md §三 4): the project owner, browser session only, looks up one exact
    email; `{items: []}` when there is no such account, `{items: [user]}` otherwise (same shape, same one
    query either way). At most LOOKUPS_PER_MINUTE lookups per user and minute."""
    human_only(user)
    require_project(db, project_id, user, MANAGE)
    _rate_limit(user.id)
    found = db.scalar(select(User).where(User.email == email.strip().lower()))
    items = (
        [{"id": found.id, "email": found.email, "display_name": found.display_name}]
        if found
        else []
    )
    return {"items": items}
