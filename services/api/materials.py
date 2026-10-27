"""Explicit TXT import commands; metadata never grants model access to text."""

import os
from uuid import UUID, uuid4

from fastapi import APIRouter, Header, Query
from sqlalchemy import select, text

from contracts.materials import (
    ImportAction,
    ImportInput,
    ImportList,
    ImportView,
    MaterialList,
    MaterialView,
    ValidatedUploadList,
)
from services.api.auth import CurrentActor
from services.api.catalog import digest, make_cursor, read_cursor
from services.api.db import transaction
from services.api.job_models import Job, Upload
from services.api.jobs import action_lookup, enqueue, fail, now, view_job
from services.api.material_models import Material, MaterialRevision
from services.api.source_mounts import project
from services.api.source_sync import EMPTY_PROGRESS

router = APIRouter(prefix="/api/v1/projects/{project_id}")


def recipe():
    from pipelines.materials.txt import RECIPE_ID, RECIPE_SHA256

    return {"id": RECIPE_ID, "sha256": RECIPE_SHA256}


def reserve_import(db, project_id):
    db.execute(
        text(
            "SELECT pg_advisory_xact_lock(hashtextextended('private-material-budget',0))"
        )
    )
    amount = int(os.environ.get("MATERIAL_IMPORT_MAX_BYTES", str(256 * 1024**2)))
    used = project_used = 0
    for row in db.scalars(select(MaterialRevision)):
        size = sum(item["bytes"] for item in row.objects)
        used += size
        if row.project_id == project_id:
            project_used += size
    for row in db.scalars(select(Job).where(Job.kind == "TXT_IMPORT")):
        used += row.reserved_bytes
        if row.project_id == project_id:
            project_used += row.reserved_bytes
    if (
        amount <= 0
        or amount > 512 * 1024**2
        or used + amount
        > int(os.environ.get("MATERIAL_STORAGE_MAX_BYTES", str(2 * 1024**3)))
        or project_used + amount
        > int(os.environ.get("MATERIAL_PROJECT_MAX_BYTES", str(1024**3)))
    ):
        fail(
            "MATERIAL_QUOTA_EXCEEDED",
            "材料预算不足，包含已登记产物、活动任务和待清理预留。",
        )
    return amount


def load_revision(db, project_id, revision_id):
    row = db.scalar(
        select(MaterialRevision).where(
            MaterialRevision.id == revision_id,
            MaterialRevision.project_id == project_id,
        )
    )
    if not row:
        fail("MATERIAL_REVISION_NOT_FOUND", "材料修订不存在或不可访问。", 404)
    if digest(row.manifest) != row.manifest_sha256:
        fail("MATERIAL_IDENTITY_MISMATCH", "材料修订身份不一致。")
    return row


def revision_view(row):
    canonical = next(item for item in row.objects if item["name"] == "canonical.utf8")
    return {
        "id": str(row.id),
        "material_id": str(row.material_id),
        "project_id": str(row.project_id),
        "revision": row.revision,
        "upload_id": str(row.upload_id),
        "language": row.language,
        "recipe": {
            "id": row.manifest["recipe_id"],
            "sha256": row.manifest["recipe_sha256"],
        },
        "manifest_sha256": row.manifest_sha256,
        "canonical_sha256": canonical["sha256"],
        "counts": {
            key: row.manifest["counts"][key]
            for key in ("documents", "segments", "characters")
        },
        "quality": row.manifest["quality"],
        "created_at": row.created_at.isoformat(),
    }


def import_view(db, job, actor_id):
    legacy = view_job(db, job, actor_id)
    revision = db.scalar(
        select(MaterialRevision).where(MaterialRevision.import_id == job.id)
    )
    return {
        "id": str(job.id),
        "job_id": str(job.id),
        "project_id": str(job.project_id),
        "actor_id": str(job.actor_id),
        "upload_id": str(job.upload_id),
        "material_id": job.input["material_id"],
        "filename": legacy["filename"],
        "language": job.input["language"],
        "recipe": job.input["recipe"],
        "state": job.state,
        "stage": "COMPLETE"
        if job.state == "SUCCEEDED"
        else job.state
        if job.state in {"FAILED", "CANCELLED"}
        else job.stage or "QUEUED",
        "attempt": job.attempt,
        "progress": job.progress or dict(EMPTY_PROGRESS),
        "error": job.error,
        "result": revision_view(revision) if revision else None,
        "allowed_actions": {
            key: key in legacy["allowed_actions"] for key in ("cancel", "retry")
        },
        "created_at": job.created_at.isoformat(),
        "updated_at": job.updated_at.isoformat(),
    }


def material_view(db, item):
    revisions = list(
        db.scalars(
            select(MaterialRevision)
            .where(MaterialRevision.material_id == item.id)
            .order_by(MaterialRevision.revision.desc())
        )
    )
    job = db.get(Job, item.import_id)
    latest = next((r for r in revisions if r.id == item.latest_revision_id), None)
    return {
        "id": str(item.id),
        "project_id": str(item.project_id),
        "name": item.name,
        "language": latest.language if latest else job.input["language"],
        "state": "READY"
        if latest
        else job.state
        if job.state in {"FAILED", "CANCELLED"}
        else "IMPORTING",
        "import_id": str(item.import_id),
        "latest_revision": revision_view(latest) if latest else None,
        "revisions": [revision_view(r) for r in revisions],
        "created_at": item.created_at.isoformat(),
    }


def listing(db, model, project_id, cursor, page_size, kind, conditions=()):
    filters = {"project_id": str(project_id), "kind": kind}
    last = read_cursor(cursor, filters)
    stmt = select(model).where(model.project_id == project_id, *conditions)
    if last:
        stmt = stmt.where(model.id > UUID(last))
    rows = list(db.scalars(stmt.order_by(model.id).limit(page_size + 1)))
    return rows[:page_size], make_cursor(str(rows[page_size - 1].id), filters) if len(
        rows
    ) > page_size else None


@router.post("/imports", status_code=202, response_model=ImportAction)
def start_import(
    project_id: UUID,
    body: ImportInput,
    actor: CurrentActor,
    idempotency_key: str = Header(),
):
    with transaction(actor.id) as db:
        project(db, actor.id, project_id, write=True)
        upload = db.scalar(
            select(Upload).where(
                Upload.id == body.upload_id, Upload.project_id == project_id
            )
        )
        if not upload:
            fail("NOT_FOUND", "上传不存在或不可访问。", 404)
        if upload.state != "VALIDATED":
            fail("UPLOAD_NOT_VALIDATED", "请先完成原件校验。")
        if not upload.filename.lower().endswith(".txt") or upload.media_type not in {
            "text/plain",
            "application/octet-stream",
        }:
            fail("TXT_REQUIRED", "本次仅支持 UTF-8 TXT 文件。", 422)
        payload = {
            "upload_id": str(upload.id),
            "language": body.language,
            "recipe": recipe(),
        }
        ledger, old = action_lookup(
            db, actor.id, project_id, idempotency_key, "imports.start", payload
        )
        fingerprint = digest(payload)
        job = db.scalar(
            select(Job).where(
                Job.upload_id == upload.id,
                Job.kind == "TXT_IMPORT",
                Job.input_sha256 == fingerprint,
            )
        )
        if old:
            job = db.get(Job, UUID(ledger.response["job_id"]))
        if job is None:
            reserved = reserve_import(db, project_id)
            material = db.scalar(
                select(Material).where(
                    Material.upload_id == upload.id, Material.project_id == project_id
                )
            )
            material_id = material.id if material else uuid4()
            job = Job(
                id=uuid4(),
                project_id=project_id,
                actor_id=actor.id,
                action_id=ledger.id,
                upload_id=upload.id,
                kind="TXT_IMPORT",
                input={
                    **payload,
                    "material_id": str(material_id),
                    "revision_id": str(uuid4()),
                },
                input_sha256=fingerprint,
                state="QUEUED",
                stage="QUEUED",
                progress=dict(EMPTY_PROGRESS),
                attempt=1,
                lease_epoch=0,
                processed_bytes=0,
                total_bytes=upload.expected_size,
                event_sequence=0,
                reserved_bytes=reserved,
                created_at=now(),
                updated_at=now(),
            )
            db.add(job)
            db.flush()
            if material:
                material.import_id = job.id
            else:
                db.add(
                    Material(
                        id=material_id,
                        project_id=project_id,
                        upload_id=upload.id,
                        name=upload.filename,
                        import_id=job.id,
                        created_at=now(),
                    )
                )
            enqueue(db, job)
        ledger.response = {"job_id": str(job.id)}
        return {
            "action_id": str(ledger.id),
            "job_id": str(job.id),
            "import_id": str(job.id),
            "state": job.state,
            "run": import_view(db, job, actor.id),
        }


@router.get("/imports/{import_id}", response_model=ImportView)
def get_import(project_id: UUID, import_id: UUID, actor: CurrentActor):
    with transaction(actor.id) as db:
        project(db, actor.id, project_id)
        job = db.scalar(
            select(Job).where(
                Job.id == import_id,
                Job.project_id == project_id,
                Job.kind == "TXT_IMPORT",
            )
        )
        if not job:
            fail("NOT_FOUND", "导入任务不存在。", 404)
        return import_view(db, job, actor.id)


@router.get("/imports", response_model=ImportList)
def list_imports(
    project_id: UUID,
    actor: CurrentActor,
    page_size: int = Query(50, ge=1, le=100),
    cursor: str | None = Query(None, max_length=512),
):
    with transaction(actor.id) as db:
        project(db, actor.id, project_id)
        rows, next_cursor = listing(
            db,
            Job,
            project_id,
            cursor,
            page_size,
            "imports",
            (Job.kind == "TXT_IMPORT",),
        )
        return {
            "items": [import_view(db, row, actor.id) for row in rows],
            "next_cursor": next_cursor,
        }


@router.get("/materials", response_model=MaterialList)
def list_materials(
    project_id: UUID,
    actor: CurrentActor,
    page_size: int = Query(50, ge=1, le=100),
    cursor: str | None = Query(None, max_length=512),
):
    with transaction(actor.id) as db:
        project(db, actor.id, project_id)
        rows, next_cursor = listing(
            db, Material, project_id, cursor, page_size, "materials"
        )
        return {
            "items": [material_view(db, row) for row in rows],
            "next_cursor": next_cursor,
        }


@router.get("/materials/{material_id}", response_model=MaterialView)
def get_material(project_id: UUID, material_id: UUID, actor: CurrentActor):
    with transaction(actor.id) as db:
        project(db, actor.id, project_id)
        row = db.scalar(
            select(Material).where(
                Material.id == material_id, Material.project_id == project_id
            )
        )
        if not row:
            fail("NOT_FOUND", "材料不存在。", 404)
        return material_view(db, row)


@router.get("/uploads", response_model=ValidatedUploadList)
def list_uploads(
    project_id: UUID,
    actor: CurrentActor,
    state: str = Query("VALIDATED", pattern="^VALIDATED$"),
    page_size: int = Query(50, ge=1, le=100),
    cursor: str | None = Query(None, max_length=512),
):
    from services.api.uploads import view_upload

    with transaction(actor.id) as db:
        project(db, actor.id, project_id)
        rows, next_cursor = listing(
            db,
            Upload,
            project_id,
            cursor,
            page_size,
            "validated-uploads",
            (Upload.state == state,),
        )
        fields = (
            "upload_id",
            "project_id",
            "state",
            "filename",
            "size",
            "sha256",
            "media_type",
            "expires_at",
            "job_id",
        )
        return {
            "items": [
                {
                    key: value
                    for key, value in view_upload(db, row).items()
                    if key in fields
                }
                for row in rows
            ],
            "next_cursor": next_cursor,
        }
