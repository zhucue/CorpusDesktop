"""Real PostgreSQL/S3/CWB research permissions, exact pages and durable restoration."""

import os
import secrets
import shutil
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch
from uuid import UUID, uuid4

from fastapi import Response
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from scripts import query_fixture
from services.api import agent_tools, projects, research, source_mounts, source_releases
from services.api.auth import Actor
from services.api.db import bound_transaction, transaction
from services.api.errors import ApiError
from services.api.jobs import EmptyBody
from tests.integration.test_source_sync_pipeline import ENABLED
from workers import research as worker


@contextmanager
def worker_role():
    with patch.dict(
        os.environ, {"DATABASE_URL": os.environ["TEST_WORKER_DATABASE_URL"]}
    ):
        yield


def query(value="Hello", unit="character"):
    return {
        "dsl_version": "corpus-query/v1",
        "unit": unit,
        "within": "sentence",
        "overlap": "all",
        "pattern": {"type": "literal", "value": value}
        if unit == "character"
        else {"type": "term", "attr": "form", "op": "eq", "value": value},
    }


@unittest.skipUnless(ENABLED and shutil.which("cwb-encode"), "Real PG/S3/CWB required")
class ResearchTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.body = {"source_id": "fixture-release-" + uuid4().hex, "accounts": {}}
        for name in ("admin", "owner", "editor", "viewer", "outsider"):
            cls.body["accounts"][name] = {
                "id": str(uuid4()),
                "email": f"query-{uuid4().hex}@example.test",
                "password": secrets.token_urlsafe(24),
            }
        root = Path(__file__).resolve().parents[2] / "tmp" / "research-tests"
        root.mkdir(parents=True, exist_ok=True)
        cls.workspace = tempfile.TemporaryDirectory(dir=root)
        cls.settings = patch.dict(
            os.environ, {"RESEARCH_CACHE_DIR": cls.workspace.name}
        )
        cls.settings.start()
        cls.engine = query_fixture.release_fixture.engine()
        try:
            cls.fixture = query_fixture.setup(cls.body)
            for name, data in cls.body["accounts"].items():
                setattr(
                    cls,
                    name,
                    Actor(UUID(data["id"]), data["email"], name == "admin", ""),
                )
            cls.source = cls.fixture["source_id"]
            cls.acquisition = UUID(cls.fixture["versions"][0]["acquisition_id"])
            cls.index = UUID(cls.fixture["versions"][0]["index_id"])
            cls.policy("allow")
            cls.release = source_releases.publish(
                cls.source,
                source_releases.PublishInput(
                    index_id=cls.index, expected_policy_revision=1
                ),
                cls.admin,
                uuid4().hex,
            )["release"]
        except BaseException:
            query_fixture.cleanup(cls.body)
            cls.settings.stop()
            raise

    @classmethod
    def tearDownClass(cls):
        query_fixture.cleanup(cls.body)
        cls.engine.dispose()
        cls.settings.stop()
        cls.workspace.cleanup()

    @classmethod
    def policy(cls, decision):
        old = source_releases.get_policy(cls.source, cls.acquisition, cls.admin)
        return source_releases.update_policy(
            cls.source,
            cls.acquisition,
            source_releases.PolicyInput(
                expected_revision=old["revision"],
                decision=decision,
                review_note="Authored query fixture only",
                evidence_urls=["https://example.test/fixture"],
            ),
            cls.admin,
            uuid4().hex,
        )

    def setUp(self):
        self.policy("allow")
        self.project = projects.create_project(
            projects.ProjectInput(name="Research fixture"), self.owner
        ).id
        projects.set_member(
            self.project,
            self.viewer.id,
            projects.MemberInput(role="viewer"),
            self.owner,
        )
        mounted = source_mounts.create(
            self.project,
            source_mounts.MountInput(
                source_snapshot_id=UUID(self.release["source_snapshot_id"])
            ),
            self.owner,
            uuid4().hex,
        )
        self.mount = UUID(mounted["mount"]["id"])

    def snapshot(self):
        value = research.create_snapshot(
            self.project,
            research.SnapshotInput(mount_ids=[self.mount]),
            self.owner,
            uuid4().hex,
        )
        self.assertEqual(value["snapshot"]["state"], "PREPARING")
        with worker_role():
            self.assertEqual(worker.execute(value["job_id"], 1)["status"], "complete")
        ident = UUID(value["snapshot"]["id"])
        self.assertEqual(
            research.get_snapshot(self.project, ident, self.viewer)["state"], "READY"
        )
        return ident

    def start(self, snapshot, ast=None, size=50, key=None):
        return research.start_query(
            self.project,
            research.QueryInput(
                snapshot_id=snapshot, query=ast or query(), page_size=size
            ),
            self.viewer,
            key or uuid4().hex,
        )

    def full(self, value):
        with worker_role():
            first = worker.execute(value["job_id"], 1)
            self.assertEqual(first["status"], "complete", first)
            with transaction() as db:
                task = research.task_for(
                    db,
                    UUID(value["run"]["snapshot_id"]),
                    UUID(value["query_run_id"]),
                    "FULL_RESULT",
                )
                full_id = task.id
            completed = worker.execute(full_id, 1)
            self.assertEqual(completed["status"], "complete", completed)
        return research.get_query(
            self.project, UUID(value["query_run_id"]), self.viewer
        )

    def page(self, value, cursor=None):
        return research.hits(
            self.project,
            UUID(value["result_set_id"]),
            Response(),
            self.viewer,
            cursor,
            value["run"]["page_size"],
        )

    def test_first_page_null_counts_all_pages_unicode_and_real_token_positions(self):
        snap = self.snapshot()
        value = self.start(snap)
        self.assertIsNone(self.page(value)["total_hits"])
        with worker_role():
            self.assertEqual(worker.execute(value["job_id"], 1)["status"], "complete")
        first = self.page(value)
        self.assertEqual(len(first["hits"]), 50)
        self.assertTrue(first["has_more"])
        self.assertIsNone(first["total_hits"])
        self.assertEqual(first["count_state"], "pending")
        with worker_role(), transaction() as db:
            task = research.task_for(
                db, snap, UUID(value["query_run_id"]), "FULL_RESULT"
            )
            ident = task.id
        with worker_role():
            self.assertEqual(worker.execute(ident, 1)["status"], "complete")
        hits, cursor = [], None
        while True:
            page = self.page(value, cursor)
            hits.extend(page["hits"])
            cursor = page["next_cursor"]
            if not cursor:
                break
        self.assertEqual(first["hits"], hits[:50])
        self.assertEqual(page["total_hits"], 120)
        self.assertEqual(page["matched_documents"], 60)
        self.assertEqual(page["matched_segments"], 60)
        # Independent authored source enumeration, including non-BMP + decomposed text.
        original = "Hello 😀 é Hello."
        expected = [
            (str(i), start, start + 5)
            for i in range(100, 160)
            for start in range(len(original))
            if original.startswith("Hello", start)
        ]
        self.assertEqual(
            [(x["source_sentence_id"], x["start_cp"], x["end_cp"]) for x in hits],
            expected,
        )
        context = research.context(
            self.project, UUID(value["result_set_id"]), 1, self.viewer
        )
        self.assertEqual(context["text"], original)
        token = self.start(snap, query(unit="token"))
        self.assertEqual(self.full(token)["total_hits"], 120)
        self.assertTrue(
            all(
                x["token_start"] is not None and x["global_token_start"] is not None
                for x in self.page(token)["hits"]
            )
        )

    def test_zero_is_complete_not_pending_and_duplicate_does_not_reexecute(self):
        snap = self.snapshot()
        key = uuid4().hex
        value = self.start(snap, query("absent-Ω"), key=key)
        same = self.start(snap, query("absent-Ω"), key=key)
        self.assertEqual(value["query_run_id"], same["query_run_id"])
        self.assertEqual(self.full(value)["total_hits"], 0)
        self.assertEqual(self.page(value)["hits"], [])
        with worker_role():
            self.assertEqual(
                worker.execute(value["job_id"], 1)["status"], "duplicate_or_ineligible"
            )

    def test_viewer_analysis_rls_and_platform_admin_has_no_project_access(self):
        with self.assertRaises(ApiError):
            research.create_snapshot(
                self.project,
                research.SnapshotInput(mount_ids=[self.mount]),
                self.viewer,
                uuid4().hex,
            )
        snap = self.snapshot()
        value = self.start(snap)
        with self.assertRaises(DBAPIError), transaction(self.viewer.id) as db:
            db.execute(
                text(
                    "INSERT INTO app.research_snapshots (id,project_id,created_by,name,state,manifest,manifest_sha256,created_at,updated_at) SELECT :new_id,project_id,:actor,name,state,manifest,manifest_sha256,created_at,updated_at FROM app.research_snapshots WHERE id=:snapshot"
                ),
                {"new_id": uuid4(), "actor": self.viewer.id, "snapshot": snap},
            )
        for actor in (self.admin, self.outsider):
            with self.assertRaises(ApiError):
                research.get_query(self.project, UUID(value["query_run_id"]), actor)
            with transaction(actor.id) as db:
                self.assertEqual(
                    db.scalar(
                        text("SELECT count(*) FROM app.query_runs WHERE id=:id"),
                        {"id": UUID(value["query_run_id"])},
                    ),
                    0,
                )
        with transaction(self.viewer.id) as db:
            self.assertEqual(
                db.scalar(
                    text("SELECT count(*) FROM app.query_runs WHERE id=:id"),
                    {"id": UUID(value["query_run_id"])},
                ),
                1,
            )
        research.cancel_query(
            self.project,
            UUID(value["query_run_id"]),
            EmptyBody(),
            self.viewer,
            uuid4().hex,
        )
        with self.assertRaises(ApiError) as error:
            self.page(value)
        self.assertEqual(error.exception.code, "QUERY_CANCELLED")

    def test_deny_blocks_stored_pages_replay_prepare_and_model_metadata(self):
        snap = self.snapshot()
        key = uuid4().hex
        value = self.start(snap, key=key)
        self.full(value)
        self.policy("deny")
        for operation in (
            lambda: self.page(value),
            lambda: self.start(snap, key=key),
            lambda: research.prepare_result(
                self.project,
                UUID(value["result_set_id"]),
                EmptyBody(),
                self.viewer,
                uuid4().hex,
            ),
        ):
            with self.assertRaises(ApiError):
                operation()
        scope = {
            "scope_kind": "project",
            "project_id": str(self.project),
            "snapshot_ids": [],
            "material_revision_ids": [],
            "alignment_overlay_revision": None,
        }
        with transaction(self.viewer.id) as db, bound_transaction(self.viewer.id, db):
            with self.assertRaises(ApiError):
                agent_tools.dispatch(
                    db,
                    self.viewer,
                    scope,
                    "results.get",
                    {"result_set_id": value["result_set_id"]},
                    None,
                )
            with self.assertRaises(ApiError) as blocked:
                agent_tools.dispatch(
                    db,
                    self.viewer,
                    scope,
                    "results.context",
                    {"result_set_id": value["result_set_id"], "ordinal": 0},
                    None,
                )
            self.assertEqual(blocked.exception.code, "MODEL_EGRESS_DENIED")

    def test_missing_cache_explicit_prepare_restores_same_durable_result(self):
        snap = self.snapshot()
        value = self.start(snap, size=1)
        self.full(value)
        first = self.page(value)
        with transaction(self.viewer.id) as db:
            run = research.load_run(
                db, self.viewer.id, self.project, UUID(value["query_run_id"])
            )
            path = research.result_path(run)
        path.unlink()
        with self.assertRaises(ApiError) as error:
            self.page(value)
        self.assertEqual(error.exception.code, "CACHE_NOT_READY")
        action = research.prepare_result(
            self.project,
            UUID(value["result_set_id"]),
            EmptyBody(),
            self.viewer,
            uuid4().hex,
        )
        with worker_role():
            self.assertEqual(worker.execute(action["job_id"], 1)["status"], "complete")
        self.assertEqual(first, self.page(value))
        # Another current viewer can restore the same fixed result after the first preparer.
        projects.set_member(
            self.project,
            self.editor.id,
            projects.MemberInput(role="viewer"),
            self.owner,
        )
        path.unlink()
        second = research.prepare_result(
            self.project,
            UUID(value["result_set_id"]),
            EmptyBody(),
            self.editor,
            uuid4().hex,
        )
        self.assertEqual(second["job_id"], action["job_id"])
        with worker_role():
            self.assertEqual(worker.execute(second["job_id"], 2)["status"], "complete")
        self.assertEqual(first, self.page(value))

    def test_cancel_and_expired_lease_fence_publication(self):
        snap = self.snapshot()
        value = self.start(snap)
        with worker_role():
            lease = worker.claim(UUID(value["job_id"]), 1)
        research.cancel_query(
            self.project,
            UUID(value["query_run_id"]),
            EmptyBody(),
            self.viewer,
            uuid4().hex,
        )
        with worker_role():
            self.assertFalse(
                worker.publish(lease, page={"hits": [], "has_more": False})
            )
        value2 = self.start(snap, query("é"))
        with worker_role():
            lease = worker.claim(UUID(value2["job_id"]), 1)
        with self.engine.begin() as db:
            db.execute(
                text(
                    "UPDATE app.research_tasks SET lease_expires_at=now()-interval '1 second' WHERE id=:id"
                ),
                {"id": UUID(value2["job_id"])},
            )
        with worker_role():
            self.assertFalse(
                worker.publish(lease, page={"hits": [], "has_more": False})
            )

    def test_result_quota_failure_preserves_preview_with_unknown_counts(self):
        snap = self.snapshot()
        value = self.start(snap)
        with worker_role():
            self.assertEqual(worker.execute(value["job_id"], 1)["status"], "complete")
            with transaction() as db:
                task = research.task_for(
                    db, snap, UUID(value["query_run_id"]), "FULL_RESULT"
                )
                ident = task.id
            with patch.dict(os.environ, {"QUERY_RESULT_MAX_BYTES": "32"}):
                self.assertEqual(worker.execute(ident, 1)["status"], "failed")
        page = self.page(value)
        self.assertEqual(page["count_state"], "failed")
        self.assertIsNone(page["total_hits"])
        self.assertEqual(len(page["hits"]), 50)

    def test_withdraw_after_cache_install_cleans_unpublished_object_and_cache(self):
        snap = self.snapshot()
        value = self.start(snap)
        api_url = os.environ["DATABASE_URL"]
        with worker_role():
            self.assertEqual(worker.execute(value["job_id"], 1)["status"], "complete")
            with transaction() as db:
                ident = research.task_for(
                    db, snap, UUID(value["query_run_id"]), "FULL_RESULT"
                ).id
            original = worker.publish

            def withdraw(lease, **kwargs):
                result = kwargs["result"]
                path = (
                    research.cache_root()
                    / "results"
                    / value["result_set_id"]
                    / (result["sha256"] + ".spans")
                )
                self.assertTrue(path.exists())
                with patch.dict(os.environ, {"DATABASE_URL": api_url}):
                    self.policy("deny")
                return original(lease, **kwargs)

            with patch.object(worker, "publish", side_effect=withdraw):
                self.assertEqual(worker.execute(ident, 1)["status"], "fenced")
        self.assertEqual(
            list(
                (research.cache_root() / "results" / value["result_set_id"]).glob(
                    "*.spans*"
                )
            ),
            [],
        )
        with self.engine.begin() as db:
            row = db.execute(
                text(
                    "SELECT state,result_object,reserved_bytes FROM app.query_runs WHERE id=:id"
                ),
                {"id": UUID(value["query_run_id"])},
            ).one()
            self.assertEqual(tuple(row), ("FAILED", None, 0))
        from services.api import storage

        objects = storage.client().list_object_versions(
            Bucket=storage.bucket(), Prefix=f"query-results/{value['result_set_id']}/"
        )
        self.assertEqual(objects.get("Versions", []), [])

    def test_uncertain_publish_ack_does_not_overwrite_claimed_task(self):
        from workers import research_dispatcher

        snap = self.snapshot()
        value = self.start(snap)
        with self.engine.begin() as db:
            # Snapshot deliveries are superseded; isolate this new outbox row.
            db.execute(
                text(
                    "UPDATE app.research_outbox SET published_at=now() WHERE task_id<>:id AND task_id IN (SELECT id FROM app.research_tasks WHERE actor_id=ANY(:actors))"
                ),
                {
                    "id": UUID(value["job_id"]),
                    "actors": [UUID(x["id"]) for x in self.body["accounts"].values()],
                },
            )
            db.execute(
                text("UPDATE app.research_outbox SET failures=19 WHERE task_id=:id"),
                {"id": UUID(value["job_id"])},
            )

        def accepted_then_lost_ack(task_id, attempt):
            self.assertIsNotNone(worker.claim(task_id, attempt))
            raise OSError("simulated missing broker ACK")

        with worker_role():
            self.assertFalse(research_dispatcher.dispatch_once(accepted_then_lost_ack))
            with transaction() as db:
                task = db.get(research.ResearchTask, UUID(value["job_id"]))
                self.assertEqual(task.state, "RUNNING")
        research.cancel_query(
            self.project,
            UUID(value["query_run_id"]),
            EmptyBody(),
            self.viewer,
            uuid4().hex,
        )
