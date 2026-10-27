"""Query-only authored fixture, with more than fifty real matches and exact cleanup."""

import bz2
import hashlib
import json
import shutil
import sys
from pathlib import Path
from unittest.mock import patch
from uuid import UUID

from sqlalchemy import text

from scripts import release_fixture
from services.api import research, storage


def setup(body):
    original = release_fixture.acquire_fixture

    def acquire(folder):
        receipt = original(folder)
        for item in receipt["files"]:
            if item["name"].startswith("eng"):
                content = "".join(
                    f"{i}\teng\tHello 😀 é Hello.\tFixture\t\\N\t\\N\n"
                    for i in range(100, 160)
                )
            elif "links" in item["name"]:
                content = "1\t100\n2\t101\n"
            else:
                continue
            raw = bz2.compress(content.encode("utf-8"))
            Path(item["path"]).write_bytes(raw)
            item.update(bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest())
        return receipt

    with patch.object(release_fixture, "acquire_fixture", acquire):
        return release_fixture.setup(
            {
                **body,
                "fixture_sentence_description": "62 authored synthetic query fixture sentences; not official Tatoeba material",
            }
        )


def cleanup(body):
    actors = [UUID(value["id"]) for value in body["accounts"].values()]
    engine = release_fixture.engine()
    result_ids, cache_keys, deleted, cache_deleted = [], [], 0, 0
    private_objects = []
    private_prefixes = []
    try:
        with engine.begin() as db:
            for value in body["accounts"].values():
                email = db.scalar(
                    text("SELECT email FROM app.users WHERE id=:id"),
                    {"id": UUID(value["id"])},
                )
                assert email is None or email == value["email"]
            params = {"actors": actors, "source": body["source_id"]}
            outcome_exists = db.scalar(
                text("SELECT to_regclass('app.research_exports') IS NOT NULL")
            )
            if outcome_exists:
                private_objects.extend(
                    db.scalars(
                        text(
                            "SELECT artifact FROM app.research_exports WHERE project_id IN (SELECT id FROM app.projects WHERE owner_id=ANY(:actors)) AND artifact IS NOT NULL"
                        ),
                        params,
                    )
                )
                for table in (
                    "research_exports",
                    "note_acceptances",
                    "note_revisions",
                    "research_notes",
                    "research_evidence",
                ):
                    db.execute(
                        text(
                            f"DELETE FROM app.{table} WHERE project_id IN (SELECT id FROM app.projects WHERE owner_id=ANY(:actors))"
                        ),
                        params,
                    )

            result_ids = list(
                db.scalars(
                    text(
                        "SELECT result_set_id FROM app.query_runs WHERE actor_id=ANY(:actors)"
                    ),
                    params,
                )
            )
            cache_keys = list(
                db.scalars(
                    text(
                        "SELECT manifest->'package'->>'sha256' FROM app.source_indexes WHERE source_id=:source"
                    ),
                    params,
                )
            )
            for receipt in db.scalars(
                text(
                    "SELECT index_result FROM app.research_snapshots WHERE created_by=ANY(:actors) AND index_result IS NOT NULL"
                ),
                params,
            ):
                cache_keys.append(receipt["manifest"]["package"]["sha256"])
                private_objects.extend(receipt["objects"])
            for objects in db.scalars(
                text(
                    "SELECT objects FROM app.material_revisions WHERE project_id IN (SELECT id FROM app.projects WHERE owner_id=ANY(:actors))"
                ),
                params,
            ):
                private_objects.extend(objects)
            for row in db.execute(
                text(
                    "SELECT object_key,version_id FROM app.upload_sessions WHERE project_id IN (SELECT id FROM app.projects WHERE owner_id=ANY(:actors))"
                ),
                params,
            ):
                if row.version_id:
                    private_objects.append(
                        {"object_key": row.object_key, "version_id": row.version_id}
                    )
            for project_id in db.scalars(
                text("SELECT id FROM app.projects WHERE owner_id=ANY(:actors)"), params
            ):
                private_prefixes.extend(
                    [
                        f"materials/{project_id}/",
                        f"project-indexes/{project_id}/",
                        f"projects/{project_id}/exports/",
                    ]
                )
            for table in ("research_outbox", "research_events"):
                db.execute(
                    text(
                        f"DELETE FROM app.{table} WHERE task_id IN (SELECT id FROM app.research_tasks WHERE actor_id=ANY(:actors))"
                    ),
                    params,
                )
            db.execute(
                text("DELETE FROM app.research_tasks WHERE actor_id=ANY(:actors)"),
                params,
            )
            db.execute(
                text("DELETE FROM app.query_runs WHERE actor_id=ANY(:actors)"), params
            )
            db.execute(
                text(
                    "DELETE FROM app.research_snapshot_members WHERE snapshot_id IN (SELECT id FROM app.research_snapshots WHERE created_by=ANY(:actors))"
                ),
                params,
            )
            db.execute(
                text(
                    "DELETE FROM app.research_snapshots WHERE created_by=ANY(:actors)"
                ),
                params,
            )
            db.execute(
                text("DELETE FROM app.research_actions WHERE actor_id=ANY(:actors)"),
                params,
            )
            db.execute(
                text(
                    "UPDATE app.material_documents SET latest_revision_id=NULL WHERE project_id IN (SELECT id FROM app.projects WHERE owner_id=ANY(:actors))"
                ),
                params,
            )
            for table in (
                "material_revisions",
                "material_documents",
                "job_outbox",
                "job_events",
                "job_attempts",
                "jobs",
                "job_actions",
                "upload_sessions",
            ):
                db.execute(
                    text(
                        f"DELETE FROM app.{table} WHERE project_id IN (SELECT id FROM app.projects WHERE owner_id=ANY(:actors))"
                    ),
                    params,
                )
        deleted_private = set()
        for item in private_objects:
            storage.client().delete_object(
                Bucket=storage.bucket(),
                Key=item["object_key"],
                VersionId=item["version_id"],
            )
            deleted_private.add((item["object_key"], item["version_id"]))
        for prefix in private_prefixes:
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
                    deleted_private.add((item["Key"], item["VersionId"]))
        for ident in result_ids:
            prefix = f"query-results/{ident}/"
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
        root = research.cache_root().resolve()
        for directory in [
            *(root / "results" / str(x) for x in result_ids),
            *(root / "indexes" / x for x in cache_keys),
        ]:
            if directory.is_dir() and directory.resolve().is_relative_to(root):
                shutil.rmtree(directory)
                cache_deleted += 1
        result = release_fixture.cleanup(body)
        return {
            **result,
            "query_result_versions_deleted": deleted,
            "private_material_index_versions_deleted": len(deleted_private),
            "cache_directories_deleted": cache_deleted,
            "cache_target_count": len(result_ids) + len(cache_keys),
            "cache_targets_remaining": sum(
                path.exists()
                for path in [
                    *(root / "results" / str(x) for x in result_ids),
                    *(root / "indexes" / x for x in cache_keys),
                ]
            ),
        }
    finally:
        engine.dispose()


if __name__ == "__main__":
    request = json.load(sys.stdin)
    print(
        json.dumps(setup(request) if request["mode"] == "setup" else cleanup(request))
    )
