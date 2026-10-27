"""Private index worker with pinned inputs, bounded storage and database fencing."""

import hashlib
import json
import logging
import os
import shutil
import time
import traceback
from datetime import timedelta
from pathlib import Path
from uuid import UUID, uuid4

from sqlalchemy import select

from services.api import index_builds as api
from services.api import storage
from services.api.catalog_models import CatalogSource
from services.api.db import lock_actor, transaction
from services.api.index_models import IndexAttempt, IndexRun, SourceIndex
from services.api.jobs import now
from services.api.models import User
from services.api.source_sync import identity, lock_source
from services.api.source_sync_models import Acquisition

LEASE_SECONDS = 90
LOGGER = logging.getLogger(__name__)


class Fenced(Exception):
    pass


def safe_exception(error):
    """Diagnostic types/locations only: never exception text, URLs, locals or bodies."""
    chain, seen = [], set()
    while error is not None and id(error) not in seen and len(chain) < 5:
        seen.add(id(error))
        entry = {
            "exception_type": type(error).__name__,
            "frames": [
                {
                    "file": Path(frame.filename).name,
                    "line": frame.lineno,
                    "function": frame.name,
                }
                for frame in traceback.extract_tb(error.__traceback__)
            ],
        }
        # HTTP status and OS error numbers are bounded primitives, not arbitrary
        # provider error messages (which can contain URLs or connection strings).
        code = getattr(error, "code", None)
        if isinstance(code, int) and 100 <= code <= 599:
            entry["http_status"] = code
        errno = getattr(error, "errno", None)
        if isinstance(errno, int):
            entry["errno"] = errno
        reason = getattr(error, "reason", None)
        if isinstance(reason, BaseException):
            entry["reason_type"] = type(reason).__name__
        chain.append(entry)
        error = error.__cause__ or error.__context__
    return chain


def locked(db, run_id):
    hint = db.get(IndexRun, run_id)
    if not hint:
        return None, False
    lock_actor(db, hint.actor_id)
    lock_source(db, hint.source_id)
    user = db.scalar(
        select(User)
        .where(User.id == hint.actor_id)
        .execution_options(populate_existing=True)
    )
    source = db.scalar(
        select(CatalogSource)
        .where(CatalogSource.source_id == hint.source_id)
        .execution_options(populate_existing=True)
    )
    row = api.load(db, run_id, lock=True)
    permitted = bool(user and user.is_active and user.is_platform_admin)
    identity_ok = source and identity(source) == row.source_identity
    return (
        row,
        "AUTHORIZATION_REVOKED"
        if not permitted
        else "SOURCE_IDENTITY_CHANGED"
        if not identity_ok
        else None,
    )


def owns(run, lease):
    return (
        run is not None
        and run.state == "RUNNING"
        and run.attempt == lease["attempt"]
        and run.lease_epoch == lease["epoch"]
        and run.lease_token == lease["token"]
        and run.lease_expires_at is not None
        and run.lease_expires_at > now()
    )


def claim(run_id, attempt):
    with transaction() as db:
        run, error = locked(db, run_id)
        if not run or run.state != "QUEUED" or run.attempt != attempt:
            return None
        if not error and run.recipe != api.recipe():
            error = "INDEX_RECIPE_CHANGED"
        if error:
            api.finish_failure(db, run, error, "发起人权限、来源身份或构建配置已改变。")
            return None
        acquired = db.get(Acquisition, run.acquisition_id)
        run.state, run.stage = "RUNNING", "FETCHING"
        run.lease_epoch += 1
        run.lease_token, run.lease_expires_at = (
            uuid4(),
            now() + timedelta(seconds=LEASE_SECONDS),
        )
        history = db.get(IndexAttempt, (run.id, attempt))
        history.state, history.started_at, history.lease_epoch = (
            "RUNNING",
            now(),
            run.lease_epoch,
        )
        api.emit(db, run, "index.started")
        return {
            "run_id": run.id,
            "attempt": attempt,
            "epoch": run.lease_epoch,
            "token": run.lease_token,
            "recipe": run.recipe,
            "manifest_sha256": acquired.manifest_sha256,
            "objects": acquired.objects,
            "acquisition_manifest": acquired.manifest,
            "reserved_bytes": run.reserved_bytes,
        }


def checkpoint(lease, update):
    with transaction() as db:
        run, error = locked(db, lease["run_id"])
        if not owns(run, lease):
            return False
        if error:
            api.finish_failure(db, run, error, "发起人权限或来源身份已改变。")
            return False
        stage = update.get("stage")
        if stage in {"FETCHING", "INDEXING", "VERIFYING", "STORING"}:
            run.stage = stage
        run.progress = {
            **run.progress,
            **{k: v for k, v in update.items() if k in api.EMPTY_PROGRESS},
        }
        run.lease_expires_at = now() + timedelta(seconds=LEASE_SECONDS)
        api.emit(
            db, run, "index.progress", {"stage": run.stage, "progress": run.progress}
        )
        return True


def publish(lease, bundle, objects):
    with transaction() as db:
        run, error = locked(db, lease["run_id"])
        if not owns(run, lease):
            return False
        if error or run.recipe != api.recipe():
            api.finish_failure(
                db,
                run,
                error or "INDEX_RECIPE_CHANGED",
                "发起人权限、来源身份或构建配置已改变。",
            )
            return False
        api.quota_lock(db)
        size = sum(obj["bytes"] for obj in objects)
        if size > run.reserved_bytes:
            api.finish_failure(
                db, run, "INDEX_QUOTA_EXCEEDED", "索引产物超过预留容量。"
            )
            return False
        from sqlalchemy import func

        used = db.scalar(select(func.coalesce(func.sum(SourceIndex.artifact_bytes), 0)))
        reserved = db.scalar(
            select(func.coalesce(func.sum(IndexRun.reserved_bytes), 0))
        )
        limit = int(os.environ.get("INDEX_STORAGE_QUOTA_BYTES", str(20 * 1024**3)))
        if used + reserved - run.reserved_bytes + size > limit:
            api.finish_failure(
                db, run, "INDEX_QUOTA_EXCEEDED", "当前索引容量预算不足。"
            )
            return False
        manifest = bundle["manifest"]
        if (
            manifest["recipe_sha256"] != run.recipe_sha256
            or manifest["recipe_id"] != run.recipe["id"]
            or manifest["identity"]["acquisition_manifest_sha256"]
            != lease["manifest_sha256"]
        ):
            raise ValueError("Index manifest does not match admitted input and recipe")
        manifest_object = next(
            obj for obj in objects if obj["name"] == Path(bundle["manifest_path"]).name
        )
        ident = uuid4()
        db.add(
            SourceIndex(
                id=ident,
                run_id=run.id,
                acquisition_id=run.acquisition_id,
                source_id=run.source_id,
                recipe_sha256=run.recipe_sha256,
                identity_sha256=manifest["identity_sha256"],
                manifest_sha256=manifest_object["sha256"],
                manifest=manifest,
                objects=objects,
                artifact_bytes=size,
                created_at=now(),
            )
        )
        run.result = {
            "index_id": str(ident),
            "state": "INDEXED",
            "searchable": False,
            "identity_sha256": manifest["identity_sha256"],
            "manifest_sha256": manifest_object["sha256"],
            "counts": bundle["counts"],
            "quality": manifest["quality"],
            "artifact_bytes": size,
        }
        run.state, run.stage, run.reserved_bytes = "SUCCEEDED", "INDEXED", 0
        run.lease_token = run.lease_expires_at = None
        attempt = db.get(IndexAttempt, (run.id, run.attempt))
        attempt.state, attempt.finished_at = "SUCCEEDED", now()
        api.emit(db, run, "index.succeeded", {"result": run.result})
        return True


def fail_run(lease, code, message, retryable):
    with transaction() as db:
        run, error = locked(db, lease["run_id"])
        if owns(run, lease):
            api.finish_failure(
                db,
                run,
                error or code,
                "发起人权限或来源身份已改变。" if error else message,
                False if error else retryable,
            )


def verify_stream(stream, expected, callback, destination=None, stage="STORING"):
    digest, size = hashlib.sha256(), 0
    while chunk := stream.read(1024 * 1024):
        size += len(chunk)
        if size > expected["bytes"]:
            raise ValueError("Object exceeds recorded size")
        digest.update(chunk)
        if destination:
            destination.write(chunk)
        callback(
            {
                "stage": stage,
                "processed_bytes": size,
                "total_bytes": expected["bytes"],
                "processed_records": 0,
                "total_records": None,
                "file_name": expected["name"],
            }
        )
    if size != expected["bytes"] or digest.hexdigest() != expected["sha256"]:
        raise ValueError("Object checksum mismatch")


class LimitExceeded(ValueError):
    pass


class ProgressReader:
    """File wrapper checks the lease during the actual SDK upload reads."""

    def __init__(self, stream, callback, item):
        self.stream, self.callback, self.item = stream, callback, item

    def read(self, size=-1):
        data = self.stream.read(size)
        self.callback(
            {
                "stage": "STORING",
                "processed_bytes": self.stream.tell(),
                "total_bytes": self.item["bytes"],
                "file_name": self.item["name"],
                "processed_records": 0,
                "total_records": None,
            }
        )
        return data

    def __getattr__(self, name):
        return getattr(self.stream, name)


def execute(run_id, attempt):
    from pipelines.query import source_index

    lease = claim(UUID(str(run_id)), attempt)
    if not lease:
        return {"status": "duplicate_or_ineligible"}
    root = Path(
        os.environ.get(
            "INDEX_BUILD_TEMP_DIR",
            str(Path(__file__).resolve().parents[1] / "tmp" / "index-build"),
        )
    )
    directory = root / str(lease["run_id"]) / f"{attempt}-{lease['epoch']}"
    last_tick, phase = 0.0, "input_download"
    budget = int(os.environ.get("INDEX_BUILD_TEMP_BYTES", str(8 * 1024**3)))
    uploaded, uncertain_put, published = [], False, False

    def tick(update):
        nonlocal last_tick
        current = time.monotonic()
        if current - last_tick < 1:
            return
        update = dict(update)
        # Builder reports records; bytes are unknown, never workspace usage.
        if update.get("processed_bytes") is None:
            update["processed_bytes"] = 0
            update["total_bytes"] = None
        update.setdefault("file_name", None)
        if update.get("stage") in {
            "VALIDATING",
            "TOKENIZING",
            "CHARACTER_INDEX",
            "CWB_INDEX",
            "PACKAGING",
        }:
            update["stage"] = "INDEXING"
        size = 0
        for path in directory.rglob("*"):
            try:
                if path.is_file():
                    size += path.stat().st_size
            except FileNotFoundError:
                continue  # CWB removes transient construction files concurrently.
        if size > budget:
            raise LimitExceeded("temporary bytes")
        if not checkpoint(lease, update):
            raise Fenced()
        last_tick = current

    try:
        directory.mkdir(parents=True, exist_ok=False)
        if budget <= 0 or shutil.disk_usage(directory).free < budget:
            raise LimitExceeded("temporary capacity")
        inputs = {}
        for name in ("manifest.json", "corpus.sqlite3"):
            item = next(obj for obj in lease["objects"] if obj["name"] == name)
            path = directory / name
            stream = storage.read_private(
                item["object_key"], item["version_id"], item["etag"]
            )
            try:
                with path.open("wb") as output:
                    verify_stream(stream, item, tick, output, stage="FETCHING")
            finally:
                stream.close()
            inputs[name] = path
        raw = inputs["manifest.json"].read_bytes()
        if (
            hashlib.sha256(raw).hexdigest() != lease["manifest_sha256"]
            or json.loads(raw) != lease["acquisition_manifest"]
        ):
            raise ValueError("Acquisition manifest mismatch")
        if not checkpoint(lease, {"stage": "INDEXING"}):
            raise Fenced()
        phase = "index_build"
        bundle = source_index.build(
            inputs["corpus.sqlite3"],
            directory / "index",
            lease["manifest_sha256"],
            tick,
            max_temporary_bytes=budget,
        )
        if not checkpoint(lease, {"stage": "STORING"}):
            raise Fenced()
        phase = "artifact_storage"
        objects = []
        if sum(item["bytes"] for item in bundle["artifacts"]) > lease["reserved_bytes"]:
            raise LimitExceeded("reserved artifact bytes")
        for item in bundle["artifacts"]:
            if item["bytes"] > 4 * 1024**3:
                raise LimitExceeded("single PUT bytes")
            with Path(item["path"]).open("rb") as stream:
                verify_stream(stream, item, tick)
                stream.seek(0)
                key = f"source-index/{lease['run_id']}/{lease['epoch']}/{uuid4().hex}"
                uncertain_put = True
                version, etag = storage.put_private(
                    key,
                    ProgressReader(stream, tick, item),
                    item["bytes"],
                    "application/octet-stream",
                )
                uploaded.append((key, version))
                uncertain_put = False
            obj = {
                k: str(v) if isinstance(v, Path) else v
                for k, v in item.items()
                if k != "path"
            }
            obj.update(object_key=key, version_id=version, etag=etag)
            stream = storage.read_private(key, version, etag)
            try:
                verify_stream(stream, item, tick)
            finally:
                stream.close()
            objects.append(obj)
        phase = "publication"
        published = publish(lease, bundle, objects)
        return {"status": "indexed" if published else "fenced"}
    except Fenced:
        return {"status": "fenced"}
    except LimitExceeded:
        fail_run(
            lease, "INDEX_QUOTA_EXCEEDED", "索引构建超过当前存储或临时磁盘预算。", False
        )
        return {"status": "failed", "code": "INDEX_QUOTA_EXCEEDED"}
    except Exception as exc:  # noqa: BLE001
        LOGGER.error(
            "index_build_failed %s",
            json.dumps(
                {
                    "run_id": str(lease["run_id"]),
                    "attempt": attempt,
                    "phase": phase,
                    "exceptions": safe_exception(exc),
                },
                separators=(",", ":"),
            ),
        )
        fail_run(
            lease, "INDEX_EXECUTION_FAILED", "索引构建失败，可有限人工重试。", True
        )
        return {"status": "failed", "code": "INDEX_EXECUTION_FAILED"}
    finally:
        cleanup_allowed = not published
        if cleanup_allowed:
            try:
                # A lost COMMIT acknowledgement must not delete a registered index.
                # Locking the run waits for the prior publication transaction.
                with transaction() as db:
                    current, _ = locked(db, lease["run_id"])
                    if current and current.state == "SUCCEEDED":
                        published, cleanup_allowed = True, False
            except Exception:  # noqa: BLE001 - uncertain DB outcome retains objects/reservation
                cleanup_allowed = False
        if cleanup_allowed:
            cleaned = not uncertain_put
            for key, version in uploaded:
                try:
                    storage.client().delete_object(
                        Bucket=storage.bucket(), Key=key, VersionId=version
                    )
                except Exception:  # noqa: BLE001 - preserve reservation on uncertain cleanup
                    cleaned = False
            if cleaned:
                with transaction() as db:
                    run, _ = locked(db, lease["run_id"])
                    if run and run.attempt == attempt and run.state != "SUCCEEDED":
                        if run.state == "RUNNING" and run.lease_expires_at <= now():
                            api.finish_failure(
                                db,
                                run,
                                "WORKER_LEASE_EXPIRED",
                                "执行租约过期，可人工重试。",
                                True,
                            )
                        if run.state in {"FAILED", "CANCELLED"}:
                            run.reserved_bytes = 0
                            api.emit(db, run, "index.staging_cleaned")
            else:
                with transaction() as db:
                    run, _ = locked(db, lease["run_id"])
                    if (
                        run
                        and run.attempt == attempt
                        and run.state in {"FAILED", "CANCELLED"}
                    ):
                        run.error = {
                            "code": "INDEX_CLEANUP_REQUIRED",
                            "message": "本次暂存对象的写入或清理结果未知，保留容量预留，需人工核查。",
                            "retryable": False,
                        }
                        api.emit(
                            db, run, "index.cleanup_required", {"error": run.error}
                        )
        if directory.is_dir() and directory.resolve().is_relative_to(root.resolve()):
            shutil.rmtree(directory)
