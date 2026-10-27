"""Actual PostgreSQL host protocol. Uploaded-row fixtures are not S3 validation."""

import multiprocessing
import os
import secrets
import time
import unittest
from datetime import timedelta
from unittest.mock import patch
from uuid import UUID, uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, delete, func, select, text, update
from sqlalchemy.orm import Session

from services.api import agent_control as control
from services.api import agent_internal, agent_routes, auth, projects
from services.api.agent_models import (
    AgentCheckpoint,
    AgentCredential,
    AgentEvent,
    AgentInvocation,
    AgentRun,
    AgentSession,
)
from services.api.db import bound_transaction, transaction
from services.api.errors import ApiError, install_error_handlers
from services.api.job_models import Action, Attempt, Job, JobEvent, Outbox, Upload
from services.api.models import Project, User


def process_claim(run_id, ready, start, results):
    ready.put(os.getpid())
    start.wait(10)
    try:
        result = control.claim(UUID(run_id), uuid4())
        results.put({"ok": True, "epoch": result["lease_epoch"], "pid": os.getpid()})
    except ApiError as exc:
        results.put({"ok": False, "code": exc.code, "pid": os.getpid()})


@unittest.skipUnless(
    os.getenv("TEST_ADMIN_DATABASE_URL") and os.getenv("TEST_OWNER_DATABASE_URL"),
    "Dedicated real PostgreSQL environment required",
)
class AgentRuntimeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.admin = create_engine(
            os.environ["TEST_ADMIN_DATABASE_URL"], hide_parameters=True
        )
        cls.owner = create_engine(
            os.environ["TEST_OWNER_DATABASE_URL"], hide_parameters=True
        )
        cls.password = secrets.token_urlsafe(24)
        cls.users = {}
        with Session(cls.owner) as db, db.begin():
            for role in ("owner", "editor", "viewer", "admin"):
                row = User(
                    id=uuid4(),
                    email=f"agent-{uuid4().hex}@example.test",
                    password_hash=auth.HASHER.hash(cls.password),
                    is_active=True,
                    is_platform_admin=role == "admin",
                )
                db.add(row)
                cls.users[role] = {"id": row.id, "email": row.email}
        cls.app = FastAPI()
        install_error_handlers(cls.app)
        for router in (
            auth.router,
            projects.router,
            agent_routes.router,
            agent_internal.router,
        ):
            cls.app.include_router(router)

    @classmethod
    def tearDownClass(cls):
        ids = [entry["id"] for entry in cls.users.values()]
        with Session(cls.admin) as db, db.begin():
            db.execute(
                update(AgentSession)
                .where(AgentSession.actor_id.in_(ids))
                .values(active_run_id=None, latest_checkpoint_id=None)
            )
            db.execute(
                update(AgentRun)
                .where(AgentRun.actor_id.in_(ids))
                .values(
                    base_checkpoint_id=None,
                    final_checkpoint_id=None,
                    resume_checkpoint_id=None,
                )
            )
            # Checkpoints can refer to earlier checkpoints, so remove newest first.
            checkpoints = list(
                db.scalars(
                    select(AgentCheckpoint)
                    .where(AgentCheckpoint.actor_id.in_(ids))
                    .order_by(AgentCheckpoint.created_at.desc())
                )
            )
            for checkpoint in checkpoints:
                db.delete(checkpoint)
                db.flush()
            for model in (
                AgentEvent,
                AgentInvocation,
                AgentCredential,
                AgentRun,
                AgentSession,
            ):
                db.execute(delete(model).where(model.actor_id.in_(ids)))
            project_ids = select(Project.id).where(Project.owner_id.in_(ids))
            for model in (Outbox, JobEvent, Attempt, Job, Action, Upload):
                db.execute(delete(model).where(model.project_id.in_(project_ids)))
            db.execute(delete(Project).where(Project.owner_id.in_(ids)))
            db.execute(delete(User).where(User.id.in_(ids)))
        cls.owner.dispose()
        cls.admin.dispose()

    def setUp(self):
        auth._attempts.clear()
        self.clients = []
        self.host_key = secrets.token_urlsafe(40)
        self.env = patch.dict(
            os.environ,
            {"AGENT_HOST_KEY": self.host_key, "AGENT_RUNTIME_MODE": "fixture"},
        )
        self.env.start()

    def tearDown(self):
        for client in self.clients:
            client.close()
        self.env.stop()

    def login(self, role="owner"):
        client = TestClient(self.app, base_url=os.environ["PUBLIC_ORIGIN"])
        self.clients.append(client)
        result = client.post(
            "/api/v1/auth/login",
            headers={"Origin": os.environ["PUBLIC_ORIGIN"]},
            json={"email": self.users[role]["email"], "password": self.password},
        )
        self.assertEqual(result.status_code, 200, result.text)
        client.headers.update(
            {
                "Origin": os.environ["PUBLIC_ORIGIN"],
                "X-CSRF-Token": result.json()["csrf_token"],
            }
        )
        return client

    def project(self, client, members=()):
        result = client.post(
            "/api/v1/projects", json={"name": "agent fixture " + uuid4().hex}
        )
        self.assertEqual(result.status_code, 201, result.text)
        pid = result.json()["id"]
        for role in members:
            response = client.put(
                f"/api/v1/projects/{pid}/members/{self.users[role]['id']}",
                json={"role": role},
            )
            self.assertEqual(response.status_code, 200, response.text)
        return pid

    def session(self, client, scope=None):
        result = client.post(
            "/api/v1/agent/sessions", json={"scope": scope or {"scope_kind": "account"}}
        )
        self.assertEqual(result.status_code, 201, result.text)
        return result.json()["session_id"]

    def start_run(self, client, sid):
        result = client.post(
            f"/api/v1/agent/sessions/{sid}/runs",
            json={
                "request_key": str(uuid4()),
                "message": "Fixture request",
                "scope_digest": client.get(f"/api/v1/agent/sessions/{sid}").json()[
                    "scope_digest"
                ],
            },
        )
        self.assertEqual(result.status_code, 201, result.text)
        return result.json()["run_id"]

    def claim(self, client, run):
        result = client.post(
            f"/internal/agent/runs/{run}/claim",
            json={"host_id": str(uuid4())},
            headers={"Authorization": "Bearer " + self.host_key},
        )
        self.assertEqual(result.status_code, 200, result.text)
        return result.json()["execution_token"]

    def invoke(self, client, run, token, tool, args=None, key=None):
        return client.post(
            f"/internal/agent/runs/{run}/invocations",
            headers={"Authorization": "Bearer " + token},
            json={
                "request_key": key or str(uuid4()),
                "tool_call_id": "sdk-call-metadata",
                "tool_name": tool,
                "arguments": args or {},
            },
        )

    def test_fixed_scope_and_hash_only_credentials(self):
        client = self.login()
        pid = self.project(client)
        self.assertEqual(
            client.post(
                "/api/v1/agent/sessions",
                json={
                    "scope": {
                        "scope_kind": "project",
                        "project_id": pid,
                        "snapshot_ids": ["unknown"],
                    }
                },
            ).status_code,
            422,
        )
        self.assertEqual(
            client.post(
                "/api/v1/agent/sessions",
                json={
                    "scope": {
                        "scope_kind": "account",
                        "actor_id": str(self.users["admin"]["id"]),
                    }
                },
            ).status_code,
            422,
        )
        admin = self.login("admin")
        self.assertEqual(
            admin.post(
                "/api/v1/agent/sessions",
                json={"scope": {"scope_kind": "project", "project_id": pid}},
            ).status_code,
            404,
        )
        sid = self.session(client)
        run = self.start_run(client, sid)
        self.assertEqual(
            client.post(
                f"/internal/agent/runs/{run}/claim", json={"host_id": str(uuid4())}
            ).status_code,
            401,
        )
        token = self.claim(client, run)
        with Session(self.admin) as db:
            row = db.get(AgentCredential, auth.token_hash(token))
            self.assertEqual(row.run_id, UUID(run))
            self.assertNotEqual(row.token_hash, token)
        events = client.get(f"/api/v1/agent/runs/{run}/events").text
        self.assertNotIn(token, events)
        self.assertNotIn(self.host_key, events)
        result = self.invoke(
            client,
            run,
            token,
            "account.get",
            {"actor_id": str(self.users["admin"]["id"])},
        )
        self.assertEqual(result.json()["result"]["error"]["code"], "INVALID_TOOL_INPUT")

    def test_two_processes_single_writer_and_new_epoch(self):
        client = self.login()
        sid = self.session(client)
        run = self.start_run(client, sid)
        ctx = multiprocessing.get_context("spawn")
        ready, results, start = ctx.Queue(), ctx.Queue(), ctx.Event()
        children = [
            ctx.Process(target=process_claim, args=(run, ready, start, results))
            for _ in range(2)
        ]
        try:
            for child in children:
                child.start()
            pids = {ready.get(timeout=20), ready.get(timeout=20)}
            self.assertEqual(len(pids), 2)
            start.set()
            outcomes = [results.get(timeout=20), results.get(timeout=20)]
            self.assertEqual(sum(row["ok"] for row in outcomes), 1)
            self.assertEqual(
                [row["code"] for row in outcomes if not row["ok"]], ["SESSION_BUSY"]
            )
        finally:
            for child in children:
                child.join(20)
                if child.is_alive():
                    child.terminate()
                    child.join()
            ready.close()
            results.close()
        self.assertEqual(
            client.post(
                f"/api/v1/agent/sessions/{sid}/runs",
                json={
                    "request_key": str(uuid4()),
                    "message": "Fixture request",
                    "scope_digest": client.get(f"/api/v1/agent/sessions/{sid}").json()[
                        "scope_digest"
                    ],
                },
            ).status_code,
            409,
        )
        client.post(f"/api/v1/agent/runs/{run}/cancel", json={})
        next_run = self.start_run(client, sid)
        self.claim(client, next_run)
        self.assertGreater(
            client.get(f"/api/v1/agent/runs/{next_run}").json()["lease_epoch"], 1
        )

    def test_response_loss_replays_one_actual_project_and_action(self):
        client = self.login()
        run = self.start_run(client, self.session(client))
        token = self.claim(client, run)
        key, name = str(uuid4()), "single write " + uuid4().hex
        first = self.invoke(client, run, token, "projects.create", {"name": name}, key)
        second = self.invoke(client, run, token, "projects.create", {"name": name}, key)
        self.assertEqual(first.json(), second.json())
        result = first.json()["result"]
        self.assertEqual(result["scope_effect"]["kind"], "produces_scope")
        self.assertEqual(
            self.invoke(
                client, run, token, "projects.create", {"name": "different"}, key
            ).status_code,
            409,
        )
        with transaction(self.users["owner"]["id"]) as db:
            self.assertEqual(
                db.scalar(
                    select(func.count())
                    .select_from(Project)
                    .where(Project.name == name)
                ),
                1,
            )
            row = db.get(AgentInvocation, UUID(result["invocation_id"]))
            self.assertEqual(str(row.action_id), result["action_id"])
        reconciled = client.get(
            f"/internal/agent/runs/{run}/invocations/{result['invocation_id']}",
            headers={"Authorization": "Bearer " + token},
        )
        self.assertEqual(reconciled.json(), first.json())

    def test_savepoint_sql_error_is_recorded_and_next_call_works(self):
        client = self.login()
        run = self.start_run(client, self.session(client))
        token = self.claim(client, run)
        name = "rollback " + uuid4().hex

        def broken(db, actor, *args):
            db.add(Project(name=name, owner_id=actor.id))
            db.flush()
            db.execute(text("SELECT 1/0"))

        with patch.object(control, "dispatch", side_effect=broken):
            result = self.invoke(client, run, token, "projects.create", {"name": name})
        self.assertEqual(
            result.json()["result"]["error"]["code"], "BUSINESS_TRANSACTION_FAILED"
        )
        self.assertEqual(
            self.invoke(client, run, token, "account.get").json()["result"]["status"],
            "succeeded",
        )
        with transaction(self.users["owner"]["id"]) as db:
            self.assertEqual(
                db.scalar(
                    select(func.count())
                    .select_from(Project)
                    .where(Project.name == name)
                ),
                0,
            )

    def test_bound_transaction_actor_and_context_cleanup(self):
        aid, other = self.users["owner"]["id"], self.users["editor"]["id"]
        with transaction(aid) as db:
            with (
                self.assertRaisesRegex(RuntimeError, "database identity"),
                bound_transaction(other, db),
            ):
                pass
            with (
                self.assertRaisesRegex(ValueError, "fixture"),
                bound_transaction(aid, db),
            ):
                with transaction(aid) as nested:
                    self.assertIs(nested, db)
                with (
                    self.assertRaisesRegex(RuntimeError, "actor mismatch"),
                    transaction(other),
                ):
                    pass
                raise ValueError("fixture")
        with transaction(other) as db:
            self.assertEqual(db.scalar(text("SELECT app.actor_id()")), other)
        with transaction() as db:
            self.assertIsNone(db.scalar(text("SELECT app.actor_id()")))

    def test_expiry_during_business_call_rolls_back_and_requires_review(self):
        client = self.login()
        run = self.start_run(client, self.session(client))
        token = self.claim(client, run)
        name = "expired write " + uuid4().hex
        with Session(self.admin) as db, db.begin():
            db.get(AgentRun, UUID(run)).lease_expires_at = control.now() + timedelta(
                milliseconds=200
            )
        dispatch = control.dispatch

        def delayed(*args):
            value = dispatch(*args)
            time.sleep(0.3)
            return value

        with patch.object(control, "dispatch", side_effect=delayed):
            response = self.invoke(
                client, run, token, "projects.create", {"name": name}
            )
        self.assertEqual(response.status_code, 401)
        with Session(self.admin) as db:
            self.assertEqual(
                db.scalar(
                    select(func.count())
                    .select_from(Project)
                    .where(Project.name == name)
                ),
                0,
            )
            self.assertEqual(
                db.scalar(
                    select(func.count())
                    .select_from(AgentInvocation)
                    .where(AgentInvocation.run_id == UUID(run))
                ),
                0,
            )
        self.assertEqual(
            client.get(f"/api/v1/agent/runs/{run}").json()["state"], "WAITING_REVIEW"
        )
        self.assertEqual(
            self.invoke(client, run, token, "account.get").status_code, 401
        )

    def test_revocation_viewer_and_platform_admin_are_rechecked(self):
        owner, editor, viewer, admin = (
            self.login(),
            self.login("editor"),
            self.login("viewer"),
            self.login("admin"),
        )
        pid = self.project(owner, ("editor", "viewer"))
        run = self.start_run(
            editor, self.session(editor, {"scope_kind": "project", "project_id": pid})
        )
        token = self.claim(editor, run)
        other = self.project(owner)
        self.assertEqual(
            self.invoke(
                editor, run, token, "projects.get", {"project_id": other}
            ).json()["result"]["error"]["code"],
            "INVALID_TOOL_INPUT",
        )
        vr = self.start_run(
            viewer, self.session(viewer, {"scope_kind": "project", "project_id": pid})
        )
        vt = self.claim(viewer, vr)
        self.assertEqual(self.invoke(viewer, vr, vt, "jobs.list").status_code, 200)
        self.assertEqual(self.invoke(viewer, vr, vt, "uploads.create").status_code, 403)
        owner.delete(f"/api/v1/projects/{pid}/members/{self.users['editor']['id']}")
        self.assertEqual(
            self.invoke(editor, run, token, "projects.get").status_code, 404
        )
        with transaction(self.users["editor"]["id"]) as db:
            self.assertIsNone(db.get(AgentRun, UUID(run)))
        ar = self.start_run(admin, self.session(admin, {"scope_kind": "platform"}))
        at = self.claim(admin, ar)
        try:
            with Session(self.admin) as db, db.begin():
                db.get(User, self.users["admin"]["id"]).is_platform_admin = False
            self.assertEqual(
                self.invoke(admin, ar, at, "sources.list").status_code, 404
            )
        finally:
            with Session(self.admin) as db, db.begin():
                db.get(User, self.users["admin"]["id"]).is_platform_admin = True

    def create_job_fixture(self, client, run, token):
        result = self.invoke(
            client,
            run,
            token,
            "uploads.create",
            {
                "filename": "agent-database-fixture.txt",
                "size": 1,
                "sha256": "a" * 64,
                "media_type": "text/plain",
            },
        ).json()
        self.assertEqual(result["data"]["next_action"], "browser_file_transfer")
        self.assertNotIn("upload_url", result["data"])
        uid = UUID(result["data"]["upload_id"])
        with Session(self.admin) as db, db.begin():
            row = db.get(Upload, uid)
            # Explicit database-only fixture; no S3 object or real validation claim.
            row.state, row.version_id, row.etag = (
                "UPLOADED",
                "agent-test-fixture",
                "fixture",
            )
        result = self.invoke(
            client, run, token, "uploads.complete", {"upload_id": str(uid)}
        ).json()
        self.assertEqual(result["result"]["status"], "accepted")
        with Session(self.admin) as db:
            job = db.get(Job, UUID(result["result"]["job_id"]))
            self.assertEqual(str(job.action_id), result["result"]["action_id"])
        return result["result"]["job_id"]

    def test_cancel_two_exclusive_jobs_and_old_token(self):
        client = self.login()
        pid = self.project(client)
        run = self.start_run(
            client, self.session(client, {"scope_kind": "project", "project_id": pid})
        )
        token = self.claim(client, run)
        jobs = [self.create_job_fixture(client, run, token) for _ in range(2)]
        response = client.post(f"/api/v1/agent/runs/{run}/cancel", json={})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["state"], "CANCELLED")
        with Session(self.admin) as db:
            self.assertEqual(
                [db.get(Job, UUID(j)).state for j in jobs], ["CANCELLED", "CANCELLED"]
            )
        self.assertEqual(
            self.invoke(client, run, token, "account.get").status_code, 401
        )

    def test_downgraded_actor_can_cancel_run_without_impersonating_owner(self):
        owner, editor = self.login(), self.login("editor")
        pid = self.project(owner, ("editor",))
        run = self.start_run(
            editor, self.session(editor, {"scope_kind": "project", "project_id": pid})
        )
        token = self.claim(editor, run)
        job = self.create_job_fixture(editor, run, token)
        owner.put(
            f"/api/v1/projects/{pid}/members/{self.users['editor']['id']}",
            json={"role": "viewer"},
        )
        response = editor.post(f"/api/v1/agent/runs/{run}/cancel", json={})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["state"], "CANCELLED")
        with Session(self.admin) as db:
            self.assertEqual(db.get(Job, UUID(job)).state, "QUEUED")
        self.assertEqual(
            self.invoke(editor, run, token, "account.get").status_code, 401
        )
        events = editor.get(f"/api/v1/agent/runs/{run}/events")
        self.assertEqual(events.status_code, 409, events.text)
        self.assertEqual(events.json()["code"], "CHECKPOINT_AUTH_CHANGED")
        with Session(self.admin) as db:
            kinds = list(
                db.scalars(select(AgentEvent.kind).where(AgentEvent.run_id == UUID(run)))
            )
        self.assertIn("job.cancel_not_applied", kinds)

    def test_settled_without_checkpoint_is_review_and_events_are_idempotent(self):
        client = self.login()
        run = self.start_run(client, self.session(client))
        token = self.claim(client, run)
        headers = {"Authorization": "Bearer " + token}
        self.assertEqual(
            client.post(
                f"/internal/agent/runs/{run}/settle", headers=headers, json={}
            ).status_code,
            409,
        )
        event_id = str(uuid4())
        body = {"event_id": event_id, "kind": "sdk.agent_settled"}
        first = client.post(
            f"/internal/agent/runs/{run}/events", headers=headers, json=body
        )
        self.assertEqual(
            first.json(),
            client.post(
                f"/internal/agent/runs/{run}/events", headers=headers, json=body
            ).json(),
        )
        response = client.post(
            f"/internal/agent/runs/{run}/settle", headers=headers, json={}
        )
        self.assertEqual(response.json()["state"], "WAITING_REVIEW")
        self.assertEqual(response.json()["reason"], "CHECKPOINT_NOT_IMPLEMENTED")
        events = client.get(f"/api/v1/agent/runs/{run}/events").json()["items"]
        self.assertEqual(
            [event["sequence"] for event in events], list(range(1, len(events) + 1))
        )
        self.assertEqual(
            self.invoke(client, run, token, "account.get").status_code, 401
        )
