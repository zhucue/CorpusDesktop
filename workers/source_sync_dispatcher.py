"""Source-domain outbox; broker messages carry only the run ID and attempt."""

from datetime import timedelta

from sqlalchemy import select

from services.api.db import transaction
from services.api.jobs import now
from services.api.source_sync import emit, finish_failure
from services.api.source_sync_models import SyncOutbox, SyncRun
from workers.app import app
from workers.source_sync import locked


def send(run_id, attempt):
    app.send_task(
        "workers.sync_tatoeba",
        args=[str(run_id), attempt],
        retry=False,
        delivery_mode=2,
        queue="corpus.sync",
        timeout=5,
        confirm_timeout=5,
    )


def dispatch_once(publisher=send):
    with transaction() as db:
        event = db.scalar(
            select(SyncOutbox)
            .where(
                SyncOutbox.published_at.is_(None),
                SyncOutbox.failures < 20,
                SyncOutbox.next_attempt_at <= now(),
            )
            .order_by(SyncOutbox.next_attempt_at)
            .with_for_update(skip_locked=True)
            .limit(1)
        )
        if not event:
            return False
        run = db.scalar(
            select(SyncRun).where(SyncRun.id == event.run_id).with_for_update()
        )
        if run.state != "QUEUED" or run.attempt != event.attempt:
            event.published_at = now()
            return True
        try:
            publisher(run.id, run.attempt)
        except Exception:  # noqa: BLE001
            event.failures += 1
            event.last_error = "BROKER_UNAVAILABLE"
            event.next_attempt_at = now() + timedelta(seconds=5)
            emit(db, run, "sync.delivery_failed", {"failures": event.failures})
            if event.failures >= 20:
                finish_failure(
                    db, run, "DELIVERY_FAILED", "任务投递失败，可人工重试。", True
                )
            return False
        event.published_at, event.last_error = now(), None
        emit(db, run, "sync.dispatched")
        return True


def expire_one_lease():
    with transaction() as db:
        ident = db.scalar(
            select(SyncRun.id)
            .where(SyncRun.state == "RUNNING", SyncRun.lease_expires_at <= now())
            .limit(1)
        )
        if ident:
            run, _ = locked(db, ident)
            if run.state == "RUNNING" and run.lease_expires_at <= now():
                finish_failure(
                    db, run, "WORKER_LEASE_EXPIRED", "执行租约过期，可人工重试。", True
                )
