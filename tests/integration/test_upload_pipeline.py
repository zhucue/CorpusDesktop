"""Explicit opt-in: real PostgreSQL roles, versioned MinIO and RabbitMQ.

Run with deploy test-auth's service environment and TEST_WORKER_DATABASE_URL.
Fixtures use random accounts/projects, remove only their own rows and versions.
"""

import hashlib
import io
import os
import subprocess
import sys
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch
from uuid import UUID, uuid4

from botocore.exceptions import ClientError
from fastapi import FastAPI
from fastapi.testclient import TestClient
from kombu import Connection, Queue
from sqlalchemy import create_engine, func, select, text

from services.api import jobs, storage, uploads
from services.api.auth import Actor, current_actor
from services.api.db import transaction
from services.api.errors import ApiError, install_error_handlers
from services.api.job_models import Action, Attempt, Job, JobEvent, Outbox, Upload
from services.api.projects import MemberInput, ProjectInput, create_project, set_member
from workers.app import app as celery
from workers.dispatcher import dispatch_once, expire_one_lease
from workers.validation import claim, publish, validate_upload

ENABLED = all(os.getenv(name) for name in ("TEST_OWNER_DATABASE_URL", "TEST_ADMIN_DATABASE_URL",
                                           "TEST_WORKER_DATABASE_URL", "S3_ENDPOINT_URL", "BROKER_URL"))


@unittest.skipUnless(ENABLED, "Explicit real PostgreSQL/MinIO/RabbitMQ test environment required")
class UploadPipelineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.api_url = os.environ["DATABASE_URL"]
        cls.worker_url = os.environ["TEST_WORKER_DATABASE_URL"]
        cls.admin = create_engine(os.environ["TEST_ADMIN_DATABASE_URL"])
        cls.owner_engine = create_engine(os.environ["TEST_OWNER_DATABASE_URL"])
        cls.app = FastAPI()
        install_error_handlers(cls.app)
        cls.app.include_router(uploads.router)
        cls.app.include_router(jobs.router)

    @classmethod
    def tearDownClass(cls):
        cls.admin.dispose()
        cls.owner_engine.dispose()

    def setUp(self):
        self.users = [Actor(uuid4(), f"upload-{uuid4().hex}@example.test", False, "") for _ in range(4)]
        self.owner, self.editor, self.viewer, self.stranger = self.users
        with self.owner_engine.begin() as connection:
            for actor in self.users:
                connection.execute(text("INSERT INTO app.users(id,email,password_hash,is_platform_admin) VALUES(:id,:email,'unused',:admin)"),
                                   {"id": actor.id, "email": actor.email, "admin": actor == self.stranger})
        self.project = create_project(ProjectInput(name="Upload integration"), self.owner)
        set_member(self.project.id, self.editor.id, MemberInput(role="editor"), self.owner)
        set_member(self.project.id, self.viewer.id, MemberInput(role="viewer"), self.owner)
        self.actor = self.owner
        self.app.dependency_overrides[current_actor] = lambda: self.actor
        self.client = TestClient(self.app)

    def tearDown(self):
        self.client.close()
        self.app.dependency_overrides.clear()
        # Include uncommitted-to-ledger object versions using this random project prefix.
        prefix = f"private/{self.project.id}/"
        paginator = storage.client().get_paginator("list_object_versions")
        for page in paginator.paginate(Bucket=storage.bucket(), Prefix=prefix):
            for version in page.get("Versions", []) + page.get("DeleteMarkers", []):
                storage.client().delete_object(Bucket=storage.bucket(), Key=version["Key"], VersionId=version["VersionId"])
        with self.admin.begin() as connection:
            for table in ("job_outbox", "job_events", "job_attempts", "jobs", "job_actions", "upload_sessions", "project_members"):
                connection.execute(text(f"DELETE FROM app.{table} WHERE project_id=:p"), {"p": self.project.id})
            connection.execute(text("DELETE FROM app.projects WHERE id=:p"), {"p": self.project.id})
            for actor in self.users:
                connection.execute(text("DELETE FROM app.users WHERE id=:u"), {"u": actor.id})

    def worker(self):
        return patch.dict(os.environ, {"DATABASE_URL": self.worker_url})

    def create(self, body=b"real private text\n", digest=None, key=None):
        response = self.client.post(f"/api/v1/projects/{self.project.id}/uploads", headers={"Idempotency-Key": key or uuid4().hex},
                                    json={"filename": "private.txt", "size": len(body), "media_type": "text/plain",
                                          "sha256": digest or hashlib.sha256(body).hexdigest()})
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()

    def uploaded(self, body=b"real private text\n", digest=None):
        upload = self.create(body, digest)
        response = self.client.put(upload["upload_url"], content=body)
        self.assertEqual(response.status_code, 200, response.text)
        return upload

    def complete(self, upload, key=None):
        response = self.client.post(f"/api/v1/uploads/{upload['upload_id']}/complete", json={},
                                    headers={"Idempotency-Key": key or uuid4().hex})
        self.assertEqual(response.status_code, 202, response.text)
        return response.json()

    def detail(self, job):
        response = self.client.get(f"/api/v1/jobs/{job['job_id']}")
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def test_real_broker_worker_success_and_refresh(self):
        upload = self.uploaded("真实私有文本\n".encode())
        job = self.complete(upload)
        queue = "corpus.test." + uuid4().hex
        log_path = Path(os.getenv("UPLOAD_TEMP_DIR", "tmp/uploads")) / f"{queue}.log"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        env = {**os.environ, "DATABASE_URL": self.worker_url}
        with log_path.open("w") as log:
            process = subprocess.Popen([sys.executable, "-m", "celery", "-A", "workers.app", "worker", "--pool=solo", "--loglevel=WARNING",
                                        "--without-gossip", "--without-mingle", "--without-heartbeat", "-Q", queue,
                                        "-n", queue + "@%h"], env=env, stdout=log, stderr=subprocess.STDOUT)
            try:
                with self.worker():
                    self.assertTrue(dispatch_once(lambda jid, attempt: celery.send_task("workers.validate_upload", args=[str(jid), attempt], queue=queue, retry=False)))
                deadline = time.monotonic() + 30
                while self.detail(job)["state"] not in jobs.TERMINAL and time.monotonic() < deadline:
                    time.sleep(0.2)
                detail = self.detail(job)
                if detail["state"] != "SUCCEEDED":
                    log.flush()
                    diagnostic = log_path.read_text()[-6000:]
                    for name in ("DATABASE_URL", "TEST_WORKER_DATABASE_URL", "BROKER_URL", "S3_SECRET_ACCESS_KEY"):
                        diagnostic = diagnostic.replace(os.environ.get(name, "nonexistent-secret"), "<redacted>")
                    self.fail(f"worker exit={process.poll()}; {diagnostic}")
                self.assertEqual(detail["state"], "SUCCEEDED", detail)
                self.assertEqual(detail["result"]["state"], "VALIDATED")
                self.assertEqual(detail["result"]["sha256"], upload["sha256"])
                with TestClient(self.app) as fresh:
                    self.assertEqual(fresh.get(f"/api/v1/jobs/{job['job_id']}").json()["result"], detail["result"])
                events = self.client.get(f"/api/v1/jobs/{job['job_id']}/events").json()["items"]
                self.assertEqual([e["sequence"] for e in events], list(range(1, len(events) + 1)))
                self.assertEqual(events[-1]["kind"], "job.succeeded")
            finally:
                process.terminate()
                process.wait(timeout=15)
                with Connection(os.environ["BROKER_URL"]) as connection:
                    Queue(queue, channel=connection.channel()).delete()

    def test_idempotency_and_concurrent_complete(self):
        upload = self.uploaded()
        def complete(index):
            return uploads.complete_upload(UUID(upload["upload_id"]), jobs.EmptyBody(), self.owner, "same-complete")
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(complete, range(2)))
        self.assertEqual(results[0], results[1])
        other = self.uploaded()
        response = self.client.post(f"/api/v1/uploads/{other['upload_id']}/complete", json={}, headers={"Idempotency-Key": "same-complete"})
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["code"], "IDEMPOTENCY_CONFLICT")
        with transaction(self.owner.id) as session:
            self.assertEqual(session.scalar(select(func.count()).select_from(Job).where(Job.project_id == self.project.id)), 1)
            self.assertEqual(session.scalar(select(func.count()).select_from(Outbox).where(Outbox.project_id == self.project.id)), 1)

    def test_duplicate_delivery_and_version_pinning(self):
        body = b"original version"
        upload = self.uploaded(body)
        job = self.complete(upload)
        with transaction(self.owner.id) as session:
            item = session.get(Upload, UUID(upload["upload_id"]))
            object_key, version = item.object_key, item.version_id
        with self.assertRaises(ClientError) as denied:
            storage.put_private(object_key, io.BytesIO(b"replacement"), 11, "text/plain")
        self.assertEqual(denied.exception.response["Error"]["Code"], "PreconditionFailed")
        replacement = storage.client().put_object(Bucket=storage.bucket(), Key=object_key, Body=b"different latest bytes")
        self.assertNotEqual(replacement["VersionId"], version)
        with self.worker():
            self.assertEqual(validate_upload(job["job_id"], 1)["status"], "published")
            self.assertEqual(validate_upload(job["job_id"], 1)["status"], "duplicate_or_ineligible")
        self.assertEqual(self.detail(job)["result"]["sha256"], hashlib.sha256(body).hexdigest())
        with transaction(self.owner.id) as session:
            count = session.scalar(select(func.count()).select_from(JobEvent).where(JobEvent.job_id == UUID(job["job_id"]), JobEvent.kind == "job.succeeded"))
            self.assertEqual(count, 1)
        response = self.client.put(upload["upload_url"], content=body)
        self.assertEqual(response.status_code, 409)

    def test_hash_and_size_failures_are_real_stream_checks(self):
        bad_hash = self.complete(self.uploaded(digest="0" * 64))
        with self.worker():
            validate_upload(bad_hash["job_id"], 1)
        self.assertEqual(self.detail(bad_hash)["error"]["code"], "CHECKSUM_MISMATCH")
        upload = self.create(b"ten bytes!")
        # Corrupt-provider fixture bypasses the HTTP length guard, retaining a real S3 version.
        with transaction(self.owner.id) as session:
            item = session.get(Upload, UUID(upload["upload_id"]))
            item.version_id, item.etag = storage.put_private(item.object_key, io.BytesIO(b"short"), 5, "text/plain")
            item.state = "UPLOADED"
        bad_size = self.complete(upload)
        with self.worker():
            validate_upload(bad_size["job_id"], 1)
        self.assertEqual(self.detail(bad_size)["error"]["code"], "SIZE_MISMATCH")
        self.assertNotIn("retry", self.detail(bad_size)["allowed_actions"])

    def test_cancel_owner_of_editor_job_fences_old_worker(self):
        self.actor = self.editor
        job = self.complete(self.uploaded())
        with self.worker():
            lease = claim(UUID(job["job_id"]), 1)
        self.actor = self.owner
        response = self.client.post(f"/api/v1/jobs/{job['job_id']}/cancel", json={}, headers={"Idempotency-Key": uuid4().hex})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["state"], "CANCELLED")
        with self.worker():
            self.assertFalse(publish(lease, result={"size": 18, "sha256": "0" * 64}))
        self.assertIsNone(self.detail(job)["result"])

    def test_revoked_actor_cannot_publish_or_read_old_action(self):
        self.actor = self.editor
        job = self.complete(self.uploaded())
        with self.worker():
            lease = claim(UUID(job["job_id"]), 1)
        from services.api.projects import remove_member
        remove_member(self.project.id, self.editor.id, self.owner)
        with self.worker():
            self.assertFalse(publish(lease, result={"size": 18, "sha256": "0" * 64}))
        with transaction(self.editor.id) as session:
            self.assertEqual(session.scalar(select(func.count()).select_from(Action).where(Action.project_id == self.project.id)), 0)
        self.actor = self.owner
        self.assertEqual(self.detail(job)["error"]["code"], "AUTHORIZATION_REVOKED")
        self.assertIsNone(self.detail(job)["result"])

    def test_owner_retry_preserves_attempt_and_rejects_old_epoch(self):
        self.actor = self.editor
        job = self.complete(self.uploaded())
        with self.worker():
            old = claim(UUID(job["job_id"]), 1)
            publish(old, error={"code": "STORAGE_UNAVAILABLE", "message": "injected unavailable", "retryable": True})
        self.actor = self.owner
        response = self.client.post(f"/api/v1/jobs/{job['job_id']}/retry", json={}, headers={"Idempotency-Key": "retry-one"})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["attempt"], 2)
        with self.worker():
            self.assertFalse(publish(old, result={"size": 18, "sha256": "0" * 64}))
            self.assertEqual(validate_upload(job["job_id"], 2)["status"], "published")
        with transaction(self.owner.id) as session:
            self.assertEqual(session.get(Attempt, (UUID(job["job_id"]), 1)).state, "FAILED")
            self.assertEqual(session.get(Attempt, (UUID(job["job_id"]), 2)).state, "SUCCEEDED")

    def test_expired_lease_and_bounded_manual_retry(self):
        job = self.complete(self.uploaded())
        for attempt in range(1, 4):
            with self.worker():
                lease = claim(UUID(job["job_id"]), attempt)
                with transaction(None) as session:
                    item = session.get(Job, UUID(job["job_id"]))
                    item.lease_expires_at = jobs.now() - timedelta(seconds=1)
                expire_one_lease()
                self.assertFalse(publish(lease, result={"size": 18, "sha256": "0" * 64}))
            detail = self.detail(job)
            self.assertEqual(detail["state"], "FAILED")
            self.assertEqual(detail["error"]["code"], "WORKER_LEASE_EXPIRED")
            response = self.client.post(f"/api/v1/jobs/{job['job_id']}/retry", json={}, headers={"Idempotency-Key": f"retry-{attempt}"})
            self.assertEqual(response.status_code, 200 if attempt < 3 else 409, response.text)
        self.assertEqual(self.detail(job)["attempt"], 3)
        self.assertNotIn("retry", self.detail(job)["allowed_actions"])

    def test_broker_failure_retains_outbox_then_real_recovery(self):
        job = self.complete(self.uploaded())
        def broken(jid, attempt):
            with Connection("amqp://guest:guest@127.0.0.1:1//", connect_timeout=1) as connection:
                connection.ensure_connection(max_retries=0)
        with self.worker():
            self.assertFalse(dispatch_once(broken))
            with transaction(None) as session:
                outbox = session.scalar(select(Outbox).where(Outbox.job_id == UUID(job["job_id"])))
                self.assertIsNone(outbox.published_at)
                self.assertEqual(outbox.failures, 1)
                outbox.next_attempt_at = jobs.now() - timedelta(seconds=1)
        queue_name = "corpus.test." + uuid4().hex
        with Connection(os.environ["BROKER_URL"], transport_options={"confirm_publish": True}) as connection:
            queue = Queue(queue_name, channel=connection.channel(), durable=False, auto_delete=True, exclusive=True)
            queue.declare()
            try:
                def real(jid, attempt):
                    connection.Producer().publish({"job_id": str(jid), "attempt": attempt}, exchange="", routing_key=queue_name, serializer="json", retry=False)
                with self.worker():
                    self.assertTrue(dispatch_once(real))
                message = queue.get(no_ack=False)
                self.assertEqual(message.payload["job_id"], job["job_id"])
                message.ack()
            finally:
                queue.delete()

    def test_access_quota_expiry_and_cursor(self):
        upload = self.create()
        for actor in (self.viewer, self.stranger):
            self.actor = actor
            response = self.client.post(f"/api/v1/projects/{self.project.id}/uploads", json={"filename": "a.txt", "size": 1,
                "sha256": "0" * 64, "media_type": "text/plain"}, headers={"Idempotency-Key": uuid4().hex})
            self.assertIn(response.status_code, (403, 404))
        self.assertEqual(self.client.get(f"/api/v1/uploads/{upload['upload_id']}").status_code, 404)
        self.actor = self.owner
        with patch.object(uploads, "PROJECT_QUOTA", 1):
            with self.assertRaises(ApiError) as caught:
                uploads.create_upload(self.project.id, uploads.CreateUpload(filename="x", size=1, media_type="text/plain", sha256="0" * 64), self.owner, uuid4().hex)
            self.assertEqual(caught.exception.code, "PROJECT_UPLOAD_QUOTA_EXCEEDED")
        with transaction(self.owner.id) as session:
            item = session.get(Upload, UUID(upload["upload_id"]))
            item.created_at = jobs.now() - timedelta(hours=2)
            item.expires_at = jobs.now() - timedelta(hours=1)
        self.assertEqual(self.client.put(upload["upload_url"], content=b"real private text\n").status_code, 410)
        expected = {self.complete(self.uploaded())["job_id"] for _ in range(3)}
        seen, cursor = set(), None
        for _ in range(3):
            params = {"page_size": 1, **({"cursor": cursor} if cursor else {})}
            response = self.client.get(f"/api/v1/projects/{self.project.id}/jobs", params=params).json()
            seen.update(item["job_id"] for item in response["items"])
            cursor = response["next_cursor"]
        self.assertEqual(seen, expected)
        self.assertIsNone(cursor)


if __name__ == "__main__":
    unittest.main()
