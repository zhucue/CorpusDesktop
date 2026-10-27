"""Version-pinned TXT import using the existing project job ledger."""

import json
import logging
import os
import shutil
import time
from datetime import timedelta
from pathlib import Path
from uuid import UUID, uuid4

from sqlalchemy import func, select, text

from services.api import materials as api
from services.api import storage
from services.api.db import transaction
from services.api.job_models import Attempt, Job, Upload
from services.api.jobs import emit, finish_failure, now
from services.api.material_models import Material, MaterialRevision
from workers.index_build import ProgressReader, safe_exception, verify_stream
from workers.validation import LEASE_SECONDS, locked_job, owns

LOGGER = logging.getLogger(__name__)


class MaterialLimit(ValueError):
    code = "MATERIAL_QUOTA_EXCEEDED"


class Fenced(Exception):
    pass


def admit(db, job):
    db.execute(
        text(
            "SELECT pg_advisory_xact_lock(hashtextextended('private-material-budget',0))"
        )
    )
    used = local = 0
    for row in db.scalars(select(MaterialRevision)):
        amount = sum(x["bytes"] for x in row.objects)
        used += amount
        if row.project_id == job.project_id:
            local += amount
    for row in db.scalars(
        select(Job).where(
            Job.kind == "TXT_IMPORT", Job.id != job.id, Job.state != "QUEUED"
        )
    ):
        used += row.reserved_bytes
        if row.project_id == job.project_id:
            local += row.reserved_bytes
    return used + job.reserved_bytes <= int(
        os.environ.get("MATERIAL_STORAGE_MAX_BYTES", str(2 * 1024**3))
    ) and local + job.reserved_bytes <= int(
        os.environ.get("MATERIAL_PROJECT_MAX_BYTES", str(1024**3))
    )


def claim(job_id, number):
    with transaction() as db:
        job, permitted = locked_job(db, job_id)
        if (
            not job
            or job.kind != "TXT_IMPORT"
            or job.state != "QUEUED"
            or job.attempt != number
        ):
            return None
        if not permitted or not admit(db, job):
            finish_failure(
                db,
                job,
                "PROJECT_FORBIDDEN" if not permitted else "MATERIAL_QUOTA_EXCEEDED",
                "当前权限或全局/项目材料预算不允许导入。",
                bool(permitted),
            )
            job.reserved_bytes = 0
            return None
        upload = db.get(Upload, job.upload_id)
        if upload.state != "VALIDATED" or job.input["recipe"] != api.recipe():
            finish_failure(
                db, job, "IMPORT_INPUT_CHANGED", "固定原件或处理配置不可用。"
            )
            job.reserved_bytes = 0
            return None
        job.state, job.stage, job.lease_token = "RUNNING", "FETCHING", uuid4()
        job.lease_epoch += 1
        job.lease_expires_at = now() + timedelta(seconds=LEASE_SECONDS)
        attempt = db.get(Attempt, (job.id, job.attempt))
        attempt.state, attempt.lease_epoch, attempt.started_at = (
            "RUNNING",
            job.lease_epoch,
            now(),
        )
        emit(db, job, "import.started")
        return {
            "job_id": job.id,
            "attempt": job.attempt,
            "epoch": job.lease_epoch,
            "token": job.lease_token,
            "project_id": job.project_id,
            "input": job.input,
            "reserved_bytes": job.reserved_bytes,
            "raw": {
                "name": "raw.txt",
                "object_key": upload.object_key,
                "version_id": upload.version_id,
                "etag": upload.etag,
                "bytes": upload.expected_size,
                "sha256": upload.expected_sha256,
            },
        }


def heartbeat(lease, update):
    with transaction() as db:
        job, permitted = locked_job(db, lease["job_id"])
        if not owns(job, lease) or job.kind != "TXT_IMPORT":
            return False
        if not permitted:
            finish_failure(db, job, "AUTHORIZATION_REVOKED", "当前项目写入权限已撤销。")
            return False
        stage = update.get("stage")
        if stage in {"FETCHING", "PARSING", "STORING"}:
            job.stage = stage
        job.progress = {
            **(job.progress or api.EMPTY_PROGRESS),
            **{k: v for k, v in update.items() if k in api.EMPTY_PROGRESS},
        }
        for key in ("processed_bytes", "processed_records"):
            if job.progress[key] is None:
                job.progress[key] = 0
        job.processed_bytes = job.progress["processed_bytes"]
        job.lease_expires_at = now() + timedelta(seconds=LEASE_SECONDS)
        emit(db, job, "import.progress", job.progress)
        return True


def publish(lease, manifest, objects):
    with transaction() as db:
        job, permitted = locked_job(db, lease["job_id"])
        if not owns(job, lease) or job.kind != "TXT_IMPORT":
            return False
        if not permitted:
            finish_failure(db, job, "AUTHORIZATION_REVOKED", "当前项目写入权限已撤销。")
            return False
        if not admit(db, job) or sum(x["bytes"] for x in objects) > job.reserved_bytes:
            finish_failure(db, job, "MATERIAL_QUOTA_EXCEEDED", "导入产物超出预留。")
            return False
        inp = job.input
        if (
            manifest["document_id"] != inp["material_id"]
            or manifest["revision_id"] != inp["revision_id"]
            or manifest["language"] != inp["language"]
            or manifest["recipe_sha256"] != inp["recipe"]["sha256"]
        ):
            raise ValueError("MATERIAL_IDENTITY_MISMATCH")
        doc = db.get(Material, UUID(inp["material_id"]))
        revision = (
            db.scalar(
                select(func.max(MaterialRevision.revision)).where(
                    MaterialRevision.material_id == doc.id
                )
            )
            or 0
        ) + 1
        row = MaterialRevision(
            id=UUID(inp["revision_id"]),
            project_id=job.project_id,
            material_id=doc.id,
            upload_id=job.upload_id,
            import_id=job.id,
            revision=revision,
            language=inp["language"],
            manifest=manifest,
            manifest_sha256=api.digest(manifest),
            objects=objects,
            created_at=now(),
        )
        db.add(row)
        db.flush()
        doc.latest_revision_id = row.id
        job.state, job.stage, job.result = (
            "SUCCEEDED",
            "COMPLETE",
            {
                "material_id": str(doc.id),
                "material_revision_id": str(row.id),
                "state": "READY",
            },
        )
        job.reserved_bytes = 0
        job.lease_token = job.lease_expires_at = None
        attempt = db.get(Attempt, (job.id, job.attempt))
        attempt.state, attempt.finished_at = "SUCCEEDED", now()
        emit(db, job, "import.succeeded", job.result)
        return True


def fetch(item, path, tick):
    stream = storage.read_private(item["object_key"], item["version_id"], item["etag"])
    try:
        with path.open("xb") as out:
            verify_stream(stream, item, tick, out, "FETCHING")
    finally:
        stream.close()


def execute(job_id, attempt):
    from pipelines.materials.txt import parse_txt

    lease = claim(UUID(str(job_id)), attempt)
    if not lease:
        return {"status": "duplicate_or_ineligible"}
    root = Path(
        os.environ.get(
            "MATERIAL_WORK_DIR",
            str(Path(__file__).resolve().parents[1] / "tmp/material-imports"),
        )
    )
    directory = root / str(lease["job_id"]) / f"{attempt}-{lease['epoch']}"
    objects = []
    uncertain = False
    published = False
    last = 0.0

    def tick(update):
        nonlocal last
        current = time.monotonic()
        if current - last >= 1:
            if not heartbeat(lease, update):
                raise Fenced()
            last = current

    try:
        directory.mkdir(parents=True, exist_ok=False)
        raw = directory / "raw.txt"
        fetch(lease["raw"], raw, tick)
        inp = lease["input"]
        bundle = parse_txt(
            raw,
            directory / "parsed",
            document_id=inp["material_id"],
            revision_id=inp["revision_id"],
            language=inp["language"],
            expected_sha256=lease["raw"]["sha256"],
            expected_bytes=lease["raw"]["bytes"],
            progress_callback=tick,
        )
        if sum(x["bytes"] for x in bundle["artifacts"]) > lease["reserved_bytes"]:
            raise MaterialLimit()
        for artifact in bundle["artifacts"]:
            item = {k: artifact[k] for k in ("name", "bytes", "sha256")}
            key = f"materials/{lease['project_id']}/{inp['revision_id']}/{uuid4().hex}/{item['name']}"
            with Path(artifact["path"]).open("rb") as stream:
                uncertain = True
                version, etag = storage.put_private(
                    key,
                    ProgressReader(stream, tick, item),
                    item["bytes"],
                    "application/octet-stream",
                )
                uncertain = False
            item.update(object_key=key, version_id=version, etag=etag)
            objects.append(item)
            stream = storage.read_private(key, version, etag)
            try:
                verify_stream(stream, item, tick)
            finally:
                stream.close()
        published = publish(lease, bundle["manifest"], objects)
        return {"status": "published" if published else "fenced"}
    except Fenced:
        return {"status": "fenced"}
    except Exception as exc:  # noqa: BLE001 - diagnostics exclude material and provider messages
        code = getattr(exc, "code", None) or "IMPORT_EXECUTION_FAILED"
        LOGGER.error(
            "import_failed %s",
            json.dumps(
                {"job_id": str(lease["job_id"]), "exceptions": safe_exception(exc)}
            ),
        )
        with transaction() as db:
            job, _ = locked_job(db, lease["job_id"])
            if owns(job, lease):
                finish_failure(
                    db,
                    job,
                    code,
                    "TXT 解析或存储失败。",
                    code == "IMPORT_EXECUTION_FAILED",
                )
        return {"status": "failed", "code": code}
    finally:
        cleanup = not published
        if cleanup:
            try:
                with transaction() as db:
                    cleanup = (
                        db.scalar(
                            select(MaterialRevision.id).where(
                                MaterialRevision.import_id == lease["job_id"]
                            )
                        )
                        is None
                    )
            except Exception:  # noqa: BLE001 - unknown storage/commit outcomes retain private objects and budget
                cleanup = False
        cleaned = not uncertain
        if cleanup:
            for item in objects:
                try:
                    storage.client().delete_object(
                        Bucket=storage.bucket(),
                        Key=item["object_key"],
                        VersionId=item["version_id"],
                    )
                except Exception:  # noqa: BLE001 - unknown storage/commit outcomes retain private objects and budget
                    cleaned = False
            with transaction() as db:
                job, _ = locked_job(db, lease["job_id"])
                if (
                    job.state == "RUNNING"
                    and job.lease_token == lease["token"]
                    and job.lease_expires_at <= now()
                ):
                    finish_failure(
                        db, job, "WORKER_LEASE_EXPIRED", "执行租约过期。", True
                    )
                if job.attempt == lease["attempt"] and job.state in {
                    "FAILED",
                    "CANCELLED",
                }:
                    if cleaned:
                        job.reserved_bytes = 0
                    elif job.state == "FAILED":
                        job.error = {
                            "code": "IMPORT_CLEANUP_REQUIRED",
                            "message": "对象写入或清理结果未知，保留预算等待核查。",
                            "retryable": False,
                        }
        if directory.is_dir() and directory.resolve().is_relative_to(root.resolve()):
            shutil.rmtree(directory)
