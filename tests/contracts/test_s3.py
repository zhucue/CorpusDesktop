import copy
import json
import unittest
from pathlib import Path
from uuid import uuid4

from jsonschema import Draft202012Validator, ValidationError

ROOT = Path(__file__).resolve().parents[2] / "contracts"


def validator(name):
    return Draft202012Validator(json.loads((ROOT / f"schemas/{name}.schema.json").read_text(encoding="utf-8")))


class IndexContracts(unittest.TestCase):
    def test_build_is_fixed_acquisition_without_configuration_or_authority(self):
        value = {"source_id": "D12", "acquisition_id": str(uuid4())}
        schema = validator("s3-index-build")
        schema.validate(value)
        for changed in [{"source_id": "D01"}, {"acquisition_id": "latest"}, {"recipe": "custom"},
                        {"url": "https://other.test"}, {"actor_id": str(uuid4())}, {"approved": True}]:
            with self.subTest(changed=changed), self.assertRaises(ValidationError):
                schema.validate({**value, **changed})

    def test_domains_are_disjoint_and_index_listing_is_explicit(self):
        ident = str(uuid4())
        refs = validator("s3-scoped-job-ref")
        for field in ["job_id", "sync_run_id", "index_run_id"]:
            refs.validate({field: ident})
        for value in [{}, {"index_run_id": ident, "sync_run_id": ident}, {"index_run_id": ident, "job_id": ident}]:
            with self.subTest(value=value), self.assertRaises(ValidationError):
                refs.validate(value)
        listing = validator("s3-scoped-job-list")
        for value in [{}, {"source_id": "D12"}, {"source_id": "D12", "task_kind": "source_index", "page_size": 100}]:
            listing.validate(value)
        for value in [{"task_kind": "source_index"}, {"source_id": "D12", "task_kind": "arbitrary"},
                      {"source_id": "D12", "task_kind": "source_index", "page_size": 101}]:
            with self.subTest(value=value), self.assertRaises(ValidationError):
                listing.validate(value)

    def test_indexed_result_cannot_be_ready_searchable_or_partial_success(self):
        value = {"id": str(uuid4()), "source_id": "D12", "acquisition_id": str(uuid4()),
                 "source_identity": {"name": "Tatoeba", "publisher": "Tatoeba", "entry_kind": "dataset", "official_url": "https://tatoeba.org"},
                 "recipe": {"id": "fixed-v1", "sha256": "b" * 64},
                 "state": "SUCCEEDED", "stage": "INDEXED", "attempt": 1,
                 "created_at": "2026-10-16T12:00:00Z", "updated_at": "2026-10-16T12:00:00Z",
                 "progress": {"processed_bytes": 1, "total_bytes": None, "processed_records": 1, "total_records": None, "file_name": None},
                 "result": {"index_id": str(uuid4()), "state": "INDEXED", "searchable": False,
                            "identity_sha256": "a" * 64, "manifest_sha256": "c" * 64, "counts": {}, "artifact_bytes": 123, "quality": {}},
                 "error": None, "allowed_actions": {"cancel": False, "retry": False}}
        schema = validator("s3-index-run")
        schema.validate(value)
        for path, change in [("state", "READY"), ("searchable", True), ("artifact_bytes", -1)]:
            bad = copy.deepcopy(value)
            bad["result"][path] = change
            with self.subTest(path=path), self.assertRaises(ValidationError):
                schema.validate(bad)
        for changed in [{"result": None}, {"state": "RUNNING"}, {"stage": "STORING"}]:
            with self.subTest(changed=changed), self.assertRaises(ValidationError):
                schema.validate({**value, **changed})

    def test_registry_adds_only_index_actions_without_production_grant(self):
        registry = json.loads((ROOT / "capabilities.json").read_text(encoding="utf-8"))["capabilities"]
        by_name = {row["capability_id"]: row for row in registry}
        self.assertEqual(len(registry), 143)
        for name in ["indexes.build", "indexes.report"]:
            self.assertEqual(by_name[name]["scope_kind"], ["platform"])
            self.assertEqual(by_name[name]["availability"]["status"], "planned")
        self.assertEqual(by_name["indexes.build"]["execution"], "job")
        self.assertEqual(by_name["releases.publish"]["input_schema"], "schemas/s3-release-publish.schema.json")
        status = json.loads((ROOT / "status.json").read_text(encoding="utf-8"))
        self.assertEqual(status["tool_adapters"]["capability_count"], 52)
        self.assertEqual(status["available_business_capabilities"], 0)


if __name__ == "__main__":
    unittest.main()
