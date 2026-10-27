"""Single worker process: polls `jobs` with FOR UPDATE SKIP LOCKED and runs one job at a time."""

import logging
import time
from datetime import UTC, datetime

from sqlalchemy import select, update

from services.api.db import transaction
from services.api.errors import ApiError
from services.api.jobs import settle_corpus
from services.api.models import Corpus, Job

log = logging.getLogger("worker")
POLL_SECONDS = 1.0


class Cancelled(Exception):
    pass


class JobFailed(Exception):
    def __init__(self, code, message):
        super().__init__(message)
        self.code, self.message = code, message


class Run:
    """Handle passed to tasks: progress updates double as cancellation checks."""

    def __init__(self, job):
        self.id, self.kind, self.params = job.id, job.kind, job.params
        self.owner_id, self.project_id = job.owner_id, job.project_id

    def progress(self, done, total=None, message=""):
        with transaction() as db:
            state = db.scalar(
                update(Job)
                .where(Job.id == self.id)
                .values(progress={"done": done, "total": total, "message": message})
                .returning(Job.state)
            )
        if state != "running":
            raise Cancelled

    def lock(self, db):
        """Lock the job row inside the task's final transaction; cancel waits for it."""
        state = db.scalar(select(Job.state).where(Job.id == self.id).with_for_update())
        if state != "running":
            raise Cancelled

    def succeed(self, db, result):
        job = db.get(Job, self.id)
        job.state, job.result, job.finished_at = "succeeded", result, now()
        if job.progress.get("total") is not None:
            job.progress = {
                **job.progress,
                "done": job.progress["total"],
                "message": "",
            }


def now():
    return datetime.now(UTC)


def claim():
    with transaction() as db:
        job = db.scalar(
            select(Job)
            .where(Job.state == "queued")
            .order_by(Job.created_at)
            .limit(1)
            .with_for_update(skip_locked=True)
        )
        if job is None:
            return None
        job.state, job.started_at = "running", now()
        return Run(job)


def recover():
    """Jobs left running by a previous worker process cannot resume; fail them for manual retry."""
    with transaction() as db:
        jobs = db.scalars(select(Job).where(Job.state == "running")).all()
        for job in jobs:
            job.state, job.finished_at = "failed", now()
            job.error = {"code": "WORKER_RESTARTED", "message": "执行中断，请重试"}
            if job.kind in ("import", "index"):
                _corpus_failed(db, job.params["corpus_id"], job.error["message"])


def _corpus_failed(db, corpus_id, message):
    corpus = db.get(Corpus, corpus_id)
    if corpus:
        corpus.status, corpus.error = "failed", message


def _fail(run, error):
    with transaction() as db:
        updated = db.execute(
            update(Job)
            .where(Job.id == run.id, Job.state == "running")
            .values(state="failed", error=error, finished_at=now())
        ).rowcount
        if updated and run.kind in ("import", "index"):
            _corpus_failed(db, run.params["corpus_id"], error["message"])


def execute(run):
    from services.worker import tasks

    log.info("job %s %s start", run.id, run.kind)
    try:
        tasks.HANDLERS[run.kind](run)
    except Cancelled:
        log.info("job %s cancelled", run.id)
        if run.kind in ("import", "index"):
            with transaction() as db:
                settle_corpus(db, run.params["corpus_id"], run.id)
        return
    except (JobFailed, ApiError) as e:
        _fail(run, {"code": e.code, "message": e.message})
        log.info("job %s failed: %s", run.id, e.message)
        return
    except Exception as e:
        log.exception("job %s crashed", run.id)
        _fail(run, {"code": "INTERNAL", "message": str(e)[:500]})
        return
    log.info("job %s done", run.id)


def run_once():
    run = claim()
    if run:
        execute(run)
    return run is not None


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    recover()
    log.info("worker ready")
    while True:
        if not run_once():
            time.sleep(POLL_SECONDS)


if __name__ == "__main__":
    main()
