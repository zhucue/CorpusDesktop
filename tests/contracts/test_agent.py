import unittest
from copy import deepcopy
from uuid import uuid4

from jsonschema import Draft202012Validator
from pydantic import ValidationError

from contracts.agent import MessageList, RunInput, RuntimeView, SessionInput


class AgentContracts(unittest.TestCase):
    def test_fixed_empty_scope_cannot_import_materials_or_identity(self):
        project = {"scope_kind": "project", "project_id": str(uuid4())}
        SessionInput(scope=project)
        for key in ["snapshot_ids", "material_revision_ids", "result_refs"]:
            with self.subTest(key=key), self.assertRaises(ValidationError):
                SessionInput(scope={**project, key: [str(uuid4())]})
        for extra in [{"actor_id": str(uuid4())}, {"model_config_id": "external"}]:
            with self.subTest(extra=extra), self.assertRaises(ValidationError):
                SessionInput(scope=project, **extra)

    def test_message_is_fixed_with_scope_and_request_not_confirmation(self):
        value = {"request_key": str(uuid4()), "message": "  Hello 😀\n", "scope_digest": "a" * 64}
        self.assertEqual(RunInput(**value).message, value["message"])
        for patch in [{"message": " \n"}, {"message": "x" * 8001},
                      {"scope_digest": "x"}, {"confirmed": True},
                      {"queue": True}, {"model_config_id": "external"}]:
            with self.subTest(patch=patch), self.assertRaises(ValidationError):
                RunInput(**{**value, **patch})

    def test_runtime_never_claims_production_or_unconfigured_submission(self):
        value = {"production_ready": False, "mode": "unconfigured", "fixture_enabled": False, "can_submit": False,
                 "config_id": None, "reason": "MODEL_NOT_CONFIGURED", "runtime_manifest": None}
        RuntimeView(**value)
        for patch in [{"production_ready": True}, {"can_submit": True}, {"api_key": "secret"}]:
            with self.subTest(patch=patch), self.assertRaises(ValidationError):
                RuntimeView(**{**value, **patch})

    def test_runtime_protocol_branches_are_strict_in_schema_and_model(self):
        fixture_manifest = {
            "sdk_package": "@earendil-works/pi-coding-agent", "sdk_version": "1.3.0",
            "session_version": 3, "host_policy": "corpus-k09-linear-v1",
            "provider": "corpus-s1-fixed", "model": "fixed-project-v1",
            "tool_schema": "s3-outcomes-tools-v1", "resource_config": "corpus-empty-resources-v1",
        }
        fixture = {"production_ready": False, "mode": "fixture", "fixture_enabled": True,
                   "can_submit": True, "config_id": "local-fixture-v1", "reason": None,
                   "runtime_manifest": fixture_manifest}
        real = {**fixture, "mode": "openai-compatible", "fixture_enabled": False,
                "config_id": "openai-" + "a" * 48,
                "runtime_manifest": {**fixture_manifest, "host_policy": "corpus-k09-openai-v1",
                                     "provider": "corpus-openai-compatible", "model": "configured-model",
                                     "resource_config": "corpus-explicit-resources-v1",
                                     "model_api": "openai-responses", "model_config_sha256": "a" * 64}}
        invalid = {**real, "can_submit": False, "config_id": None, "runtime_manifest": None,
                   "reason": "MODEL_CONFIGURATION_INVALID"}
        validator = Draft202012Validator(RuntimeView.model_json_schema())
        for value in [fixture, real, invalid]:
            with self.subTest(valid=value["mode"]):
                self.assertFalse(list(validator.iter_errors(value)))
                self.assertEqual(RuntimeView(**value).model_dump(), value)
        for value in [
            {**fixture, "mode": "openai-compatible"}, {**real, "fixture_enabled": True},
            {**real, "config_id": "local-fixture-v1"}, {**invalid, "can_submit": True},
            {**fixture, "runtime_manifest": {**fixture_manifest, "model_api": None}},
            {**real, "runtime_manifest": {**real["runtime_manifest"], "base_url": "https://private.example"}},
            {**real, "runtime_manifest": {**real["runtime_manifest"], "model_api": "arbitrary"}},
        ]:
            with self.subTest(invalid=value), self.assertRaises(ValidationError):
                self.assertTrue(list(validator.iter_errors(value)))
                RuntimeView(**value)
        mismatched_digest = deepcopy(real)
        mismatched_digest["runtime_manifest"]["model_config_sha256"] = "b" * 64
        with self.assertRaises(ValidationError):
            RuntimeView(**mismatched_digest)

    def test_browser_projection_rejects_checkpoint_thinking_and_raw_tool_data(self):
        turn = {"run_id": str(uuid4()), "user_message": "hello", "assistant_messages": [],
                "tools": [], "state": "SUCCEEDED", "created_at": "2026-10-17T00:00:00Z"}
        MessageList(items=[turn], next_before=None)
        for field in ["checkpoint", "thinking", "execution_token"]:
            with self.subTest(field=field), self.assertRaises(ValidationError):
                MessageList(items=[{**turn, field: "private"}], next_before=None)
        tool = {"invocation_id": str(uuid4()), "tool_name": "projects.create", "status": "succeeded",
                "result_view": {"kind": "project", "resource_id": str(uuid4())}}
        MessageList(items=[{**turn, "tools": [tool]}], next_before=None)
        for patch in [{"arguments": {}}, {"data": {}}, {"result_view": {"kind": "url", "resource_id": "https://invalid"}}]:
            with self.subTest(patch=patch), self.assertRaises(ValidationError):
                MessageList(items=[{**turn, "tools": [{**tool, **patch}]}], next_before=None)
