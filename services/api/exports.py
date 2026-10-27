"""Authorized background exports using the existing project job/outbox ledger."""

import os
from uuid import UUID, uuid4

from fastapi import APIRouter, Header, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import select, text

from contracts.outcomes import ExportAction, ExportInput, ExportList, ExportView
from services.api import outcomes, source_mounts, storage
from services.api.auth import CurrentActor
from services.api.catalog import digest
from services.api.db import transaction
from services.api.job_models import Job
from services.api.jobs import action_lookup, enqueue, fail, now
from services.api.outcome_models import ExportRecord
from services.api.source_sync import EMPTY_PROGRESS

router = APIRouter(prefix="/api/v1/projects/{project_id}/exports")


def recipe():
    from pipelines.exports.render import RECIPE_ID, RECIPE_SHA256

    return {"id": RECIPE_ID, "sha256": RECIPE_SHA256}


def authorize(db, actor_id, record):
    if record is None:
        fail("EXPORT_UNAVAILABLE", "导出引用已不可访问。", 403)
    return outcomes.authorize_dependencies(
        db,
        actor_id,
        record.project_id,
        record.authorization_evidence_ids,
        record.authorization_query_run_ids,
        export=True,
    )


def target_dependencies(db, actor_id, project_id, target):
    if target["kind"] == "query_runs":
        evidence, queries = [], target["query_run_ids"]
    else:
        _, row = outcomes.load_note(
            db, actor_id, project_id, UUID(target["note_id"]), target["revision"]
        )
        evidence, queries = (
            row.authorization_evidence_ids,
            row.authorization_query_run_ids,
        )
    outcomes.authorize_dependencies(
        db, actor_id, project_id, evidence, queries, export=True
    )
    return evidence, queries


def reserve_export(db, project_id):
    db.execute(
        text(
            "SELECT pg_advisory_xact_lock(hashtextextended('export-storage-budget',0))"
        )
    )
    maximum = int(os.environ.get("EXPORT_MAX_BYTES", str(512 * 1024**2)))
    used = db.scalar(text("SELECT app.export_project_bytes(:p)"), {"p": project_id})
    if used is None:
        fail("PROJECT_FORBIDDEN", "当前项目不可访问。", 403)
    if (
        maximum <= 0
        or maximum > 512 * 1024**2
        or used + maximum
        > int(os.environ.get("EXPORT_PROJECT_MAX_BYTES", str(2 * 1024**3)))
    ):
        fail("EXPORT_QUOTA_EXCEEDED", "项目导出预算不足（含在途或待清理预留）。")
    return maximum


def view(db, actor_id, record):
    authorize(db, actor_id, record)
    job = db.get(Job, record.id)
    project = source_mounts.project(db, actor_id, record.project_id)
    permitted = actor_id in {job.actor_id, project.owner_id}
    artifact = record.artifact
    result = (
        {
            "filename": artifact["name"],
            "media_type": artifact["media_type"],
            "container": "zip" if record.format == "csv" else "file",
            "byte_size": artifact["bytes"],
            "sha256": artifact["sha256"],
            "manifest_sha256": digest(record.methods),
            "row_count": artifact["row_count"],
        }
        if artifact
        else None
    )
    return {
        "id": str(job.id),
        "job_id": str(job.id),
        "project_id": str(job.project_id),
        "actor_id": str(job.actor_id),
        "target": record.target,
        "format": record.format,
        "state": job.state,
        "stage": "COMPLETE"
        if job.state == "SUCCEEDED"
        else job.state
        if job.state in {"QUEUED", "FAILED", "CANCELLED"}
        else job.stage,
        "attempt": job.attempt,
        "progress": job.progress or dict(EMPTY_PROGRESS),
        "error": job.error,
        "result": result,
        "created_at": job.created_at.isoformat(),
        "updated_at": job.updated_at.isoformat(),
        "allowed_actions": {
            "cancel": permitted and job.state in {"QUEUED", "RUNNING"},
            "retry": permitted
            and job.state == "FAILED"
            and job.attempt < 3
            and not job.reserved_bytes
            and bool((job.error or {}).get("retryable")),
            "download": bool(job.state == "SUCCEEDED" and artifact),
        },
    }


def load(db, actor_id, project_id, ident):
    source_mounts.project(db, actor_id, project_id)
    record = db.get(ExportRecord, ident)
    if not record or record.project_id != project_id:
        fail("EXPORT_NOT_FOUND", "导出不存在或不可访问。", 404)
    authorize(db, actor_id, record)
    return record


@router.post("", status_code=202, response_model=ExportAction)
def create_export(
    project_id: UUID,
    body: ExportInput,
    actor: CurrentActor,
    idempotency_key: str = Header(),
):
    with transaction(actor.id) as db:
        source_mounts.project(db, actor.id, project_id)
        payload = body.model_dump(mode="json")
        evidence, queries = target_dependencies(
            db, actor.id, project_id, payload["target"]
        )
        ledger, old = action_lookup(
            db, actor.id, project_id, idempotency_key, "exports.create", payload
        )
        if old:
            record = load(db, actor.id, project_id, UUID(ledger.response["export_id"]))
        else:
            reserved = reserve_export(db, project_id)
            inp = {**payload, "recipe": recipe()}
            job = Job(
                id=uuid4(),
                project_id=project_id,
                actor_id=actor.id,
                action_id=ledger.id,
                upload_id=None,
                kind="EXPORT",
                input=inp,
                input_sha256=digest(inp),
                state="QUEUED",
                stage="QUEUED",
                attempt=1,
                lease_epoch=0,
                reserved_bytes=reserved,
                processed_bytes=0,
                total_bytes=0,
                event_sequence=0,
                progress=dict(EMPTY_PROGRESS),
                created_at=now(),
                updated_at=now(),
            )
            db.add(job)
            db.flush()
            record = ExportRecord(
                id=job.id,
                project_id=project_id,
                actor_id=actor.id,
                target=payload["target"],
                format=body.format,
                authorization_evidence_ids=outcomes.ids(evidence),
                authorization_query_run_ids=outcomes.ids(queries),
                created_at=now(),
            )
            db.add(record)
            enqueue(db, job)
            db.flush()
            ledger.response = {"export_id": str(job.id)}
        result = view(db, actor.id, record)
        return {
            "action_id": str(ledger.id),
            "export_id": str(record.id),
            "job_id": str(record.id),
            "state": result["state"],
            "run": result,
        }


@router.get("/{export_id}", response_model=ExportView)
def get_export(project_id: UUID, export_id: UUID, actor: CurrentActor):
    with transaction(actor.id) as db:
        return view(db, actor.id, load(db, actor.id, project_id, export_id))


@router.get("", response_model=ExportList)
def list_exports(
    project_id: UUID,
    actor: CurrentActor,
    cursor: str | None = Query(None, max_length=512),
    page_size: int = Query(50, ge=1, le=100),
):
    with transaction(actor.id) as db:
        source_mounts.project(db, actor.id, project_id)
        records = list(
            db.scalars(
                select(ExportRecord)
                .where(ExportRecord.project_id == project_id)
                .order_by(ExportRecord.id)
            )
        )
        # One sorted source lock set before examining different targets.
        outcomes.authorize_dependencies(
            db,
            actor.id,
            project_id,
            [x for r in records for x in r.authorization_evidence_ids],
            [x for r in records for x in r.authorization_query_run_ids],
        )
        rows = []
        from services.api.errors import ApiError

        for record in records:
            try:
                rows.append(view(db, actor.id, record))
            except ApiError as exc:
                if exc.code != "EXPORT_POLICY_DENIED":
                    raise
        return outcomes.paginate(rows, cursor, page_size, "exports", project_id)


@router.get("/{export_id}/download")
def download_export(project_id: UUID, export_id: UUID, actor: CurrentActor):
    with transaction(actor.id) as db:
        record = load(db, actor.id, project_id, export_id)
        job = db.get(Job, record.id)
        if job.state != "SUCCEEDED" or not record.artifact:
            fail("EXPORT_NOT_READY", "导出文件尚未生成。")
        artifact = dict(record.artifact)
        stream = storage.read_private(
            artifact["object_key"], artifact["version_id"], artifact["etag"]
        )

    def chunks():
        try:
            while data := stream.read(1024**2):
                yield data
        finally:
            stream.close()

    return StreamingResponse(
        chunks(),
        media_type=artifact["media_type"],
        headers={
            "Content-Disposition": f'attachment; filename="{artifact["name"]}"',
            "Content-Length": str(artifact["bytes"]),
            "Cache-Control": "no-store",
            "X-Content-SHA256": artifact["sha256"],
        },
    )
