"""Fenced snapshot preparation and first-page/full-span tasks in the index worker."""

import hashlib
import json
import logging
import os
import shutil
import time
from datetime import timedelta
from pathlib import Path
from uuid import UUID, uuid4

from sqlalchemy import select

from services.api import research as api
from services.api import storage
from services.api.db import lock_actor, lock_project, transaction
from services.api.errors import ApiError
from services.api.jobs import now
from services.api.research_models import QueryRun, ResearchTask, Snapshot
from workers.index_build import Fenced, ProgressReader, safe_exception

LOGGER = logging.getLogger(__name__)
LEASE_SECONDS = 90


def check_cache_budget(root):
    from pipelines.query.engine import QueryError

    used = 0
    for path in root.rglob("*"):
        try:
            if path.is_file():
                used += path.stat().st_size
        except FileNotFoundError:
            continue
    if used > int(os.environ.get("QUERY_CACHE_MAX_BYTES", str(16 * 1024**3))):
        raise QueryError("QUERY_CACHE_QUOTA_EXCEEDED")
    return used


def locked(db, task_id):
    hint = db.get(ResearchTask, task_id)
    if not hint:
        return None, None, "TASK_NOT_FOUND"
    lock_actor(db, hint.actor_id)
    lock_project(db, hint.project_id)
    index, error = None, None
    try:
        project, _, index = api.resolve_snapshot(
            db, hint.actor_id, hint.project_id, hint.snapshot_id
        )
        if hint.phase == "SNAPSHOT" and api.project_role(
            db, hint.actor_id, project
        ) not in {"owner", "editor"}:
            error = "PROJECT_FORBIDDEN"
    except ApiError as exc:
        error = exc.code
    task = db.scalar(
        select(ResearchTask)
        .where(ResearchTask.id == task_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    return task, index, error


def owns(task, lease):
    return bool(
        task
        and task.state == "RUNNING"
        and task.attempt == lease["attempt"]
        and task.lease_epoch == lease["epoch"]
        and task.lease_token == lease["token"]
        and task.lease_expires_at
        and task.lease_expires_at > now()
    )


def admit(db, run):
    """Worker sees all rows; queued reservations compete only when actually claimed."""
    from sqlalchemy import text

    db.execute(
        text(
            "SELECT pg_advisory_xact_lock(hashtextextended('research-result-budget',0))"
        )
    )
    rows = list(db.scalars(select(QueryRun).where(QueryRun.id != run.id)))
    used = project_used = 0
    for row in rows:
        amount = int((row.result_object or {}).get("bytes", 0))
        if row.state != "QUEUED":
            amount += row.reserved_bytes
        used += amount
        if row.project_id == run.project_id:
            project_used += amount
    return used + run.reserved_bytes <= int(
        os.environ.get("QUERY_STORAGE_MAX_BYTES", str(2 * 1024**3))
    ) and project_used + run.reserved_bytes <= int(
        os.environ.get("QUERY_PROJECT_MAX_BYTES", str(1024**3))
    )


def claim(task_id, attempt):
    with transaction() as db:
        task, index, error = locked(db, task_id)
        if not task or task.state != "QUEUED" or task.attempt != attempt:
            return None
        run = db.get(QueryRun, task.run_id) if task.run_id else None
        snapshot = db.get(Snapshot, task.snapshot_id)
        if error:
            unclaimed = task.state == "QUEUED"
            api.finish_failure(
                db,
                task,
                error or "PROJECT_FORBIDDEN",
                "当前成员、来源或挂载权限已改变。",
            )
            if run and run.state == "FAILED" and unclaimed:
                run.reserved_bytes = 0
            if snapshot and task.phase == "SNAPSHOT" and unclaimed:
                snapshot.reserved_bytes = 0
            return None
        if task.phase == "SNAPSHOT" and api.is_project(snapshot):
            from workers.project_material_index import admit as admit_index

            if not admit_index(db, snapshot):
                api.finish_failure(
                    db,
                    task,
                    "PROJECT_INDEX_QUOTA_EXCEEDED",
                    "全局或项目索引预算不足。",
                    True,
                )
                snapshot.reserved_bytes = 0
                return None
        if run and task.phase != "PREPARE_CACHE":
            if run.state in api.TERMINAL:
                return None
            if (
                task.phase == "FIRST_PAGE"
                and run.state == "QUEUED"
                and not admit(db, run)
            ):
                api.finish_failure(
                    db,
                    task,
                    "QUERY_QUOTA_EXCEEDED",
                    "全局或项目已登记结果及已领取任务超出预算。",
                    True,
                )
                run.reserved_bytes = 0
                return None
            run.state, run.updated_at = "RUNNING", now()
        task.state, task.lease_epoch = "RUNNING", task.lease_epoch + 1
        task.lease_token, task.lease_expires_at = (
            uuid4(),
            now() + timedelta(seconds=LEASE_SECONDS),
        )
        api.emit(db, task, "research.started")
        return {
            "task_id": task.id,
            "project_id": task.project_id,
            "project_build": task.phase == "SNAPSHOT" and api.is_project(snapshot),
            "snapshot_inputs": api.snapshot_inputs(db, snapshot)
            if task.phase == "SNAPSHOT" and api.is_project(snapshot)
            else [],
            "snapshot_manifest_sha256": snapshot.manifest_sha256,
            "snapshot_reserved_bytes": snapshot.reserved_bytes,
            "attempt": task.attempt,
            "epoch": task.lease_epoch,
            "token": task.lease_token,
            "phase": task.phase,
            "run_id": task.run_id,
            "snapshot_id": task.snapshot_id,
            "index_manifest": index.manifest,
            "manifest_sha256": index.manifest_sha256,
            "index_identity": index.identity_sha256,
            "index_objects": index.objects,
            "query": run.query if run else None,
            "page_size": run.page_size if run else None,
            "context_codepoints": run.context_codepoints if run else None,
            "result_set_id": run.result_set_id if run else None,
            "result_object": run.result_object if run else None,
            "counts": run.counts if run else None,
            "run_attempt": run.attempt if run else None,
            "first_page": run.first_page if run else None,
        }


def heartbeat(lease, update):
    with transaction() as db:
        task, _, error = locked(db, lease["task_id"])
        if not owns(task, lease):
            return False
        if error:
            api.finish_failure(db, task, error, "当前成员、来源或挂载权限已改变。")
            return False
        task.progress = {
            **task.progress,
            **{
                key: value for key, value in update.items() if key in api.EMPTY_PROGRESS
            },
        }
        if task.progress["processed_bytes"] is None:
            task.progress["processed_bytes"] = 0
        if task.progress["processed_records"] is None:
            task.progress["processed_records"] = 0
        task.lease_expires_at = now() + timedelta(seconds=LEASE_SECONDS)
        api.emit(db, task, "research.progress", task.progress)
        return True


def publish(lease, *, page=None, result=None, counts=None, index_result=None):
    check_cache_budget(
        api.cache_root()
    )  # Always check final bytes, without sampling throttle.
    with transaction() as db:
        task, _, error = locked(db, lease["task_id"])
        if not owns(task, lease):
            return False
        if error:
            api.finish_failure(db, task, error, "当前成员、来源或挂载权限已改变。")
            return False
        snapshot = db.get(Snapshot, task.snapshot_id)
        run = db.get(QueryRun, task.run_id) if task.run_id else None
        if task.phase == "SNAPSHOT":
            if api.is_project(snapshot):
                from workers.project_material_index import admit as admit_index

                if (
                    not index_result
                    or not admit_index(db, snapshot)
                    or sum(x["bytes"] for x in index_result["objects"])
                    > snapshot.reserved_bytes
                ):
                    api.finish_failure(
                        db,
                        task,
                        "PROJECT_INDEX_QUOTA_EXCEEDED",
                        "项目索引产物超出预留。",
                    )
                    return False
                snapshot.index_result = index_result
                snapshot.reserved_bytes = 0
            snapshot.state, snapshot.updated_at = "READY", now()
        elif task.phase == "FIRST_PAGE":
            if run.attempt != lease["run_attempt"] or run.state != "RUNNING":
                return False
            run.first_page, run.updated_at = page, now()
            full = api.task_for(db, snapshot.id, run.id, "FULL_RESULT")
            if full:
                api.reset_task(db, full)
            else:
                api.new_task(db, snapshot, run.actor_id, "FULL_RESULT", run)
        elif task.phase == "FULL_RESULT":
            if (
                run.attempt != lease["run_attempt"]
                or run.state != "RUNNING"
                or result["bytes"] > run.reserved_bytes
            ):
                return False
            run.result_object, run.counts, run.reserved_bytes = (
                result,
                {
                    key: counts[key]
                    for key in (
                        "total_hits",
                        "matched_segments",
                        "matched_documents",
                        "matched_source_documents",
                        "matched_private_documents",
                    )
                    if key in counts
                },
                0,
            )
            run.state, run.updated_at = "SUCCEEDED", now()
        task.state, task.lease_token, task.lease_expires_at = "SUCCEEDED", None, None
        api.emit(db, task, "research.succeeded")
        return True


def fail_task(lease, code, message, retryable):
    with transaction() as db:
        task, _, error = locked(db, lease["task_id"])
        if owns(task, lease):
            cleanup = (task.error or {}).get("code") == "PROJECT_INDEX_CLEANUP_REQUIRED"
            if cleanup:
                code, message, retryable = (
                    task.error["code"],
                    task.error["message"],
                    False,
                )
            api.finish_failure(
                db,
                task,
                error or code,
                "当前成员、来源或挂载权限已改变。" if error else message,
                retryable and not error,
            )


def execute(task_id, attempt):
    from pipelines.query.source_cache import open_cached, prepare_index
    from pipelines.query.source_reader import SourceIndexReader
    from pipelines.query.source_results import (
        first_page,
        install_result,
        read_page,
        write_spans,
    )

    lease = claim(UUID(str(task_id)), attempt)
    if not lease:
        return {"status": "duplicate_or_ineligible"}
    root = api.cache_root()
    temporary = root / "work" / str(lease["task_id"]) / f"{attempt}-{lease['epoch']}"
    uploaded, uncertain, published, last_tick = None, False, False, 0.0
    installed_path = None

    def tick(update):
        nonlocal last_tick
        current = time.monotonic()
        if current - last_tick >= 1:
            check_cache_budget(root)
            if not heartbeat(lease, update):
                raise Fenced()
            last_tick = current

    try:
        temporary.mkdir(parents=True, exist_ok=False)
        if lease["project_build"]:
            from workers.project_material_index import execute as build_snapshot

            published = build_snapshot(lease, temporary, tick)
            return {"status": "complete" if published else "fenced"}
        objects = {item["name"]: item for item in lease["index_objects"]}
        manifest_item, package = objects["manifest.json"], objects["index.tar"]
        stream = storage.read_private(
            manifest_item["object_key"],
            manifest_item["version_id"],
            manifest_item["etag"],
        )
        try:
            raw = stream.read(1024**2 + 1)
        finally:
            stream.close()
        if (
            len(raw) != manifest_item["bytes"]
            or hashlib.sha256(raw).hexdigest() != lease["manifest_sha256"]
            or json.loads(raw) != lease["index_manifest"]
            or package["sha256"] != lease["index_manifest"]["package"]["sha256"]
            or package["bytes"] != lease["index_manifest"]["package"]["bytes"]
        ):
            raise ValueError("INDEX_RECEIPT_MISMATCH")
        cached = None
        if lease["phase"] in {"FIRST_PAGE", "FULL_RESULT"}:
            try:
                with open_cached(
                    root / "indexes", package["sha256"], lease["index_identity"]
                ) as check:
                    cached = {"directory": check.directory}
            except (ValueError, OSError):
                if lease["phase"] == "FULL_RESULT":
                    raise ValueError("CACHE_NOT_READY") from None
        if cached is None:
            cached = prepare_index(
                root / "indexes",
                raw,
                lease["manifest_sha256"],
                lambda: storage.read_private(
                    package["object_key"], package["version_id"], package["etag"]
                ),
                tick,
                max_cache_bytes=int(
                    os.environ.get("QUERY_INDEX_CACHE_MAX_BYTES", str(12 * 1024**3))
                ),
            )
        if lease["phase"] == "SNAPSHOT":
            published = publish(lease)
        elif lease["phase"] == "PREPARE_CACHE":
            item = lease["result_object"]
            path = (
                root
                / "results"
                / str(lease["result_set_id"])
                / (item["sha256"] + ".spans")
            )
            stream = storage.read_private(
                item["object_key"], item["version_id"], item["etag"]
            )
            try:
                install_result(stream, item["bytes"], item["sha256"], path, tick)
            finally:
                stream.close()
            published = publish(lease)
        else:
            with SourceIndexReader(
                cached["directory"], temporary / "cqp", verify=False
            ) as reader:
                if lease["phase"] == "FIRST_PAGE":
                    page = first_page(
                        reader,
                        lease["query"],
                        limit=lease["page_size"],
                        context_codepoints=lease["context_codepoints"],
                        progress_callback=tick,
                    )
                    published = publish(lease, page=page)
                else:
                    result = write_spans(
                        reader,
                        lease["query"],
                        temporary / "result.spans",
                        tick,
                        max_bytes=int(
                            os.environ.get("QUERY_RESULT_MAX_BYTES", str(512 * 1024**2))
                        ),
                    )
                    page = read_page(
                        reader,
                        result["path"],
                        0,
                        limit=lease["page_size"],
                        context_codepoints=lease["context_codepoints"],
                        expected_sha256=result["sha256"],
                        expected_records=result["record_count"],
                    )
                    if page != lease["first_page"]:
                        raise ValueError("FIRST_PAGE_RESULT_MISMATCH")
                    item = {
                        "name": "result.spans",
                        "bytes": result["bytes"],
                        "sha256": result["sha256"],
                    }
                    with Path(result["path"]).open("rb") as stream:
                        key = f"query-results/{lease['result_set_id']}/{uuid4().hex}"
                        uncertain = True
                        version, etag = storage.put_private(
                            key,
                            ProgressReader(stream, tick, item),
                            item["bytes"],
                            "application/octet-stream",
                        )
                        uploaded, uncertain = (key, version), False
                    item.update(object_key=key, version_id=version, etag=etag)
                    stream = storage.read_private(key, version, etag)
                    try:
                        target = (
                            root
                            / "results"
                            / str(lease["result_set_id"])
                            / (item["sha256"] + ".spans")
                        )
                        installed_path = target
                        install_result(
                            stream, item["bytes"], item["sha256"], target, tick
                        )
                    finally:
                        stream.close()
                    published = publish(lease, result=item, counts=result["counts"])
        return {"status": "complete" if published else "fenced"}
    except Fenced:
        return {"status": "fenced"}
    except Exception as exc:  # noqa: BLE001 - no raw provider text or material in logs
        known = (
            str(exc)
            if type(exc).__name__ in {"QueryError", "IndexBuildError", "MaterialError"}
            and str(exc).isupper()
            and len(str(exc)) < 80
            else "PROJECT_INDEX_EXECUTION_FAILED"
            if lease["project_build"]
            else "QUERY_EXECUTION_FAILED"
        )
        LOGGER.error(
            "research_failed %s",
            json.dumps(
                {"task_id": str(lease["task_id"]), "exceptions": safe_exception(exc)},
                separators=(",", ":"),
            ),
        )
        fail_task(
            lease,
            known,
            "项目索引准备失败，请查看任务状态。"
            if lease["project_build"]
            else "查询或缓存准备失败，请查看任务状态。",
            known
            in {
                "QUERY_EXECUTION_FAILED",
                "PROJECT_INDEX_EXECUTION_FAILED",
                "QUERY_TIMEOUT",
                "CACHE_NOT_READY",
            },
        )
        return {"status": "failed", "code": known}
    finally:
        cleanup = not published
        if cleanup:
            try:
                with transaction() as db:
                    task, _, _ = locked(db, lease["task_id"])
                    run = (
                        db.get(QueryRun, task.run_id) if task and task.run_id else None
                    )
                    # A lost COMMIT response must not delete a published immutable object.
                    if (
                        run
                        and run.result_object
                        and uploaded
                        and run.result_object["object_key"] == uploaded[0]
                    ):
                        cleanup = False
            except Exception:  # noqa: BLE001 - uncertain commit retains exact objects and reservation
                cleanup = False
        cleaned = not uncertain
        if cleanup and uploaded:
            try:
                storage.client().delete_object(
                    Bucket=storage.bucket(), Key=uploaded[0], VersionId=uploaded[1]
                )
            except Exception:  # noqa: BLE001
                cleaned = False
        if cleanup and installed_path is not None:
            try:
                with transaction() as db:
                    task, _, _ = locked(db, lease["task_id"])
                    registered = db.get(QueryRun, lease["run_id"])
                    registered_digest = (
                        (registered.result_object or {}).get("sha256")
                        if registered
                        else None
                    )
                    if registered_digest != installed_path.stem:
                        if not installed_path.resolve().is_relative_to(
                            (root / "results" / str(lease["result_set_id"])).resolve()
                        ):
                            raise ValueError("Invalid private result path")
                        installed_path.unlink(missing_ok=True)
                        installed_path.with_name(
                            installed_path.name + ".ready.json"
                        ).unlink(missing_ok=True)
            except Exception:  # noqa: BLE001 - uncertain publication/cache cleanup retains reservation
                cleaned = False
        if cleanup and lease["run_id"] and lease["phase"] != "PREPARE_CACHE":
            with transaction() as db:
                task, _, _ = locked(db, lease["task_id"])
                run = db.get(QueryRun, lease["run_id"])
                if (
                    task
                    and task.state == "RUNNING"
                    and task.lease_token == lease["token"]
                    and task.lease_expires_at <= now()
                ):
                    api.finish_failure(
                        db, task, "WORKER_LEASE_EXPIRED", "执行租约已过期。", True
                    )
                if (
                    run
                    and run.attempt == lease["run_attempt"]
                    and run.state in {"FAILED", "CANCELLED"}
                ):
                    if cleaned:
                        run.reserved_bytes = 0
                    else:
                        run.error = {
                            "code": "QUERY_CLEANUP_REQUIRED",
                            "message": "私有对象写入或清理结果未知，保留预算等待核查。",
                            "retryable": False,
                        }
        if temporary.is_dir() and temporary.resolve().is_relative_to(root.resolve()):
            shutil.rmtree(temporary)
