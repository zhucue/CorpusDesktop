"""Model identity tests: no requests to a real provider, no external credentials.

Integration cases use real PG/private S3 with explicitly synthetic Pi JSONL.
The separate Node protocol suite exercises actual SDK transport against loopback.
"""

import copy
import json
import os
import unittest
from unittest.mock import patch
from uuid import UUID, uuid4

from sqlalchemy.orm import Session

from services.api import agent_checkpoints as checkpoints
from services.api import agent_config
from services.api.errors import ApiError
from services.api.job_models import Upload
from tests.api import test_agent_checkpoints as archives
from tests.api import test_agent_runtime as runtime

MODEL_ENV = {
    "AGENT_RUNTIME_MODE": "openai-compatible",
    "AGENT_MODEL_API": "openai-completions",
    "AGENT_MODEL_BASE_URL": "https://model.example.test/v1",
    "AGENT_MODEL_ID": "research-model-v1",
    "AGENT_MODEL_CONTEXT_WINDOW": "8192",
    "AGENT_MODEL_MAX_OUTPUT_TOKENS": "1024",
    "AGENT_MODEL_REQUEST_TIMEOUT_MS": "60000",
    "AGENT_MODEL_ALLOW_LOOPBACK_HTTP": "false",
}
VECTOR_SHA = "756090785086b08af0069d1cd1165498755ea3895d54c4a0ffb9c8e61fc61b3d"


def provider_archive(session_id, manifest, calls=()):
    rows = [
        json.loads(line) for line in archives.archive(session_id, calls).splitlines()
    ]
    for row in rows:
        if row["type"] == "model_change":
            row.update(provider=manifest["provider"], modelId=manifest["model"])
        message = row.get("message", {})
        if message.get("role") == "assistant":
            message.update(
                provider=manifest["provider"],
                model=manifest["model"],
                api=manifest["model_api"],
            )
    return "\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n"


class ProviderConfigurationTests(unittest.TestCase):
    def test_shared_digest_and_no_credential_identity(self):
        with patch.dict(os.environ, MODEL_ENV, clear=True):
            view = agent_config.runtime_view()
            self.assertTrue(view["can_submit"])
            self.assertFalse(view["production_ready"])
            self.assertFalse(view["fixture_enabled"])
            self.assertEqual(view["config_id"], "openai-" + VECTOR_SHA[:48])
            self.assertEqual(
                view["runtime_manifest"]["model_config_sha256"], VECTOR_SHA
            )
            with patch.dict(
                os.environ, {"AGENT_MODEL_API_KEY": "test-secret-not-a-real-key"}
            ):
                self.assertEqual(agent_config.runtime_view(), view)
            with patch.dict(
                os.environ,
                {
                    "AGENT_MODEL_BASE_URL": " https://model.example.test/v1/// ",
                    "AGENT_MODEL_ID": " research-model-v1 ",
                },
            ):
                self.assertEqual(agent_config.runtime_view(), view)
            for key, value in (
                ("AGENT_MODEL_API", "openai-responses"),
                ("AGENT_MODEL_BASE_URL", "https://other.example.test/v1"),
                ("AGENT_MODEL_ID", "different-model"),
                ("AGENT_MODEL_MAX_OUTPUT_TOKENS", "512"),
            ):
                with self.subTest(key=key), patch.dict(os.environ, {key: value}):
                    self.assertNotEqual(
                        agent_config.runtime_view()["config_id"], view["config_id"]
                    )

    def test_missing_and_invalid_configuration_is_safe(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(
                agent_config.runtime_view()["reason"], "MODEL_NOT_CONFIGURED"
            )
        invalid = [
            ("AGENT_MODEL_API", ""),
            ("AGENT_MODEL_ID", ""),
            ("AGENT_MODEL_ID", "模型"),
            ("AGENT_MODEL_ID", "\u001cresearch-model-v1"),
            ("AGENT_MODEL_API", "arbitrary"),
            ("AGENT_MODEL_BASE_URL", "https://user:secret@model.example.test/v1"),
            ("AGENT_MODEL_BASE_URL", "https://@model.example.test/v1"),
            ("AGENT_MODEL_BASE_URL", "https:model.example.test/v1"),
            ("AGENT_MODEL_BASE_URL", "\u0085https://model.example.test/v1"),
            ("AGENT_MODEL_BASE_URL", "https://model.example.test/v1?key=secret"),
            ("AGENT_MODEL_BASE_URL", "https://model.example.test/#"),
            ("AGENT_MODEL_BASE_URL", "https://model.example.test\\x"),
            ("AGENT_MODEL_BASE_URL", "https://model.example.test/a b"),
            ("AGENT_MODEL_BASE_URL", "http://127.0.0.1:9000/v1"),
            ("AGENT_MODEL_CONTEXT_WINDOW", "1023"),
            ("AGENT_MODEL_CONTEXT_WINDOW", "1048577"),
            ("AGENT_MODEL_MAX_OUTPUT_TOKENS", "8193"),
            ("AGENT_MODEL_REQUEST_TIMEOUT_MS", "120001"),
            ("AGENT_MODEL_REQUEST_TIMEOUT_MS", "1e4"),
            ("AGENT_MODEL_REQUEST_TIMEOUT_MS", " 60000"),
            ("AGENT_MODEL_ALLOW_LOOPBACK_HTTP", "yes"),
        ]
        for key, value in invalid:
            with (
                self.subTest(key=key, value=value),
                patch.dict(os.environ, {**MODEL_ENV, key: value}, clear=True),
            ):
                view = agent_config.runtime_view()
                self.assertEqual(view["reason"], "MODEL_CONFIGURATION_INVALID")
                self.assertFalse(view["can_submit"])
                self.assertIsNone(view["runtime_manifest"])
                self.assertIsNone(view["config_id"])
                with self.assertRaises(ApiError) as error:
                    agent_config.require_runtime()
                self.assertEqual(error.exception.code, "AGENT_RUNTIME_UNAVAILABLE")
                self.assertNotIn("secret", error.exception.message)
        with patch.dict(
            os.environ,
            {
                **MODEL_ENV,
                "AGENT_MODEL_BASE_URL": "http://127.0.0.1:9000/v1",
                "AGENT_MODEL_ALLOW_LOOPBACK_HTTP": "true",
            },
            clear=True,
        ):
            self.assertTrue(agent_config.runtime_view()["can_submit"])
            with patch.dict(
                os.environ, {"AGENT_MODEL_BASE_URL": "http://192.0.2.1/v1"}
            ):
                self.assertFalse(agent_config.runtime_view()["can_submit"])
            for url in (
                "http:127.0.0.1",
                "http://127.0.0.2/v1",
                "http://127.1/v1",
                "http://2130706433/v1",
                "http://[0:0:0:0:0:0:0:1]/v1",
                "http://@localhost/v1",
            ):
                with (
                    self.subTest(url=url),
                    patch.dict(os.environ, {"AGENT_MODEL_BASE_URL": url}),
                ):
                    self.assertFalse(agent_config.runtime_view()["can_submit"])
            for url in ("http://localhost:9000/v1", "http://[::1]:9000/v1"):
                with (
                    self.subTest(url=url),
                    patch.dict(os.environ, {"AGENT_MODEL_BASE_URL": url}),
                ):
                    self.assertTrue(agent_config.runtime_view()["can_submit"])

    def test_archive_model_protocol_and_terminal_errors(self):
        with patch.dict(os.environ, MODEL_ENV, clear=True):
            manifest = agent_config.require_runtime()
        raw = provider_archive(str(uuid4()), manifest)
        # Historical parsing remains valid after current configuration is removed.
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(len(checkpoints.parsed(raw.encode(), manifest)), 4)
        with self.assertRaises(ApiError):
            checkpoints.parsed(raw.encode())
        fixture = archives.archive(str(uuid4())).encode()
        with self.assertRaises(ApiError):
            checkpoints.parsed(fixture, manifest)
        for key, value in (
            ("api", "openai-responses"),
            ("model", "other"),
            ("provider", "other"),
            ("stopReason", "error"),
            ("stopReason", "aborted"),
            ("stopReason", "length"),
        ):
            candidate = [json.loads(line) for line in raw.splitlines()]
            candidate[-1]["message"][key] = value
            with self.subTest(key=key, value=value), self.assertRaises(ApiError):
                checkpoints.parsed(
                    "\n".join(json.dumps(r) for r in candidate).encode(), manifest
                )

    def test_fixture_manifest_and_archive_identity_are_fixed(self):
        with patch.dict(os.environ, {"AGENT_RUNTIME_MODE": "fixture"}, clear=True):
            self.assertEqual(
                agent_config.require_runtime(), checkpoints.RUNTIME_MANIFEST
            )
            self.assertEqual(len(agent_config.require_runtime()), 8)
            with self.assertRaises(ApiError):
                agent_config.require_runtime("openai-" + VECTOR_SHA[:48])
        invalid = copy.deepcopy(checkpoints.RUNTIME_MANIFEST)
        invalid["host_policy"] = "unknown-policy"
        with self.assertRaises(ValueError):
            agent_config.manifest_config_id(invalid)


@unittest.skipUnless(
    os.getenv("TEST_ADMIN_DATABASE_URL") and os.getenv("S3_ENDPOINT_URL"),
    "Dedicated real PostgreSQL/versioned S3 required",
)
class AgentProviderTests(unittest.TestCase):
    setUpClass = classmethod(runtime.AgentRuntimeTests.setUpClass.__func__)
    tearDownClass = classmethod(runtime.AgentRuntimeTests.tearDownClass.__func__)
    setUp = archives.AgentCheckpointTests.setUp
    tearDown = archives.AgentCheckpointTests.tearDown
    login = runtime.AgentRuntimeTests.login
    project = runtime.AgentRuntimeTests.project
    session = runtime.AgentRuntimeTests.session
    start_run = runtime.AgentRuntimeTests.start_run
    claim = runtime.AgentRuntimeTests.claim
    call = archives.AgentCheckpointTests.call
    settled = archives.AgentCheckpointTests.settled
    publish = archives.AgentCheckpointTests.publish
    put = archives.AgentCheckpointTests.put
    make_completed = archives.AgentCheckpointTests.make_completed

    def put_provider(self, client, run, token, raw, manifest):
        return client.post(
            f"/internal/agent/runs/{run}/checkpoint",
            headers={"Authorization": "Bearer " + token},
            json={
                "request_key": str(uuid4()),
                "base_checkpoint_id": None,
                "runtime_manifest": manifest,
                "session_jsonl": raw,
            },
        )

    def test_config_rotation_fences_execution_but_keeps_authorized_history(self):
        client = self.login()
        with patch.dict(os.environ, MODEL_ENV):
            sid = self.session(client)
            run = self.start_run(client, sid)
            token = self.claim(client, run)
            manifest = agent_config.require_runtime()
            self.settled(client, run, token)
            archive = provider_archive(sid, manifest)
            self.assertEqual(
                self.put(client, run, token, archive).json()["code"],
                "CHECKPOINT_RUNTIME_MISMATCH",
            )
            saved = self.put_provider(client, run, token, archive, manifest)
            self.assertEqual(saved.status_code, 200, saved.text)
            self.assertEqual(
                self.publish(client, run, token, saved.json()["checkpoint_id"]).json()[
                    "state"
                ],
                "SUCCEEDED",
            )
            queued = self.start_run(client, sid)
            for key, value in (
                ("AGENT_MODEL_API", "openai-responses"),
                ("AGENT_MODEL_BASE_URL", "https://another.example.test/v1"),
                ("AGENT_MODEL_ID", "different"),
            ):
                with self.subTest(key=key), patch.dict(os.environ, {key: value}):
                    denied = client.post(
                        f"/internal/agent/runs/{queued}/claim",
                        headers={"Authorization": "Bearer " + self.host_key},
                        json={"host_id": str(uuid4())},
                    )
                    self.assertEqual(denied.json()["code"], "AGENT_RUNTIME_UNAVAILABLE")
                    history = client.get(f"/api/v1/agent/sessions/{sid}/messages")
                    self.assertEqual(history.status_code, 200, history.text)
        # Old queued run can be cancelled using browser identity after config changes.
        client.post(f"/api/v1/agent/runs/{queued}/cancel", json={})
        response = client.post(
            f"/api/v1/agent/sessions/{sid}/runs",
            json={
                "request_key": str(uuid4()),
                "message": "new",
                "scope_digest": client.get(f"/api/v1/agent/sessions/{sid}").json()[
                    "scope_digest"
                ],
            },
        )
        self.assertEqual(response.json()["code"], "AGENT_CONFIG_CHANGED")
        self.assertEqual(
            client.get(f"/api/v1/agent/sessions/{sid}/messages").status_code, 200
        )

    def test_fixture_history_survives_provider_selection_and_still_checks_permissions(
        self,
    ):
        client = self.login()
        project = self.project(client, ("editor",))
        editor = self.login("editor")
        _client, sid, _run, _token, _archive, _checkpoint = self.make_completed(
            editor,
            {"scope_kind": "project", "project_id": project},
            "projects.get",
            {"project_id": project},
        )
        with patch.dict(os.environ, MODEL_ENV):
            history = editor.get(f"/api/v1/agent/sessions/{sid}/messages")
            self.assertEqual(history.status_code, 200, history.text)
            removed = client.delete(
                f"/api/v1/projects/{project}/members/{self.users['editor']['id']}"
            )
            self.assertEqual(removed.status_code, 204, removed.text)
            self.assertIn(
                editor.get(f"/api/v1/agent/sessions/{sid}/messages").status_code,
                {403, 404, 409},
            )

    def test_model_error_without_invocation_releases_session_but_written_run_requires_review(
        self,
    ):
        client = self.login()
        with patch.dict(os.environ, MODEL_ENV):
            sid = self.session(client)
            for reason in (
                "MODEL_AUTH_FAILED",
                "MODEL_RATE_LIMITED",
                "MODEL_TIMEOUT",
                "MODEL_REQUEST_FAILED",
                "MODEL_RESPONSE_INVALID",
            ):
                run = self.start_run(client, sid)
                token = self.claim(client, run)
                failed = client.post(
                    f"/internal/agent/runs/{run}/review",
                    headers={"Authorization": "Bearer " + token},
                    json={"reason": reason},
                )
                self.assertEqual(failed.status_code, 200, failed.text)
                self.assertEqual(failed.json()["state"], "FAILED")
                self.assertIsNone(
                    client.get(f"/api/v1/agent/sessions/{sid}").json()["active_run_id"]
                )
                self.assertNotEqual(
                    self.publish(client, run, token, None).status_code, 200
                )
            run = self.start_run(client, sid)
            token = self.claim(client, run)
            self.call(
                client,
                run,
                token,
                "projects.create",
                {"name": "provider fixture project"},
            )
            response = client.post(
                f"/internal/agent/runs/{run}/review",
                headers={"Authorization": "Bearer " + token},
                json={"reason": "MODEL_TIMEOUT"},
            )
            self.assertEqual(response.json()["state"], "WAITING_REVIEW")
            self.assertEqual(
                client.get(f"/api/v1/agent/sessions/{sid}").json()["active_run_id"], run
            )
            project = self.project(client)
            pending_sid = self.session(
                client, {"scope_kind": "project", "project_id": project}
            )
            pending_run = self.start_run(client, pending_sid)
            pending_token = self.claim(client, pending_run)
            uploaded = self.call(
                client,
                pending_run,
                pending_token,
                "uploads.create",
                {
                    "filename": "ledger-only.txt",
                    "size": 1,
                    "sha256": "a" * 64,
                    "media_type": "text/plain",
                },
            )
            upload_id = uploaded[2]["data"]["upload_id"]
            with Session(self.admin) as db, db.begin():
                upload = db.get(Upload, UUID(upload_id))
                upload.state, upload.version_id, upload.etag = (
                    "UPLOADED",
                    "ledger-only",
                    "ledger-only",
                )
            accepted = self.call(
                client,
                pending_run,
                pending_token,
                "uploads.complete",
                {"upload_id": upload_id},
            )
            self.assertEqual(accepted[2]["result"]["status"], "accepted")
            response = client.post(
                f"/internal/agent/runs/{pending_run}/review",
                headers={"Authorization": "Bearer " + pending_token},
                json={"reason": "MODEL_REQUEST_FAILED"},
            )
            self.assertEqual(response.json()["state"], "WAITING_REVIEW")

    def test_provider_protocol_error_cannot_publish(self):
        client = self.login()
        with patch.dict(os.environ, MODEL_ENV):
            sid = self.session(client)
            run = self.start_run(client, sid)
            token = self.claim(client, run)
            self.settled(client, run, token)
            manifest = agent_config.require_runtime()
            raw = provider_archive(sid, manifest)
            for mutation in ("error", "length"):
                rows = [json.loads(line) for line in raw.splitlines()]
                rows[-1]["message"]["stopReason"] = mutation
                response = self.put_provider(
                    client, run, token, "\n".join(json.dumps(r) for r in rows), manifest
                )
                self.assertEqual(
                    response.json()["code"], "CHECKPOINT_FORMAT_UNSUPPORTED"
                )
            self.assertIsNone(
                client.get(f"/api/v1/agent/sessions/{sid}").json()[
                    "latest_checkpoint_id"
                ]
            )
