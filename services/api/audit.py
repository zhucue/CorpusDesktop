"""Audit log (contracts/p9.md §四): sensitive operations, written in the transaction of the operation itself.
Platform admins list everything (GET /admin/audit); project owners list their project's entries."""

from datetime import datetime, time
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query, Request
from sqlalchemy import select

from services.api.access import (
    MANAGE,
    Paging,
    human_only,
    require_admin,
    require_project,
)
from services.api.auth import CurrentUser, Db
from services.api.errors import ApiError
from services.api.models import AuditLog

router = APIRouter(prefix="/api")

ACTIONS = (
    "login",
    "login_failed",
    "password_change",
    "password_reset",
    "user_create",
    "user_disable",
    "user_enable",
    "admin_grant",
    "admin_revoke",
    "member_add",
    "member_remove",
    "member_role",
    "project_delete",
    "project_restore",
    "project_purge",
    "project_owner",
    "corpus_delete",
    "document_delete",
    "subcorpus_delete",
    "layer_delete",
    "kb_document_delete",
    "job_cancel_admin",
)


def client_ip(request: Request | None) -> str | None:
    """Last X-Forwarded-For address (the one our nginx appended), else the peer address."""
    if request is None:
        return None
    forwarded = [
        a.strip()
        for a in request.headers.get("x-forwarded-for", "").split(",")
        if a.strip()
    ]
    if forwarded:
        return forwarded[-1]
    return request.client.host if request.client else None


def record(
    db,
    user,
    action,
    target_type,
    target_id,
    target_name,
    project_id=None,
    detail=None,
    request=None,
):
    """Add one entry to the session; the caller's commit writes it with the operation. user None = system."""
    assert action in ACTIONS, action
    db.add(
        AuditLog(
            actor_id=user.id if user is not None else None,
            actor_email=user.email if user is not None else None,
            action=action,
            target_type=target_type,
            target_id=str(target_id) if target_id is not None else None,
            target_name=target_name,
            project_id=project_id,
            detail=detail or {},
            ip=client_ip(request),
        )
    )


def audit_view(a: AuditLog):
    return {
        "id": a.id,
        "at": a.at,
        "actor_id": a.actor_id,
        "actor_email": a.actor_email,
        "action": a.action,
        "target_type": a.target_type,
        "target_id": a.target_id,
        "target_name": a.target_name,
        "project_id": a.project_id,
        "detail": a.detail,
        "ip": a.ip,
    }


def _bound(value: str, end=False) -> datetime:
    """YYYY-MM-DD (whole day, local time zone) or an ISO date-time."""
    try:
        if len(value) == 10:
            day = datetime.fromisoformat(value).date()
            return datetime.combine(day, time.max if end else time.min).astimezone()
        moment = datetime.fromisoformat(value)
    except ValueError:
        raise ApiError(422, "VALIDATION_ERROR", f"日期格式不正确：{value}")
    return moment if moment.tzinfo else moment.astimezone()


def _filtered(stmt, actor, action, project_id, start, end):
    if actor and actor.strip():
        actor = actor.strip()
        try:
            stmt = stmt.where(AuditLog.actor_id == UUID(actor))
        except ValueError:
            stmt = stmt.where(AuditLog.actor_email.icontains(actor, autoescape=True))
    if action:
        stmt = stmt.where(AuditLog.action.in_([a for a in action.split(",") if a]))
    if project_id:
        stmt = stmt.where(AuditLog.project_id == project_id)
    if start:
        stmt = stmt.where(AuditLog.at >= _bound(start))
    if end:
        stmt = stmt.where(AuditLog.at <= _bound(end, end=True))
    return stmt.order_by(AuditLog.at.desc(), AuditLog.id.desc())


Actor = Annotated[str | None, Query(max_length=254)]
Action = Annotated[str | None, Query(max_length=500)]
From = Annotated[str | None, Query(alias="from", max_length=40)]
To = Annotated[str | None, Query(alias="to", max_length=40)]


@router.get("/admin/audit")
def admin_audit(
    user: CurrentUser,
    db: Db,
    paging: Paging,
    actor: Actor = None,
    action: Action = None,
    project_id: UUID | None = None,
    start: From = None,
    end: To = None,
):
    """actor: user id or part of the email; action: one or comma-separated; from / to: date or date-time."""
    require_admin(user)
    stmt = _filtered(select(AuditLog), actor, action, project_id, start, end)
    return paging.run(db, stmt, audit_view)


@router.get("/projects/{project_id}/audit")
def project_audit(
    project_id: UUID,
    user: CurrentUser,
    db: Db,
    paging: Paging,
    actor: Actor = None,
    action: Action = None,
    start: From = None,
    end: To = None,
):
    """The project's entries, for its owners (browser session)."""
    human_only(user)
    require_project(db, project_id, user, MANAGE)
    stmt = _filtered(select(AuditLog), actor, action, project_id, start, end)
    return paging.run(db, stmt, audit_view)
