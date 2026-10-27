"""Shared upload job commands and durable status/event queries."""

import base64
import hashlib
import json
from datetime import UTC, datetime
from uuid import UUID, uuid4

from fastapi import APIRouter, Header, Query
from pydantic import BaseModel, ConfigDict
from sqlalchemy import and_, or_, select

from services.api.auth import CurrentActor
from services.api.db import transaction
from services.api.errors import ApiError
from services.api.job_models import Action, Attempt, Job, JobEvent, Outbox, Upload
from services.api.projects import require_project

router = APIRouter(prefix="/api/v1")
MAX_ATTEMPTS = 3
TERMINAL = {"SUCCEEDED", "FAILED", "CANCELLED"}


class EmptyBody(BaseModel):
    model_config = ConfigDict(extra="forbid")


def now():
    return datetime.now(UTC)


def fail(code, message, status=409):
    raise ApiError(status, code, message)


def action_lookup(session, actor_id, project_id, key, operation, args):
    """Caller holds actor/project locks and has checked current authorization."""
    if not key or len(key) > 128 or not key.isascii() or any(ord(c) < 33 for c in key):
        fail("IDEMPOTENCY_KEY_REQUIRED", "提供有效的 Idempotency-Key。", 422)
    digest = hashlib.sha256(
        json.dumps(
            {"operation": operation, "project_id": str(project_id), "args": args},
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()
    previous = session.scalar(
        select(Action).where(
            Action.actor_id == actor_id,
            Action.project_id == project_id,
            Action.operation == operation,
            Action.idempotency_key == key,
        )
    )
    if previous:
        if previous.request_sha256 != digest:
            fail("IDEMPOTENCY_CONFLICT", "相同操作标识不能用于不同请求。")
        return previous, True
    action = Action(
        id=uuid4(),
        actor_id=actor_id,
        project_id=project_id,
        idempotency_key=key,
        operation=operation,
        request_sha256=digest,
        response={},
        created_at=now(),
    )
    session.add(action)
    return action, False


def emit(session, job, kind, payload=None):
    job.event_sequence += 1
    job.updated_at = now()
    session.add(
        JobEvent(
            project_id=job.project_id,
            job_id=job.id,
            sequence=job.event_sequence,
            kind=kind,
            state=job.state,
            attempt=job.attempt,
            payload=payload or {},
            created_at=now(),
        )
    )


def enqueue(session, job):
    session.add(
        Attempt(
            job_id=job.id,
            project_id=job.project_id,
            number=job.attempt,
            state="QUEUED",
            lease_epoch=job.lease_epoch,
        )
    )
    session.add(
        Outbox(
            project_id=job.project_id,
            job_id=job.id,
            attempt=job.attempt,
            next_attempt_at=now(),
        )
    )
    emit(session, job, "job.queued")


def load_job(session, job_id, actor_id, *, write=False):
    job = session.get(Job, job_id)
    if not job:
        fail("NOT_FOUND", "任务不存在或不可访问。", 404)
    project = require_project(
        session, actor_id, job.project_id, write=write and job.kind != "EXPORT"
    )
    if job.kind == "EXPORT":
        from services.api.exports import authorize
        from services.api.outcome_models import ExportRecord

        authorize(session, actor_id, session.get(ExportRecord, job.id))
    if write:
        if actor_id != job.actor_id and actor_id != project.owner_id:
            fail("ACCESS_DENIED", "仅任务发起人或项目负责人可操作此任务。", 403)
        job = session.scalar(
            select(Job)
            .where(Job.id == job_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    return job


def view_job(session, job, actor_id):
    project = require_project(session, actor_id, job.project_id)
    upload = session.get(Upload, job.upload_id) if job.upload_id else None
    # Viewer analysis permissions include only their own EXPORT jobs.
    from sqlalchemy import text

    role = session.scalar(text("SELECT app.project_role(:p)"), {"p": job.project_id})
    mutable = (
        role in {"owner", "editor"} or job.kind == "EXPORT" and role == "viewer"
    ) and (actor_id == job.actor_id or actor_id == project.owner_id)
    actions = []
    if mutable and job.state not in TERMINAL:
        actions.append("cancel")
    if (
        mutable
        and job.state == "FAILED"
        and job.attempt < MAX_ATTEMPTS
        and (job.error or {}).get("retryable")
        and not job.reserved_bytes
    ):
        actions.append("retry")
    import_job = job.kind == "TXT_IMPORT"
    structured = job.kind in {"TXT_IMPORT", "EXPORT"}
    return {
        "job_id": str(job.id),
        "project_id": str(job.project_id),
        "actor_id": str(job.actor_id),
        "action_id": str(job.action_id),
        "upload_id": str(job.upload_id) if job.upload_id else None,
        "kind": job.kind,
        "filename": upload.filename if upload else None,
        "state": job.state,
        "stage": job.state
        if job.kind == "EXPORT" and job.state in {"FAILED", "CANCELLED"}
        else job.stage
        if structured
        else {
            "QUEUED": "queued",
            "RUNNING": "validating",
            "SUCCEEDED": "validated",
            "FAILED": "failed",
            "CANCELLED": "cancelled",
        }[job.state],
        "attempt": job.attempt,
        "lease_epoch": job.lease_epoch,
        "lease_expires_at": job.lease_expires_at.isoformat()
        if job.lease_expires_at
        else None,
        "progress": job.progress
        if structured
        else {"processed_bytes": job.processed_bytes, "total_bytes": job.total_bytes},
        "error": job.error,
        "result": job.result,
        "result_ref": (
            {
                "material_revision_id": job.result["material_revision_id"],
                "state": "READY",
            }
            if import_job
            else {"export_id": str(job.id), "state": "READY"}
            if job.kind == "EXPORT"
            else {"upload_id": str(job.upload_id), "state": "VALIDATED"}
        )
        if job.result
        else None,
        "allowed_actions": actions,
        "created_at": job.created_at.isoformat(),
        "updated_at": job.updated_at.isoformat(),
    }


def finish_failure(session, job, code, message, retryable=False):
    unclaimed = job.state == "QUEUED"
    job.state = "FAILED"
    job.error = {"code": code, "message": message, "retryable": retryable}
    job.lease_epoch += 1
    job.lease_token = None
    job.lease_expires_at = None
    attempt = session.get(Attempt, (job.id, job.attempt))
    attempt.state, attempt.error, attempt.finished_at = "FAILED", job.error, now()
    if job.kind == "UPLOAD_VALIDATE":
        session.get(Upload, job.upload_id).state = "VALIDATION_FAILED"
    elif unclaimed:
        job.reserved_bytes = 0
    emit(session, job, "job.failed", {"error": job.error})


@router.get("/projects/{project_id}/jobs")
def list_jobs(
    project_id: UUID,
    actor: CurrentActor,
    page_size: int = Query(50, ge=1, le=100),
    cursor: str | None = None,
):
    with transaction(actor.id) as session:
        require_project(session, actor.id, project_id)
        query = select(Job).where(Job.project_id == project_id)
        if cursor:
            try:
                page = json.loads(base64.urlsafe_b64decode(cursor.encode()))
                if page["project_id"] != str(project_id):
                    raise ValueError("project mismatch")
                created = datetime.fromisoformat(page["created_at"])
                last_id = UUID(page["id"])
                if created.tzinfo is None:
                    raise ValueError("missing timezone")
            except (ValueError, KeyError, TypeError):
                fail("INVALID_CURSOR", "分页游标无效。", 422)
            query = query.where(
                or_(
                    Job.created_at < created,
                    and_(Job.created_at == created, Job.id < last_id),
                )
            )
        rows = session.scalars(
            query.order_by(Job.created_at.desc(), Job.id.desc()).limit(page_size + 1)
        ).all()
        jobs, more = rows[:page_size], len(rows) > page_size
        next_cursor = None
        if more:
            last = jobs[-1]
            next_cursor = base64.urlsafe_b64encode(
                json.dumps(
                    {
                        "project_id": str(project_id),
                        "created_at": last.created_at.isoformat(),
                        "id": str(last.id),
                    }
                ).encode()
            ).decode()
        from services.api import exports, outcomes
        from services.api.outcome_models import ExportRecord

        export_rows = [
            session.get(ExportRecord, j.id) for j in jobs if j.kind == "EXPORT"
        ]
        visible = [r for r in export_rows if r is not None]
        outcomes.authorize_dependencies(
            session,
            actor.id,
            project_id,
            [e for r in visible for e in r.authorization_evidence_ids],
            [q for r in visible for q in r.authorization_query_run_ids],
        )
        items = []
        for job in jobs:
            if job.kind == "EXPORT":
                try:
                    exports.authorize(
                        session, actor.id, session.get(ExportRecord, job.id)
                    )
                except ApiError:
                    continue
            items.append(view_job(session, job, actor.id))
        return {"items": items, "next_cursor": next_cursor}


@router.get("/jobs/{job_id}")
def get_job(job_id: UUID, actor: CurrentActor):
    with transaction(actor.id) as session:
        return view_job(session, load_job(session, job_id, actor.id), actor.id)


@router.get("/jobs/{job_id}/events")
def get_events(job_id: UUID, actor: CurrentActor, after: int = Query(0, ge=0)):
    with transaction(actor.id) as session:
        load_job(session, job_id, actor.id)
        events = session.scalars(
            select(JobEvent)
            .where(JobEvent.job_id == job_id, JobEvent.sequence > after)
            .order_by(JobEvent.sequence)
            .limit(100)
        ).all()
        return {
            "items": [
                {
                    "event_id": str(e.id),
                    "job_id": str(e.job_id),
                    "sequence": e.sequence,
                    "kind": e.kind,
                    "state": e.state,
                    "attempt": e.attempt,
                    "payload": e.payload,
                    "created_at": e.created_at.isoformat(),
                }
                for e in events
            ],
            "next_after": events[-1].sequence if events else after,
        }


@router.post("/jobs/{job_id}/cancel")
def cancel(
    job_id: UUID, body: EmptyBody, actor: CurrentActor, idempotency_key: str = Header()
):
    with transaction(actor.id) as session:
        job = load_job(session, job_id, actor.id, write=True)
        action, old = action_lookup(
            session,
            actor.id,
            job.project_id,
            idempotency_key,
            "jobs.cancel",
            {"job_id": str(job_id)},
        )
        if old:
            return action.response
        if job.state == "SUCCEEDED":
            fail("JOB_FINISHED", "已校验材料不会被取消删除。")
        if job.state not in TERMINAL:
            unclaimed = job.state == "QUEUED"
            job.state = "CANCELLED"
            job.lease_epoch += 1
            job.lease_token = None
            job.lease_expires_at = None
            attempt = session.get(Attempt, (job.id, job.attempt))
            attempt.state, attempt.finished_at = "CANCELLED", now()
            if job.kind == "UPLOAD_VALIDATE":
                session.get(Upload, job.upload_id).state = "CANCELLED"
            elif unclaimed:
                job.reserved_bytes = 0
            emit(session, job, "job.cancelled")
        action.response = view_job(session, job, actor.id)
        return action.response


@router.post("/jobs/{job_id}/retry")
def retry(
    job_id: UUID, body: EmptyBody, actor: CurrentActor, idempotency_key: str = Header()
):
    with transaction(actor.id) as session:
        job = load_job(session, job_id, actor.id, write=True)
        action, old = action_lookup(
            session,
            actor.id,
            job.project_id,
            idempotency_key,
            "jobs.retry",
            {"job_id": str(job_id)},
        )
        if old:
            return action.response
        if (
            job.state != "FAILED"
            or job.attempt >= MAX_ATTEMPTS
            or not (job.error or {}).get("retryable")
        ):
            fail("JOB_NOT_RETRYABLE", "此任务不能重试。")
        job.attempt += 1
        job.state, job.error, job.processed_bytes = "QUEUED", None, 0
        if job.kind == "UPLOAD_VALIDATE":
            session.get(Upload, job.upload_id).state = "VALIDATING"
        elif job.kind == "EXPORT":
            from services.api.exports import reserve_export

            if job.reserved_bytes:
                fail("EXPORT_CLEANUP_REQUIRED", "未确认清理导出对象，不能重试。")
            job.reserved_bytes = reserve_export(session, job.project_id)
            job.stage = "QUEUED"
        else:
            from services.api.materials import reserve_import

            if job.reserved_bytes:
                fail("IMPORT_CLEANUP_REQUIRED", "未完成对象清理，不能重试。")
            job.reserved_bytes = reserve_import(session, job.project_id)
            job.stage = "QUEUED"
        enqueue(session, job)
        action.response = view_job(session, job, actor.id)
        return action.response
