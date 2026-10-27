"""Bounded durable delivery for project research tasks."""

from datetime import timedelta

from sqlalchemy import select

from services.api import research as api
from services.api.db import transaction
from services.api.jobs import now
from services.api.research_models import QueryRun, ResearchOutbox, ResearchTask
from workers.app import app
from workers.research import locked


def send(task_id, attempt):
    app.send_task(
        "workers.research",
        args=[str(task_id), attempt],
        queue="corpus.index",
        retry=False,
        delivery_mode=2,
        timeout=5,
        confirm_timeout=5,
    )


def dispatch_once(publisher=send):
    with transaction() as db:
        item = db.scalar(
            select(ResearchOutbox)
            .where(
                ResearchOutbox.published_at.is_(None),
                ResearchOutbox.failures < 20,
                ResearchOutbox.next_attempt_at <= now(),
            )
            .order_by(ResearchOutbox.next_attempt_at)
            .with_for_update(skip_locked=True)
            .limit(1)
        )
        if not item:
            return False
        task = db.get(ResearchTask, item.task_id)
        if task.state != "QUEUED" or task.attempt != item.attempt:
            item.published_at = now()
            return True
        try:
            publisher(task.id, task.attempt)
        except Exception:  # noqa: BLE001
            item.failures += 1
            item.next_attempt_at = now() + timedelta(seconds=5)
            if item.failures >= 20:
                task, _, _ = locked(db, item.task_id)
                if task and task.attempt == item.attempt and task.state == "QUEUED":
                    unclaimed = task.lease_epoch == 0
                    api.finish_failure(
                        db,
                        task,
                        "DELIVERY_FAILED",
                        "任务投递多次失败，可人工重试。",
                        True,
                    )
                    if task.run_id and task.phase == "FIRST_PAGE" and unclaimed:
                        db.get(QueryRun, task.run_id).reserved_bytes = 0
            return False
        item.published_at = now()
        return True


def expire_one_lease():
    with transaction() as db:
        ident = db.scalar(
            select(ResearchTask.id)
            .where(
                ResearchTask.state == "RUNNING", ResearchTask.lease_expires_at <= now()
            )
            .limit(1)
        )
        if ident:
            task, _, _ = locked(db, ident)
            if task.state == "RUNNING" and task.lease_expires_at <= now():
                api.finish_failure(
                    db,
                    task,
                    "WORKER_LEASE_EXPIRED",
                    "任务租约过期，结果未发布；需核查暂存对象。",
                    True,
                )
                if task.phase == "FIRST_PAGE" and task.run_id:
                    # First-page work only reads source/cache and cannot write a result object.
                    db.get(QueryRun, task.run_id).reserved_bytes = 0
