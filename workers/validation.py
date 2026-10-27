"""Version-pinned stream validation with database fencing and publication."""

import codecs
import hashlib
import time
from datetime import timedelta
from uuid import UUID, uuid4

from sqlalchemy import select, text

from services.api import storage
from services.api.db import lock_actor, lock_project, transaction
from services.api.job_models import Attempt, Job, Upload
from services.api.jobs import emit, finish_failure, now

LEASE_SECONDS = 90


def authorized(session, actor_id, project_id):
    # These same locks serialize account disabling and project member changes.
    lock_actor(session, actor_id)
    lock_project(session, project_id)
    return bool(
        session.scalar(
            text("""
        SELECT EXISTS(SELECT 1 FROM app.users u JOIN app.project_members m ON m.user_id=u.id
        WHERE u.id=:actor AND u.is_active AND m.project_id=:project AND m.role IN ('owner','editor'))
        """),
            {"actor": actor_id, "project": project_id},
        )
    )


def locked_job(session, job_id):
    job = session.get(Job, job_id)
    if not job:
        return None, False
    permitted = authorized(session, job.actor_id, job.project_id)
    job = session.scalar(
        select(Job)
        .where(Job.id == job_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    return job, permitted


def claim(job_id, expected_attempt):
    with transaction(None) as session:
        job, permitted = locked_job(session, job_id)
        if (
            job is None
            or job.kind != "UPLOAD_VALIDATE"
            or job.state != "QUEUED"
            or job.attempt != expected_attempt
        ):
            return None
        if not permitted:
            finish_failure(
                session,
                job,
                "AUTHORIZATION_REVOKED",
                "任务发起人的项目写入权限已失效。",
            )
            return None
        job.state, job.lease_token = "RUNNING", uuid4()
        job.lease_epoch += 1
        job.lease_expires_at = now() + timedelta(seconds=LEASE_SECONDS)
        attempt = session.get(Attempt, (job.id, job.attempt))
        attempt.state, attempt.lease_epoch, attempt.started_at = (
            "RUNNING",
            job.lease_epoch,
            now(),
        )
        emit(session, job, "job.started")
        upload = session.get(Upload, job.upload_id)
        return {
            "job_id": job.id,
            "attempt": job.attempt,
            "epoch": job.lease_epoch,
            "token": job.lease_token,
            "key": upload.object_key,
            "version": upload.version_id,
            "etag": upload.etag,
            "size": upload.expected_size,
            "sha256": upload.expected_sha256,
        }


def owns(job, lease):
    return (
        job is not None
        and job.state == "RUNNING"
        and job.attempt == lease["attempt"]
        and job.lease_epoch == lease["epoch"]
        and job.lease_token == lease["token"]
        and job.lease_expires_at is not None
        and job.lease_expires_at > now()
    )


def heartbeat(lease, processed):
    with transaction(None) as session:
        job, permitted = locked_job(session, lease["job_id"])
        if not owns(job, lease) or job.kind != "UPLOAD_VALIDATE":
            return False
        if not permitted:
            finish_failure(
                session,
                job,
                "AUTHORIZATION_REVOKED",
                "任务发起人的项目写入权限已失效。",
            )
            return False
        job.processed_bytes = processed
        job.lease_expires_at = now() + timedelta(seconds=LEASE_SECONDS)
        emit(
            session,
            job,
            "job.progress",
            {"processed_bytes": processed, "total_bytes": job.total_bytes},
        )
        return True


def publish(lease, result=None, error=None):
    with transaction(None) as session:
        job, permitted = locked_job(session, lease["job_id"])
        if not owns(job, lease) or job.kind != "UPLOAD_VALIDATE":
            return False
        if not permitted:
            finish_failure(
                session,
                job,
                "AUTHORIZATION_REVOKED",
                "任务发起人的项目写入权限已失效。",
            )
            return False
        if error:
            finish_failure(session, job, **error)
            return True
        job.state = "SUCCEEDED"
        job.processed_bytes = result["size"]
        job.result = {**result, "upload_id": str(job.upload_id), "state": "VALIDATED"}
        job.lease_token, job.lease_expires_at = None, None
        attempt = session.get(Attempt, (job.id, job.attempt))
        attempt.state, attempt.finished_at = "SUCCEEDED", now()
        session.get(Upload, job.upload_id).state = "VALIDATED"
        emit(session, job, "job.succeeded", {"result": job.result})
        return True


class ValidationFailure(Exception):
    def __init__(self, code, message):
        self.code, self.message = code, message
        super().__init__(code)


def validate_stream(stream, expected_size, expected_sha256, checkpoint=lambda _: True):
    digest, size = hashlib.sha256(), 0
    decoder = codecs.getincrementaldecoder("utf-8-sig")("strict")
    began = last_heartbeat = time.monotonic()
    while chunk := stream.read(1024 * 1024):
        size += len(chunk)
        if size > expected_size:
            raise ValidationFailure("SIZE_MISMATCH", "真实对象大小与声明不一致。")
        digest.update(chunk)
        try:
            decoded = decoder.decode(chunk)
        except UnicodeDecodeError as exc:
            raise ValidationFailure(
                "INVALID_TEXT_ENCODING", "只接受 UTF-8 文本。"
            ) from exc
        if "\x00" in decoded:
            raise ValidationFailure("UNSUPPORTED_CONTENT", "文件含二进制 NUL 字符。")
        current = time.monotonic()
        if current - began > 300:
            raise ValidationFailure("VALIDATION_TIMEOUT", "文件校验超过执行时限。")
        if current - last_heartbeat >= 15:
            if not checkpoint(size):
                return None
            last_heartbeat = current
    try:
        decoder.decode(b"", final=True)
    except UnicodeDecodeError as exc:
        raise ValidationFailure(
            "INVALID_TEXT_ENCODING", "UTF-8 文本结尾不完整。"
        ) from exc
    if size != expected_size:
        raise ValidationFailure("SIZE_MISMATCH", "真实对象大小与声明不一致。")
    actual = digest.hexdigest()
    if actual != expected_sha256:
        raise ValidationFailure("CHECKSUM_MISMATCH", "真实对象 SHA256 与声明不一致。")
    return {"size": size, "sha256": actual, "validation": "utf8-text-and-integrity/v1"}


def validate_upload(job_id: str, attempt: int):
    lease = claim(UUID(job_id), attempt)
    if lease is None:
        return {"status": "duplicate_or_ineligible"}
    try:
        stream = storage.read_private(lease["key"], lease["version"], lease["etag"])
        try:
            result = validate_stream(
                stream,
                lease["size"],
                lease["sha256"],
                lambda processed: heartbeat(lease, processed),
            )
        finally:
            stream.close()
        if result is None:
            return {"status": "fenced"}
        return {"status": "published" if publish(lease, result=result) else "fenced"}
    except ValidationFailure as exc:
        publish(
            lease, error={"code": exc.code, "message": exc.message, "retryable": False}
        )
        return {"status": "validation_failed", "code": exc.code}
    except Exception:  # noqa: BLE001 - never leak credentials/objects from SDK errors
        publish(
            lease,
            error={
                "code": "STORAGE_UNAVAILABLE",
                "message": "对象读取失败，可人工重试。",
                "retryable": True,
            },
        )
        return {"status": "storage_failed"}
