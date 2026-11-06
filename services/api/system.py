"""Health and system information (contracts/p7.md §六)."""

import os
from urllib.parse import urlsplit

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from engine.kb import embed
from services.api.auth import CurrentUser
from services.api.db import engine

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
