"""Private single-file upload sessions; completion only schedules validation."""

import asyncio
import os
import tempfile
from datetime import timedelta
from pathlib import Path
from uuid import UUID, uuid4

from fastapi import APIRouter, Header, Request
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import func, select

from services.api import storage
from services.api.auth import CurrentActor
from services.api.db import transaction
from services.api.errors import ApiError
from services.api.job_models import Job, Upload
from services.api.jobs import EmptyBody, action_lookup, enqueue, fail, now
from services.api.projects import require_project

router = APIRouter(prefix="/api/v1")
MAX_BYTES = int(os.getenv("MAX_UPLOAD_BYTES", "100000000"))
PROJECT_QUOTA = int(os.getenv("PROJECT_UPLOAD_QUOTA_BYTES", "1000000000"))
FORMATS = {
    "text/plain",
    "text/csv",
    "text/tab-separated-values",
    "application/json",
    "application/x-ndjson",
}
# Failed/cancelled versioned objects also consume storage until a separate cleanup.
RESERVED_STATES = {
    "CREATED",
    "UPLOADING",
    "UPLOADED",
    "VALIDATING",
    "VALIDATED",
    "VALIDATION_FAILED",
    "CANCELLED",
    "FAILED",
}


class CreateUpload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    filename: str = Field(min_length=1, max_length=255)
    size: int = Field(gt=0)
    media_type: str = Field(max_length=100)
    sha256: str = Field(pattern=r"^[a-fA-F0-9]{64}$")

    @field_validator("filename")
    @classmethod
    def plain_filename(cls, value):
        if (
            any(ord(c) < 32 for c in value)
            or "/" in value
            or "\\" in value
            or value in {".", ".."}
        ):
            raise ValueError("filename must be a plain file name")
        return value


def load_upload(session, upload_id, actor_id, *, write=False):
    upload = session.get(Upload, upload_id)
    if not upload:
        fail("NOT_FOUND", "上传会话不存在或不可访问。", 404)
    require_project(session, actor_id, upload.project_id, write=write)
    if write:
        if upload.actor_id != actor_id:
            fail("ACCESS_DENIED", "只能提交本人创建的上传会话。", 403)
        upload = session.scalar(
            select(Upload)
            .where(Upload.id == upload_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    return upload


def view_upload(session, upload):
    job = session.scalar(
        select(Job).where(Job.upload_id == upload.id, Job.kind == "UPLOAD_VALIDATE")
    )
    return {
        "upload_id": str(upload.id),
        "project_id": str(upload.project_id),
        "filename": upload.filename,
        "size": upload.expected_size,
        "sha256": upload.expected_sha256,
        "media_type": upload.media_type,
        "state": upload.state,
        "error_code": upload.error_code,
        "expires_at": upload.expires_at.isoformat(),
        "job_id": str(job.id) if job else None,
        "upload_url": f"/api/v1/uploads/{upload.id}/content",
        "method": "PUT",
        "max_bytes": MAX_BYTES,
    }


@router.post("/projects/{project_id}/uploads", status_code=201)
def create_upload(
    project_id: UUID,
    body: CreateUpload,
    actor: CurrentActor,
    idempotency_key: str = Header(),
):
    if body.size > MAX_BYTES:
        fail("UPLOAD_TOO_LARGE", f"单文件不能超过 {MAX_BYTES} 字节。", 413)
    if body.media_type not in FORMATS:
        fail(
            "UNSUPPORTED_FORMAT",
            "仅支持声明为 TXT、CSV、TSV、JSON 或 JSONL 的文本文件。",
            422,
        )
    with transaction(actor.id) as session:
        require_project(session, actor.id, project_id, write=True)
        args = body.model_dump()
        args["sha256"] = body.sha256.lower()
        action, old = action_lookup(
            session, actor.id, project_id, idempotency_key, "uploads.create", args
        )
        if old:
            return action.response
        # The project lock serializes reservations with other creates. Expired unused
        # CREATED sessions have no object and may release their reservation.
        used = session.scalar(
            select(func.coalesce(func.sum(Upload.expected_size), 0)).where(
                Upload.project_id == project_id,
                Upload.state.in_(RESERVED_STATES),
                (Upload.state != "CREATED") | (Upload.expires_at > now()),
            )
        )
        if used + body.size > PROJECT_QUOTA:
            fail("PROJECT_UPLOAD_QUOTA_EXCEEDED", "项目上传字节额度不足。", 413)
        upload = Upload(
            id=uuid4(),
            project_id=project_id,
            actor_id=actor.id,
            filename=body.filename,
            media_type=body.media_type,
            expected_size=body.size,
            expected_sha256=body.sha256.lower(),
            object_key=f"private/{project_id}/{uuid4().hex}/{uuid4().hex}",
            state="CREATED",
            created_at=now(),
            expires_at=now() + timedelta(minutes=30),
        )
        session.add(upload)
        session.flush()
        action.response = {**view_upload(session, upload), "action_id": str(action.id)}
        return action.response


@router.get("/uploads/{upload_id}")
def get_upload(upload_id: UUID, actor: CurrentActor):
    with transaction(actor.id) as session:
        return view_upload(session, load_upload(session, upload_id, actor.id))


@router.put("/uploads/{upload_id}/content")
async def put_content(upload_id: UUID, request: Request, actor: CurrentActor):
    with transaction(actor.id) as session:
        upload = load_upload(session, upload_id, actor.id, write=True)
        if upload.state != "CREATED":
            fail("UPLOAD_ALREADY_USED", "此上传会话已使用，不能覆盖已有对象。")
        if upload.expires_at <= now():
            fail("UPLOAD_EXPIRED", "上传会话已过期，请重新创建。", 410)
        try:
            declared = int(request.headers.get("content-length", "-1"))
        except ValueError:
            declared = -1
        if declared != upload.expected_size:
            fail("SIZE_MISMATCH", "请求字节数必须与上传会话一致。", 422)
        upload.state = "UPLOADING"
        key, size, media_type = (
            upload.object_key,
            upload.expected_size,
            upload.media_type,
        )
    temp_dir = Path(
        os.getenv(
            "UPLOAD_TEMP_DIR", str(Path(__file__).resolve().parents[2] / "tmp/uploads")
        )
    )
    temp_dir.mkdir(parents=True, exist_ok=True)
    try:
        with tempfile.SpooledTemporaryFile(
            max_size=1024 * 1024, mode="w+b", dir=temp_dir
        ) as stream:
            received = 0
            async with asyncio.timeout(120):
                async for chunk in request.stream():
                    received += len(chunk)
                    if received > size or received > MAX_BYTES:
                        fail("SIZE_MISMATCH", "传输超出上传会话声明的字节数。", 413)
                    stream.write(chunk)
            if received != size:
                fail("SIZE_MISMATCH", "文件传输不完整。", 422)
            stream.seek(0)
            version, etag = await asyncio.to_thread(
                storage.put_private, key, stream, size, media_type
            )
        with transaction(actor.id) as session:
            upload = load_upload(session, upload_id, actor.id, write=True)
            if upload.state != "UPLOADING" or upload.expires_at <= now():
                fail("UPLOAD_EXPIRED", "上传会话已失效，对象未提交。", 410)
            upload.version_id, upload.etag, upload.state = version, etag, "UPLOADED"
            return view_upload(session, upload)
    except Exception as exc:
        code = exc.code if isinstance(exc, ApiError) else "UPLOAD_FAILED"
        if isinstance(exc, ValueError) and str(exc) == "STORAGE_VERSIONING_REQUIRED":
            code = "STORAGE_VERSIONING_REQUIRED"
        try:
            with transaction(actor.id) as session:
                upload = load_upload(session, upload_id, actor.id, write=True)
                if upload.state == "UPLOADING":
                    upload.state, upload.error_code = "FAILED", code
        except ApiError:
            pass  # Revocation prevents publishing or mutating the private ledger.
        if isinstance(exc, ApiError):
            raise
        fail(code, "文件传输失败，请创建新的上传会话。", 503)


@router.post("/uploads/{upload_id}/complete", status_code=202)
def complete_upload(
    upload_id: UUID,
    body: EmptyBody,
    actor: CurrentActor,
    idempotency_key: str = Header(),
):
    with transaction(actor.id) as session:
        upload = load_upload(session, upload_id, actor.id, write=True)
        action, old = action_lookup(
            session,
            actor.id,
            upload.project_id,
            idempotency_key,
            "uploads.complete",
            {"upload_id": str(upload_id)},
        )
        if old:
            return action.response
        job = session.scalar(
            select(Job).where(Job.upload_id == upload_id, Job.kind == "UPLOAD_VALIDATE")
        )
        if job is None:
            if upload.state != "UPLOADED" or not upload.version_id:
                fail("UPLOAD_NOT_COMPLETE", "文件尚未成功上传。")
            if upload.expires_at <= now():
                fail("UPLOAD_EXPIRED", "上传会话已过期。", 410)
            job = Job(
                id=uuid4(),
                project_id=upload.project_id,
                actor_id=actor.id,
                action_id=action.id,
                upload_id=upload.id,
                kind="UPLOAD_VALIDATE",
                state="QUEUED",
                attempt=1,
                lease_epoch=0,
                processed_bytes=0,
                total_bytes=upload.expected_size,
                event_sequence=0,
                created_at=now(),
                updated_at=now(),
            )
            session.add(job)
            session.flush()
            enqueue(session, job)
            upload.state = "VALIDATING"
        action.response = {
            "status": "accepted",
            "action_id": str(action.id),
            "job_id": str(job.id),
            "upload_id": str(upload_id),
            "state": job.state,
            "result_ref": None,
        }
        return action.response
