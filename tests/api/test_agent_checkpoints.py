"""Actual PG/private versioned S3 checkpoints; synthetic SDK-format fixtures.

The separate Node smoke proves SessionManager reopening. Job state fixtures here
exercise the terminal gate, not worker execution or material validation.
"""

import copy
import hashlib
import io
import json
import os
import time
import unittest
from datetime import timedelta
from unittest.mock import patch
from uuid import UUID, uuid4

from botocore.exceptions import ClientError, ReadTimeoutError
from sqlalchemy import select, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from services.api import agent_checkpoints as checkpoints
from services.api import agent_control as control
from services.api import storage
from services.api.agent_models import AgentCheckpoint, AgentRun, AgentSession
from services.api.db import transaction
from services.api.errors import ApiError
from services.api.job_models import Job, Upload
from tests.api import test_agent_runtime as runtime_tests


def archive(session_id, calls=(), baseline=None, message="Fixture request"):
    """Explicit test fixture, not a file claimed to have been emitted by Pi."""
    rows = (
        [json.loads(x) for x in baseline.splitlines()]
        if baseline
        else [
            {
                "type": "session",
                "version": 3,
                "id": session_id,
                "timestamp": "2026-10-16T00:00:00Z",
                "cwd": "fixture",
            }
        ]
    )

    def add(kind, **values):
        parent = rows[-1].get("id") if len(rows) > 1 else None
        rows.append(
            {
                "type": kind,
                "id": uuid4().hex[:8],
                "parentId": parent,
                "timestamp": "2026-10-16T00:00:00Z",
                **values,
            }
        )

    def assistant(content, reason):
        add(
            "message",
            message={
                "role": "assistant",
                "content": content,
                "stopReason": reason,
                "provider": checkpoints.RUNTIME_MANIFEST["provider"],
                "model": checkpoints.RUNTIME_MANIFEST["model"],
                "timestamp": 1,
            },
        )

    if not baseline:
        add(
            "model_change",
            provider=checkpoints.RUNTIME_MANIFEST["provider"],
            modelId=checkpoints.RUNTIME_MANIFEST["model"],
        )
    add(
        "message",
        message={"role": "user", "content": message, "timestamp": 1},
    )
    for tool, args, output, call_id in calls:
        name = tool.replace(".", "_")
        assistant(
            [{"type": "toolCall", "id": call_id, "name": name, "arguments": args}],
            "toolUse",
        )
        add(
            "message",
            message={
                "role": "toolResult",
                "toolCallId": call_id,
                "toolName": name,
                "content": [{"type": "text", "text": json.dumps(output)}],
                "details": output,
                "isError": False,
                "timestamp": 1,
            },
        )
    assistant([{"type": "text", "text": "Fixture completed"}], "stop")
    return "\n".join(json.dumps(x, ensure_ascii=False) for x in rows) + "\n"


class CheckpointFormatTests(unittest.TestCase):
    def test_supported_fixture_and_malformed_content_rejection(self):
        raw = archive(str(uuid4()))
        self.assertEqual(checkpoints.parsed(raw.encode())[0]["version"], 3)
        for content in (
            None,
            "bad",
            [None],
            ["bad"],
            [{"type": "toolCall"}],
            [{"type": "text", "text": 4}],
        ):
            with self.subTest(content=content):
                rows = [json.loads(x) for x in raw.splitlines()]
                rows[-1]["message"]["content"] = content
                with self.assertRaises(ApiError) as failure:
                    checkpoints.parsed("\n".join(json.dumps(x) for x in rows).encode())
                self.assertEqual(failure.exception.status, 422)

    def test_branch_compaction_and_unknown_results_not_silently_dropped(self):
        rows = [json.loads(x) for x in archive(str(uuid4())).splitlines()]
        for mutation in ("compaction", "context_edit", "branch_summary"):
            candidate = copy.deepcopy(rows)
            candidate[1]["type"] = mutation
            with self.subTest(mutation=mutation), self.assertRaises(ApiError):
                checkpoints.parsed("\n".join(json.dumps(x) for x in candidate).encode())
        rows[-1]["parentId"] = None
        with self.assertRaises(ApiError):
            checkpoints.parsed("\n".join(json.dumps(x) for x in rows).encode())


@unittest.skipUnless(
    os.getenv("TEST_ADMIN_DATABASE_URL") and os.getenv("S3_ENDPOINT_URL"),
    "Dedicated real PostgreSQL and versioned S3 required",
)
class AgentCheckpointTests(unittest.TestCase):
    setUpClass = classmethod(runtime_tests.AgentRuntimeTests.setUpClass.__func__)
    tearDownClass = classmethod(runtime_tests.AgentRuntimeTests.tearDownClass.__func__)
    login = runtime_tests.AgentRuntimeTests.login
    project = runtime_tests.AgentRuntimeTests.project
    session = runtime_tests.AgentRuntimeTests.session
    start_run = runtime_tests.AgentRuntimeTests.start_run
    claim = runtime_tests.AgentRuntimeTests.claim

    def setUp(self):
        runtime_tests.AgentRuntimeTests.setUp(self)
        self.objects = []
        self.real_put = storage.put_private

        def record(key, *args):
            result = self.real_put(key, *args)
            self.objects.append((key, result[0]))
            return result

        self.store_patch = patch.object(storage, "put_private", side_effect=record)
        self.store_patch.start()

    def tearDown(self):
        self.store_patch.stop()
        for key, version in self.objects:
            storage.client().delete_object(
                Bucket=storage.bucket(), Key=key, VersionId=version
            )
        runtime_tests.AgentRuntimeTests.tearDown(self)

    def call(self, client, run, token, tool, args=None):
        call_id, args = uuid4().hex, args or {}
        response = client.post(
            f"/internal/agent/runs/{run}/invocations",
            headers={"Authorization": "Bearer " + token},
            json={
                "request_key": str(uuid4()),
                "tool_call_id": call_id,
                "tool_name": tool,
                "arguments": args,
            },
        )
        self.assertEqual(response.status_code, 200, response.text)
        return tool, args, response.json(), call_id

    def settled(self, client, run, token):
        result = client.post(
            f"/internal/agent/runs/{run}/events",
            headers={"Authorization": "Bearer " + token},
            json={"event_id": str(uuid4()), "kind": "sdk.agent_settled"},
        )
        self.assertEqual(result.status_code, 200, result.text)

    def put(self, client, run, token, raw, base=None, key=None):
        return client.post(
            f"/internal/agent/runs/{run}/checkpoint",
            headers={"Authorization": "Bearer " + token},
            json={
                "request_key": key or str(uuid4()),
                "base_checkpoint_id": base,
                "runtime_manifest": checkpoints.RUNTIME_MANIFEST,
                "session_jsonl": raw,
            },
        )

    def publish(self, client, run, token, checkpoint_id):
        return client.post(
            f"/internal/agent/runs/{run}/settle",
            headers={"Authorization": "Bearer " + token},
            json={"checkpoint_id": checkpoint_id},
        )

    def make_completed(
        self, client=None, scope=None, tool="projects.create", args=None
    ):
        client = client or self.login()
        sid = self.session(client, scope)
        run = self.start_run(client, sid)
        token = self.claim(client, run)
        args = args if args is not None else {"name": "checkpoint " + uuid4().hex}
        call = self.call(client, run, token, tool, args)
        raw = archive(sid, [call])
        self.settled(client, run, token)
        response = self.put(client, run, token, raw)
        self.assertEqual(response.status_code, 200, response.text)
        checkpoint = response.json()
        result = self.publish(client, run, token, checkpoint["checkpoint_id"])
        self.assertEqual(result.status_code, 200, result.text)
        self.assertEqual(result.json()["state"], "SUCCEEDED")
        return client, sid, run, token, raw, checkpoint

    def test_publish_reopen_idempotency_and_old_cancel_preserves_new_writer(self):
        client, sid, run, token, raw, checkpoint = self.make_completed()
        next_run = self.start_run(client, sid)
        next_token = self.claim(client, next_run)
        loaded = client.get(
            f"/internal/agent/runs/{next_run}/checkpoint",
            headers={"Authorization": "Bearer " + next_token},
        )
        self.assertEqual(loaded.status_code, 200, loaded.text)
        self.assertEqual(loaded.json()["session_jsonl"], raw)
        self.assertEqual(loaded.json()["checkpoint"], checkpoint)
        self.assertEqual(checkpoint["sha256"], hashlib.sha256(raw.encode()).hexdigest())
        self.assertEqual(
            self.publish(client, run, token, checkpoint["checkpoint_id"]).json()[
                "state"
            ],
            "SUCCEEDED",
        )
        self.assertEqual(
            self.publish(client, run, token, str(uuid4())).status_code, 409
        )
        before = client.get(f"/api/v1/agent/sessions/{sid}").json()
        self.assertEqual(
            client.post(f"/api/v1/agent/runs/{run}/cancel", json={}).json()["state"],
            "SUCCEEDED",
        )
        self.assertEqual(client.get(f"/api/v1/agent/sessions/{sid}").json(), before)
        self.assertEqual(before["active_run_id"], next_run)
        with transaction(self.users["owner"]["id"]) as db:
            row = db.get(AgentCheckpoint, UUID(checkpoint["checkpoint_id"]))
            self.assertTrue(row.version_id and row.version_id != "null")
            self.assertEqual(checkpoints.read_bytes(row), raw.encode())
            with self.assertRaises(ClientError) as rejected:
                storage.put_private(
                    row.object_key, io.BytesIO(b"overwrite"), 9, "application/x-ndjson"
                )
            self.assertEqual(
                rejected.exception.response["ResponseMetadata"]["HTTPStatusCode"], 412
            )
            self.assertEqual(checkpoints.read_bytes(row), raw.encode())
        with (
            self.assertRaises(SQLAlchemyError),
            transaction(self.users["owner"]["id"]) as db,
        ):
            db.execute(
                text("UPDATE app.agent_checkpoints SET sha256=:h WHERE id=:id"),
                {"h": "0" * 64, "id": checkpoint["checkpoint_id"]},
            )
        raw2 = archive(sid, baseline=raw)
        self.settled(client, next_run, next_token)
        cp2 = self.put(client, next_run, next_token, raw2, checkpoint["checkpoint_id"])
        self.assertEqual(cp2.status_code, 200, cp2.text)
        self.assertEqual(
            self.publish(
                client, next_run, next_token, cp2.json()["checkpoint_id"]
            ).json()["state"],
            "SUCCEEDED",
        )

    def test_cross_session_tamper_and_omitted_tool_result_rejected(self):
        client = self.login()
        sid = self.session(client)
        run = self.start_run(client, sid)
        token = self.claim(client, run)
        call = self.call(client, run, token, "account.get")
        self.settled(client, run, token)
        self.assertEqual(
            self.put(client, run, token, archive(str(uuid4()), [call])).json()["code"],
            "CHECKPOINT_SESSION_MISMATCH",
        )
        self.assertEqual(
            self.put(client, run, token, archive(sid)).json()["code"],
            "CHECKPOINT_TOOL_UNRESOLVED",
        )
        bad = copy.deepcopy(call)
        bad[2]["data"]["email"] = "forged@example.test"
        self.assertEqual(
            self.put(client, run, token, archive(sid, [bad])).json()["code"],
            "CHECKPOINT_TOOL_MISMATCH",
        )
        response = self.put(client, run, token, archive(sid, [call]))
        self.assertEqual(response.status_code, 200, response.text)
        self.assertIsNone(
            client.get(f"/api/v1/agent/sessions/{sid}").json()["latest_checkpoint_id"]
        )

    def test_storage_timeout_and_database_failure_never_publish(self):
        client = self.login()
        sid = self.session(client)
        run = self.start_run(client, sid)
        token = self.claim(client, run)
        raw = archive(sid)
        self.settled(client, run, token)
        key = str(uuid4())
        tracked = storage.put_private

        def lost_ack(*args):
            tracked(*args)
            raise ReadTimeoutError(endpoint_url="private-object-fixture")

        with patch.object(storage, "put_private", side_effect=lost_ack):
            self.assertEqual(
                self.put(client, run, token, raw, key=key).json()["code"],
                "CHECKPOINT_STORE_UNCERTAIN",
            )
        self.assertIsNone(
            client.get(f"/api/v1/agent/sessions/{sid}").json()["latest_checkpoint_id"]
        )
        emit = control.emit

        def db_failure(db, current, kind, payload=None):
            if kind == "checkpoint.stored":
                db.execute(text("SELECT 1/0"))
            return emit(db, current, kind, payload)

        with (
            patch.object(control, "emit", side_effect=db_failure),
            self.assertRaises(SQLAlchemyError),
        ):
            self.put(client, run, token, raw, key=key)
        with Session(self.admin) as db:
            self.assertIsNone(
                db.scalar(
                    select(AgentCheckpoint).where(AgentCheckpoint.run_id == UUID(run))
                )
            )
        response = self.put(client, run, token, raw, key=key)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(
            self.put(client, run, token, raw, key=key).json(), response.json()
        )
        self.assertEqual(len(self.objects), 3)
        self.assertEqual(
            self.publish(client, run, token, response.json()["checkpoint_id"]).json()[
                "state"
            ],
            "SUCCEEDED",
        )

    def test_storage_crosses_lease_deadline_and_rolls_back(self):
        client = self.login()
        sid = self.session(client)
        run = self.start_run(client, sid)
        token = self.claim(client, run)
        self.settled(client, run, token)
        with Session(self.admin) as db, db.begin():
            db.get(AgentRun, UUID(run)).lease_expires_at = control.now() + timedelta(
                milliseconds=200
            )
        tracked = storage.put_private

        def slow(*args):
            value = tracked(*args)
            time.sleep(0.3)
            return value

        with patch.object(storage, "put_private", side_effect=slow):
            response = self.put(client, run, token, archive(sid))
        self.assertEqual(response.status_code, 401, response.text)
        self.assertEqual(
            len(self.objects), 1, "The fault must occur after a real object write"
        )
        with Session(self.admin) as db:
            self.assertIsNone(
                db.scalar(
                    select(AgentCheckpoint).where(AgentCheckpoint.run_id == UUID(run))
                )
            )
            self.assertIsNone(db.get(AgentSession, UUID(sid)).latest_checkpoint_id)
        self.assertEqual(
            client.get(f"/api/v1/agent/runs/{run}").json()["state"], "WAITING_REVIEW"
        )

    def test_cancelled_unpublished_archive_cannot_replace_previous(self):
        client, sid, _run, _token, raw, checkpoint = self.make_completed()
        run = self.start_run(client, sid)
        token = self.claim(client, run)
        self.settled(client, run, token)
        staged = self.put(
            client, run, token, archive(sid, baseline=raw), checkpoint["checkpoint_id"]
        )
        self.assertEqual(staged.status_code, 200, staged.text)
        client.post(f"/api/v1/agent/runs/{run}/cancel", json={})
        self.assertEqual(
            self.publish(
                client, run, token, staged.json()["checkpoint_id"]
            ).status_code,
            401,
        )
        self.assertEqual(
            client.get(f"/api/v1/agent/sessions/{sid}").json()["latest_checkpoint_id"],
            checkpoint["checkpoint_id"],
        )

    def test_corrupted_storage_read_requires_review_without_changing_pointer(self):
        client, sid, _run, _token, _raw, checkpoint = self.make_completed()
        next_run = self.start_run(client, sid)
        real_read = storage.read_private

        def corrupted(*args):
            # Read the actual pinned S3 object, then inject a corrupted byte at
            # the storage boundary. This is not a claim that S3 changed a version.
            stream = real_read(*args)
            try:
                raw = stream.read()
            finally:
                stream.close()
            return io.BytesIO(b"!" + raw[1:])

        with patch.object(storage, "read_private", side_effect=corrupted):
            response = client.post(
                f"/internal/agent/runs/{next_run}/claim",
                json={"host_id": str(uuid4())},
                headers={"Authorization": "Bearer " + self.host_key},
            )
        self.assertEqual(response.json()["code"], "CHECKPOINT_INTEGRITY_FAILED")
        self.assertEqual(
            client.get(f"/api/v1/agent/runs/{next_run}").json()["state"],
            "WAITING_REVIEW",
        )
        self.assertEqual(
            client.get(f"/api/v1/agent/sessions/{sid}").json()["latest_checkpoint_id"],
            checkpoint["checkpoint_id"],
        )

    def test_old_project_dependency_revoked_but_new_unrelated_membership_allowed(self):
        owner, editor = self.login(), self.login("editor")
        project = self.project(owner, ("editor",))
        editor, sid, _run, _token, _raw, _cp = self.make_completed(
            editor, tool="projects.list", args={}
        )
        self.project(owner, ("editor",))  # Additional access must not invalidate.
        run = self.start_run(editor, sid)
        token = self.claim(editor, run)
        self.assertEqual(
            editor.get(
                f"/internal/agent/runs/{run}/checkpoint",
                headers={"Authorization": "Bearer " + token},
            ).status_code,
            200,
        )
        owner.delete(f"/api/v1/projects/{project}/members/{self.users['editor']['id']}")
        result = editor.post(
            f"/internal/agent/runs/{run}/heartbeat",
            headers={"Authorization": "Bearer " + token},
            json={},
        )
        self.assertEqual(result.json()["code"], "CHECKPOINT_AUTH_CHANGED")
        self.assertEqual(
            editor.get(f"/api/v1/agent/runs/{run}").json()["code"], "CHECKPOINT_AUTH_CHANGED"
        )
        with Session(self.admin) as db:
            self.assertEqual(db.get(AgentRun, UUID(run)).state, "WAITING_REVIEW")

    def test_job_pending_and_result_not_observed_gate_publication(self):
        client = self.login()
        pid = self.project(client)
        sid = self.session(client, {"scope_kind": "project", "project_id": pid})
        run = self.start_run(client, sid)
        token = self.claim(client, run)
        calls = [
            self.call(
                client,
                run,
                token,
                "uploads.create",
                {
                    "filename": "ledger-fixture.txt",
                    "size": 1,
                    "sha256": "a" * 64,
                    "media_type": "text/plain",
                },
            )
        ]
        upload_id = calls[0][2]["data"]["upload_id"]
        with Session(self.admin) as db, db.begin():
            upload = db.get(Upload, UUID(upload_id))
            upload.state, upload.version_id, upload.etag = (
                "UPLOADED",
                "db-fixture",
                "db-fixture",
            )
        calls.append(
            self.call(client, run, token, "uploads.complete", {"upload_id": upload_id})
        )
        job_id = calls[-1][2]["result"]["job_id"]
        self.settled(client, run, token)
        staged = self.put(client, run, token, archive(sid, calls))
        self.assertEqual(staged.status_code, 200, staged.text)
        checkpoint_id = staged.json()["checkpoint_id"]
        self.assertEqual(
            self.publish(client, run, token, checkpoint_id).json()["code"],
            "JOBS_PENDING",
        )
        with Session(self.admin) as db, db.begin():
            job = db.get(Job, UUID(job_id))
            job.state, job.result = "SUCCEEDED", {"state": "VALIDATED", "fixture": True}
        self.assertEqual(
            self.publish(client, run, token, checkpoint_id).json()["code"],
            "JOB_RESULT_NOT_OBSERVED",
        )
        calls.append(self.call(client, run, token, "jobs.get", {"job_id": job_id}))
        self.settled(client, run, token)
        final = self.put(client, run, token, archive(sid, calls))
        self.assertEqual(final.status_code, 200, final.text)
        self.assertEqual(
            self.publish(client, run, token, final.json()["checkpoint_id"]).json()[
                "state"
            ],
            "SUCCEEDED",
        )

    def test_known_failed_tool_can_be_handled_but_missing_context_requires_review(self):
        client = self.login()
        sid = self.session(client)
        run = self.start_run(client, sid)
        token = self.claim(client, run)
        failed = self.call(client, run, token, "projects.create", {"name": ""})
        self.assertEqual(failed[2]["result"]["status"], "failed")
        corrected = self.call(
            client, run, token, "projects.create", {"name": "corrected " + uuid4().hex}
        )
        self.settled(client, run, token)
        stored = self.put(client, run, token, archive(sid, [failed, corrected]))
        self.assertEqual(stored.status_code, 200, stored.text)
        self.assertEqual(
            self.publish(client, run, token, stored.json()["checkpoint_id"]).json()[
                "state"
            ],
            "SUCCEEDED",
        )
        second = self.start_run(client, sid)
        token2 = self.claim(client, second)
        result = client.post(
            f"/internal/agent/runs/{second}/review",
            headers={"Authorization": "Bearer " + token2},
            json={"reason": "SDK_CONTEXT_UNCERTAIN"},
        )
        self.assertEqual(result.json()["state"], "WAITING_REVIEW")


if __name__ == "__main__":
    unittest.main()
