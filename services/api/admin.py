"""Account administration (contracts/p7.md §五): platform admins list, create, reset, disable and enable
users and grant or revoke admin. Browser sessions only (access.require_admin)."""

import secrets
import string
from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select

from services.api.access import Paging, require_admin
from services.api.auth import HASHER, CurrentUser, Db, normalize_email, revoke
from services.api.errors import ApiError, not_found
from services.api.models import ProjectMember, User

router = APIRouter(prefix="/api/admin/users")
# no look-alikes (0/O, 1/l/I) so a password read off the screen types correctly
ALPHABET = "".join(c for c in string.ascii_letters + string.digits if c not in "0O1lI")


def temporary_password() -> str:
    return "".join(secrets.choice(ALPHABET) for _ in range(16))


def admin_view(u: User, projects: int):
    return {
        "id": u.id,
        "email": u.email,
        "display_name": u.display_name,
        "is_admin": u.is_admin,
        "disabled_at": u.disabled_at,
        "last_login_at": u.last_login_at,
        "created_at": u.created_at,
        "projects": projects,
    }


def _projects(db, user_id) -> int:
    return db.scalar(select(func.count()).where(ProjectMember.user_id == user_id))


def _target(db, user_id) -> User:
    user = db.get(User, user_id)
    if not user:
        raise not_found("用户")
    return user


def _keep_one_admin(db, target: User):
    """Refuse when target is the only active admin. Locks every active admin row, target included,
    in id order: two admins disabling or demoting each other at once queue on the same first row
    instead of deadlocking, and the second sees the first one's result (rows are refreshed)."""
    admins = db.scalars(
        select(User)
        .where(User.is_admin, User.disabled_at.is_(None))
        .order_by(User.id)
        .with_for_update()
        .execution_options(populate_existing=True)
    ).all()
    if target in admins and len(admins) == 1:
        raise ApiError(409, "LAST_ADMIN", "至少保留一位可用的管理员")


@router.get("")
def list_users(
    user: CurrentUser,
    db: Db,
    paging: Paging,
    q: Annotated[str | None, Query(max_length=254)] = None,
):
    require_admin(user)
    projects = (
        select(func.count())
        .where(ProjectMember.user_id == User.id)
        .correlate(User)
        .scalar_subquery()
    )
    stmt = select(User, projects).order_by(User.created_at, User.email)
    if q and q.strip():
        stmt = stmt.where(
            or_(
                User.email.icontains(q.strip(), autoescape=True),
                User.display_name.icontains(q.strip(), autoescape=True),
            )
        )
    return paging.run(db, stmt, admin_view)


class NewUser(BaseModel):
    email: str = Field(max_length=254)
    display_name: str = Field(min_length=1, max_length=100)
    is_admin: bool = False


@router.post("")
def create_user(body: NewUser, user: CurrentUser, db: Db):
    require_admin(user)
    try:
        email = normalize_email(body.email)
    except ValueError as e:
        raise ApiError(422, "VALIDATION_ERROR", str(e))
    name = body.display_name.strip()
    if not name:
        raise ApiError(422, "VALIDATION_ERROR", "姓名不能为空")
    if db.scalar(select(User.id).where(User.email == email)):
        raise ApiError(409, "USER_EXISTS", "该邮箱已有账号")
    password = temporary_password()
    created = User(
        email=email,
        display_name=name,
        password_hash=HASHER.hash(password),
        is_admin=body.is_admin,
        must_change_password=True,
    )
    db.add(created)
    db.commit()
    return {"user": admin_view(created, 0), "temporary_password": password}


@router.post("/{user_id}/reset-password")
def reset_password(user_id: UUID, user: CurrentUser, db: Db):
    require_admin(user)
    target = _target(db, user_id)
    password = temporary_password()
    target.password_hash = HASHER.hash(password)
    target.must_change_password = True
    revoke(db, target.id)
    db.commit()
    return {"temporary_password": password}


@router.post("/{user_id}/disable")
def disable(user_id: UUID, user: CurrentUser, db: Db):
    require_admin(user)
    target = _target(db, user_id)
    if target.id == user.id:
        raise ApiError(409, "CANNOT_DISABLE_SELF", "不能停用自己的账号")
    _keep_one_admin(db, target)
    if target.disabled_at is None:
        target.disabled_at = datetime.now(UTC)
    revoke(db, target.id)
    db.commit()
    return admin_view(target, _projects(db, target.id))


@router.post("/{user_id}/enable")
def enable(user_id: UUID, user: CurrentUser, db: Db):
    require_admin(user)
    target = _target(db, user_id)
    target.disabled_at = None
    db.commit()
    return admin_view(target, _projects(db, target.id))


class AdminFlag(BaseModel):
    is_admin: bool


@router.post("/{user_id}/admin")
def set_admin(user_id: UUID, body: AdminFlag, user: CurrentUser, db: Db):
    require_admin(user)
    target = _target(db, user_id)
    if not body.is_admin:
        _keep_one_admin(db, target)
    target.is_admin = body.is_admin
    db.commit()
    return admin_view(target, _projects(db, target.id))
