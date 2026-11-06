"""Account administration (contracts/p7.md §五): platform admins list, create, reset, disable and enable
users and grant or revoke admin; P9 (contracts/p9.md §三): projects, owner change and jobs across the
platform. Browser sessions only (access.require_admin)."""

import secrets
import string
import time
from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select

from services.api.access import Paging, require_admin
from services.api.audit import record
from services.api.auth import HASHER, CurrentUser, Db, normalize_email, revoke
from services.api.errors import ApiError, not_found
from services.api.models import (
    AnnotationLayer,
    Corpus,
    Job,
    KbDocument,
    Project,
    ProjectMember,
    User,
)
from services.api.storage import corpus_dir, data_dir, dir_bytes, kb_dir, upload_dir
from services.api.views import job_view, user_view

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
def create_user(body: NewUser, request: Request, user: CurrentUser, db: Db):
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
    db.flush()
    record(
        db,
        user,
        "user_create",
        "user",
        created.id,
        email,
        detail={"is_admin": body.is_admin},
        request=request,
    )
    db.commit()
    return {"user": admin_view(created, 0), "temporary_password": password}


@router.post("/{user_id}/reset-password")
def reset_password(user_id: UUID, request: Request, user: CurrentUser, db: Db):
    require_admin(user)
    target = _target(db, user_id)
    password = temporary_password()
    target.password_hash = HASHER.hash(password)
    target.must_change_password = True
    revoke(db, target.id)
    record(db, user, "password_reset", "user", target.id, target.email, request=request)
    db.commit()
    return {"temporary_password": password}


@router.post("/{user_id}/disable")
def disable(user_id: UUID, request: Request, user: CurrentUser, db: Db):
    require_admin(user)
    target = _target(db, user_id)
    if target.id == user.id:
        raise ApiError(409, "CANNOT_DISABLE_SELF", "不能停用自己的账号")
    _keep_one_admin(db, target)
    if target.disabled_at is None:
        target.disabled_at = datetime.now(UTC)
    revoke(db, target.id)
    record(db, user, "user_disable", "user", target.id, target.email, request=request)
    db.commit()
    return admin_view(target, _projects(db, target.id))


@router.post("/{user_id}/enable")
def enable(user_id: UUID, request: Request, user: CurrentUser, db: Db):
    require_admin(user)
    target = _target(db, user_id)
    target.disabled_at = None
    record(db, user, "user_enable", "user", target.id, target.email, request=request)
    db.commit()
    return admin_view(target, _projects(db, target.id))


class AdminFlag(BaseModel):
    is_admin: bool


@router.post("/{user_id}/admin")
def set_admin(
    user_id: UUID, body: AdminFlag, request: Request, user: CurrentUser, db: Db
):
    require_admin(user)
    target = _target(db, user_id)
    if not body.is_admin:
        _keep_one_admin(db, target)
    if target.is_admin != body.is_admin:
        action = "admin_grant" if body.is_admin else "admin_revoke"
        record(db, user, action, "user", target.id, target.email, request=request)
    target.is_admin = body.is_admin
    db.commit()
    return admin_view(target, _projects(db, target.id))


# ---- projects and jobs across the platform (contracts/p9.md §三) ----

ops_router = APIRouter(prefix="/api/admin")
DISK_TTL = 600  # seconds disk_bytes of a project is cached
_disk_cache: dict = {}


def project_disk_bytes(db, project_id) -> int:
    """Corpus, knowledge base, upload and export files of the project; cached DISK_TTL seconds per process."""
    hit = _disk_cache.get(project_id)
    if hit and time.monotonic() - hit[0] < DISK_TTL:
        return hit[1]
    corpora = db.scalars(select(Corpus.id).where(Corpus.project_id == project_id))
    docs = db.scalars(select(KbDocument.id).where(KbDocument.project_id == project_id))
    jobs = db.scalars(select(Job.id).where(Job.project_id == project_id)).all()
    total = sum(dir_bytes(corpus_dir(c)) for c in corpora)
    total += sum(dir_bytes(kb_dir(d)) for d in docs)
    total += sum(dir_bytes(upload_dir(j)) for j in jobs)
    exports = data_dir() / "exports"
    total += sum(dir_bytes(f) for j in jobs for f in exports.glob(f"{j}.*"))
    _disk_cache[project_id] = (time.monotonic(), total)
    return total


def _owner(db, project):
    """The project's owner: its creator while still owner, else the first owner by email."""
    row = db.execute(
        select(User)
        .join(ProjectMember, ProjectMember.user_id == User.id)
        .where(ProjectMember.project_id == project.id, ProjectMember.role == "owner")
        .order_by((User.id != project.created_by), User.email)
        .limit(1)
    ).scalar()
    return user_view(row) if row else None


def _count_of(model, column):
    return (
        select(func.count())
        .select_from(model)
        .where(column == Project.id)
        .correlate(Project)
        .scalar_subquery()
    )


def admin_project_view(db, p, members, corpora, layers, kb_documents):
    return {
        "id": p.id,
        "name": p.name,
        "owner": _owner(db, p),
        "members": members,
        "corpora": corpora,
        "layers": layers,
        "kb_documents": kb_documents,
        "disk_bytes": project_disk_bytes(db, p.id),
        "created_at": p.created_at,
        "deleted_at": p.deleted_at,
    }


@ops_router.get("/projects")
def list_projects(
    user: CurrentUser,
    db: Db,
    paging: Paging,
    q: Annotated[str | None, Query(max_length=254)] = None,
    deleted: bool | None = None,
):
    """Every project, deleted ones included (with deleted_at); deleted=1 only deleted, deleted=0 only
    projects in use. q: part of the name or of an owner's email."""
    require_admin(user)
    stmt = select(
        Project,
        _count_of(ProjectMember, ProjectMember.project_id),
        _count_of(Corpus, Corpus.project_id),
        _count_of(AnnotationLayer, AnnotationLayer.project_id),
        _count_of(KbDocument, KbDocument.project_id),
    ).order_by(Project.created_at.desc(), Project.id)
    if deleted is not None:
        stmt = stmt.where(
            Project.deleted_at.is_not(None) if deleted else Project.deleted_at.is_(None)
        )
    if q and q.strip():
        q = q.strip()
        owner_match = (
            select(ProjectMember.project_id)
            .join(User, User.id == ProjectMember.user_id)
            .where(
                ProjectMember.role == "owner",
                User.email.icontains(q, autoescape=True),
            )
        )
        stmt = stmt.where(
            or_(
                Project.name.icontains(q, autoescape=True),
                Project.id.in_(owner_match),
            )
        )
    return paging.run(db, stmt, lambda *row: admin_project_view(db, *row))


class OwnerInput(BaseModel):
    user_id: UUID


@ops_router.post("/projects/{project_id}/owner")
def set_owner(
    project_id: UUID, body: OwnerInput, request: Request, user: CurrentUser, db: Db
):
    """The user becomes owner (added as a member when not one); the previous owners become editors."""
    require_admin(user)
    project = db.get(Project, project_id, with_for_update=True)
    if not project:
        raise not_found("项目")
    target = _target(db, body.user_id)
    if target.disabled_at is not None:
        raise ApiError(409, "USER_DISABLED", "该用户已停用，不能设为负责人")
    owners = db.scalars(
        select(ProjectMember)
        .where(ProjectMember.project_id == project_id, ProjectMember.role == "owner")
        .with_for_update()
    ).all()
    previous = []
    for m in owners:
        if m.user_id != target.id:
            m.role = "editor"
            previous.append(str(m.user_id))
    member = db.get(ProjectMember, (project_id, target.id))
    if member is None:
        db.add(ProjectMember(project_id=project_id, user_id=target.id, role="owner"))
    else:
        member.role = "owner"
    record(
        db,
        user,
        "project_owner",
        "project",
        project.id,
        project.name,
        project.id,
        {
            "to": str(target.id),
            "to_email": target.email,
            "from": previous,
            "added": member is None,
        },
        request,
    )
    db.commit()
    counts = [
        db.scalar(select(func.count()).select_from(m).where(c == project.id))
        for m, c in (
            (ProjectMember, ProjectMember.project_id),
            (Corpus, Corpus.project_id),
            (AnnotationLayer, AnnotationLayer.project_id),
            (KbDocument, KbDocument.project_id),
        )
    ]
    return admin_project_view(db, project, *counts)


def admin_job_view(j, project_name):
    return {**job_view(j), "project_name": project_name}


@ops_router.get("/jobs")
def list_jobs(
    user: CurrentUser,
    db: Db,
    paging: Paging,
    state: Annotated[str | None, Query(max_length=100)] = None,
    kind: Annotated[str | None, Query(max_length=200)] = None,
):
    """Jobs of every project and of built-in corpora (project_name null), newest first; state / kind: one
    value or comma-separated."""
    require_admin(user)
    stmt = (
        select(Job, Project.name)
        .outerjoin(Project, Project.id == Job.project_id)
        .order_by(Job.created_at.desc(), Job.id)
    )
    if state:
        stmt = stmt.where(Job.state.in_([s for s in state.split(",") if s]))
    if kind:
        stmt = stmt.where(Job.kind.in_([k for k in kind.split(",") if k]))
    return paging.run(db, stmt, admin_job_view)
