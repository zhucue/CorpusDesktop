"""Isolated synthetic source, real parser/CWB artifacts, and exact test cleanup.

Only invoked by coordinated tests or the release HTTP smoke. No official source
is mutated and no production license is approved. Credentials arrive via stdin.
"""

import bz2
import hashlib
import json
import os
import tempfile
from pathlib import Path
from uuid import UUID, uuid4

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from pipelines.query import source_index
from pipelines.sources import tatoeba
from services.api import catalog, index_builds, storage
from services.api.auth import HASHER, Actor
from services.api.catalog_models import CatalogSource
from services.api.index_models import IndexRun, SourceIndex
from services.api.jobs import now
from services.api.models import User
from services.api.source_sync import EMPTY_PROGRESS, identity
from services.api.source_sync_models import Acquisition, SyncRun
from tests.integration.test_source_sync_pipeline import acquire_fixture


def engine():
    return create_engine(os.environ["TEST_ADMIN_DATABASE_URL"], hide_parameters=True)


def upload(source_id, prefix, artifacts):
    objects = []
    for item in artifacts:
        path = Path(item["path"])
        key = f"release-fixture/{source_id}/{prefix}/{item['name']}"
        with path.open("rb") as stream:
            version, etag = storage.put_private(
                key, stream, path.stat().st_size, "application/octet-stream"
            )
        objects.append(
            {
                "name": item["name"],
                "bytes": path.stat().st_size,
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                "object_key": key,
                "version_id": version,
                "etag": etag,
            }
        )
    return objects


def setup(body):
    source_id = body["source_id"]
    assert source_id.startswith("fixture-release-") and len(source_id) <= 64
    actors = {
        name: Actor(UUID(item["id"]), item["email"], name == "admin", "")
        for name, item in body["accounts"].items()
    }
    db_engine = engine()
    try:
        with Session(db_engine) as db, db.begin():
            for name, actor in actors.items():
                db.add(
                    User(
                        id=actor.id,
                        email=actor.email,
                        password_hash=HASHER.hash(body["accounts"][name]["password"]),
                        is_platform_admin=actor.is_platform_admin,
                    )
                )
        catalog.create_catalog(
            catalog.CatalogCreate(
                source_id=source_id,
                name="Synthetic release fixture " + source_id[-8:],
                publisher="Project integration fixture",
                entry_kind="dataset",
                categories=["fixture"],
                languages=["cmn", "eng"],
                official_url="https://example.test/synthetic-fixture",
                materials=body.get(
                    "fixture_sentence_description",
                    "Four authored synthetic sentences per acquisition",
                ),
                access_route="Private integration fixture",
                boundary="Fixture-only permission; never approval for Tatoeba or other real data",
            ),
            actors["admin"],
            uuid4().hex,
        )
        root = Path(__file__).resolve().parents[1] / "tmp" / "release-fixture"
        root.mkdir(parents=True, exist_ok=True)
        receipts = []
        with tempfile.TemporaryDirectory(dir=root, prefix=source_id + "-") as workspace:
            for ordinal in range(2):
                folder = Path(workspace) / str(ordinal)
                folder.mkdir()
                acquired = acquire_fixture(folder / "raw")
                if ordinal:
                    item = next(
                        x for x in acquired["files"] if x["name"].startswith("eng")
                    )
                    path = Path(item["path"])
                    raw = bz2.compress(
                        bz2.decompress(path.read_bytes()).replace(
                            b"Hello.", b"Hello again."
                        )
                    )
                    path.write_bytes(raw)
                    item.update(bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest())
                bundle = tatoeba.parse(acquired, folder / "parsed", lambda _: None)
                manifest = bundle["manifest"]
                manifest["fixture"] = True
                manifest["source_id"] = source_id
                manifest["scope"] = body.get(
                    "fixture_sentence_description",
                    "Four synthetic authored fixture sentences; not official Tatoeba material",
                )
                manifest["license"] = {
                    "status": "fixture_only",
                    "basis": "Authored synthetic test sentences; not official source permission",
                }
                license_item = next(
                    x for x in bundle["artifacts"] if x["name"] == "license.json"
                )
                Path(license_item["path"]).write_text(
                    json.dumps(manifest["license"]), encoding="utf-8"
                )
                for item in bundle["artifacts"]:
                    if item["name"] == "manifest.json":
                        continue
                    path = Path(item["path"])
                    item.update(
                        bytes=path.stat().st_size,
                        sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
                    )
                    for listed in manifest["artifacts"]:
                        if listed["name"] == item["name"]:
                            listed.update(bytes=item["bytes"], sha256=item["sha256"])
                Path(bundle["manifest_path"]).write_text(
                    json.dumps(manifest, ensure_ascii=False, sort_keys=True),
                    encoding="utf-8",
                )
                manifest_sha = hashlib.sha256(
                    Path(bundle["manifest_path"]).read_bytes()
                ).hexdigest()
                database = next(
                    x["path"]
                    for x in bundle["artifacts"]
                    if x["name"] == "corpus.sqlite3"
                )
                built = source_index.build(
                    Path(database), folder / "index", manifest_sha, lambda _: None
                )
                acquired_objects = upload(
                    source_id, f"acquisition-{ordinal}", bundle["artifacts"]
                )
                index_objects = upload(
                    source_id, f"index-{ordinal}", built["artifacts"]
                )
                acquired_id, sync_id, index_id, index_run_id = (
                    uuid4() for _ in range(4)
                )
                with Session(db_engine) as db, db.begin():
                    source = db.get(CatalogSource, source_id)
                    source_identity = identity(source)
                    db.add(
                        SyncRun(
                            id=sync_id,
                            source_id=source_id,
                            actor_id=actors["admin"].id,
                            connector_id="synthetic-release-fixture/v1",
                            source_revision=source.revision,
                            source_identity=source_identity,
                            state="SUCCEEDED",
                            stage="VALIDATED",
                            attempt=1,
                            progress=EMPTY_PROGRESS,
                            result={
                                "acquisition_id": str(acquired_id),
                                "state": "VALIDATED",
                            },
                            created_at=now(),
                            updated_at=now(),
                        )
                    )
                    db.flush()
                    db.add(
                        Acquisition(
                            id=acquired_id,
                            run_id=sync_id,
                            source_id=source_id,
                            connector_id="synthetic-release-fixture/v1",
                            source_identity=source_identity,
                            manifest_sha256=manifest_sha,
                            manifest=manifest,
                            objects=acquired_objects,
                            created_at=now(),
                        )
                    )
                    db.flush()
                    result = {
                        "index_id": str(index_id),
                        "acquisition_id": str(acquired_id),
                        "state": "INDEXED",
                        "searchable": False,
                        "manifest_sha256": next(
                            x["sha256"]
                            for x in index_objects
                            if x["name"] == "manifest.json"
                        ),
                        "recipe": index_builds.recipe(),
                        "counts": built["manifest"]["counts"],
                        "quality": built["manifest"]["quality"],
                        "artifact_bytes": sum(x["bytes"] for x in index_objects),
                    }
                    db.add(
                        IndexRun(
                            id=index_run_id,
                            source_id=source_id,
                            acquisition_id=acquired_id,
                            actor_id=actors["admin"].id,
                            source_identity=source_identity,
                            recipe=index_builds.recipe(),
                            recipe_sha256=index_builds.recipe()["sha256"],
                            state="SUCCEEDED",
                            stage="INDEXED",
                            attempt=1,
                            reserved_bytes=0,
                            progress=EMPTY_PROGRESS,
                            result=result,
                            created_at=now(),
                            updated_at=now(),
                        )
                    )
                    db.flush()
                    db.add(
                        SourceIndex(
                            id=index_id,
                            run_id=index_run_id,
                            acquisition_id=acquired_id,
                            source_id=source_id,
                            recipe_sha256=index_builds.recipe()["sha256"],
                            identity_sha256=built["manifest"]["identity_sha256"],
                            manifest_sha256=result["manifest_sha256"],
                            manifest=built["manifest"],
                            objects=index_objects,
                            artifact_bytes=result["artifact_bytes"],
                            created_at=now(),
                        )
                    )
                receipts.append(
                    {
                        "acquisition_id": str(acquired_id),
                        "index_id": str(index_id),
                        "index_run_id": str(index_run_id),
                        "manifest_sha256": result["manifest_sha256"],
                        "counts": result["counts"],
                    }
                )
        return {"source_id": source_id, "versions": receipts, "fixture_only": True}
    finally:
        db_engine.dispose()


def cleanup(body):
    source_id = body["source_id"]
    assert source_id.startswith("fixture-release-") and len(source_id) <= 64
    ids = [UUID(x["id"]) for x in body["accounts"].values()]
    db_engine = engine()
    deleted = 0
    try:
        with db_engine.begin() as db:
            for value in body["accounts"].values():
                actual = db.scalar(
                    text("SELECT email FROM app.users WHERE id=:id"),
                    {"id": UUID(value["id"])},
                )
                assert actual is None or actual == value["email"]
            args = {"source": source_id, "actors": ids}
            # Refuse to delete a fixture subsequently mounted by an unrelated user.
            external = db.scalar(
                text(
                    "SELECT count(*) FROM app.project_source_mounts m JOIN app.catalog_releases r ON r.source_snapshot_id=m.source_snapshot_id WHERE r.source_id=:source AND m.created_by<>ALL(:actors)"
                ),
                args,
            )
            assert external == 0, "External fixture references require explicit cleanup"
            db.execute(
                text("DELETE FROM app.mount_actions WHERE actor_id=ANY(:actors)"), args
            )
            db.execute(
                text(
                    "DELETE FROM app.project_source_mounts WHERE created_by=ANY(:actors)"
                ),
                args,
            )
            db.execute(
                text("DELETE FROM app.source_release_heads WHERE source_id=:source"),
                args,
            )
            db.execute(
                text("DELETE FROM app.catalog_releases WHERE source_id=:source"), args
            )
            db.execute(
                text("DELETE FROM app.source_policy_heads WHERE source_id=:source"),
                args,
            )
            db.execute(
                text("DELETE FROM app.source_policies WHERE source_id=:source"), args
            )
            db.execute(
                text(
                    "DELETE FROM app.source_release_actions WHERE actor_id=ANY(:actors)"
                ),
                args,
            )
            db.execute(
                text("DELETE FROM app.source_indexes WHERE source_id=:source"), args
            )
            db.execute(
                text("DELETE FROM app.index_build_runs WHERE source_id=:source"), args
            )
            db.execute(
                text("DELETE FROM app.source_acquisitions WHERE source_id=:source"),
                args,
            )
            db.execute(
                text("DELETE FROM app.source_sync_runs WHERE source_id=:source"), args
            )
            db.execute(
                text("DELETE FROM app.catalog_actions WHERE actor_id=ANY(:actors)"),
                args,
            )
            db.execute(
                text("DELETE FROM app.catalog_sources WHERE source_id=:source"), args
            )
            db.execute(
                text(
                    "UPDATE app.agent_sessions SET active_run_id=NULL,latest_checkpoint_id=NULL WHERE actor_id=ANY(:actors)"
                ),
                args,
            )
            db.execute(
                text(
                    "UPDATE app.agent_runs SET base_checkpoint_id=NULL,final_checkpoint_id=NULL WHERE actor_id=ANY(:actors)"
                ),
                args,
            )
            for table in (
                "agent_checkpoints",
                "agent_events",
                "agent_invocations",
                "agent_credentials",
                "agent_runs",
                "agent_sessions",
            ):
                db.execute(
                    text(f"DELETE FROM app.{table} WHERE actor_id=ANY(:actors)"), args
                )
            db.execute(
                text(
                    "DELETE FROM app.project_members WHERE project_id IN (SELECT id FROM app.projects WHERE owner_id=ANY(:actors))"
                ),
                args,
            )
            db.execute(
                text("DELETE FROM app.projects WHERE owner_id=ANY(:actors)"), args
            )
            db.execute(text("DELETE FROM app.users WHERE id=ANY(:actors)"), args)
        prefix = f"release-fixture/{source_id}/"
        for page in (
            storage.client()
            .get_paginator("list_object_versions")
            .paginate(Bucket=storage.bucket(), Prefix=prefix)
        ):
            for item in page.get("Versions", []) + page.get("DeleteMarkers", []):
                assert item["Key"].startswith(prefix)
                storage.client().delete_object(
                    Bucket=storage.bucket(),
                    Key=item["Key"],
                    VersionId=item["VersionId"],
                )
                deleted += 1
        return {
            "cleaned": True,
            "source_id": source_id,
            "object_versions_deleted": deleted,
        }
    finally:
        db_engine.dispose()


if __name__ == "__main__":
    import sys

    request = json.load(sys.stdin)
    result = setup(request) if request["mode"] == "setup" else cleanup(request)
    print(json.dumps(result))
