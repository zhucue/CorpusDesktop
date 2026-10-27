"""Small durable outbox publisher. Failed publications remain in PostgreSQL."""

import time
from datetime import timedelta

from sqlalchemy import select

from services.api.db import transaction
from services.api.job_models import Job, Outbox
from services.api.jobs import emit, finish_failure, now
from workers.app import app
from workers.validation import locked_job


def send(job_id, attempt):
    with transaction() as session:
        kind = session.scalar(select(Job.kind).where(Job.id == job_id))
    task, queue = {
        "UPLOAD_VALIDATE": ("workers.validate_upload", "corpus.jobs"),
        "TXT_IMPORT": ("workers.import_txt", "corpus.index"),
        "EXPORT": ("workers.export_results", "corpus.index"),
    }[kind]
    app.send_task(
        task,
        args=[str(job_id), attempt],
        retry=False,
        delivery_mode=2,
        queue=queue,
        timeout=5,
        confirm_timeout=5,
    )


def dispatch_once(publisher=send):
    """One publish per transaction; uncertain acknowledgements may duplicate delivery."""
    with transaction(None) as session:
        event = session.scalar(
            select(Outbox)
            .where(
                Outbox.published_at.is_(None),
                Outbox.failures < 20,
                Outbox.next_attempt_at <= now(),
            )
            .order_by(Outbox.next_attempt_at)
            .with_for_update(skip_locked=True)
            .limit(1)
        )
        if event is None:
            return False
        job = session.scalar(
            select(Job).where(Job.id == event.job_id).with_for_update()
        )
        if job.state != "QUEUED" or job.attempt != event.attempt:
            event.published_at = (
                now()
            )  # superseded; do not deliver a cancelled/old attempt
            return True
        try:
            publisher(job.id, job.attempt)
        except Exception:  # noqa: BLE001 - persist safe failure, not broker credentials
            event.failures += 1
            event.last_error = "BROKER_UNAVAILABLE"
            event.next_attempt_at = now() + timedelta(seconds=5)
            emit(
                session,
                job,
                "job.delivery_failed",
                {
                    "failures": event.failures,
                    "retry_at": event.next_attempt_at.isoformat(),
                },
            )
            if event.failures >= 20:
                finish_failure(
                    session,
                    job,
                    "DELIVERY_FAILED",
                    "任务投递多次失败，可人工重试。",
                    True,
                )
            return False
        event.published_at, event.last_error = now(), None
        emit(session, job, "job.dispatched")
        return True


def expire_one_lease():
    with transaction(None) as session:
        job_id = session.scalar(
            select(Job.id)
            .where(Job.state == "RUNNING", Job.lease_expires_at <= now())
            .limit(1)
        )
        if job_id is None:
            return
        job, _ = locked_job(session, job_id)
        if job.state == "RUNNING" and job.lease_expires_at <= now():
            finish_failure(
                session, job, "WORKER_LEASE_EXPIRED", "执行租约过期，可人工重试。", True
            )


def main():
    from workers import index_dispatcher, research_dispatcher, source_sync_dispatcher

    while True:
        try:
            expire_one_lease()
            sent = dispatch_once()
            source_sync_dispatcher.expire_one_lease()
            sent = source_sync_dispatcher.dispatch_once() or sent
            index_dispatcher.expire_one_lease()
            sent = index_dispatcher.dispatch_once() or sent
            research_dispatcher.expire_one_lease()
            sent = research_dispatcher.dispatch_once() or sent
        except Exception:  # noqa: BLE001 - bounded polling after DB outage
            print("dispatcher: database operation failed", flush=True)
            sent = False
        time.sleep(0.1 if sent else 2)


if __name__ == "__main__":
    main()
