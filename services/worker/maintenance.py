"""Daily maintenance (contracts/p9.md §五), run by worker-light (services.worker.main.maintenance_enabled).

The worker checks every hour; when DATA_DIR/maintenance/last-run is missing or older than 24 hours it
- purges soft-deleted projects past PROJECT_PURGE_DAYS (services.api.projects.purge_project: rows, files and
  the project_purge audit entry),
- deletes the files of exports that finished more than EXPORT_RETENTION_DAYS ago (downloads then answer 410),
- deletes the upload folders of imports that failed or were cancelled more than EXPORT_RETENTION_DAYS ago,
then writes last-run and one log line. A failing step is logged; the others still run, and the next day's run
retries it."""

import logging
import os
import shutil
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy import func, select

from services.api.db import data_dir, session
from services.api.models import Job

log = logging.getLogger("worker")
INTERVAL = timedelta(hours=24)
ENDED = ("succeeded", "failed", "cancelled")


def retention_days() -> int:
    return int(os.environ.get("EXPORT_RETENTION_DAYS") or 30)


def last_run_path():
    return data_dir() / "maintenance" / "last-run"


def due(now=None) -> bool:
    path = last_run_path()
    if not path.exists():
        return True
    now = time.time() if now is None else now
    return now - path.stat().st_mtime >= INTERVAL.total_seconds()


def purge_projects() -> int:
    from services.api.projects import expired_project_ids, purge_project

    with session() as db:
        ids = expired_project_ids(db)
    purged = 0
    for pid in ids:
        try:
            with session() as db:
                purged += bool(purge_project(db, pid))
        except Exception:
            log.exception("maintenance: purging project %s failed", pid)
    return purged


def _old_jobs(kind, states, cutoff):
    with session() as db:
        return db.scalars(
            select(Job.id).where(
                Job.kind == kind, Job.state.in_(states), Job.finished_at < cutoff
            )
        ).all()


def remove_exports(cutoff) -> int:
    removed = 0
    folder = data_dir() / "exports"
    for jid in _old_jobs("export", ["succeeded"], cutoff):
        for f in folder.glob(f"{jid}.*"):
            f.unlink(missing_ok=True)
            removed += 1
    return removed


def remove_uploads(cutoff) -> int:
    """Upload folders (params.dir) of imports that failed or were cancelled. A retry reuses the folder of the
    original job, so a folder goes only when every import job using it has ended, the last before cutoff."""
    folder = Job.params["dir"].astext
    with session() as db:
        dirs = db.scalars(
            select(folder)
            .select_from(Job)
            .where(Job.kind == "import", folder.is_not(None))
            .group_by(folder)
            .having(
                func.bool_and(Job.state.in_(ENDED)),
                func.bool_or(Job.state.in_(["failed", "cancelled"])),
                func.max(Job.finished_at) < cutoff,
            )
        ).all()
    root = (data_dir() / "uploads").resolve()
    removed = 0
    for d in dirs:
        path = Path(d).resolve()
        if path.parent != root or not path.exists():
            continue
        shutil.rmtree(path, ignore_errors=True)
        removed += 1
    return removed


def run():
    """One maintenance run; returns the counts it logged."""
    cutoff = datetime.now(UTC) - timedelta(days=retention_days())
    counts, failed = {}, []
    for name, step in (
        ("projects", purge_projects),
        ("exports", lambda: remove_exports(cutoff)),
        ("uploads", lambda: remove_uploads(cutoff)),
    ):
        try:
            counts[name] = step()
        except Exception:
            log.exception("maintenance: %s failed", name)
            failed.append(name)
    path = last_run_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(datetime.now(UTC).isoformat(timespec="seconds"), encoding="utf-8")
    log.info(
        "maintenance: purged %s projects, removed %s export files and %s upload folders%s",
        counts.get("projects", "-"),
        counts.get("exports", "-"),
        counts.get("uploads", "-"),
        f"; failed: {', '.join(failed)}" if failed else "",
    )
    return counts


def run_if_due():
    if due():
        run()
