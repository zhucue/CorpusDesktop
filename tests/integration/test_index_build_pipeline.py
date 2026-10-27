"""Real PG/S3/CWB checks with four explicitly synthetic upstream sentences."""

import hashlib
import io
import json
import os
import shutil
import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch
from uuid import UUID, uuid4

from botocore.exceptions import ClientError
from sqlalchemy import select, text

from pipelines.query import source_index
from services.api import (
    agent_checkpoints,
    agent_control,
    agent_routes,
    catalog,
    index_builds,
    storage,
)
from services.api.agent_internal import InvocationInput
from services.api.db import transaction
from services.api.errors import ApiError
from services.api.index_models import IndexRun, SourceIndex
from services.api.jobs import EmptyBody
from tests.integration import test_source_sync_pipeline as sync_tests
from workers import index_build as worker
from workers import index_dispatcher as dispatcher


class IndexStreamTests(unittest.TestCase):
    def test_stream_reports_actual_bytes_and_rejects_corruption(self):
        raw = b"actual bytes"
        item = {
            "name": "tiny",
            "bytes": len(raw),
            "sha256": hashlib.sha256(raw).hexdigest(),
        }
        events = []
        worker.verify_stream(io.BytesIO(raw), item, events.append, stage="FETCHING")
        self.assertEqual(events[-1]["processed_bytes"], len(raw))
        self.assertEqual(events[-1]["total_bytes"], len(raw))
        self.assertEqual(events[-1]["file_name"], "tiny")
        with self.assertRaises(ValueError):
            worker.verify_stream(io.BytesIO(b"corrupt"), item, events.append)


@unittest.skipUnless(
    sync_tests.ENABLED and shutil.which("cwb-encode"),
    "Real PG/S3 and CWB index image required",
)
class IndexBuildPipelineTests(unittest.TestCase):
    setUpClass = classmethod(sync_tests.SourceSyncPipelineTests.setUpClass.__func__)
    tearDownClass = classmethod(
        sync_tests.SourceSyncPipelineTests.tearDownClass.__func__
    )

    def setUp(self):
        sync_tests.SourceSyncPipelineTests.setUp(self)
        sync = sync_tests.SourceSyncPipelineTests.start(self)
        self.assertEqual(
            sync_tests.SourceSyncPipelineTests.work(self, sync)["status"], "staged"
        )
        from services.api import source_sync

        self.acquisition = UUID(
            source_sync.report(sync, self.admin)["result"]["acquisition_id"]
        )

    def tearDown(self):
        with self.admin_db.begin() as db:
            for table in (
                "source_indexes",
                "index_build_outbox",
                "index_build_events",
                "index_build_attempts",
            ):
                db.execute(
                    text(
                        f"DELETE FROM app.{table} WHERE run_id IN (SELECT id FROM app.index_build_runs WHERE actor_id=:id)"
                    ),
                    {"id": self.admin.id},
                )
            db.execute(
                text("DELETE FROM app.index_build_runs WHERE actor_id=:id"),
                {"id": self.admin.id},
            )
            db.execute(
                text("DELETE FROM app.index_build_actions WHERE actor_id=:id"),
                {"id": self.admin.id},
            )
        sync_tests.SourceSyncPipelineTests.tearDown(self)

    def start(self, key=None):
        return index_builds.start(
            "D12",
            index_builds.BuildInput(acquisition_id=self.acquisition),
            self.admin,
            key or uuid4().hex,
        )

    def work(self, ident, attempt=1):
        with patch.dict(os.environ, {"DATABASE_URL": self.worker_url}):
            return worker.execute(ident, attempt)

    def row(self, ident):
        return index_builds.report(UUID(str(ident)), self.admin)

    def test_admin_rls_concurrent_start_and_double_claim(self):
        with self.assertRaises(ApiError) as caught:
            index_builds.start(
                "D12",
                index_builds.BuildInput(acquisition_id=self.acquisition),
                self.reader,
                uuid4().hex,
            )
        self.assertEqual(caught.exception.code, "ADMIN_REQUIRED")
        key = uuid4().hex
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _: self.start(key), range(2)))
        self.assertEqual(results[0], results[1])
        ident = UUID(results[0]["index_run_id"])
        with transaction(self.reader.id) as db:
            self.assertIsNone(db.get(IndexRun, ident))
        with self.assertRaises(ApiError) as caught:
            self.start()
        self.assertEqual(caught.exception.code, "INDEX_ALREADY_ACTIVE")
        with (
            patch.dict(os.environ, {"DATABASE_URL": self.worker_url}),
            ThreadPoolExecutor(max_workers=2) as pool,
        ):
            claims = list(pool.map(lambda _: worker.claim(ident, 1), range(2)))
        self.assertEqual(sum(value is not None for value in claims), 1)

    def test_real_builder_immutable_objects_existing_result_and_no_release(self):
        ident = UUID(self.start()["index_run_id"])
        self.assertEqual(self.work(ident)["status"], "indexed")
        row = self.row(ident)
        self.assertEqual(
            (row["state"], row["stage"], row["result"]["searchable"]),
            ("SUCCEEDED", "INDEXED", False),
        )
        self.assertEqual(row["result"]["counts"]["sentences"], 4)
        self.assertTrue(row["result"]["quality"]["token_roundtrip_verified"])
        with transaction(self.admin.id) as db:
            index = db.scalar(select(SourceIndex).where(SourceIndex.run_id == ident))
            for item in index.objects:
                stream = storage.read_private(
                    item["object_key"], item["version_id"], item["etag"]
                )
                try:
                    worker.verify_stream(stream, item, lambda _: None)
                finally:
                    stream.close()
            self.assertEqual(db.get(IndexRun, ident).reserved_bytes, 0)
        count = len(self.objects)
        again = self.start()
        self.assertTrue(again["existing"])
        self.assertEqual(again["index_run_id"], str(ident))
        self.assertEqual(self.work(ident)["status"], "duplicate_or_ineligible")
        self.assertEqual(len(self.objects), count)
        self.assertEqual(catalog.source_versions("D12", self.admin, None, 50).items, [])

    def test_cancellation_after_upload_deletes_only_unpublished_versions(self):
        ident = UUID(self.start()["index_run_id"])
        publish = worker.publish

        def cancel_then_publish(lease, bundle, objects):
            with patch.dict(os.environ, {"DATABASE_URL": self.app_url}):
                index_builds.cancel(ident, EmptyBody(), self.admin, uuid4().hex)
            return publish(lease, bundle, objects)

        with patch.object(worker, "publish", side_effect=cancel_then_publish):
            self.assertEqual(self.work(ident)["status"], "fenced")
        self.assertEqual(self.row(ident)["state"], "CANCELLED")
        with transaction(self.admin.id) as db:
            self.assertEqual(db.get(IndexRun, ident).reserved_bytes, 0)
            self.assertIsNone(
                db.scalar(select(SourceIndex).where(SourceIndex.run_id == ident))
            )
        for key, version in self.objects:
            if key.startswith("source-index/"):
                with self.assertRaises(ClientError) as caught:
                    storage.client().get_object(
                        Bucket=storage.bucket(), Key=key, VersionId=version
                    )
                self.assertIn(
                    caught.exception.response["Error"]["Code"],
                    {"NoSuchKey", "NoSuchVersion"},
                )

    def test_publish_rechecks_admin_identity_lease_and_manifest(self):
        # Each failure happens after actual S3 writes and must leave no registered index.
        original_publish = worker.publish
        for condition in ("admin", "identity", "lease", "manifest"):
            with self.subTest(condition=condition):
                ident = UUID(self.start()["index_run_id"])

                def alter(lease, bundle, objects, condition=condition, ident=ident):
                    with self.admin_db.begin() as db:
                        if condition == "admin":
                            db.execute(
                                text(
                                    "UPDATE app.users SET is_platform_admin=false WHERE id=:id"
                                ),
                                {"id": self.admin.id},
                            )
                        elif condition == "identity":
                            metadata = dict(self.original_metadata)
                            metadata["name"] = "Changed identity"
                            db.execute(
                                text(
                                    "UPDATE app.catalog_sources SET metadata_json=CAST(:data AS jsonb) WHERE source_id='D12'"
                                ),
                                {"data": json.dumps(metadata)},
                            )
                        elif condition == "lease":
                            db.execute(
                                text(
                                    "UPDATE app.index_build_runs SET lease_expires_at=now()-interval '1 second' WHERE id=:id"
                                ),
                                {"id": ident},
                            )
                        else:
                            bundle["manifest"]["recipe_sha256"] = "0" * 64
                    return original_publish(lease, bundle, objects)

                with patch.object(worker, "publish", side_effect=alter):
                    self.assertIn(self.work(ident)["status"], {"failed", "fenced"})
                with self.admin_db.begin() as db:
                    self.assertEqual(
                        db.scalar(
                            text(
                                "SELECT count(*) FROM app.source_indexes WHERE run_id=:id"
                            ),
                            {"id": ident},
                        ),
                        0,
                    )
                    self.assertEqual(
                        db.scalar(
                            text(
                                "SELECT reserved_bytes FROM app.index_build_runs WHERE id=:id"
                            ),
                            {"id": ident},
                        ),
                        0,
                    )
                    db.execute(
                        text(
                            "UPDATE app.users SET is_platform_admin=true WHERE id=:id"
                        ),
                        {"id": self.admin.id},
                    )
                    db.execute(
                        text(
                            "UPDATE app.catalog_sources SET metadata_json=CAST(:data AS jsonb) WHERE source_id='D12'"
                        ),
                        {"data": json.dumps(self.original_metadata)},
                    )

    def test_failed_retry_after_another_success_reuses_index_instead_of_queue(self):
        old = UUID(self.start()["index_run_id"])
        with patch.object(
            source_index,
            "build",
            side_effect=RuntimeError("controlled fixture failure"),
        ):
            self.assertEqual(self.work(old)["status"], "failed")
        self.assertTrue(self.row(old)["allowed_actions"]["retry"])
        new = UUID(self.start()["index_run_id"])
        self.assertEqual(self.work(new)["status"], "indexed")
        with self.assertRaises(ApiError) as caught:
            index_builds.retry(old, EmptyBody(), self.admin, uuid4().hex)
        self.assertEqual(caught.exception.code, "INDEX_ALREADY_BUILT")
        self.assertEqual(self.row(old)["attempt"], 1)

    def test_unknown_put_holds_budget_and_blocks_retry(self):
        ident = UUID(self.start()["index_run_id"])
        original = storage.put_private

        def lost_ack(*args):
            original(*args)
            raise TimeoutError("simulated lost PUT acknowledgement")

        with patch.object(storage, "put_private", side_effect=lost_ack):
            self.assertEqual(self.work(ident)["status"], "failed")
        row = self.row(ident)
        self.assertEqual(row["error"]["code"], "INDEX_CLEANUP_REQUIRED")
        self.assertFalse(row["allowed_actions"]["retry"])
        with self.assertRaises(ApiError) as caught:
            index_builds.retry(ident, EmptyBody(), self.admin, uuid4().hex)
        self.assertEqual(caught.exception.code, "INDEX_CLEANUP_REQUIRED")
        with (
            patch.dict(os.environ, {"INDEX_STORAGE_QUOTA_BYTES": str(8 * 1024**3)}),
            self.assertRaises(ApiError) as caught,
        ):
            self.start()
        self.assertEqual(caught.exception.code, "INDEX_QUOTA_EXCEEDED")

    def test_finite_retry_outbox_and_old_delivery(self):
        ident = UUID(self.start()["index_run_id"])
        with patch.dict(os.environ, {"DATABASE_URL": self.worker_url}):
            self.assertTrue(dispatcher.dispatch_once(lambda *_: None))
        for attempt in range(1, 4):
            with patch.object(
                source_index, "build", side_effect=RuntimeError("fixture")
            ):
                self.assertEqual(self.work(ident, attempt)["status"], "failed")
            if attempt < 3:
                index_builds.retry(ident, EmptyBody(), self.admin, uuid4().hex)
                self.assertEqual(
                    self.work(ident, attempt)["status"], "duplicate_or_ineligible"
                )
        self.assertFalse(self.row(ident)["allowed_actions"]["retry"])

    @patch.dict(os.environ, {"AGENT_RUNTIME_MODE": "fixture"})
    def test_pi_requires_index_report_and_does_not_cancel_shared_build(self):
        session = agent_control.create_session(
            self.admin.id, {"scope_kind": "platform"}
        )
        run = agent_control.create_run(
            self.admin.id,
            UUID(session["session_id"]),
            uuid4(),
            "Fixture request",
            session["scope_digest"],
        )
        ident = UUID(run["run_id"])
        grant = agent_control.claim(ident, uuid4())

        def invoke(tool, arguments):
            with agent_control.execution(ident, grant["execution_token"]) as (
                db,
                owner,
                current,
                actor,
                tools,
            ):
                return agent_control.invoke(
                    db,
                    owner,
                    current,
                    actor,
                    tools,
                    InvocationInput(
                        request_key=uuid4(),
                        tool_call_id=uuid4().hex,
                        tool_name=tool,
                        arguments=arguments,
                    ),
                )

        response = invoke(
            "indexes.build",
            {"source_id": "D12", "acquisition_id": str(self.acquisition)},
        )
        self.assertEqual(response["result"]["status"], "accepted")
        index_id = UUID(response["result"]["job_id"])
        for expected in ("JOBS_PENDING", "JOB_RESULT_NOT_OBSERVED"):
            with (
                self.assertRaises(ApiError) as caught,
                agent_control.execution(ident, grant["execution_token"]) as (
                    db,
                    _,
                    current,
                    _,
                    _,
                ),
            ):
                agent_checkpoints.necessary_results(db, current)
            self.assertEqual(caught.exception.code, expected)
            if expected == "JOBS_PENDING":
                self.assertEqual(self.work(index_id)["status"], "indexed")
        invoke("indexes.report", {"index_run_id": str(index_id)})
        with agent_control.execution(ident, grant["execution_token"]) as (
            db,
            _,
            current,
            _,
            _,
        ):
            agent_checkpoints.necessary_results(db, current)
        agent_routes.cancel(ident, EmptyBody(), self.admin)
        self.assertEqual(self.row(index_id)["state"], "SUCCEEDED")
