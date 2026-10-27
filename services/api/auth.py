"""Email/password login with server-side hashed sessions and same-origin writes."""

import hashlib
import hmac
import os
import secrets
import threading
import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Annotated
from urllib.parse import urlsplit
from uuid import UUID

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from argon2.low_level import Type
from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator
from sqlalchemy import delete, select

from services.api.db import lock_actor, transaction
from services.api.errors import ApiError
from services.api.models import LoginSession, User

router = APIRouter(prefix="/api/v1/auth", tags=["authentication"])
COOKIE = "corpus_session"
HASHER = PasswordHasher(type=Type.ID)
DUMMY_HASH = HASHER.hash(secrets.token_urlsafe(32))
_attempts = {}
_attempt_lock = threading.Lock()


def normalize_email(value):
    value = value.strip().lower()
    if (
        len(value) > 254
        or len(value.split("@")) != 2
        or any(c.isspace() for c in value)
    ):
        raise ValueError("Invalid email")
    local, domain = value.split("@")
    if not local or not domain or "." not in domain:
        raise ValueError("Invalid email")
    return value


def site_config():
    origin = os.environ.get("PUBLIC_ORIGIN", "")
    parsed = urlsplit(origin)
    insecure = os.environ.get("ALLOW_INSECURE_HTTP", "false").lower() == "true"
    local_http = (
        insecure
        and parsed.scheme == "http"
        and parsed.hostname in {"localhost", "127.0.0.1", "::1"}
    )
    if (
        not origin
        or parsed.username
        or parsed.password
        or parsed.path
        or parsed.query
        or parsed.fragment
        or not parsed.netloc
        or (parsed.scheme != "https" and not local_http)
    ):
        raise RuntimeError(
            "PUBLIC_ORIGIN must be an HTTPS origin; local HTTP requires explicit opt-in"
        )
    return origin, parsed.scheme == "https"


def check_origin(request):
    if request.headers.get("origin") != site_config()[0]:
        raise ApiError(403, "ORIGIN_REJECTED", "Request origin is not allowed")


def token_hash(value):
    return hashlib.sha256(value.encode()).hexdigest()


def csrf_token(token):
    return hmac.new(token.encode(), b"corpus-csrf-v1", hashlib.sha256).hexdigest()


class LoginInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    email: str = Field(max_length=254)
    password: SecretStr = Field(min_length=1, max_length=1024)

    @field_validator("email")
    @classmethod
    def email_valid(cls, value):
        return normalize_email(value)


class ActorView(BaseModel):
    id: UUID
    email: str
    is_platform_admin: bool


class AuthView(BaseModel):
    actor: ActorView
    csrf_token: str


@dataclass(frozen=True)
class Actor:
    id: UUID
    email: str
    is_platform_admin: bool
    session_hash: str


def current_actor(request: Request):
    token = request.cookies.get(COOKIE, "")
    if not token or len(token) > 128:
        raise ApiError(401, "AUTH_REQUIRED", "Sign in required")
    with transaction() as session:
        entry = session.get(LoginSession, token_hash(token))
        user = session.get(User, entry.user_id) if entry else None
        if (
            not entry
            or entry.expires_at <= datetime.now(UTC)
            or not user
            or not user.is_active
        ):
            raise ApiError(401, "AUTH_REQUIRED", "Sign in required")
        if request.method not in {"GET", "HEAD", "OPTIONS"}:
            check_origin(request)
            supplied = request.headers.get("x-csrf-token", "")
            if not hmac.compare_digest(token_hash(supplied), entry.csrf_hash):
                raise ApiError(403, "CSRF_REJECTED", "Invalid CSRF token")
        return Actor(user.id, user.email, user.is_platform_admin, entry.token_hash)


CurrentActor = Annotated[Actor, Depends(current_actor)]


def _rate_limit(key):
    """Small per-process bound; single API process deployment, not a distributed quota."""
    now = time.monotonic()
    with _attempt_lock:
        for old in [key for key, (start, _) in _attempts.items() if now - start > 60]:
            del _attempts[old]
        if len(_attempts) >= 4096 and key not in _attempts:
            raise ApiError(429, "AUTH_RATE_LIMITED", "Try again later", retryable=True)
        start, count = _attempts.get(key, (now, 0))
        if count >= 10:
            raise ApiError(429, "AUTH_RATE_LIMITED", "Try again later", retryable=True)
        _attempts[key] = (start, count + 1)


@router.post("/login", response_model=AuthView)
def login(body: LoginInput, request: Request, response: Response):
    check_origin(request)
    if (
        request.headers.get("content-type", "").split(";", 1)[0].lower()
        != "application/json"
    ):
        raise ApiError(415, "JSON_REQUIRED", "JSON request required")
    _rate_limit(request.client.host if request.client else "unknown")
    with transaction() as session:
        user = session.scalar(select(User).where(User.email == body.email))
        try:
            HASHER.verify(
                user.password_hash if user else DUMMY_HASH,
                body.password.get_secret_value(),
            )
            valid = user is not None and user.is_active
        except (VerificationError, InvalidHashError):
            valid = False
        if not valid:
            raise ApiError(401, "AUTH_INVALID", "Invalid email or password")
        lock_actor(session, user.id)
        session.refresh(user)
        if not user.is_active:
            raise ApiError(401, "AUTH_INVALID", "Invalid email or password")
        if HASHER.check_needs_rehash(user.password_hash):
            user.password_hash = HASHER.hash(body.password.get_secret_value())
        token = secrets.token_urlsafe(32)
        csrf = csrf_token(token)
        ttl = 12 * 3600
        old = request.cookies.get(COOKIE)
        if old:
            session.execute(
                delete(LoginSession).where(LoginSession.token_hash == token_hash(old))
            )
        session.add(
            LoginSession(
                token_hash=token_hash(token),
                user_id=user.id,
                csrf_hash=token_hash(csrf),
                expires_at=datetime.now(UTC) + timedelta(seconds=ttl),
            )
        )
        response.set_cookie(
            COOKIE,
            token,
            max_age=ttl,
            httponly=True,
            secure=site_config()[1],
            samesite="lax",
            path="/",
        )
        response.headers["Cache-Control"] = "no-store"
        return AuthView(
            actor=ActorView(
                id=user.id, email=user.email, is_platform_admin=user.is_platform_admin
            ),
            csrf_token=csrf,
        )


@router.get("/session", response_model=AuthView)
def session_view(request: Request, response: Response, actor: CurrentActor):
    response.headers["Cache-Control"] = "no-store"
    return AuthView(
        actor=ActorView(
            id=actor.id, email=actor.email, is_platform_admin=actor.is_platform_admin
        ),
        csrf_token=csrf_token(request.cookies[COOKIE]),
    )


@router.post("/logout", status_code=204)
def logout(response: Response, actor: CurrentActor):
    with transaction(actor.id) as session:
        session.execute(
            delete(LoginSession).where(LoginSession.token_hash == actor.session_hash)
        )
    response.delete_cookie(
        COOKIE, httponly=True, secure=site_config()[1], samesite="lax", path="/"
    )
