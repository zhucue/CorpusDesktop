"""Worker process: polls `jobs` with FOR UPDATE SKIP LOCKED and runs one job at a time.

Several workers may run side by side. WORKER_KINDS limits the job kinds one takes (empty = all);
a running job's heartbeat_at is refreshed every HEARTBEAT_SECONDS, and jobs whose heartbeat went
stale (their worker died) are failed at startup and by a periodic reaper."""

import logging
import os
import socket
import threading
import time
from datetime import UTC, datetime, timedelta

from sqlalchemy import and_, func, or_, select, update

from services.api.db import transaction
from services.api.errors import ApiError
from services.api.jobs import settle_corpus, settle_kb_document, settle_layer
from services.api.models import JOB_KINDS, Corpus, Job

HEAVY_KINDS = ("import", "index")
log = logging.getLogger("worker")
POLL_SECONDS = 1.0
HEARTBEAT_SECONDS = 30
REAP_SECONDS = 300
STALE_AFTER = timedelta(minutes=10)
LEGACY_STALE_AFTER = timedelta(hours=24)
WORKER_ID = os.environ.get("WORKER_ID") or socket.gethostname()


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


def worker_kinds():
    """WORKER_KINDS: comma list of job kinds this worker takes; empty = all kinds.
    WORKER_HEAVY=0 additionally drops the long-running import/index kinds."""
    kinds = [
        k.strip() for k in os.environ.get("WORKER_KINDS", "").split(",") if k.strip()
    ]
    if os.environ.get("WORKER_HEAVY", "1") == "0":
        kinds = [k for k in kinds or JOB_KINDS if k not in HEAVY_KINDS]
    return kinds


def claim(kinds=None):
    kinds = worker_kinds() if kinds is None else kinds
    with transaction() as db:
        q = select(Job).where(Job.state == "queued")
        if kinds:
            q = q.where(Job.kind.in_(kinds))
        job = db.scalar(
            q.order_by(Job.created_at).limit(1).with_for_update(skip_locked=True)
        )
        if job is None:
            return None
        job.state, job.started_at = "running", now()
        job.heartbeat_at, job.worker_id = func.now(), WORKER_ID
        return Run(job)


def heartbeat(job_id):
    with transaction() as db:
        db.execute(
            update(Job)
            .where(Job.id == job_id, Job.state == "running")
            .values(heartbeat_at=func.now())
        )


def _beat(job_id, stop):
    while not stop.wait(HEARTBEAT_SECONDS):
        try:
            heartbeat(job_id)
        except Exception:
            log.exception("heartbeat for job %s failed", job_id)


def recover():
    """Fail running jobs whose worker is gone: heartbeat older than STALE_AFTER, or (jobs claimed
    before heartbeats existed) no heartbeat and started more than LEGACY_STALE_AFTER ago.
    Jobs of live workers are never touched. They cannot resume; the user retries manually."""
    with transaction() as db:
        jobs = db.scalars(
            select(Job)
            .where(
                Job.state == "running",
                or_(
                    Job.heartbeat_at < func.now() - STALE_AFTER,
                    and_(
                        Job.heartbeat_at.is_(None),
                        Job.started_at < func.now() - LEGACY_STALE_AFTER,
                    ),
                ),
            )
            .with_for_update(skip_locked=True)
        ).all()
        for job in jobs:
            log.warning(
                "job %s %s stale (worker %s), failing", job.id, job.kind, job.worker_id
            )
            job.state, job.finished_at = "failed", now()
            job.error = {"code": "WORKER_RESTARTED", "message": "执行中断，请重试"}
            if job.kind in ("import", "index"):
                _corpus_failed(db, job.params["corpus_id"], job.error["message"])
            if job.kind == "preannotate":
                settle_layer(db, job, job.error["message"])
            if job.kind == "kb_import":
                settle_kb_document(db, job, job.error["message"])


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
        if updated and run.kind == "kb_import":
            settle_kb_document(db, run, error["message"])


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
        stop = threading.Event()
        beat = threading.Thread(target=_beat, args=(run.id, stop), daemon=True)
        beat.start()
        try:
            execute(run)
        finally:
            stop.set()
            beat.join()
    return run is not None


def reap():
    while True:
        time.sleep(REAP_SECONDS)
        try:
            recover()
        except Exception:
            log.exception("reaper failed")


def warm_embeddings():
    """Load (on first start: download) the knowledge base embedding model while jobs run."""
    from engine.kb import embed

    started = time.monotonic()
    try:
        embed.load(download=True)
        log.info(
            "embedding model %s ready in %.1f s",
            embed.model_name(),
            time.monotonic() - started,
        )
    except embed.EmbedUnavailable as e:
        log.warning("embedding model unavailable: %s", e)


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    recover()
    threading.Thread(target=reap, daemon=True).start()
    threading.Thread(target=warm_embeddings, daemon=True).start()
    log.info("worker %s ready, kinds: %s", WORKER_ID, ",".join(worker_kinds()) or "all")
    while True:
        if not run_once():
            time.sleep(POLL_SECONDS)


if __name__ == "__main__":
    main()
