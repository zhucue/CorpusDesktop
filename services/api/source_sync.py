"""Administrator-only synchronization commands, progress and acquisition reports."""

import base64
import hashlib
import json
from datetime import datetime
from pathlib import Path
from uuid import UUID, uuid4

from fastapi import APIRouter, Header, Query
from sqlalchemy import and_, func, or_, select, text

from services.api.auth import CurrentActor
from services.api.catalog import require_admin
from services.api.catalog_models import CatalogSource
from services.api.db import transaction
from services.api.jobs import EmptyBody, fail, now
from services.api.source_sync_models import (
    Acquisition,
    SyncAction,
    SyncAttempt,
    SyncEvent,
    SyncOutbox,
    SyncRun,
)

router = APIRouter(prefix="/api/v1/admin")
CONNECTOR = "tatoeba-cmn-eng-v1"
IDENTITY_FIELDS = ("name", "publisher", "entry_kind", "official_url")
TERMINAL = {"SUCCEEDED", "FAILED", "CANCELLED"}
EMPTY_PROGRESS = {
    "processed_bytes": 0,
    "total_bytes": None,
    "processed_records": 0,
    "total_records": None,
    "file_name": None,
}


def identity(source):
    return {key: source.metadata_json[key] for key in IDENTITY_FIELDS}


def fixed_identity():
    seed = json.loads(
        Path(__file__).with_name("catalog_seed.json").read_text(encoding="utf-8")
    )
    row = next(row for row in seed["items"] if row["source_id"] == "D12")
    return {key: row["metadata"][key] for key in IDENTITY_FIELDS}


def source_lock(db, source_id):
    if source_id != "D12":
        fail("CONNECTOR_UNAVAILABLE", "该来源尚未接入同步。", 422)
    lock_source(db, source_id)
    row = db.scalar(
        select(CatalogSource)
        .where(CatalogSource.source_id == source_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if row is None:
        fail("SOURCE_NOT_FOUND", "来源不存在。", 404)
    return row


def lock_source(db, source_id):
    db.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:key,0))"),
        {"key": "catalog:" + source_id},
    )


def validate_identity(source, expected=None):
    if identity(source) != (expected or fixed_identity()):
        fail("SOURCE_IDENTITY_CHANGED", "来源身份已变更，固定连接器不能用于此登记。")


def emit(db, run, kind, data=None):
    run.event_sequence += 1
    run.updated_at = now()
    db.add(
        SyncEvent(
            run_id=run.id,
            sequence=run.event_sequence,
            event_type=kind,
            data=data or {},
            created_at=now(),
        )
    )


def enqueue(db, run):
    db.add(
        SyncAttempt(
            run_id=run.id,
            number=run.attempt,
            state="QUEUED",
            lease_epoch=run.lease_epoch,
        )
    )
    db.flush()
    db.add(SyncOutbox(run_id=run.id, attempt=run.attempt, next_attempt_at=now()))
    emit(db, run, "sync.queued")


def view(run):
    return {
        "id": str(run.id),
        "source_id": run.source_id,
        "connector_id": run.connector_id,
        "source_revision": run.source_revision,
        "source_identity": run.source_identity,
        "state": run.state,
        "stage": run.stage,
        "attempt": run.attempt,
        "created_at": run.created_at.isoformat(),
        "updated_at": run.updated_at.isoformat(),
        "progress": run.progress,
        "result": run.result,
        "error": run.error,
        "allowed_actions": {
            "cancel": run.state not in TERMINAL,
            "retry": run.state == "FAILED"
            and run.attempt < 3
            and bool((run.error or {}).get("retryable")),
        },
    }


def load(db, run_id, *, lock=False):
    query = select(SyncRun).where(SyncRun.id == run_id)
    if lock:
        query = query.with_for_update().execution_options(populate_existing=True)
    row = db.scalar(query)
    if row is None:
        fail("SYNC_RUN_NOT_FOUND", "同步任务不存在或不可访问。", 404)
    return row


def action(db, actor_id, operation, key, args):
    if not key or len(key) > 128 or not key.isascii() or any(ord(c) < 33 for c in key):
        fail("IDEMPOTENCY_KEY_REQUIRED", "提供有效的 Idempotency-Key。", 422)
    digest = hashlib.sha256(
        json.dumps(args, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    previous = db.scalar(
        select(SyncAction).where(
            SyncAction.actor_id == actor_id,
            SyncAction.operation == operation,
            SyncAction.idempotency_key == key,
        )
    )
    if previous:
        if previous.request_sha256 != digest:
            fail("IDEMPOTENCY_CONFLICT", "相同操作标识不能用于不同请求。")
        return previous, True
    row = SyncAction(
        id=uuid4(),
        actor_id=actor_id,
        operation=operation,
        idempotency_key=key,
        request_sha256=digest,
        response={},
        created_at=now(),
    )
    db.add(row)
    return row, False


def action_view(row, run):
    row.response = {
        "action_id": str(row.id),
        "sync_run_id": str(run.id),
        "job_id": str(run.id),
        "state": run.state,
        "run": view(run),
    }
    return row.response


def finish_failure(db, run, code, message, retryable=False):
    run.state = run.stage = "FAILED"
    run.error = {"code": code, "message": message, "retryable": retryable}
    run.lease_epoch += 1
    run.lease_token = run.lease_expires_at = None
    attempt = db.get(SyncAttempt, (run.id, run.attempt))
    attempt.state, attempt.error, attempt.finished_at = "FAILED", run.error, now()
    emit(db, run, "sync.failed", {"error": run.error})


@router.post("/sources/{source_id}/sync-runs", status_code=202)
def start(
    source_id: str,
    body: EmptyBody,
    actor: CurrentActor,
    idempotency_key: str = Header(),
):
    with transaction(actor.id) as db:
        require_admin(db, actor)
        source = source_lock(db, source_id)
        row, old = action(
            db, actor.id, "sync.start", idempotency_key, {"source_id": source_id}
        )
        if old:
            return row.response
        validate_identity(source)
        if db.scalar(
            select(SyncRun.id).where(
                SyncRun.source_id == source_id, SyncRun.state.in_(["QUEUED", "RUNNING"])
            )
        ):
            fail("SYNC_ALREADY_ACTIVE", "该来源已有同步任务。")
        previous = db.scalar(
            select(Acquisition)
            .where(
                Acquisition.source_id == source_id,
                Acquisition.connector_id == CONNECTOR,
                Acquisition.source_identity == identity(source),
            )
            .order_by(Acquisition.created_at.desc(), Acquisition.id.desc())
            .limit(1)
        )
        run = SyncRun(
            id=uuid4(),
            source_id=source_id,
            actor_id=actor.id,
            connector_id=CONNECTOR,
            source_revision=source.revision,
            source_identity=identity(source),
            previous_acquisition_id=previous.id if previous else None,
            state="QUEUED",
            stage="QUEUED",
            attempt=1,
            lease_epoch=0,
            event_sequence=0,
            progress=dict(EMPTY_PROGRESS),
            created_at=now(),
            updated_at=now(),
        )
        db.add(run)
        db.flush()
        enqueue(db, run)
        return action_view(row, run)


@router.get("/sources/{source_id}/sync-runs")
def list_runs(
    source_id: str,
    actor: CurrentActor,
    cursor: str | None = None,
    page_size: int = Query(50, ge=1, le=100),
):
    with transaction(actor.id) as db:
        require_admin(db, actor)
        source = source_lock(db, source_id)
        query = select(SyncRun).where(SyncRun.source_id == source_id)
        total = db.scalar(
            select(func.count())
            .select_from(SyncRun)
            .where(SyncRun.source_id == source_id)
        )
        if cursor:
            try:
                page = json.loads(base64.urlsafe_b64decode(cursor))
                created, ident = (
                    datetime.fromisoformat(page["created_at"]),
                    UUID(page["id"]),
                )
                if page["source_id"] != source_id or created.tzinfo is None:
                    raise ValueError("cursor scope")
            except (ValueError, KeyError, TypeError):
                fail("INVALID_CURSOR", "分页游标无效。", 422)
            query = query.where(
                or_(
                    SyncRun.created_at < created,
                    and_(SyncRun.created_at == created, SyncRun.id < ident),
                )
            )
        rows = list(
            db.scalars(
                query.order_by(SyncRun.created_at.desc(), SyncRun.id.desc()).limit(
                    page_size + 1
                )
            )
        )
        next_cursor = None
        if len(rows) > page_size:
            last = rows[page_size - 1]
            next_cursor = base64.urlsafe_b64encode(
                json.dumps(
                    {
                        "source_id": source_id,
                        "created_at": last.created_at.isoformat(),
                        "id": str(last.id),
                    }
                ).encode()
            ).decode()
        active = db.scalar(
            select(SyncRun.id).where(
                SyncRun.source_id == source_id, SyncRun.state.in_(["QUEUED", "RUNNING"])
            )
        )
        return {
            "items": [view(row) for row in rows[:page_size]],
            "total": total,
            "next_cursor": next_cursor,
            "allowed_actions": {
                "start": active is None and identity(source) == fixed_identity()
            },
        }


@router.get("/sync-runs/{sync_run_id}")
def report(sync_run_id: UUID, actor: CurrentActor):
    with transaction(actor.id) as db:
        require_admin(db, actor)
        return view(load(db, sync_run_id))


@router.get("/sync-runs/{sync_run_id}/events")
def events(
    sync_run_id: UUID,
    actor: CurrentActor,
    after_sequence: int = Query(0, ge=0),
    page_size: int = Query(100, ge=1, le=100),
):
    with transaction(actor.id) as db:
        require_admin(db, actor)
        load(db, sync_run_id)
        rows = list(
            db.scalars(
                select(SyncEvent)
                .where(
                    SyncEvent.run_id == sync_run_id, SyncEvent.sequence > after_sequence
                )
                .order_by(SyncEvent.sequence)
                .limit(page_size)
            )
        )
        return {
            "items": [
                {
                    "sequence": e.sequence,
                    "event_type": e.event_type,
                    "data": e.data,
                    "created_at": e.created_at.isoformat(),
                }
                for e in rows
            ],
            "next_sequence": rows[-1].sequence if rows else after_sequence,
        }


def mutate(sync_run_id, actor, key, operation):
    with transaction(actor.id) as db:
        require_admin(db, actor)
        hint = load(db, sync_run_id)
        source = source_lock(db, hint.source_id)
        run = load(db, sync_run_id, lock=True)
        row, old = action(
            db, actor.id, operation, key, {"sync_run_id": str(sync_run_id)}
        )
        if old:
            return row.response
        if operation == "sync.cancel":
            if run.state not in TERMINAL:
                run.state = run.stage = "CANCELLED"
                run.lease_epoch += 1
                run.lease_token = run.lease_expires_at = None
                attempt = db.get(SyncAttempt, (run.id, run.attempt))
                attempt.state, attempt.finished_at = "CANCELLED", now()
                emit(db, run, "sync.cancelled")
        else:
            validate_identity(source, run.source_identity)
            if not view(run)["allowed_actions"]["retry"]:
                fail("SYNC_NOT_RETRYABLE", "任务不可重试或已达到三次尝试上限。")
            if db.scalar(
                select(SyncRun.id).where(
                    SyncRun.source_id == run.source_id,
                    SyncRun.state.in_(["QUEUED", "RUNNING"]),
                )
            ):
                fail("SYNC_ALREADY_ACTIVE", "该来源已有同步任务。")
            # A different administrator does not silently take over the initiating identity.
            from services.api.models import User

            user = db.get(User, run.actor_id)
            if not user or not user.is_active or not user.is_platform_admin:
                fail("SYNC_ACTOR_REVOKED", "原发起人已失去权限，请创建新任务。", 403)
            run.attempt += 1
            run.state = run.stage = "QUEUED"
            run.error, run.progress = None, dict(EMPTY_PROGRESS)
            enqueue(db, run)
        return action_view(row, run)


@router.post("/sync-runs/{sync_run_id}/cancel")
def cancel(
    sync_run_id: UUID,
    body: EmptyBody,
    actor: CurrentActor,
    idempotency_key: str = Header(),
):
    return mutate(sync_run_id, actor, idempotency_key, "sync.cancel")


@router.post("/sync-runs/{sync_run_id}/retry", status_code=202)
def retry(
    sync_run_id: UUID,
    body: EmptyBody,
    actor: CurrentActor,
    idempotency_key: str = Header(),
):
    return mutate(sync_run_id, actor, idempotency_key, "sync.retry")
