import hashlib
import os
import secrets
from datetime import UTC, datetime, timedelta
from typing import Annotated

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from fastapi import APIRouter, Depends, Query, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from services.api.db import get_db
from services.api.errors import ApiError
from services.api.models import LoginSession, User
from services.api.views import user_view

router = APIRouter(prefix="/api/auth")
COOKIE = "corpus_session"
SESSION_DAYS = 14
HASHER = PasswordHasher()
DUMMY_HASH = HASHER.hash(secrets.token_urlsafe(16))
SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}

Db = Annotated[Session, Depends(get_db)]


def normalize_email(value: str) -> str:
    value = value.strip().lower()
    local, _, domain = value.partition("@")
    if not local or "." not in domain or len(value) > 254 or " " in value:
        raise ValueError("邮箱格式不正确")
    return value


def allowed_origins():
    return {o.strip() for o in os.environ["PUBLIC_ORIGIN"].split(",") if o.strip()}


def origin_rejected(request: Request) -> bool:
    return (
        request.method not in SAFE_METHODS
        and request.headers.get("origin") not in allowed_origins()
    )


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def current_user(request: Request, db: Db) -> User:
    token = request.cookies.get(COOKIE)
    entry = db.get(LoginSession, token_hash(token)) if token else None
    if not entry or entry.expires_at <= datetime.now(UTC):
        raise ApiError(401, "AUTH_REQUIRED", "请先登录")
    return db.get(User, entry.user_id)


CurrentUser = Annotated[User, Depends(current_user)]


class LoginInput(BaseModel):
    email: str = Field(max_length=254)
    password: str = Field(min_length=1, max_length=1024)


@router.post("/login")
def login(body: LoginInput, response: Response, db: Db):
    user = db.scalar(select(User).where(User.email == body.email.strip().lower()))
    try:
        HASHER.verify(user.password_hash if user else DUMMY_HASH, body.password)
    except (VerificationError, InvalidHashError):
        user = None
    if not user:
        raise ApiError(401, "INVALID_CREDENTIALS", "邮箱或密码错误")
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
    return user_view(user)


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


@router.get("/me")
def me(user: CurrentUser):
    return user_view(user)


users_router = APIRouter(prefix="/api/users")


@users_router.get("")
def find_user(email: Annotated[str, Query(max_length=254)], user: CurrentUser, db: Db):
    found = db.scalar(select(User).where(User.email == email.strip().lower()))
    if not found:
        raise ApiError(404, "NOT_FOUND", "用户不存在")
    return user_view(found)
