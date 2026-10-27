import json
import unittest
from pathlib import Path
from uuid import uuid4

from jsonschema import Draft202012Validator, ValidationError

ROOT = Path(__file__).resolve().parents[2] / "contracts"


def validator(name):
    return Draft202012Validator(json.loads((ROOT / f"schemas/{name}.schema.json").read_text(encoding="utf-8")))


class SourceSyncContracts(unittest.TestCase):
    def test_fixed_connector_rejects_config_and_authority(self):
        schema = validator("s2-sync-start")
        schema.validate({"source_id": "D12"})
        for value in [{"source_id": "D01"}, {"source_id": "D12", "url": "https://other.test"},
                      {"source_id": "D12", "actor_id": "admin"}, {"source_id": "D12", "recipe": "custom"}]:
            with self.subTest(value=value), self.assertRaises(ValidationError):
                schema.validate(value)

    def test_job_domain_references_are_disjoint(self):
        schema = validator("s2-scoped-job-ref")
        ident = str(uuid4())
        schema.validate({"job_id": ident})
        schema.validate({"sync_run_id": ident})
        for value in [{}, {"job_id": ident, "sync_run_id": ident}, {"sync_run_id": "not-a-uuid"},
                      {"sync_run_id": ident, "project_id": "invented"}]:
            with self.subTest(value=value), self.assertRaises(ValidationError):
                schema.validate(value)

    def test_platform_list_requires_fixed_source_and_bounded_pagination(self):
        schema = validator("s2-scoped-job-list")
        schema.validate({})  # Existing trusted project scope supplies its project.
        schema.validate({"source_id": "D12", "page_size": 10, "cursor": "next"})
        for value in [{"source_id": "D12", "page_size": 101}, {"source_id": "D01"},
                      {"source_id": "D12", "job_id": "invented"}]:
            with self.subTest(value=value), self.assertRaises(ValidationError):
                schema.validate(value)

    def test_validated_acquisition_is_not_searchable_or_public(self):
        value = {"id": str(uuid4()), "source_id": "D12", "connector_id": "tatoeba", "source_revision": 1,
                 "source_identity": {"name": "Tatoeba", "publisher": "Tatoeba", "entry_kind": "dataset", "official_url": "https://tatoeba.org"},
                 "state": "SUCCEEDED", "stage": "VALIDATED", "attempt": 1,
                 "created_at": "2026-10-16T12:00:00Z", "updated_at": "2026-10-16T12:00:00Z",
                 "progress": {"processed_bytes": 1, "total_bytes": None, "processed_records": 1, "total_records": None, "file_name": None},
                 "result": {"acquisition_id": str(uuid4()), "state": "VALIDATED", "searchable": False,
                            "manifest_sha256": "a" * 64, "export_date": None, "quality": {}, "diff": {}, "license": {}},
                 "error": None, "allowed_actions": {"cancel": False, "retry": False}}
        schema = validator("s2-sync-run")
        schema.validate(value)
        for result in [{**value["result"], "state": "READY"}, {**value["result"], "searchable": True}, None]:
            with self.subTest(result=result), self.assertRaises(ValidationError):
                schema.validate({**value, "result": result})
        with self.assertRaises(ValidationError):
            schema.validate({**value, "state": "RUNNING"})

    def test_only_two_new_actions_and_no_production_tools(self):
        registry = json.loads((ROOT / "capabilities.json").read_text(encoding="utf-8"))["capabilities"]
        inventory = json.loads((ROOT / "s2-capabilities.json").read_text(encoding="utf-8"))
        self.assertEqual(len(registry), 143)
        self.assertEqual(inventory["available_tools"], [])
        self.assertEqual({row["capability_id"] for row in inventory["coverage"]},
                         {"sync.start", "sync.report", "jobs.list", "jobs.get", "jobs.cancel", "jobs.retry"})
        by_name = {row["capability_id"]: row for row in registry}
        self.assertEqual(by_name["sync.check"]["input_schema"], "schemas/planned.schema.json")
        self.assertEqual(by_name["releases.publish"]["input_schema"], "schemas/s3-release-publish.schema.json")
        self.assertEqual(by_name["jobs.cancel"]["scope_kind"], ["project", "platform"])
        self.assertTrue(all(row["availability"]["status"] == "planned" for row in registry))


if __name__ == "__main__":
    unittest.main()
