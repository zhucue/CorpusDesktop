import os
import shutil
from datetime import UTC, datetime, timedelta
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field
from sqlalchemy import delete, exists, func, select

from services.api import audit
from services.api.access import (
    MANAGE,
    Paging,
    member_role,
    require_project,
    token_project,
)
from services.api.auth import CurrentUser, Db
from services.api.errors import ApiError, forbidden, not_found
from services.api.jobs import ACTIVE, stop
from services.api.label_sets import human_only
from services.api.models import (
    AnnotationLayer,
    AuditLog,
    Corpus,
    Job,
    KbDocument,
    KbTerm,
    Project,
    ProjectMember,
    User,
)
from services.api.storage import corpus_dir, data_dir, kb_dir, upload_dir
from services.api.views import project_view

router = APIRouter(prefix="/api/projects")
me_router = APIRouter(prefix="/api/me")


def purge_days() -> int:
    """PROJECT_PURGE_DAYS: a soft-deleted project can be restored this long, then the worker purges it."""
    return int(os.environ.get("PROJECT_PURGE_DAYS") or 7)


def purge_cutoff() -> datetime:
    return datetime.now(UTC) - timedelta(days=purge_days())


class ProjectInput(BaseModel):
    name: str = Field(min_length=1, max_length=200)


class MemberInput(BaseModel):
    role: Literal["owner", "editor", "annotator", "viewer"]


def member_view(user, role):
    return {"user_id": user.id, "email": user.email, "role": role}


@router.get("")
def list_projects(user: CurrentUser, db: Db, paging: Paging):
    stmt = (
        select(Project, ProjectMember.role)
        .join(ProjectMember, ProjectMember.project_id == Project.id)
        .where(ProjectMember.user_id == user.id, Project.deleted_at.is_(None))
        .order_by(Project.created_at, Project.id)
    )
    if token_project(user):
        stmt = stmt.where(Project.id == token_project(user))
    return paging.run(db, stmt, project_view)


@router.post("")
def create_project(body: ProjectInput, user: CurrentUser, db: Db):
    if token_project(user):
        raise forbidden()
    project = Project(name=body.name.strip(), created_by=user.id)
    db.add(project)
    db.flush()
    db.add(ProjectMember(project_id=project.id, user_id=user.id, role="owner"))
    db.commit()
    return project_view(project, "owner")


@router.get("/{project_id}")
def get_project(project_id: UUID, user: CurrentUser, db: Db):
    role = require_project(db, project_id, user)
    return project_view(db.get(Project, project_id), role)


@router.patch("/{project_id}")
def rename_project(project_id: UUID, body: ProjectInput, user: CurrentUser, db: Db):
    human_only(user)
    role = require_project(db, project_id, user, MANAGE)
    project = db.get(Project, project_id)
    project.name = body.name.strip()
    db.commit()
    return project_view(project, role)


def _count(db, model, *where):
    return db.scalar(select(func.count()).select_from(model).where(*where)) or 0


@router.get("/{project_id}/usage")
def project_usage(project_id: UUID, user: CurrentUser, db: Db):
    """What deleting the project removes: corpora, annotation layers, notes, other KB documents, terms, members."""
    require_project(db, project_id, user)
    kb = KbDocument.project_id == project_id
    return {
        "corpora": _count(db, Corpus, Corpus.project_id == project_id),
        "layers": _count(db, AnnotationLayer, AnnotationLayer.project_id == project_id),
        "notes": _count(db, KbDocument, kb, KbDocument.kind == "note"),
        "kb_documents": _count(db, KbDocument, kb, KbDocument.kind != "note"),
        "terms": _count(db, KbTerm, KbTerm.project_id == project_id),
        "members": _count(db, ProjectMember, ProjectMember.project_id == project_id),
    }


@router.delete("/{project_id}", status_code=204)
def delete_project(project_id: UUID, request: Request, user: CurrentUser, db: Db):
    """Owner only, cookie session only. Soft delete: from now on the project answers 404 (access.project_role)
    and keeps its data and files; owners or admins can restore it for PROJECT_PURGE_DAYS, then the worker
    purges it (purge_project)."""
    human_only(user)
    require_project(db, project_id, user, MANAGE)
    project = db.get(Project, project_id, with_for_update=True)
    project.deleted_at = datetime.now(UTC)
    # its queued / running jobs stop now; after a restore they can be retried
    active = db.scalars(
        select(Job)
        .where(Job.project_id == project_id, Job.state.in_(ACTIVE))
        .order_by(Job.created_at)
        .with_for_update()
    ).all()
    for job in active:
        stop(db, job)
    audit.record(
        db,
        user,
        "project_delete",
        "project",
        project.id,
        project.name,
        project.id,
        request=request,
    )
    db.commit()


def deleted_view(p, role=None):
    return {
        **project_view(p, role),
        "deleted_at": p.deleted_at,
        "purge_at": p.deleted_at + timedelta(days=purge_days()),
    }


@me_router.get("/deleted-projects")
def my_deleted_projects(user: CurrentUser, db: Db, paging: Paging):
    """Projects the user owns that were deleted within PROJECT_PURGE_DAYS, newest first."""
    human_only(user)
    stmt = (
        select(Project, ProjectMember.role)
        .join(ProjectMember, ProjectMember.project_id == Project.id)
        .where(
            ProjectMember.user_id == user.id,
            ProjectMember.role == "owner",
            Project.deleted_at.is_not(None),
            Project.deleted_at > purge_cutoff(),
        )
        .order_by(Project.deleted_at.desc(), Project.id)
    )
    return paging.run(db, stmt, deleted_view)


def _purged():
    return ApiError(410, "PURGED", "项目已超过恢复期限，无法恢复")


@router.post("/{project_id}/restore")
def restore_project(project_id: UUID, request: Request, user: CurrentUser, db: Db):
    """Owner or platform admin, browser session. 410 PURGED past PROJECT_PURGE_DAYS or once purged."""
    human_only(user)
    project = db.get(Project, project_id, with_for_update=True)
    if project is None:
        purged = db.scalar(
            select(
                exists().where(
                    AuditLog.action == "project_purge",
                    AuditLog.target_id == str(project_id),
                )
            )
        )
        raise _purged() if purged else not_found("项目")
    role = member_role(db, project_id, user.id)
    if role is None and not user.is_admin:
        raise not_found("项目")
    if role != "owner" and not user.is_admin:
        raise forbidden()
    if project.deleted_at is None:
        raise ApiError(409, "NOT_DELETED", "项目未被删除")
    if project.deleted_at <= purge_cutoff():
        raise _purged()
    project.deleted_at = None
    audit.record(
        db,
        user,
        "project_restore",
        "project",
        project.id,
        project.name,
        project.id,
        request=request,
    )
    db.commit()
    return project_view(project, role)


def expired_project_ids(db) -> list[UUID]:
    """Soft-deleted projects past PROJECT_PURGE_DAYS, oldest deletion first (worker maintenance job)."""
    return list(
        db.scalars(
            select(Project.id)
            .where(
                Project.deleted_at.is_not(None), Project.deleted_at <= purge_cutoff()
            )
            .order_by(Project.deleted_at)
        )
    )


def purge_project(db, project_id) -> bool:
    """Hard delete of a soft-deleted project: database rows (cascade) and its corpus, knowledge base, upload
    and export files; writes audit project_purge (no actor). Commits: pass a plain session
    (services.api.db.session()). False (nothing done) when the project is gone or was restored meanwhile."""
    project = db.get(Project, project_id, with_for_update=True)
    if project is None or project.deleted_at is None:
        db.rollback()
        return False
    corpora = db.scalars(select(Corpus.id).where(Corpus.project_id == project_id)).all()
    docs = db.scalars(
        select(KbDocument.id).where(KbDocument.project_id == project_id)
    ).all()
    jobs = db.scalars(select(Job.id).where(Job.project_id == project_id)).all()
    audit.record(
        db,
        None,
        "project_purge",
        "project",
        project.id,
        project.name,
        project.id,
        {"deleted_at": project.deleted_at.isoformat()},
    )
    # layers first: their label sets (also project rows) are referenced with ON DELETE RESTRICT
    db.execute(delete(AnnotationLayer).where(AnnotationLayer.project_id == project_id))
    db.delete(project)
    db.commit()
    for cid in corpora:
        shutil.rmtree(corpus_dir(cid), ignore_errors=True)
    for did in docs:
        shutil.rmtree(kb_dir(did), ignore_errors=True)
    for jid in jobs:
        shutil.rmtree(upload_dir(jid), ignore_errors=True)
        for f in (data_dir() / "exports").glob(f"{jid}.*"):
            f.unlink(missing_ok=True)
    return True


@router.get("/{project_id}/members")
def list_members(project_id: UUID, user: CurrentUser, db: Db, paging: Paging):
    require_project(db, project_id, user)
    stmt = (
        select(User, ProjectMember.role)
        .join(ProjectMember, ProjectMember.user_id == User.id)
        .where(ProjectMember.project_id == project_id)
        .order_by(User.email)
    )
    return paging.run(db, stmt, member_view)


def _check_last_owner(db, project_id, user_id):
    owners = db.scalars(
        select(ProjectMember.user_id)
        .where(ProjectMember.project_id == project_id, ProjectMember.role == "owner")
        .with_for_update()
    ).all()
    if owners == [user_id]:
        raise ApiError(409, "LAST_OWNER", "项目至少保留一名所有者")


@router.put("/{project_id}/members/{user_id}")
def put_member(
    project_id: UUID,
    user_id: UUID,
    body: MemberInput,
    request: Request,
    user: CurrentUser,
    db: Db,
):
    # membership changes only from a cookie session, never an agent token
    human_only(user)
    require_project(db, project_id, user, MANAGE)
    target = db.get(User, user_id)
    if not target:
        raise not_found("用户")
    member = db.get(ProjectMember, (project_id, user_id))
    if member is None:
        member = ProjectMember(project_id=project_id, user_id=user_id, role=body.role)
        db.add(member)
        audit.record(
            db,
            user,
            "member_add",
            "user",
            target.id,
            target.email,
            project_id,
            {"role": body.role},
            request,
        )
    elif member.role != body.role:
        if member.role == "owner":
            _check_last_owner(db, project_id, user_id)
        audit.record(
            db,
            user,
            "member_role",
            "user",
            target.id,
            target.email,
            project_id,
            {"from": member.role, "to": body.role},
            request,
        )
        member.role = body.role
    db.commit()
    return member_view(target, member.role)


@router.delete("/{project_id}/members/{user_id}", status_code=204)
def delete_member(
    project_id: UUID, user_id: UUID, request: Request, user: CurrentUser, db: Db
):
    # membership changes only from a cookie session, never an agent token
    human_only(user)
    require_project(db, project_id, user, MANAGE)
    member = db.get(ProjectMember, (project_id, user_id))
    if member is None:
        raise not_found("成员")
    if member.role == "owner":
        _check_last_owner(db, project_id, user_id)
    audit.record(
        db,
        user,
        "member_remove",
        "user",
        user_id,
        db.get(User, user_id).email,
        project_id,
        {"role": member.role},
        request,
    )
    db.delete(member)
    db.commit()
