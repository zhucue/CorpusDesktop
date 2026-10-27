"""Actual S1 boundaries stay separate from planned production Pi capabilities."""

import json
import unittest
from pathlib import Path

from jsonschema import Draft202012Validator, ValidationError

ROOT = Path(__file__).resolve().parents[2]


def schema(name):
    return Draft202012Validator(json.loads((ROOT / f"contracts/schemas/{name}.schema.json").read_text(encoding="utf-8")))


class S1Contracts(unittest.TestCase):
    def test_manual_action_does_not_require_agent_run(self):
        value = {"action_id": "a", "project_id": "p", "actor_id": "u", "operation": "uploads.complete",
                 "idempotency_key": "k", "request_sha256": "f" * 64, "agent": None}
        schema("s1-action").validate(value)
        schema("s1-action").validate({**value, "agent": {"invocation_id": "i", "run_id": "r"}})
        with self.assertRaises(ValidationError):
            schema("s1-action").validate({**value, "agent": {"invocation_id": "i"}})

    def test_empty_project_upload_needs_no_snapshot_or_identity_arguments(self):
        value = {"filename": "sample.txt", "size": 4, "media_type": "text/plain", "sha256": "a" * 64}
        schema("s1-upload-create").validate(value)
        for extra in ("actor_id", "snapshot_id", "authorization", "object_key"):
            with self.subTest(extra=extra), self.assertRaises(ValidationError):
                schema("s1-upload-create").validate({**value, extra: "injected"})

    def test_upload_complete_is_accepted_not_success_or_searchable(self):
        value = {"status": "accepted", "action_id": "a", "job_id": "j", "upload_id": "u", "state": "QUEUED", "result_ref": None}
        schema("s1-accepted-upload").validate(value)
        with self.assertRaises(ValidationError):
            schema("s1-accepted-upload").validate({**value, "status": "succeeded"})
        with self.assertRaises(ValidationError):
            schema("s1-accepted-upload").validate({**value, "result_ref": "READY"})

    def test_job_events_do_not_need_agent_run(self):
        event = {"event_id": "e", "job_id": "j", "sequence": 1, "kind": "job.queued", "state": "QUEUED", "attempt": 1, "payload": {}, "created_at": "2026-10-16T12:00:00Z"}
        schema("job-event").validate(event)
        with self.assertRaises(ValidationError):
            schema("job-event").validate({**event, "run_id": "invented"})

    def test_registry_does_not_open_untested_or_undelegated_tools(self):
        data = json.loads((ROOT / "contracts/capabilities.json").read_text(encoding="utf-8"))
        actions = {item["tool_name"]: item for item in data["capabilities"]}
        self.assertEqual(len(actions), 143)
        self.assertTrue(all(item["availability"]["status"] == "planned" for item in actions.values()))
        self.assertEqual(actions["uploads.complete"]["execution"], "job")
        self.assertEqual(actions["uploads.create"]["version_inputs"], [])
        inventory = json.loads((ROOT / "contracts/s1-capabilities.json").read_text(encoding="utf-8"))
        self.assertEqual(inventory["available_tools"], [])
        self.assertEqual(len(inventory["coverage"]), 18)

    def test_catalog_metadata_cannot_grant_production_capabilities(self):
        value = {"source_id": "D99", "name": "Example", "publisher": "Example", "entry_kind": "dataset",
                 "categories": ["parallel"], "languages": ["zh", "en"], "official_url": "https://example.org",
                 "materials": "sentences", "access_route": "catalog", "boundary": "pending review"}
        schema("s1-catalog-create").validate(value)
        for key, extra in {"capabilities": {"fulltext_analysis": True}, "license_status": "approved", "integration_status": "READY", "actor_id": "admin"}.items():
            with self.subTest(key=key), self.assertRaises(ValidationError):
                schema("s1-catalog-create").validate({**value, key: extra})
        schema("s1-catalog-update").validate({**{key: item for key, item in value.items()}, "expected_revision": 2})
        with self.assertRaises(ValidationError):
            schema("s1-catalog-update").validate(value)

    def test_source_reads_are_account_scoped_and_versions_are_paged(self):
        schema("s1-source-list").validate({"q": "D12", "language": "zh"})
        schema("s1-source-versions").validate({"source_id": "D12", "page_size": 10, "cursor": "next"})
        with self.assertRaises(ValidationError):
            schema("s1-source-id").validate({"source_id": "D12", "project_id": "invented"})
        data = json.loads((ROOT / "contracts/capabilities.json").read_text(encoding="utf-8"))
        actions = {item["tool_name"]: item for item in data["capabilities"]}
        for name in ("sources.list", "sources.get", "sources.versions", "account.get"):
            self.assertEqual(actions[name]["scope_kind"], ["account", "platform", "project"])
        self.assertEqual(actions["catalog.update"]["scope_kind"], ["platform"])


if __name__ == "__main__":
    unittest.main()
