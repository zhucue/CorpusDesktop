"""Build one immutable private/mixed index within the existing snapshot task."""

import hashlib
import json
import os
import shutil
from pathlib import Path
from uuid import uuid4

from sqlalchemy import select, text

from pipelines.query.source_index import IndexBuildError
from services.api import research as api
from services.api import storage
from services.api.db import transaction
from services.api.index_models import SourceIndex
from services.api.research_models import Snapshot
from workers.index_build import ProgressReader, verify_stream
from workers.materials import fetch


def admit(db, snapshot):
    db.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended('project-index-budget',0))")
    )
    used = local = 0
    for row in db.scalars(select(Snapshot).where(Snapshot.id != snapshot.id)):
        amount = sum(x["bytes"] for x in (row.index_result or {}).get("objects", []))
        task = api.task_for(db, row.id)
        if task and task.state != "QUEUED":
            amount += row.reserved_bytes
        used += amount
        if row.project_id == snapshot.project_id:
            local += amount
    return used + snapshot.reserved_bytes <= int(
        os.environ.get("PROJECT_INDEX_STORAGE_MAX_BYTES", str(12 * 1024**3))
    ) and local + snapshot.reserved_bytes <= int(
        os.environ.get("PROJECT_INDEX_PROJECT_MAX_BYTES", str(8 * 1024**3))
    )


def prepare_source(item, root, tick):
    from pipelines.query.source_cache import prepare_index

    objects = {x["name"]: x for x in item["objects"]}
    manifest = objects["manifest.json"]
    package = objects["index.tar"]
    stream = storage.read_private(
        manifest["object_key"], manifest["version_id"], manifest["etag"]
    )
    try:
        raw = stream.read(1024**2 + 1)
    finally:
        stream.close()
    if (
        len(raw) != manifest["bytes"]
        or hashlib.sha256(raw).hexdigest() != item["manifest_sha256"]
        or json.loads(raw) != item["manifest"]
        or package["sha256"] != item["manifest"]["package"]["sha256"]
        or package["bytes"] != item["manifest"]["package"]["bytes"]
    ):
        raise ValueError("INDEX_RECEIPT_MISMATCH")
    return prepare_index(
        root / "indexes",
        raw,
        item["manifest_sha256"],
        lambda: storage.read_private(
            package["object_key"], package["version_id"], package["etag"]
        ),
        tick,
        max_cache_bytes=int(
            os.environ.get("QUERY_INDEX_CACHE_MAX_BYTES", str(12 * 1024**3))
        ),
    )


def execute(lease, temporary, tick):
    from pipelines.query.project_index import build_project
    from workers.research import locked, publish

    root = api.cache_root()
    objects = []
    uncertain = False
    published = False
    cache = None
    try:
        members = []
        for ordinal, item in enumerate(lease["snapshot_inputs"]):
            if item["kind"] == "source":
                cached = prepare_source(item, root, tick)
                # Engine wants the inner bundle manifest, not the S3 outer package manifest.
                directory = cached["directory"]
                raw = (directory / "manifest.json").read_bytes()
                members.append(
                    {
                        "kind": "source",
                        "source_id": item["source_id"],
                        "directory": directory,
                        "identity_sha256": item["identity_sha256"],
                        "manifest_sha256": hashlib.sha256(raw).hexdigest(),
                    }
                )
            else:
                directory = temporary / f"private-{ordinal}"
                directory.mkdir()
                if {x["name"] for x in item["objects"]} != {
                    "canonical.utf8",
                    "segments.jsonl",
                    "manifest.json",
                }:
                    raise ValueError("MATERIAL_ARTIFACTS_INVALID")
                for artifact in item["objects"]:
                    fetch(artifact, directory / artifact["name"], tick)
                raw = (directory / "manifest.json").read_bytes()
                if (
                    hashlib.sha256(raw).hexdigest() != item["manifest_sha256"]
                    or json.loads(raw) != item["manifest"]
                ):
                    raise ValueError("MATERIAL_IDENTITY_MISMATCH")
                members.append(
                    {
                        "kind": "private",
                        "directory": directory,
                        "manifest_sha256": item["manifest_sha256"],
                    }
                )
        bundle = build_project(
            members, temporary / "index", lease["snapshot_manifest_sha256"], tick
        )
        manifest = bundle["manifest"]
        if (
            manifest["recipe_sha256"] != api.project_recipe()["sha256"]
            or manifest["identity"]["snapshot_manifest_sha256"]
            != lease["snapshot_manifest_sha256"]
        ):
            raise IndexBuildError("PROJECT_INDEX_RECIPE_MISMATCH")
        if (
            sum(x["bytes"] for x in bundle["artifacts"])
            > lease["snapshot_reserved_bytes"]
        ):
            raise IndexBuildError("PROJECT_INDEX_QUOTA_EXCEEDED")
        for artifact in bundle["artifacts"]:
            item = {k: artifact[k] for k in ("name", "bytes", "sha256")}
            if item["bytes"] > 4 * 1024**3:
                raise IndexBuildError("PROJECT_INDEX_QUOTA_EXCEEDED")
            key = f"project-indexes/{lease['project_id']}/{lease['snapshot_id']}/{uuid4().hex}/{item['name']}"
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
        receipt = {
            "manifest": manifest,
            "manifest_sha256": hashlib.sha256(
                Path(bundle["manifest_path"]).read_bytes()
            ).hexdigest(),
            "identity_sha256": manifest["identity_sha256"],
            "objects": objects,
        }
        cached = prepare_source(receipt, root, tick)
        cache = cached["directory"]
        published = publish(lease, index_result=receipt)
        return published
    finally:
        cleanup = not published
        if cleanup:
            try:
                with transaction() as db:
                    task, _, _ = locked(db, lease["task_id"])
                    snapshot = db.get(Snapshot, lease["snapshot_id"])
                    if snapshot.index_result:
                        cleanup = False
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
            if cache is not None:
                try:
                    with transaction() as db:
                        locked(db, lease["task_id"])
                        sha = next(
                            x["sha256"] for x in objects if x["name"] == "index.tar"
                        )
                        registered = any(
                            (s.index_result or {})
                            .get("manifest", {})
                            .get("package", {})
                            .get("sha256")
                            == sha
                            for s in db.scalars(select(Snapshot))
                        )
                        registered = registered or any(
                            s.manifest["package"]["sha256"] == sha
                            for s in db.scalars(select(SourceIndex))
                        )
                        if not registered and cache.resolve().is_relative_to(
                            (root / "indexes").resolve()
                        ):
                            shutil.rmtree(cache)
                except Exception:  # noqa: BLE001 - unknown storage/commit outcomes retain private objects and budget
                    cleaned = False
            with transaction() as db:
                task, _, _ = locked(db, lease["task_id"])
                snapshot = db.get(Snapshot, lease["snapshot_id"])
                if not snapshot.index_result:
                    if cleaned:
                        snapshot.reserved_bytes = 0
                    else:
                        task.error = {
                            "code": "PROJECT_INDEX_CLEANUP_REQUIRED",
                            "message": "对象写入或清理结果未知，保留预算。",
                            "retryable": False,
                        }
