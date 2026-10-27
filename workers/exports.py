"""Full immutable-result exports on corpus.index; no query is executed again."""

import json
import logging
import os
import shutil
import time
from datetime import timedelta
from pathlib import Path
from uuid import UUID, uuid4

from sqlalchemy import select, text

from services.api import exports as api
from services.api import outcomes, research, source_mounts, source_releases, storage
from services.api.db import transaction
from services.api.errors import ApiError
from services.api.job_models import Attempt, Job
from services.api.jobs import emit, finish_failure, now
from services.api.material_models import Material, MaterialRevision
from services.api.outcome_models import ExportRecord
from workers.index_build import ProgressReader, safe_exception, verify_stream
from workers.validation import LEASE_SECONDS, owns

LOGGER = logging.getLogger(__name__)


class Fenced(Exception):
    pass


def locked_job(db, ident):
    job = db.get(Job, ident)
    if not job or job.kind != "EXPORT":
        return None, False
    permitted = True
    try:
        source_mounts.project(db, job.actor_id, job.project_id)
        record = db.get(ExportRecord, job.id)
        if not record:
            return job, False
        api.authorize(db, job.actor_id, record)
    except ApiError:
        permitted = False
    job = db.scalar(
        select(Job)
        .where(Job.id == ident)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    return job, permitted


def admit(db, job):
    db.execute(
        text(
            "SELECT pg_advisory_xact_lock(hashtextextended('export-storage-budget',0))"
        )
    )
    total = local = 0
    for record in db.scalars(select(ExportRecord)):
        size = (record.artifact or {}).get("bytes", 0)
        total += size
        if record.project_id == job.project_id:
            local += size
    for other in db.scalars(
        select(Job).where(Job.kind == "EXPORT", Job.id != job.id, Job.state != "QUEUED")
    ):
        total += other.reserved_bytes
        if other.project_id == job.project_id:
            local += other.reserved_bytes
    return total + job.reserved_bytes <= int(
        os.environ.get("EXPORT_STORAGE_MAX_BYTES", str(4 * 1024**3))
    ) and local + job.reserved_bytes <= int(
        os.environ.get("EXPORT_PROJECT_MAX_BYTES", str(2 * 1024**3))
    )


def claim(job_id, number):
    with transaction() as db:
        job, permitted = locked_job(db, job_id)
        if not job or job.state != "QUEUED" or job.attempt != number:
            return None
        if (
            not permitted
            or not admit(db, job)
            or job.input.get("recipe") != api.recipe()
        ):
            finish_failure(
                db,
                job,
                "EXPORT_POLICY_DENIED" if not permitted else "EXPORT_QUOTA_EXCEEDED",
                "当前权限、固定配置或导出预算不允许执行。",
            )
            job.reserved_bytes = 0
            return None
        job.state, job.stage, job.lease_token = "RUNNING", "EXPORTING", uuid4()
        job.lease_epoch += 1
        job.lease_expires_at = now() + timedelta(seconds=LEASE_SECONDS)
        attempt = db.get(Attempt, (job.id, job.attempt))
        attempt.state, attempt.lease_epoch, attempt.started_at = (
            "RUNNING",
            job.lease_epoch,
            now(),
        )
        emit(db, job, "export.started")
        return {
            "job_id": job.id,
            "project_id": job.project_id,
            "actor_id": job.actor_id,
            "attempt": job.attempt,
            "epoch": job.lease_epoch,
            "token": job.lease_token,
            "reserved_bytes": job.reserved_bytes,
        }


def heartbeat(lease, update):
    with transaction() as db:
        job, permitted = locked_job(db, lease["job_id"])
        if not owns(job, lease):
            return False
        if not permitted:
            finish_failure(
                db, job, "EXPORT_POLICY_DENIED", "当前项目或来源导出权限已撤销。"
            )
            return False
        job.stage = "STORING" if update.get("stage") == "STORING" else "EXPORTING"
        job.progress = {
            **(job.progress or api.EMPTY_PROGRESS),
            **{k: v for k, v in update.items() if k in api.EMPTY_PROGRESS},
        }
        for key in ("processed_bytes", "processed_records"):
            if job.progress[key] is None:
                job.progress[key] = 0
        job.lease_expires_at = now() + timedelta(seconds=LEASE_SECONDS)
        emit(db, job, "export.progress", job.progress)
        return True


def build_inputs(lease, checkpoint=lambda: None):
    with transaction() as db:
        job, permitted = locked_job(db, lease["job_id"])
        if not owns(job, lease) or not permitted:
            raise Fenced()
        record = db.get(ExportRecord, job.id)
        authorized = api.authorize(db, job.actor_id, record)
        run_map = {str(r.id): r for r in authorized}
        ordered = (
            record.target["query_run_ids"]
            if record.target["kind"] == "query_runs"
            else sorted(run_map)
        )
        methods = {
            "schema_version": "corpus-export/v1",
            "target": record.target,
            "project_id": str(job.project_id),
            "created_at": job.created_at.isoformat(),
            "recipe": api.recipe(),
            "queries": [],
            "snapshot_manifests": [],
            "source_permissions": [],
            "private_materials": [],
        }
        inputs = []
        for ident in ordered:
            checkpoint()
            run = run_map[ident]
            _, snapshot, index = research.resolve_snapshot(
                db, job.actor_id, job.project_id, run.snapshot_id, ready=True
            )
            methods["queries"].append(outcomes.method(db, job.actor_id, run))
            methods["snapshot_manifests"].append(
                {
                    "snapshot_id": str(snapshot.id),
                    "manifest_sha256": snapshot.manifest_sha256,
                    "index_identity_sha256": index.identity_sha256,
                    "recipe": methods["queries"][-1]["recipe"],
                    "members": snapshot.manifest["members"],
                }
            )
            for member in snapshot.manifest["members"]:
                if member["kind"] == "whole_source_mount":
                    _, _, release, _ = source_mounts.resolve_mount(
                        db, job.actor_id, job.project_id, UUID(member["mount_id"])
                    )
                    policy = source_releases.current_policy(db, release.acquisition_id)
                    methods["source_permissions"].append(
                        {
                            "source_id": release.source_id,
                            "acquisition_id": str(release.acquisition_id),
                            "policy_revision": policy.revision,
                            "export_decision": policy.export_decision,
                            "license_sha256": policy.license_sha256,
                            "license": source_releases.acquisition(
                                db, release.source_id, release.acquisition_id
                            ).manifest.get("license", {}),
                            "evidence_urls": policy.evidence_urls,
                        }
                    )
                else:
                    revision = db.get(
                        MaterialRevision, UUID(member["material_revision_id"])
                    )
                    material = db.get(Material, revision.material_id)
                    methods["private_materials"].append(
                        {
                            "material_id": str(material.id),
                            "revision_id": str(revision.id),
                            "filename": material.name,
                            "upload_id": str(revision.upload_id),
                        }
                    )
            inputs.append(
                {
                    "run": run,
                    "index": index,
                    "single_source_id": snapshot.manifest["members"][0]["source_id"]
                    if not research.is_project(snapshot)
                    else None,
                }
            )
        note_row = None
        if record.target["kind"] == "note_revision":
            note, row = outcomes.load_note(
                db,
                job.actor_id,
                job.project_id,
                UUID(record.target["note_id"]),
                record.target["revision"],
            )
            value = outcomes.note_view(db, job.actor_id, note, row)
            note_row = {
                "record_type": "note_revision",
                "note_id": str(note.id),
                "revision": row.revision,
                "title": row.title,
                "body": row.body,
                "status": value["status"],
                "evidence_refs": [],
                "query_run_ids": row.query_run_ids,
                "authorization_evidence_ids": row.authorization_evidence_ids,
                "authorization_query_run_ids": row.authorization_query_run_ids,
            }
            for eid in row.evidence_ids:
                checkpoint()
                evidence = db.get(outcomes.Evidence, UUID(eid))
                run = run_map[str(evidence.query_run_id)]
                item = next(x for x in inputs if x["run"].id == run.id)
                ordinal = research.read_cached(run, item["index"], evidence.ordinal, 1)[
                    "hits"
                ][0]["sentence_ordinal"]
                value = outcomes.evidence_view(db, job.actor_id, evidence)
                note_row["evidence_refs"].append(value)
                value["_sentence_ordinal"] = ordinal
        checkpoint()
        return record.format, methods, inputs, note_row


def publish(lease, artifact, methods):
    with transaction() as db:
        job, permitted = locked_job(db, lease["job_id"])
        if not owns(job, lease):
            return False
        if not permitted:
            finish_failure(
                db, job, "EXPORT_POLICY_DENIED", "发布前当前导出权限已失效。"
            )
            return False
        if not admit(db, job) or artifact["bytes"] > job.reserved_bytes:
            finish_failure(db, job, "EXPORT_QUOTA_EXCEEDED", "导出文件超出预留预算。")
            return False
        record = db.get(ExportRecord, job.id)
        record.artifact, record.methods = artifact, methods
        job.state, job.stage, job.result = (
            "SUCCEEDED",
            "COMPLETE",
            {"export_id": str(job.id), "state": "READY"},
        )
        job.reserved_bytes = 0
        job.lease_token = job.lease_expires_at = None
        attempt = db.get(Attempt, (job.id, job.attempt))
        attempt.state, attempt.finished_at = "SUCCEEDED", now()
        emit(db, job, "export.succeeded", job.result)
        return True


def execute(job_id, attempt):
    from pipelines.exports.render import render_export
    from pipelines.exports.rows import iter_query_rows
    from pipelines.query.source_cache import open_cached

    lease = claim(UUID(str(job_id)), attempt)
    if not lease:
        return {"status": "duplicate_or_ineligible"}
    root = Path(
        os.environ.get(
            "EXPORT_WORK_DIR", str(Path(__file__).resolve().parents[1] / "tmp/exports")
        )
    )
    directory = root / str(lease["job_id"]) / f"{attempt}-{lease['epoch']}"
    published = False
    uncertain = False
    artifact = None
    last = 0.0
    deadline = time.monotonic() + 600

    def checkpoint():
        from pipelines.exports.render import ExportError

        if time.monotonic() > deadline:
            raise ExportError("EXPORT_TIMEOUT")

    def tick(update):
        nonlocal last
        checkpoint()
        current = time.monotonic()
        if current - last >= 1:
            if not heartbeat(lease, update):
                raise Fenced()
            last = current

    try:
        directory.mkdir(parents=True, exist_ok=False)
        format, methods, inputs, note = build_inputs(lease, checkpoint)
        if note is not None:
            from pipelines.exports.rows import attribution_for_ordinals

            def attribution_tick():
                checkpoint()
                tick({"stage": "EXPORTING"})

            for item in inputs:
                refs = [
                    v
                    for v in note["evidence_refs"]
                    if v["query_run_id"] == str(item["run"].id)
                ]
                if not refs:
                    continue
                index = item["index"]
                with open_cached(
                    research.cache_root() / "indexes",
                    index.manifest["package"]["sha256"],
                    index.identity_sha256,
                ) as reader:
                    attrs = attribution_for_ordinals(
                        reader,
                        [v["_sentence_ordinal"] for v in refs],
                        single_source_id=item["single_source_id"],
                        checkpoint=attribution_tick,
                    )
                    for value in refs:
                        value["attribution"] = attrs[value.pop("_sentence_ordinal")]

        def rows(checkpoint):
            if note is not None:
                checkpoint()
                yield note
                return
            for item in inputs:
                checkpoint()
                run, index = item["run"], item["index"]
                with open_cached(
                    research.cache_root() / "indexes",
                    index.manifest["package"]["sha256"],
                    index.identity_sha256,
                ) as reader:
                    yield from iter_query_rows(
                        reader,
                        research.result_path(run),
                        expected_sha256=run.result_object["sha256"],
                        expected_records=run.counts["total_hits"],
                        result_set_id=str(run.result_set_id),
                        query_run_id=str(run.id),
                        snapshot_id=str(run.snapshot_id),
                        single_source_id=item["single_source_id"],
                        context_codepoints=run.context_codepoints,
                        progress_callback=tick,
                        checkpoint=checkpoint,
                    )

        result = render_export(
            directory / "rendered",
            format=format,
            kind="notes" if note is not None else "query",
            methods=methods,
            rows=rows,
            expected_rows=1
            if note is not None
            else sum(i["run"].counts["total_hits"] for i in inputs),
            progress_callback=tick,
            max_bytes=lease["reserved_bytes"],
            max_temporary_bytes=lease["reserved_bytes"],
        )
        artifact = {
            k: result[k] for k in ("name", "media_type", "bytes", "sha256", "row_count")
        }
        key = f"projects/{lease['project_id']}/exports/{lease['job_id']}/{attempt}-{lease['epoch']}/{uuid4()}"
        with result["path"].open("rb") as stream:
            uncertain = True
            version, etag = storage.put_private(
                key,
                ProgressReader(stream, tick, artifact),
                artifact["bytes"],
                artifact["media_type"],
            )
            uncertain = False
        artifact.update(object_key=key, version_id=version, etag=etag)
        stream = storage.read_private(key, version, etag)
        try:
            verify_stream(stream, artifact, tick)
        finally:
            stream.close()
        checkpoint()
        published = publish(lease, artifact, methods)
        return {"status": "published" if published else "fenced"}
    except Fenced:
        return {"status": "fenced"}
    except Exception as exc:  # noqa: BLE001 - safe diagnostic frames omit content/configuration
        code = getattr(exc, "code", None) or "EXPORT_EXECUTION_FAILED"
        LOGGER.error(
            "export_failed %s",
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
                    "导出生成或存储失败。",
                    code
                    in {
                        "EXPORT_EXECUTION_FAILED",
                        "CACHE_NOT_READY",
                        "RESULT_CACHE_INVALID",
                    },
                )
        return {"status": "failed", "code": code}
    finally:
        cleanup = not published
        if cleanup:
            try:
                with transaction() as db:
                    record = db.get(ExportRecord, lease["job_id"])
                    cleanup = record is not None and record.artifact is None
            except Exception:  # noqa: BLE001 - preserve unknown committed object and reservation
                cleanup = False
        cleaned = not uncertain
        if cleanup:
            if artifact and artifact.get("version_id"):
                try:
                    storage.client().delete_object(
                        Bucket=storage.bucket(),
                        Key=artifact["object_key"],
                        VersionId=artifact["version_id"],
                    )
                except Exception:  # noqa: BLE001 - exact-version cleanup only
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
                    else:
                        job.error = {
                            "code": "EXPORT_CLEANUP_REQUIRED",
                            "message": "对象写入或清理结果未知，保留预算等待核查。",
                            "retryable": False,
                        }
        if directory.is_dir() and directory.resolve().is_relative_to(root.resolve()):
            shutil.rmtree(directory)
