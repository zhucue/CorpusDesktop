"""Real PG/S3 source ledger tests. Network is replaced by an explicit tiny fixture."""

import bz2
import hashlib
import json
import os
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError
from uuid import UUID, uuid4

from sqlalchemy import create_engine, select, text
from sqlalchemy.exc import DBAPIError

from pipelines.sources import tatoeba
from services.api import (
    agent_checkpoints,
    agent_control,
    agent_routes,
    catalog,
    source_sync,
    storage,
)
from services.api.agent_internal import InvocationInput
from services.api.auth import Actor
from services.api.db import _engine, transaction
from services.api.errors import ApiError
from services.api.jobs import EmptyBody
from services.api.source_sync_models import Acquisition, SyncRun
from workers import source_sync as worker
from workers import source_sync_dispatcher as dispatcher

ENABLED = all(
    os.getenv(key)
    for key in (
        "DATABASE_URL",
        "TEST_OWNER_DATABASE_URL",
        "TEST_ADMIN_DATABASE_URL",
        "TEST_WORKER_DATABASE_URL",
        "S3_ENDPOINT_URL",
        "BROKER_URL",
    )
)


class SourceDiagnosticsTests(unittest.TestCase):
    def test_exception_diagnostics_exclude_url_message_body_and_locals(self):
        secret = "must-not-appear-in-diagnostics"
        try:
            try:
                raise HTTPError(
                    "https://user:" + secret + "@example.test/", 503, secret, {}, None
                )
            except HTTPError as cause:
                raise RuntimeError(secret) from cause
        except RuntimeError as error:
            diagnostic = worker.safe_exception(error)
        encoded = json.dumps(diagnostic)
        self.assertNotIn(secret, encoded)
        self.assertNotIn("https://", encoded)
        self.assertEqual(
            [item["exception_type"] for item in diagnostic],
            ["RuntimeError", "HTTPError"],
        )
        self.assertEqual(diagnostic[1]["http_status"], 503)
        self.assertTrue(diagnostic[0]["frames"])


def acquire_fixture(output, callback=lambda _: None, *, expected=None):
    """Four real text rows, two direct pairs; no official network quality claim."""
    output = Path(output)
    output.mkdir(parents=True)
    records, validators = [], {}
    bodies = [
        "1\tcmn\t你好。\tAlice\t\\N\t\\N\n2\tcmn\t再见。\tAlice\t\\N\t\\N\n",
        "3\teng\tHello.\tBob\t\\N\t\\N\n4\teng\tGoodbye.\tBob\t\\N\t\\N\n",
        "1\t3\n2\t4\n3\t1\n",
    ]
    for (name, url), body in zip(tatoeba.FILES.items(), bodies, strict=True):
        raw = bz2.compress(body.encode())
        path = output / name
        path.write_bytes(raw)
        validators[name] = {
            "bytes": len(raw),
            "etag": '"fixture-v1"',
            "last_modified": "Sat, 10 Oct 2026 06:29:32 GMT",
            "export_date": "2026-10-10",
        }
        records.append(
            {
                "name": name,
                "url": url,
                "path": str(path),
                "bytes": len(raw),
                "sha256": hashlib.sha256(raw).hexdigest(),
                **validators[name],
            }
        )
    if expected is not None and expected != validators:
        raise tatoeba.SourceError("Fixture changed", "SOURCE_VERSION_CHANGED")
    callback({"stage": "pinned", "expected": validators})
    callback(
        {
            "stage": "download",
            "processed_bytes": sum(x["bytes"] for x in records),
            "total_bytes": sum(x["bytes"] for x in records),
            "processed_records": 0,
            "total_records": None,
            "file_name": None,
        }
    )
    return {
        "schema": "tatoeba-acquisition/v1",
        "files": records,
        "license_evidence": [],
        "export_date": "2026-10-10",
        "expected": validators,
    }


@unittest.skipUnless(ENABLED, "Explicit real PG roles, private S3 and broker required")
class SourceSyncPipelineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.admin_db = create_engine(os.environ["TEST_ADMIN_DATABASE_URL"])
        cls.owner_db = create_engine(os.environ["TEST_OWNER_DATABASE_URL"])
        cls.app_url = os.environ["DATABASE_URL"]
        cls.worker_url = os.environ["TEST_WORKER_DATABASE_URL"]

    @classmethod
    def tearDownClass(cls):
        for url in (cls.app_url, cls.worker_url):
            _engine(url).dispose()
        cls.admin_db.dispose()
        cls.owner_db.dispose()

    def setUp(self):
        self.admin = Actor(uuid4(), f"sync-{uuid4().hex}@example.test", True, "")
        self.reader = Actor(uuid4(), f"sync-{uuid4().hex}@example.test", False, "")
        self.ids, self.objects = [], []
        with self.owner_db.begin() as db:
            for actor in (self.admin, self.reader):
                db.execute(
                    text(
                        "INSERT INTO app.users(id,email,password_hash,is_platform_admin) VALUES(:id,:email,'unused',:admin)"
                    ),
                    {
                        "id": actor.id,
                        "email": actor.email,
                        "admin": actor.is_platform_admin,
                    },
                )
        with self.admin_db.connect() as db:
            self.original_metadata = db.scalar(
                text(
                    "SELECT metadata_json FROM app.catalog_sources WHERE source_id='D12'"
                )
            )
        self.original_put = storage.put_private

        def tracked_put(key, stream, size, media_type):
            version, etag = self.original_put(key, stream, size, media_type)
            self.objects.append((key, version))
            return version, etag

        self.storage_patch = patch.object(
            storage, "put_private", side_effect=tracked_put
        )
        self.storage_patch.start()

    def tearDown(self):
        self.storage_patch.stop()
        for key, version in self.objects:
            storage.client().delete_object(
                Bucket=storage.bucket(), Key=key, VersionId=version
            )
        with self.admin_db.begin() as db:
            db.execute(
                text(
                    "UPDATE app.catalog_sources SET metadata_json=CAST(:metadata AS jsonb) WHERE source_id='D12'"
                ),
                {"metadata": json.dumps(self.original_metadata)},
            )
            db.execute(
                text(
                    "UPDATE app.source_sync_runs SET previous_acquisition_id=NULL WHERE actor_id=:id"
                ),
                {"id": self.admin.id},
            )
            for table in (
                "source_acquisitions",
                "source_sync_outbox",
                "source_sync_events",
                "source_sync_attempts",
            ):
                db.execute(
                    text(
                        f"DELETE FROM app.{table} WHERE run_id IN (SELECT id FROM app.source_sync_runs WHERE actor_id=:id)"
                    ),
                    {"id": self.admin.id},
                )
            db.execute(
                text("DELETE FROM app.source_sync_runs WHERE actor_id=:id"),
                {"id": self.admin.id},
            )
            db.execute(
                text("DELETE FROM app.source_sync_actions WHERE actor_id=:id"),
                {"id": self.admin.id},
            )
            db.execute(
                text(
                    "UPDATE app.agent_sessions SET active_run_id=NULL WHERE actor_id=:id"
                ),
                {"id": self.admin.id},
            )
            for table in (
                "agent_events",
                "agent_invocations",
                "agent_credentials",
                "agent_runs",
                "agent_sessions",
            ):
                db.execute(
                    text(f"DELETE FROM app.{table} WHERE actor_id=:id"),
                    {"id": self.admin.id},
                )
            for actor in (self.admin, self.reader):
                db.execute(text("DELETE FROM app.users WHERE id=:id"), {"id": actor.id})

    def start(self, key=None):
        data = source_sync.start("D12", EmptyBody(), self.admin, key or uuid4().hex)
        ident = UUID(data["sync_run_id"])
        self.ids.append(ident)
        return ident

    def work(self, ident, attempt=1, acquire=acquire_fixture):
        with (
            patch.dict(os.environ, {"DATABASE_URL": self.worker_url}),
            patch.object(tatoeba, "acquire", side_effect=acquire),
        ):
            return worker.execute(ident, attempt)

    def row(self, ident):
        return source_sync.report(ident, self.admin)

    def test_nonadmin_api_and_rls_reject_shared_ledger(self):
        ident = self.start()
        for fn in (
            lambda: source_sync.start("D12", EmptyBody(), self.reader, uuid4().hex),
            lambda: source_sync.report(ident, self.reader),
            lambda: source_sync.cancel(ident, EmptyBody(), self.reader, uuid4().hex),
        ):
            with self.assertRaises(ApiError) as caught:
                fn()
            self.assertEqual(caught.exception.code, "ADMIN_REQUIRED")
        with transaction(self.reader.id) as db:
            self.assertIsNone(db.get(SyncRun, ident))
        with self.assertRaises(DBAPIError), transaction(self.reader.id) as db:
            db.execute(
                text(
                    "INSERT INTO app.source_sync_actions(id,actor_id,operation,idempotency_key,request_sha256,response,created_at) VALUES(:id,:actor,'sync.start','x',:sha,'{}',now())"
                ),
                {"id": uuid4(), "actor": self.reader.id, "sha": "a" * 64},
            )

    def test_concurrent_idempotency_active_slot_and_double_claim(self):
        key = uuid4().hex
        with ThreadPoolExecutor(max_workers=2) as pool:
            ids = list(pool.map(lambda _: self.start(key), range(2)))
        self.assertEqual(ids[0], ids[1])
        with self.assertRaises(ApiError) as caught:
            self.start()
        self.assertEqual(caught.exception.code, "SYNC_ALREADY_ACTIVE")
        with (
            patch.dict(os.environ, {"DATABASE_URL": self.worker_url}),
            ThreadPoolExecutor(max_workers=2) as pool,
        ):
            claims = list(pool.map(lambda _: worker.claim(ids[0], 1), range(2)))
        self.assertEqual(sum(x is not None for x in claims), 1)

    @patch.dict(os.environ, {"AGENT_RUNTIME_MODE": "fixture"})
    def test_platform_pi_accepted_needs_sync_report_and_cancel_is_not_exclusive(self):
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
        run_id = UUID(run["run_id"])
        grant = agent_control.claim(run_id, uuid4())

        def invoke(tool, args):
            with agent_control.execution(run_id, grant["execution_token"]) as (
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
                        arguments=args,
                    ),
                )

        response = invoke("sync.start", {"source_id": "D12"})
        self.assertEqual(response["result"]["status"], "accepted")
        ident = UUID(response["result"]["job_id"])
        with (
            self.assertRaises(ApiError) as caught,
            agent_control.execution(run_id, grant["execution_token"]) as (
                db,
                _,
                current,
                _,
                _,
            ),
        ):
            agent_checkpoints.necessary_results(db, current)
        self.assertEqual(caught.exception.code, "JOBS_PENDING")
        self.assertEqual(self.work(ident)["status"], "staged")
        with (
            self.assertRaises(ApiError) as caught,
            agent_control.execution(run_id, grant["execution_token"]) as (
                db,
                _,
                current,
                _,
                _,
            ),
        ):
            agent_checkpoints.necessary_results(db, current)
        self.assertEqual(caught.exception.code, "JOB_RESULT_NOT_OBSERVED")
        invoke("sync.report", {"sync_run_id": str(ident)})
        with agent_control.execution(run_id, grant["execution_token"]) as (
            db,
            _,
            current,
            _,
            _,
        ):
            agent_checkpoints.necessary_results(db, current)
        next_response = invoke("sync.start", {"source_id": "D12"})
        next_id = UUID(next_response["result"]["job_id"])
        agent_routes.cancel(run_id, EmptyBody(), self.admin)
        self.assertEqual(self.row(next_id)["state"], "QUEUED")
        source_sync.cancel(next_id, EmptyBody(), self.admin, uuid4().hex)

    def test_real_parse_private_versions_checksums_diff_and_no_public_release(self):
        ident = self.start()
        self.assertEqual(self.work(ident), {"status": "staged"})
        row = self.row(ident)
        self.assertEqual(
            (row["state"], row["stage"], row["result"]["searchable"]),
            ("SUCCEEDED", "VALIDATED", False),
        )
        self.assertEqual(row["result"]["quality"]["sentences"], 4)
        self.assertEqual(row["result"]["quality"]["direct_edges"], 2)
        with transaction(self.admin.id) as db:
            acquisition = db.scalar(
                select(Acquisition).where(Acquisition.run_id == ident)
            )
            for item in acquisition.objects:
                stream = storage.read_private(
                    item["object_key"], item["version_id"], item["etag"]
                )

                try:
                    raw = stream.read()
                finally:
                    stream.close()
                self.assertEqual(
                    (len(raw), hashlib.sha256(raw).hexdigest()),
                    (item["bytes"], item["sha256"]),
                )
        self.assertEqual(catalog.source_versions("D12", self.admin, None, 50).items, [])
        self.assertEqual(self.work(ident)["status"], "duplicate_or_ineligible")
        next_id = self.start()
        self.assertEqual(self.work(next_id)["status"], "staged")
        self.assertEqual(self.row(next_id)["result"]["diff"]["status"], "compared")
        self.assertEqual(self.row(next_id)["result"]["diff"]["sentence_added"], 0)

    def test_cancel_after_s3_put_never_registers_acquisition(self):
        ident = self.start()
        tracked = storage.put_private

        def cancel_after_write(*args):
            output = tracked(*args)
            with patch.dict(os.environ, {"DATABASE_URL": self.app_url}):
                source_sync.cancel(ident, EmptyBody(), self.admin, uuid4().hex)
            return output

        with patch.object(storage, "put_private", side_effect=cancel_after_write):
            self.assertEqual(self.work(ident)["status"], "fenced")
        self.assertTrue(self.objects)
        self.assertEqual(self.row(ident)["state"], "CANCELLED")
        with transaction(self.admin.id) as db:
            self.assertIsNone(
                db.scalar(select(Acquisition).where(Acquisition.run_id == ident))
            )

    def test_revocation_expiry_and_identity_change_after_object_write(self):
        for mode in ("revoked", "expired", "identity"):
            with self.subTest(mode=mode):
                ident = self.start()
                tracked = storage.put_private

                def break_authorization(*args, tracked=tracked, mode=mode, ident=ident):
                    output = tracked(*args)
                    with self.admin_db.begin() as db:
                        if mode == "revoked":
                            db.execute(
                                text(
                                    "UPDATE app.users SET is_platform_admin=false WHERE id=:id"
                                ),
                                {"id": self.admin.id},
                            )
                        elif mode == "expired":
                            db.execute(
                                text(
                                    "UPDATE app.source_sync_runs SET lease_expires_at=now()-interval '1 second' WHERE id=:id"
                                ),
                                {"id": ident},
                            )
                        else:
                            db.execute(
                                text(
                                    "UPDATE app.catalog_sources SET metadata_json=jsonb_set(metadata_json,'{name}', '\"Changed identity\"') WHERE source_id='D12'"
                                )
                            )
                    return output

                with patch.object(
                    storage, "put_private", side_effect=break_authorization
                ):
                    self.assertEqual(self.work(ident)["status"], "fenced")
                with self.admin_db.begin() as db:
                    self.assertEqual(
                        db.scalar(
                            text(
                                "SELECT count(*) FROM app.source_acquisitions WHERE run_id=:id"
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
                            "UPDATE app.catalog_sources SET metadata_json=CAST(:m AS jsonb) WHERE source_id='D12'"
                        ),
                        {"m": json.dumps(self.original_metadata)},
                    )
                with patch.dict(os.environ, {"DATABASE_URL": self.worker_url}):
                    dispatcher.expire_one_lease()
                self.assertEqual(self.row(ident)["state"], "FAILED")

    def test_retry_keeps_pinned_inputs_and_old_validated_acquisition(self):
        first = self.start()
        self.work(first)
        prior = self.row(first)["result"]
        ident = self.start()

        def unavailable(output, callback, *, expected):
            acquire_fixture(output, callback, expected=expected)
            raise tatoeba.SourceError(
                "simulated transport after metadata", "SOURCE_DOWNLOAD_FAILED"
            )

        self.assertEqual(
            self.work(ident, acquire=unavailable)["code"], "SOURCE_DOWNLOAD_FAILED"
        )
        with transaction(self.admin.id) as db:
            expected = db.get(SyncRun, ident).expected_inputs
        self.assertTrue(expected)
        source_sync.retry(ident, EmptyBody(), self.admin, uuid4().hex)

        def changed(output, callback, *, expected):
            self.assertTrue(expected)
            raise tatoeba.SourceError(
                "simulated weekly update", "SOURCE_VERSION_CHANGED"
            )

        self.assertEqual(self.work(ident, 2, changed)["code"], "SOURCE_VERSION_CHANGED")
        self.assertFalse(self.row(ident)["allowed_actions"]["retry"])
        self.assertEqual(self.row(first)["result"], prior)

    def test_durable_outbox_failure_bounded_retry_and_expired_attempt(self):
        ident = self.start()
        with self.admin_db.begin() as db:
            db.execute(
                text("UPDATE app.source_sync_outbox SET failures=19 WHERE run_id=:id"),
                {"id": ident},
            )

        def rejected(*_):
            raise ConnectionError("explicit fake broker ACK failure")

        with patch.dict(os.environ, {"DATABASE_URL": self.worker_url}):
            self.assertFalse(dispatcher.dispatch_once(rejected))
        self.assertEqual(self.row(ident)["error"]["code"], "DELIVERY_FAILED")
        for attempt in (2, 3):
            source_sync.retry(ident, EmptyBody(), self.admin, uuid4().hex)
            with patch.dict(os.environ, {"DATABASE_URL": self.worker_url}):
                self.assertIsNotNone(worker.claim(ident, attempt))
            with self.admin_db.begin() as db:
                db.execute(
                    text(
                        "UPDATE app.source_sync_runs SET lease_expires_at=now()-interval '1 second' WHERE id=:id"
                    ),
                    {"id": ident},
                )
            with patch.dict(os.environ, {"DATABASE_URL": self.worker_url}):
                dispatcher.expire_one_lease()
        self.assertFalse(self.row(ident)["allowed_actions"]["retry"])
        events = source_sync.events(ident, self.admin, 0, 100)["items"]
        self.assertEqual(
            [e["sequence"] for e in events], list(range(1, len(events) + 1))
        )


if __name__ == "__main__":
    unittest.main()
