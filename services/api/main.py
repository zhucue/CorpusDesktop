"""S1 authenticated project and private upload task entry."""

import asyncio
import json
import os
from collections.abc import Callable
from pathlib import Path
from uuid import UUID, uuid4

import httpx
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from kombu import Connection
from sqlalchemy import create_engine, text
from starlette.exceptions import HTTPException

from services.api import (
    agent_internal,
    agent_routes,
    auth,
    catalog,
    exports,
    index_builds,
    jobs,
    materials,
    outcomes,
    projects,
    research,
    source_mounts,
    source_releases,
    source_sync,
    uploads,
)
from services.api.auth import CurrentActor
from services.api.db import transaction, validate_runtime_role
from services.api.errors import install_error_handlers

ROOT = Path(__file__).resolve().parents[2]
app = FastAPI(title="Corpus Workbench", version="0.0.0")
install_error_handlers(app)
for router in (
    auth.router,
    projects.router,
    uploads.router,
    jobs.router,
    catalog.router,
    agent_routes.router,
    agent_internal.router,
    source_sync.router,
    index_builds.router,
    source_releases.router,
    source_mounts.router,
    research.router,
    materials.router,
    outcomes.router,
    exports.router,
):
    app.include_router(router)


@app.exception_handler(HTTPException)
async def http_error(request, error):
    detail = error.detail if isinstance(error.detail, dict) else {}
    return JSONResponse(
        {
            "code": detail.get(
                "code", "NOT_FOUND" if error.status_code == 404 else "HTTP_ERROR"
            ),
            "message": detail.get("message", "请求无法完成"),
            "request_id": str(uuid4()),
            "field_errors": [],
            "retryable": bool(detail.get("retryable", False)),
        },
        status_code=error.status_code,
        headers=error.headers,
    )


def check_database(url: str) -> None:
    engine = create_engine(url, connect_args={"connect_timeout": 3})
    try:
        with engine.connect() as connection:
            validate_runtime_role(connection)
            for table in (
                "projects",
                "upload_sessions",
                "jobs",
                "research_evidence",
                "research_notes",
                "research_exports",
                "catalog_sources",
                "agent_sessions",
                "agent_runs",
                "agent_invocations",
                "agent_checkpoints",
                "source_sync_runs",
                "source_acquisitions",
                "index_build_runs",
                "source_indexes",
                "source_policies",
                "project_source_mounts",
                "source_release_heads",
                "material_documents",
                "material_revisions",
                "research_snapshots",
                "query_runs",
                "research_tasks",
            ):
                connection.execute(text(f"SELECT 1 FROM app.{table} LIMIT 0"))
    finally:
        engine.dispose()


def check_broker(url: str) -> None:
    with Connection(url, connect_timeout=3) as connection:
        connection.ensure_connection(max_retries=0)


def check_storage(url: str) -> None:
    with httpx.Client(timeout=3, trust_env=False) as client:
        client.get(url.rstrip("/") + "/minio/health/ready").raise_for_status()


CHECKS: dict[str, tuple[str, Callable[[str], None]]] = {
    "database": ("DATABASE_URL", check_database),
    "broker": ("BROKER_URL", check_broker),
    "object_storage": ("OBJECT_STORAGE_URL", check_storage),
}


@app.get("/api/v1/health/live")
def live() -> dict:
    return {"status": "alive", "service": "api", "stage": "S1"}


@app.get("/api/v1/health/ready")
async def ready() -> JSONResponse:
    async def probe(name: str, environment: str, check: Callable[[str], None]) -> tuple:
        value = os.getenv(environment)
        if not value:
            return name, {"status": "not_configured"}
        try:
            await asyncio.to_thread(check, value)
            return name, {"status": "ready"}
        except Exception:  # noqa: BLE001 - dependency failures must not leak credentials
            # Connection strings and credentials must never enter API error bodies.
            return name, {"status": "unavailable"}

    results = dict(
        await asyncio.gather(*(probe(name, *check) for name, check in CHECKS.items()))
    )
    is_ready = all(result["status"] == "ready" for result in results.values())
    return JSONResponse(
        {"status": "ready" if is_ready else "not_ready", "dependencies": results},
        status_code=200 if is_ready else 503,
    )


@app.get("/api/v1/system/capabilities")
def capabilities() -> dict:
    """Public implementation inventory, never a user's authorization decision."""
    registry = json.loads(
        (ROOT / "contracts/capabilities.json").read_text(encoding="utf-8")
    )
    items = registry["capabilities"]
    return {
        "schema_version": registry["schema_version"],
        "available": [],
        "planned_count": sum(
            item["availability"]["status"] == "planned" for item in items
        ),
        "authentication": "server_session",
        "tool_authorization": "production_delegation_not_accepted",
    }


@app.get("/api/v1/me/capabilities")
def my_capabilities(actor: CurrentActor, project_id: UUID | None = None) -> dict:
    actions = [
        "account.get",
        "projects.list",
        "projects.create",
        "sources.list",
        "sources.get",
        "sources.versions",
        "releases.get",
    ]
    if actor.is_platform_admin:
        actions += [
            "catalog.create",
            "catalog.update",
            "policies.get",
            "policies.update",
            "releases.publish",
        ]
    if project_id:
        with transaction(actor.id) as session:
            project = projects.require_project(session, actor.id, project_id)
            view = projects.view(session, actor.id, project)
            actions = [
                "account.get",
                "sources.list",
                "sources.get",
                "sources.versions",
                "releases.get",
                "projects.get",
                "jobs.list",
                "jobs.get",
                "mounts.list",
                "mounts.get",
                "mounts.manifest",
                "imports.get",
                "materials.list",
                "materials.get",
                "snapshots.get",
                "corpus.describe",
                "corpus.search",
                "results.get",
                "results.context",
                "evidence.get",
                "evidence.list",
                "notes.get",
                "notes.list",
                "exports.create",
                "exports.get",
                "exports.list",
            ]
            if view.permissions.upload:
                actions += [
                    "uploads.create",
                    "uploads.complete",
                    "mounts.create",
                    "mounts.remove",
                    "imports.start",
                    "snapshots.create",
                    "evidence.create",
                    "notes.create",
                    "notes.update",
                    "notes.accept",
                ]
            if view.permissions.manage_members:
                actions += ["members.list", "members.update", "members.remove"]
    return {
        "manual_actions": actions,
        "available_tools": [],
        "tool_authorization": "production_delegation_not_accepted",
        "resource_actions": "Job cancel/retry permissions are returned on each job.",
    }


web_dist = Path(os.getenv("WEB_DIST_DIR", str(ROOT / "apps/web/dist")))
if web_dist.is_dir():
    app.mount("/", StaticFiles(directory=web_dist, html=True), name="web")
