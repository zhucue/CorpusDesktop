"""Administrator-only private index builds, admission and progress."""

import base64
import hashlib
import json
import os
from datetime import datetime
from uuid import UUID, uuid4

from fastapi import APIRouter, Header, Query
from pydantic import BaseModel, ConfigDict
from sqlalchemy import and_, func, or_, select, text

from services.api.auth import CurrentActor
from services.api.catalog import require_admin
from services.api.db import transaction
from services.api.index_models import (
    IndexAction,
    IndexAttempt,
    IndexEvent,
    IndexOutbox,
    IndexRun,
    SourceIndex,
)
from services.api.jobs import EmptyBody, fail, now
from services.api.source_sync import (
    EMPTY_PROGRESS,
    identity,
    source_lock,
    validate_identity,
)
from services.api.source_sync_models import Acquisition

router = APIRouter(prefix="/api/v1/admin")
TERMINAL = {"SUCCEEDED", "FAILED", "CANCELLED"}


class BuildInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    acquisition_id: UUID


def recipe():
    from pipelines.query.source_recipe import RECIPE_ID, RECIPE_SHA256

    return {"id": RECIPE_ID, "sha256": RECIPE_SHA256}


def quota_lock(db):
    db.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended('index-storage',0))")
    )


def reserve(db):
    quota_lock(db)
    amount = int(os.environ.get("INDEX_BUILD_RESERVED_BYTES", str(8 * 1024**3)))
    limit = int(os.environ.get("INDEX_STORAGE_QUOTA_BYTES", str(20 * 1024**3)))
    if amount <= 0 or limit <= 0:
        raise RuntimeError("Invalid index quota configuration")
    used = db.scalar(select(func.coalesce(func.sum(SourceIndex.artifact_bytes), 0)))
    reserved = db.scalar(select(func.coalesce(func.sum(IndexRun.reserved_bytes), 0)))
    if used + reserved + amount > limit:
        fail(
            "INDEX_QUOTA_EXCEEDED",
            "索引存储预算不足，包含已登记产物、活动任务和待清理预留。",
        )
    return amount


def emit(db, run, kind, data=None):
    run.event_sequence += 1
    run.updated_at = now()
    db.add(
        IndexEvent(
            run_id=run.id,
            sequence=run.event_sequence,
            event_type=kind,
            data=data or {},
            created_at=now(),
        )
    )


def enqueue(db, run):
    db.add(
        IndexAttempt(
            run_id=run.id,
            number=run.attempt,
            state="QUEUED",
            lease_epoch=run.lease_epoch,
        )
    )
    db.flush()
    db.add(IndexOutbox(run_id=run.id, attempt=run.attempt, next_attempt_at=now()))
    emit(db, run, "index.queued")


def view(run):
    return {
        "id": str(run.id),
        "source_id": run.source_id,
        "acquisition_id": str(run.acquisition_id),
        "recipe": run.recipe,
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
            and run.reserved_bytes == 0
            and bool((run.error or {}).get("retryable")),
        },
    }


def load(db, run_id, *, lock=False):
    query = select(IndexRun).where(IndexRun.id == run_id)
    if lock:
        query = query.with_for_update().execution_options(populate_existing=True)
    row = db.scalar(query)
    if row is None:
        fail("INDEX_RUN_NOT_FOUND", "索引构建任务不存在或不可访问。", 404)
    return row


def action(db, actor_id, operation, key, args):
    if not key or len(key) > 128 or not key.isascii() or any(ord(c) < 33 for c in key):
        fail("IDEMPOTENCY_KEY_REQUIRED", "提供有效的 Idempotency-Key。", 422)
    digest = hashlib.sha256(
        json.dumps(args, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    previous = db.scalar(
        select(IndexAction).where(
            IndexAction.actor_id == actor_id,
            IndexAction.operation == operation,
            IndexAction.idempotency_key == key,
        )
    )
    if previous:
        if previous.request_sha256 != digest:
            fail("IDEMPOTENCY_CONFLICT", "相同操作标识不能用于不同请求。")
        return previous, True
    row = IndexAction(
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


def action_view(row, run, existing=False):
    row.response = {
        "action_id": str(row.id),
        "index_run_id": str(run.id),
        "existing": existing,
        "job_id": str(run.id),
        "state": run.state,
        "run": view(run),
    }
    return row.response


def finish_failure(db, run, code, message, retryable=False):
    if run.state == "QUEUED":
        run.reserved_bytes = 0
    run.state = run.stage = "FAILED"
    run.error = {"code": code, "message": message, "retryable": retryable}
    run.lease_epoch += 1
    run.lease_token = run.lease_expires_at = None
    attempt = db.get(IndexAttempt, (run.id, run.attempt))
    attempt.state, attempt.error, attempt.finished_at = "FAILED", run.error, now()
    emit(db, run, "index.failed", {"error": run.error})


@router.post("/sources/{source_id}/index-builds", status_code=202)
def start(
    source_id: str,
    body: BuildInput,
    actor: CurrentActor,
    idempotency_key: str = Header(),
):
    with transaction(actor.id) as db:
        require_admin(db, actor)
        source = source_lock(db, source_id)
        row, old = action(
            db,
            actor.id,
            "indexes.build",
            idempotency_key,
            {"source_id": source_id, "acquisition_id": str(body.acquisition_id)},
        )
        if old:
            return row.response
        acquisition = db.get(Acquisition, body.acquisition_id)
        if not acquisition or acquisition.source_id != source_id:
            fail("ACQUISITION_NOT_FOUND", "固定来源暂存版本不存在。", 404)
        validate_identity(source, acquisition.source_identity)
        selected = recipe()
        previous = db.scalar(
            select(SourceIndex).where(
                SourceIndex.acquisition_id == acquisition.id,
                SourceIndex.recipe_sha256 == selected["sha256"],
            )
        )
        if previous:
            return action_view(row, load(db, previous.run_id), existing=True)
        if db.scalar(
            select(IndexRun.id).where(
                IndexRun.source_id == source_id,
                IndexRun.state.in_(["QUEUED", "RUNNING"]),
            )
        ):
            fail("INDEX_ALREADY_ACTIVE", "该来源已有索引构建任务。")
        reservation = reserve(db)
        run = IndexRun(
            id=uuid4(),
            source_id=source_id,
            acquisition_id=acquisition.id,
            actor_id=actor.id,
            source_identity=identity(source),
            recipe=selected,
            recipe_sha256=selected["sha256"],
            state="QUEUED",
            stage="QUEUED",
            attempt=1,
            lease_epoch=0,
            event_sequence=0,
            reserved_bytes=reservation,
            progress=dict(EMPTY_PROGRESS),
            created_at=now(),
            updated_at=now(),
        )
        db.add(run)
        db.flush()
        enqueue(db, run)
        return action_view(row, run)


@router.get("/sources/{source_id}/index-builds")
def list_runs(
    source_id: str,
    actor: CurrentActor,
    cursor: str | None = None,
    page_size: int = Query(50, ge=1, le=100),
):
    with transaction(actor.id) as db:
        require_admin(db, actor)
        from services.api.catalog import get_row
        from services.api.source_sync import lock_source

        lock_source(db, source_id)
        get_row(db, source_id)
        query = select(IndexRun).where(IndexRun.source_id == source_id)
        total = db.scalar(
            select(func.count())
            .select_from(IndexRun)
            .where(IndexRun.source_id == source_id)
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
                    IndexRun.created_at < created,
                    and_(IndexRun.created_at == created, IndexRun.id < ident),
                )
            )
        rows = list(
            db.scalars(
                query.order_by(IndexRun.created_at.desc(), IndexRun.id.desc()).limit(
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
            select(IndexRun.id).where(
                IndexRun.source_id == source_id,
                IndexRun.state.in_(["QUEUED", "RUNNING"]),
            )
        )
        return {
            "items": [view(row) for row in rows[:page_size]],
            "total": total,
            "next_cursor": next_cursor,
            "allowed_actions": {"start": source_id == "D12" and active is None},
        }


@router.get("/index-builds/{index_run_id}")
def report(index_run_id: UUID, actor: CurrentActor):
    with transaction(actor.id) as db:
        require_admin(db, actor)
        return view(load(db, index_run_id))


@router.get("/index-builds/{index_run_id}/events")
def events(
    index_run_id: UUID,
    actor: CurrentActor,
    after_sequence: int = Query(0, ge=0),
    page_size: int = Query(100, ge=1, le=100),
):
    with transaction(actor.id) as db:
        require_admin(db, actor)
        load(db, index_run_id)
        rows = list(
            db.scalars(
                select(IndexEvent)
                .where(
                    IndexEvent.run_id == index_run_id,
                    IndexEvent.sequence > after_sequence,
                )
                .order_by(IndexEvent.sequence)
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


def mutate(index_run_id, actor, key, operation):
    with transaction(actor.id) as db:
        require_admin(db, actor)
        hint = load(db, index_run_id)
        source = source_lock(db, hint.source_id)
        run = load(db, index_run_id, lock=True)
        row, old = action(
            db, actor.id, operation, key, {"index_run_id": str(index_run_id)}
        )
        if old:
            return row.response
        if operation == "indexes.cancel":
            if run.state not in TERMINAL:
                if run.state == "QUEUED":
                    run.reserved_bytes = 0
                run.state = run.stage = "CANCELLED"
                run.lease_epoch += 1
                run.lease_token = run.lease_expires_at = None
                attempt = db.get(IndexAttempt, (run.id, run.attempt))
                attempt.state, attempt.finished_at = "CANCELLED", now()
                emit(db, run, "indexes.cancelled")
        else:
            validate_identity(source, run.source_identity)
            completed = db.scalar(
                select(SourceIndex).where(
                    SourceIndex.acquisition_id == run.acquisition_id,
                    SourceIndex.recipe_sha256 == run.recipe_sha256,
                )
            )
            if completed:
                fail(
                    "INDEX_ALREADY_BUILT",
                    "相同输入与配置已有完整索引，请复用已成功构建结果。",
                )
            if run.reserved_bytes:
                fail(
                    "INDEX_CLEANUP_REQUIRED",
                    "上一尝试的对象占用尚未确认清理，保留容量预留；核查后再重试。",
                )
            if not view(run)["allowed_actions"]["retry"]:
                fail("INDEX_NOT_RETRYABLE", "任务不可重试或已达到三次尝试上限。")
            if db.scalar(
                select(IndexRun.id).where(
                    IndexRun.source_id == run.source_id,
                    IndexRun.state.in_(["QUEUED", "RUNNING"]),
                )
            ):
                fail("INDEX_ALREADY_ACTIVE", "该来源已有索引构建任务。")
            # A different administrator does not silently take over the initiating identity.
            from services.api.models import User

            user = db.get(User, run.actor_id)
            if not user or not user.is_active or not user.is_platform_admin:
                fail("INDEX_ACTOR_REVOKED", "原发起人已失去权限，请创建新任务。", 403)
            if run.recipe != recipe():
                fail("INDEX_RECIPE_CHANGED", "构建配置已改变，请创建新任务。")
            run.reserved_bytes = reserve(db)
            run.attempt += 1
            run.state = run.stage = "QUEUED"
            run.error, run.progress = None, dict(EMPTY_PROGRESS)
            enqueue(db, run)
        return action_view(row, run)


@router.post("/index-builds/{index_run_id}/cancel")
def cancel(
    index_run_id: UUID,
    body: EmptyBody,
    actor: CurrentActor,
    idempotency_key: str = Header(),
):
    return mutate(index_run_id, actor, idempotency_key, "indexes.cancel")


@router.post("/index-builds/{index_run_id}/retry", status_code=202)
def retry(
    index_run_id: UUID,
    body: EmptyBody,
    actor: CurrentActor,
    idempotency_key: str = Header(),
):
    return mutate(index_run_id, actor, idempotency_key, "indexes.retry")
