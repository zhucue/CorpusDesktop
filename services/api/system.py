"""Health and system information (contracts/p7.md §六); admin system view (contracts/p9.md §三)."""

import json
import os
import shutil
import time
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlsplit

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from engine.kb import embed
from services.api.access import require_admin
from services.api.auth import CurrentUser
from services.api.db import data_dir, engine
from services.api.storage import dir_bytes

router = APIRouter(prefix="/api")


@router.get("/health")
def health():
    try:
        with engine().connect() as conn:
            conn.execute(text("SELECT 1"))
    except SQLAlchemyError:
        return JSONResponse({"ok": False, "db": False}, status_code=503)
    return {"ok": True, "db": True}


def _env(name):
    return (os.environ.get(name) or "").strip()


def host_of(url: str) -> str | None:
    """Host name only: no scheme, port, path or credentials."""
    try:
        return urlsplit(url).hostname if url else None
    except ValueError:
        return None


def _embed_ready() -> bool:
    if embed.remote():
        return bool(_env("EMBED_BASE_URL") and _env("EMBED_MODEL"))
    try:
        embed.load(download=False)  # cache only; already loaded at startup when present
    except embed.EmbedUnavailable:
        return False
    return True


@router.get("/system/info")
def info(_: CurrentUser):
    base, model_id = _env("MODEL_BASE_URL"), _env("MODEL_ID")
    remote = embed.remote()
    return {
        "version": _env("APP_VERSION") or "dev",
        "model": {
            "configured": bool(base and model_id),
            "host": host_of(base),
            "model_id": model_id or None,
        },
        "embed": {
            "mode": "remote" if remote else "local",
            "host": host_of(_env("EMBED_BASE_URL")) if remote else None,
            "model": (_env("EMBED_MODEL") or None) if remote else embed.model_name(),
            "ready": _embed_ready(),
        },
    }


HEALTHY_SECONDS = 90  # as the compose worker healthcheck
SIZE_TTL = 600  # seconds the data-directory sizes are cached
_sizes: dict = {}


def _mtime(path: Path):
    return datetime.fromtimestamp(path.stat().st_mtime, UTC)


def _worker(path: Path):
    """DATA_DIR/worker-health/<WORKER_ID>: mtime = last sign of life; content may be JSON {"kinds": [...]}
    or comma-separated kinds (empty / unreadable = unknown, kinds null)."""
    kinds = None
    try:
        raw = path.read_text(encoding="utf-8").strip()
    except (OSError, UnicodeDecodeError):
        raw = ""
    if raw:
        try:
            value = json.loads(raw)
            kinds = value.get("kinds") if isinstance(value, dict) else None
        except ValueError:
            kinds = [k.strip() for k in raw.split(",") if k.strip()]
    seen = _mtime(path)
    return {
        "id": path.name,
        "kinds": kinds,
        "last_seen": seen,
        "healthy": (datetime.now(UTC) - seen).total_seconds() < HEALTHY_SECONDS,
    }


def dir_bytes_cached(path: Path) -> int:
    hit = _sizes.get(str(path))
    if hit and time.monotonic() - hit[0] < SIZE_TTL:
        return hit[1]
    size = dir_bytes(path)
    _sizes[str(path)] = (time.monotonic(), size)
    return size


def last_backup_at():
    """Newest backup under BACKUP_DIR (directories from scripts/backup.sh, by their manifest.txt when
    present); None when the directory is not set, not mounted or empty."""
    root = _env("BACKUP_DIR")
    if not root or not Path(root).is_dir():
        return None
    times = []
    try:
        for entry in Path(root).iterdir():
            manifest = entry / "manifest.txt"
            if manifest.is_file():
                times.append(_mtime(manifest))
            elif entry.is_dir():
                times.append(_mtime(entry))
    except OSError:
        return None
    return max(times, default=None)


@router.get("/admin/system")
def admin_system(user: CurrentUser):
    require_admin(user)
    base = info(user)
    health = data_dir() / "worker-health"
    workers = (
        [_worker(p) for p in sorted(health.iterdir()) if p.is_file()]
        if health.is_dir()
        else []
    )
    try:
        usage = shutil.disk_usage(data_dir())
        disk = {"path": str(data_dir()), "total": usage.total, "free": usage.free}
    except OSError:
        disk = {"path": str(data_dir()), "total": None, "free": None}
    return {
        **base,
        "workers": workers,
        "disk": disk,
        "search_cache_bytes": dir_bytes_cached(data_dir() / "search-cache"),
        "data_bytes": dir_bytes_cached(data_dir()),
        "last_backup_at": last_backup_at(),
    }
