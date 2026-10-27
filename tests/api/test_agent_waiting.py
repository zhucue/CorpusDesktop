"""Real PG/S3 control tests; job outcomes are explicit ledger fixtures.

The separate resident-Node HTTP smoke covers a real worker completing the upload.
These tests do not represent generated JSONL as an actual SDK execution.
"""

import multiprocessing
import os
import unittest
from datetime import timedelta
from unittest.mock import patch
from uuid import UUID, uuid4

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from services.api import agent_checkpoints as checkpoints
from services.api import agent_control as control
from services.api.agent_models import (
    AgentCredential,
    AgentInvocation,
    AgentRun,
    AgentSession,
)
from services.api.auth import token_hash
from services.api.errors import ApiError
from services.api.job_models import Job, Upload
from services.api.models import User
from tests.api import test_agent_checkpoints as archive_tests
from tests.api import test_agent_runtime as runtime_tests


def claim_next_process(ready, start, output):
    ready.put(os.getpid())
    start.wait(10)
    try:
        grant = control.claim_next(uuid4(), "local-fixture-v1")["grant"]
        output.put({"run_id": grant["run_id"] if grant else None, "pid": os.getpid()})
    except ApiError as exc:
        output.put({"error": exc.code, "pid": os.getpid()})


@unittest.skipUnless(
    os.getenv("TEST_ADMIN_DATABASE_URL") and os.getenv("S3_ENDPOINT_URL"),
    "Dedicated real PostgreSQL/versioned S3 required",
)
class AgentWaitingTests(unittest.TestCase):
    setUpClass = classmethod(runtime_tests.AgentRuntimeTests.setUpClass.__func__)
    tearDownClass = classmethod(runtime_tests.AgentRuntimeTests.tearDownClass.__func__)
    login = runtime_tests.AgentRuntimeTests.login
    project = runtime_tests.AgentRuntimeTests.project
    session = runtime_tests.AgentRuntimeTests.session
    start_run = runtime_tests.AgentRuntimeTests.start_run
    claim = runtime_tests.AgentRuntimeTests.claim
    call = archive_tests.AgentCheckpointTests.call
    settled = archive_tests.AgentCheckpointTests.settled
    put = archive_tests.AgentCheckpointTests.put
    publish = archive_tests.AgentCheckpointTests.publish
    setUp = archive_tests.AgentCheckpointTests.setUp

    def tearDown(self):
        # Stop only this class's accounts, so subsequent claim-next cases cannot
        # accidentally consume earlier queued test runs. Objects are exact receipts.
        ids = [item["id"] for item in self.users.values()]
        with Session(self.admin) as db, db.begin():
            db.execute(
                update(AgentRun)
                .where(
                    AgentRun.actor_id.in_(ids),
                    AgentRun.state.in_(
                        ["QUEUED", "RUNNING", "WAITING_JOB", "WAITING_REVIEW"]
                    ),
                )
                .values(state="CANCELLED", lease_expires_at=None, host_id=None)
            )
            db.execute(
                update(AgentSession)
                .where(AgentSession.actor_id.in_(ids))
                .values(active_run_id=None)
            )
        archive_tests.AgentCheckpointTests.tearDown(self)

    def suspend(self, client, run, token, checkpoint):
        return client.post(
            f"/internal/agent/runs/{run}/suspend",
            headers={"Authorization": "Bearer " + token},
            json={"checkpoint_id": checkpoint},
        )

    def grant(self, client, run):
        response = client.post(
            f"/internal/agent/runs/{run}/claim",
            headers={"Authorization": "Bearer " + self.host_key},
            json={"host_id": str(uuid4())},
        )
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def waiting(self, client=None, project=None):
        client = client or self.login()
        project = project or self.project(client)
        sid = self.session(client, {"scope_kind": "project", "project_id": project})
        run = self.start_run(client, sid)
        token = self.claim(client, run)
        calls = [
            self.call(
                client,
                run,
                token,
                "uploads.create",
                {
                    "filename": "waiting-ledger.txt",
                    "size": 1,
                    "sha256": "b" * 64,
                    "media_type": "text/plain",
                },
            )
        ]
        upload_id = calls[0][2]["data"]["upload_id"]
        with Session(self.admin) as db, db.begin():
            upload = db.get(Upload, UUID(upload_id))
            upload.state, upload.version_id, upload.etag = (
                "UPLOADED",
                "explicit-ledger-fixture",
                "fixture",
            )
        calls.append(
            self.call(client, run, token, "uploads.complete", {"upload_id": upload_id})
        )
        job = calls[-1][2]["result"]["job_id"]
        raw = archive_tests.archive(sid, calls)
        self.settled(client, run, token)
        put = self.put(client, run, token, raw)
        self.assertEqual(put.status_code, 200, put.text)
        checkpoint = put.json()["checkpoint_id"]
        wait = self.suspend(client, run, token, checkpoint)
        self.assertEqual(wait.status_code, 200, wait.text)
        self.assertEqual(wait.json()["state"], "WAITING_JOB")
        return client, sid, run, token, checkpoint, raw, job

    def succeed_job(self, job_id):
        with Session(self.admin) as db, db.begin():
            job = db.get(Job, UUID(job_id))
            job.state, job.result = "SUCCEEDED", {"state": "VALIDATED", "fixture": True}

    def test_disabled_runtime_message_scope_idempotency_and_archive_binding(self):
        client = self.login()
        sid = self.session(client)
        digest = client.get(f"/api/v1/agent/sessions/{sid}").json()["scope_digest"]
        body = {
            "request_key": str(uuid4()),
            "message": "  Exact user input 😀\n",
            "scope_digest": digest,
        }
        with patch.dict(os.environ, {"AGENT_RUNTIME_MODE": ""}):
            self.assertFalse(client.get("/api/v1/agent/runtime").json()["can_submit"])
            self.assertEqual(
                client.post(f"/api/v1/agent/sessions/{sid}/runs", json=body).json()[
                    "code"
                ],
                "AGENT_RUNTIME_UNAVAILABLE",
            )
        first = client.post(f"/api/v1/agent/sessions/{sid}/runs", json=body)
        self.assertEqual(first.status_code, 201, first.text)
        run = first.json()["run_id"]
        self.assertEqual(
            client.post(f"/api/v1/agent/sessions/{sid}/runs", json=body).json()[
                "run_id"
            ],
            run,
        )
        self.assertEqual(
            client.post(
                f"/api/v1/agent/sessions/{sid}/runs",
                json={**body, "message": "changed"},
            ).json()["code"],
            "RUN_REQUEST_CONFLICT",
        )
        self.assertEqual(
            client.post(
                f"/api/v1/agent/sessions/{sid}/runs",
                json={**body, "scope_digest": "0" * 64},
            ).json()["code"],
            "SESSION_SCOPE_CHANGED",
        )
        self.assertEqual(
            client.post(
                f"/api/v1/agent/sessions/{sid}/runs",
                json={**body, "request_key": str(uuid4())},
            ).json()["code"],
            "SESSION_BUSY",
        )
        token = self.claim(client, run)
        self.settled(client, run, token)
        self.assertEqual(
            self.put(client, run, token, archive_tests.archive(sid)).json()["code"],
            "CHECKPOINT_MESSAGE_MISMATCH",
        )
        stored = self.put(
            client, run, token, archive_tests.archive(sid, message=body["message"])
        )
        self.assertEqual(stored.status_code, 200, stored.text)
        self.assertEqual(
            self.publish(client, run, token, stored.json()["checkpoint_id"]).json()[
                "state"
            ],
            "SUCCEEDED",
        )
        messages = client.get(f"/api/v1/agent/sessions/{sid}/messages").json()
        self.assertEqual(messages["items"][0]["user_message"], body["message"])
        self.assertEqual(
            messages["items"][0]["assistant_messages"][0]["text"], "Fixture completed"
        )
        self.assertNotIn(token, str(messages))
        self.assertNotIn("session_jsonl", str(messages))

    def test_two_process_claim_next_has_one_writer(self):
        client = self.login()
        run = self.start_run(client, self.session(client))
        context = multiprocessing.get_context("spawn")
        ready, output, start = context.Queue(), context.Queue(), context.Event()
        children = [
            context.Process(target=claim_next_process, args=(ready, start, output))
            for _ in range(2)
        ]
        try:
            for child in children:
                child.start()
            for _ in children:
                ready.get(timeout=20)
            start.set()
            results = [output.get(timeout=30) for _ in children]
            self.assertEqual(
                sum(item.get("run_id") == run for item in results), 1, results
            )
            self.assertEqual(len({item["pid"] for item in results}), 2)
        finally:
            for child in children:
                child.join(10)
                if child.is_alive():
                    child.terminate()
                    child.join(10)

    def test_wait_reclaim_after_old_token_expiry_and_exact_result_observation(self):
        client, sid, run, old_token, cp, raw, job = self.waiting()
        repeated = self.suspend(client, run, old_token, cp)
        self.assertEqual(repeated.status_code, 200, repeated.text)
        with Session(self.admin) as db:
            owner, row = db.get(AgentSession, UUID(sid)), db.get(AgentRun, UUID(run))
            old_epoch = row.lease_epoch
            self.assertIsNone(owner.latest_checkpoint_id)
            self.assertEqual(row.resume_checkpoint_id, UUID(cp))
            self.assertIsNone(row.lease_expires_at)
        with patch.object(
            checkpoints,
            "read_bytes",
            side_effect=AssertionError("Unready job must not read S3 archive"),
        ):
            response = client.post(
                f"/internal/agent/runs/{run}/claim",
                headers={"Authorization": "Bearer " + self.host_key},
                json={"host_id": str(uuid4())},
            )
            self.assertEqual(response.json()["code"], "JOBS_PENDING")
        self.succeed_job(job)
        later = control.now() + timedelta(seconds=301)
        with patch.object(control, "now", return_value=later):
            grant = self.grant(client, run)
        self.assertGreater(grant["lease_epoch"], old_epoch)
        self.assertEqual(grant["resume_checkpoint"]["checkpoint_id"], cp)
        self.assertEqual(grant["waiting_jobs"][0]["report_arguments"], {"job_id": job})
        token = grant["execution_token"]
        self.assertEqual(
            client.post(
                f"/internal/agent/runs/{run}/heartbeat",
                headers={"Authorization": "Bearer " + old_token},
                json={},
            ).status_code,
            401,
        )
        # A fresh process must use the controller continuation once, not replay user input.
        wrong = archive_tests.archive(sid, baseline=raw)
        self.settled(client, run, token)
        self.assertEqual(
            self.put(client, run, token, wrong).json()["code"],
            "CHECKPOINT_MESSAGE_MISMATCH",
        )
        unobserved = archive_tests.archive(
            sid, baseline=raw, message=grant["continuation_message"]
        )
        stored = self.put(client, run, token, unobserved)
        self.assertEqual(stored.status_code, 200, stored.text)
        self.assertEqual(
            self.publish(client, run, token, stored.json()["checkpoint_id"]).json()[
                "code"
            ],
            "JOB_RESULT_NOT_OBSERVED",
        )
        observed = self.call(client, run, token, "jobs.get", {"job_id": job})
        self.settled(client, run, token)
        final = self.put(
            client,
            run,
            token,
            archive_tests.archive(
                sid, [observed], baseline=raw, message=grant["continuation_message"]
            ),
        )
        self.assertEqual(final.status_code, 200, final.text)
        self.assertEqual(
            self.publish(client, run, token, final.json()["checkpoint_id"]).json()[
                "state"
            ],
            "SUCCEEDED",
        )
        with Session(self.admin) as db:
            calls = list(
                db.scalars(
                    select(AgentInvocation).where(
                        AgentInvocation.run_id == UUID(run),
                        AgentInvocation.tool_name == "uploads.complete",
                    )
                )
            )
            self.assertEqual(len(calls), 1)
            self.assertEqual(calls[0].response["result"]["job_id"], job)

    def test_cancel_waiting_fences_resume_and_preserves_success_baseline(self):
        client, sid, run, token, cp, _raw, job = self.waiting()
        cancelled = client.post(f"/api/v1/agent/runs/{run}/cancel", json={})
        self.assertEqual(cancelled.json()["state"], "CANCELLED")
        self.assertEqual(self.suspend(client, run, token, cp).status_code, 401)
        with Session(self.admin) as db:
            self.assertEqual(db.get(Job, UUID(job)).state, "CANCELLED")
            self.assertIsNone(db.get(AgentSession, UUID(sid)).latest_checkpoint_id)
        self.start_run(client, sid)
        self.assertEqual(
            client.post(f"/api/v1/agent/runs/{run}/cancel", json={}).json()["state"],
            "CANCELLED",
        )

    def test_cancelled_old_turn_revocation_cannot_hide_behind_clean_new_run(self):
        owner, editor = self.login(), self.login("editor")
        pid = self.project(owner, ("editor",))
        sid = self.session(editor)
        old = self.start_run(editor, sid)
        token = self.claim(editor, old)
        call = self.call(editor, old, token, "projects.list")
        editor.post(f"/api/v1/agent/runs/{old}/cancel", json={})
        new = self.start_run(editor, sid)
        owner.delete(f"/api/v1/projects/{pid}/members/{self.users['editor']['id']}")
        self.assertEqual(editor.get(f"/api/v1/agent/runs/{new}").status_code, 200)
        for path in (
            f"/runs/{old}",
            f"/runs/{old}/events",
            f"/runs/{old}/invocations/{call[2]['result']['invocation_id']}",
            f"/sessions/{sid}/messages",
        ):
            with self.subTest(path=path):
                self.assertEqual(
                    editor.get("/api/v1/agent" + path).json()["code"],
                    "CHECKPOINT_AUTH_CHANGED",
                )

    def test_renew_and_wait_deadlines_are_distinct_and_bounded(self):
        client = self.login()
        run = self.start_run(client, self.session(client))
        token = self.claim(client, run)
        with Session(self.admin) as db, db.begin():
            db.get(AgentCredential, token_hash(token)).expires_at = (
                control.now() + timedelta(seconds=5)
            )
        response = client.post(
            f"/internal/agent/runs/{run}/renew",
            headers={"Authorization": "Bearer " + token},
            json={},
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["execution_token"], token)
        with Session(self.admin) as db, db.begin():
            credential, row = (
                db.get(AgentCredential, token_hash(token)),
                db.get(AgentRun, UUID(run)),
            )
            self.assertLessEqual(credential.expires_at, row.active_deadline_at)
            row.active_deadline_at = control.now() - timedelta(seconds=1)
        self.assertEqual(
            client.post(
                f"/internal/agent/runs/{run}/renew",
                headers={"Authorization": "Bearer " + token},
                json={},
            ).status_code,
            401,
        )
        waiting_client, _sid, waiting_run, _token, _cp, _raw, _job = self.waiting()
        with Session(self.admin) as db, db.begin():
            db.get(AgentRun, UUID(waiting_run)).wait_deadline_at = (
                control.now() - timedelta(seconds=1)
            )
        value = waiting_client.get(f"/api/v1/agent/runs/{waiting_run}")
        self.assertEqual(value.json()["reason"], "WAIT_DEADLINE_EXCEEDED")

    def test_waiting_role_downgrade_and_disabled_actor_cannot_resume(self):
        owner, editor = self.login(), self.login("editor")
        project = self.project(owner, ("editor",))
        client, _sid, run, _token, _cp, _raw, job = self.waiting(editor, project)
        self.succeed_job(job)
        changed = owner.put(
            f"/api/v1/projects/{project}/members/{self.users['editor']['id']}",
            json={"role": "viewer"},
        )
        self.assertEqual(changed.status_code, 200, changed.text)
        denied = client.post(
            f"/internal/agent/runs/{run}/claim",
            headers={"Authorization": "Bearer " + self.host_key},
            json={"host_id": str(uuid4())},
        )
        self.assertEqual(denied.json()["code"], "CHECKPOINT_AUTH_CHANGED")
        with Session(self.admin) as db:
            self.assertEqual(db.get(AgentRun, UUID(run)).state, "WAITING_REVIEW")
        client, _sid, run, _token, _cp, _raw, job = self.waiting()
        self.succeed_job(job)
        try:
            with Session(self.admin) as db, db.begin():
                db.get(User, self.users["owner"]["id"]).is_active = False
            denied = client.post(
                f"/internal/agent/runs/{run}/claim",
                headers={"Authorization": "Bearer " + self.host_key},
                json={"host_id": str(uuid4())},
            )
            self.assertIn(denied.status_code, (403, 404))
        finally:
            with Session(self.admin) as db, db.begin():
                db.get(User, self.users["owner"]["id"]).is_active = True

    def test_failed_or_cancelled_job_is_observed_without_resubmission_or_success(self):
        for terminal in ("FAILED", "CANCELLED"):
            with self.subTest(terminal=terminal):
                client, _sid, run, _token, _cp, raw, job = self.waiting()
                with Session(self.admin) as db, db.begin():
                    row = db.get(Job, UUID(job))
                    row.state = terminal
                    row.error = (
                        {
                            "code": "FIXTURE_JOB_FAILED",
                            "message": "Explicit failed job fixture",
                            "retryable": False,
                        }
                        if terminal == "FAILED"
                        else None
                    )
                grant = self.grant(client, run)
                self.assertEqual(grant["waiting_jobs"][0]["state"], terminal)
                token = grant["execution_token"]
                read = self.call(client, run, token, "jobs.get", {"job_id": job})
                self.assertEqual(read[2]["data"]["state"], terminal)
                self.settled(client, run, token)
                archive = archive_tests.archive(
                    grant["session_id"],
                    [read],
                    baseline=raw,
                    message=grant["continuation_message"],
                )
                stored = self.put(client, run, token, archive)
                self.assertEqual(stored.status_code, 200, stored.text)
                self.assertEqual(
                    self.publish(
                        client, run, token, stored.json()["checkpoint_id"]
                    ).json()["code"],
                    "JOB_NOT_SUCCEEDED",
                )
                review = client.post(
                    f"/internal/agent/runs/{run}/review",
                    headers={"Authorization": "Bearer " + token},
                    json={"reason": "JOB_NOT_SUCCEEDED"},
                )
                self.assertEqual(review.json()["reason"], "JOB_NOT_SUCCEEDED")
                with Session(self.admin) as db:
                    calls = list(
                        db.scalars(
                            select(AgentInvocation).where(
                                AgentInvocation.run_id == UUID(run),
                                AgentInvocation.tool_name == "uploads.complete",
                            )
                        )
                    )
                    self.assertEqual(len(calls), 1)
                    self.assertIsNone(
                        db.get(
                            AgentSession, UUID(grant["session_id"])
                        ).latest_checkpoint_id
                    )
