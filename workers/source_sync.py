"""Bounded source acquisition worker with database fencing and private artifacts."""

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

from services.api import source_sync as api
from services.api import storage
from services.api.catalog_models import CatalogSource
from services.api.db import lock_actor, transaction
from services.api.jobs import now
from services.api.models import User
from services.api.source_sync_models import Acquisition, SyncAttempt, SyncRun

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
    hint = db.get(SyncRun, run_id)
    if not hint:
        return None, False
    lock_actor(db, hint.actor_id)
    api.lock_source(db, hint.source_id)
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
    identity_ok = source and api.identity(source) == row.source_identity
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
        if error:
            api.finish_failure(db, run, error, "发起人权限或来源身份已改变。")
            return None
        run.state, run.stage = "RUNNING", "ACQUIRING"
        run.lease_epoch += 1
        run.lease_token, run.lease_expires_at = (
            uuid4(),
            now() + timedelta(seconds=LEASE_SECONDS),
        )
        history = db.get(SyncAttempt, (run.id, attempt))
        history.state, history.started_at, history.lease_epoch = (
            "RUNNING",
            now(),
            run.lease_epoch,
        )
        api.emit(db, run, "sync.started")
        previous = (
            db.get(Acquisition, run.previous_acquisition_id)
            if run.previous_acquisition_id
            else None
        )
        return {
            "run_id": run.id,
            "attempt": attempt,
            "epoch": run.lease_epoch,
            "token": run.lease_token,
            "expected": run.expected_inputs,
            "previous": previous.objects if previous else [],
        }


def checkpoint(lease, update):
    with transaction() as db:
        run, error = locked(db, lease["run_id"])
        if not owns(run, lease):
            return False
        if error:
            api.finish_failure(db, run, error, "发起人权限或来源身份已改变。")
            return False
        if update.get("expected") is not None:
            if (
                run.expected_inputs is not None
                and run.expected_inputs != update["expected"]
            ):
                api.finish_failure(
                    db,
                    run,
                    "SOURCE_VERSION_CHANGED",
                    "上游版本已改变，请新建同步任务。",
                )
                return False
            run.expected_inputs = update["expected"]
        stage = update.get("stage")
        if stage in {"ACQUIRING", "PARSING", "STORING"}:
            run.stage = stage
        run.progress = {
            **run.progress,
            **{k: v for k, v in update.items() if k in api.EMPTY_PROGRESS},
        }
        run.lease_expires_at = now() + timedelta(seconds=LEASE_SECONDS)
        api.emit(
            db, run, "sync.progress", {"stage": run.stage, "progress": run.progress}
        )
        return True


def publish(lease, bundle, objects):
    with transaction() as db:
        run, error = locked(db, lease["run_id"])
        if not owns(run, lease):
            return False
        if error:
            api.finish_failure(db, run, error, "发起人权限或来源身份已改变。")
            return False
        manifest = bundle["manifest"]
        manifest_object = next(
            obj for obj in objects if obj["name"] == Path(bundle["manifest_path"]).name
        )
        ident = uuid4()
        db.add(
            Acquisition(
                id=ident,
                run_id=run.id,
                source_id=run.source_id,
                connector_id=run.connector_id,
                source_identity=run.source_identity,
                manifest_sha256=manifest_object["sha256"],
                manifest=manifest,
                objects=objects,
                created_at=now(),
            )
        )
        run.result = {
            "acquisition_id": str(ident),
            "state": "VALIDATED",
            "searchable": False,
            "manifest_sha256": manifest_object["sha256"],
            "export_date": manifest.get("export_date"),
            "quality": manifest["quality"],
            "diff": manifest["diff"],
            "license": manifest["license"],
        }
        run.state, run.stage = "SUCCEEDED", "VALIDATED"
        run.lease_token = run.lease_expires_at = None
        attempt = db.get(SyncAttempt, (run.id, run.attempt))
        attempt.state, attempt.finished_at = "SUCCEEDED", now()
        api.emit(db, run, "sync.succeeded", {"result": run.result})
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
        callback({"stage": stage})
    if size != expected["bytes"] or digest.hexdigest() != expected["sha256"]:
        raise ValueError("Object checksum mismatch")


def execute(run_id, attempt):
    from pipelines.sources import tatoeba

    lease = claim(UUID(str(run_id)), attempt)
    if not lease:
        return {"status": "duplicate_or_ineligible"}
    root = Path(
        os.environ.get(
            "SOURCE_SYNC_TEMP_DIR",
            Path(__file__).resolve().parents[1] / "tmp" / "source-sync",
        )
    )
    directory = root / str(lease["run_id"]) / f"{attempt}-{lease['epoch']}"
    directory.mkdir(parents=True, exist_ok=False)
    last_tick = 0.0
    phase = "acquisition"

    def tick(update):
        nonlocal last_tick
        update = dict(update)
        mapped_stage = {
            "download": "ACQUIRING",
            "pinned": "ACQUIRING",
            "parse": "PARSING",
        }.get(update.get("stage"))
        if mapped_stage:
            update["stage"] = mapped_stage
        current = time.monotonic()
        if "expected" not in update and current - last_tick < 1:
            return
        if not checkpoint(lease, update):
            raise Fenced()
        last_tick = current

    try:
        acquired = tatoeba.acquire(directory / "raw", tick, expected=lease["expected"])
        if not checkpoint(
            lease, {"expected": acquired["expected"], "stage": "PARSING"}
        ):
            raise Fenced()
        previous_path = None
        phase = "baseline_read"
        previous = next(
            (obj for obj in lease["previous"] if obj["name"].endswith(".sqlite3")), None
        )
        if previous:
            previous_path = directory / "previous.sqlite3"
            stream = storage.read_private(
                previous["object_key"], previous["version_id"], previous["etag"]
            )
            try:
                with previous_path.open("wb") as output:
                    verify_stream(stream, previous, tick, output, stage="PARSING")
            finally:
                stream.close()
        phase = "parsing"
        bundle = tatoeba.parse(
            acquired, directory / "parsed", tick, previous_database=previous_path
        )
        if not checkpoint(lease, {"stage": "STORING"}):
            raise Fenced()
        phase = "artifact_storage"
        objects = []
        for item in bundle["artifacts"]:
            # Each artifact is verified before and after version-pinned storage.
            with Path(item["path"]).open("rb") as stream:
                verify_stream(stream, item, tick)
                stream.seek(0)
                key = f"source-sync/{lease['run_id']}/{lease['epoch']}/{uuid4().hex}"
                version, etag = storage.put_private(
                    key, stream, item["bytes"], item["media_type"]
                )
            obj = {k: v for k, v in item.items() if k != "path"}
            obj.update(object_key=key, version_id=version, etag=etag)
            stream = storage.read_private(key, version, etag)
            try:
                verify_stream(stream, item, tick)
            finally:
                stream.close()
            objects.append(obj)
            if not checkpoint(lease, {"stage": "STORING"}):
                raise Fenced()
        phase = "publication"
        return {"status": "staged" if publish(lease, bundle, objects) else "fenced"}
    except Fenced:
        return {"status": "fenced"}
    except tatoeba.SourceError as exc:
        code = getattr(exc, "code", "SOURCE_VALIDATION_FAILED")
        fail_run(
            lease,
            code,
            "来源获取或质量校验失败；详见固定错误码。",
            code == "SOURCE_DOWNLOAD_FAILED",
        )
        return {"status": "failed", "code": code}
    except Exception as exc:  # noqa: BLE001 - no credentials/body/exception text
        LOGGER.error(
            "source_sync_failed %s",
            json.dumps(
                {
                    "run_id": str(lease["run_id"]),
                    "attempt": lease["attempt"],
                    "phase": phase,
                    "exceptions": safe_exception(exc),
                },
                separators=(",", ":"),
            ),
        )
        fail_run(
            lease, "SOURCE_EXECUTION_FAILED", "同步执行失败，可有限人工重试。", True
        )
        return {"status": "failed", "code": "SOURCE_EXECUTION_FAILED"}
    finally:
        # Only this newly-created attempt directory; never shared data or old objects.
        if directory.resolve().is_relative_to(root.resolve()):
            shutil.rmtree(directory)
