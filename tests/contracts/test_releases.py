import copy
import json
import unittest
from pathlib import Path
from uuid import uuid4

from jsonschema import Draft202012Validator, FormatChecker, ValidationError

ROOT = Path(__file__).resolve().parents[2] / "contracts"
ID = str(uuid4())


def validator(name):
    return Draft202012Validator(json.loads((ROOT / f"schemas/s3-release-{name}.schema.json").read_text(encoding="utf-8")), format_checker=FormatChecker())


def release():
    return {"release_id": ID, "source_id": "fixture", "source_snapshot_id": ID, "index_id": ID,
            "acquisition_id": ID, "version": "fixed-1", "published_at": "2026-10-16T00:00:00Z",
            "manifest_sha256": "a" * 64, "index_identity_sha256": "b" * 64,
            "recipe": {"id": "fixed", "sha256": "c" * 64},
            "counts": dict.fromkeys(["sentences", "cmn_sentences", "eng_sentences", "characters", "tokens", "direct_edges", "unknown_owner"], 1),
            "quality": {"all_source_sentences_indexed": True, "rejected_sentences": 0,
                        "token_roundtrip_verified": True, "attributes": ["form"],
                        "document_count_unit": "imported_sentence_record", "normalization": "none"},
            "policy_revision": 1, "current_policy_revision": 2, "state": "PUBLISHED", "searchable": False,
            "available": False, "unavailable_reason": "SOURCE_POLICY_DENIED"}


class ReleaseContracts(unittest.TestCase):
    def test_policy_requires_explicit_acquisition_decision_and_evidence(self):
        value = {"policy_kind": "source", "source_id": "fixture", "acquisition_id": ID,
                 "expected_revision": 0, "decision": "allow", "review_note": "Fixture-only explicit review",
                 "evidence_urls": ["https://example.test/license"]}
        check = validator("policy-update")
        check.validate(value)
        for patch in [{"decision": "unknown"}, {"evidence_urls": []}, {"evidence_urls": ["file:///secret"]},
                      {"evidence_urls": ["https://example.test"] * 13}, {"expected_revision": -1},
                      {"policy_kind": "model"}, {"model_egress": True}, {"actor_id": ID}]:
            with self.subTest(patch=patch), self.assertRaises(ValidationError):
                check.validate({**value, **patch})

    def test_publish_and_mount_are_fixed_without_arbitrary_configuration(self):
        for name, value in [("publish", {"source_id": "fixture", "index_id": ID, "expected_policy_revision": 1}),
                            ("mount-create", {"source_snapshot_id": ID})]:
            check = validator(name)
            check.validate(value)
            for patch in [{"filters": {}}, {"project_id": ID}, {"recipe": "new"}, {"url": "https://example.test"}, {"source_snapshot_id": "latest"}]:
                with self.subTest(name=name, patch=patch), self.assertRaises(ValidationError):
                    check.validate({**value, **patch})

    def test_release_counts_and_dynamic_query_capability_are_strict(self):
        check = validator("view")
        check.validate(release())
        for field, value in [("sentences", -1), ("tokens", "12"), ("characters", 1.5)]:
            changed = release()
            changed["counts"][field] = value
            with self.subTest(field=field), self.assertRaises(ValidationError):
                check.validate(changed)
        check.validate({**release(), "searchable": True})
        for patch in [{"searchable": "yes"}, {"state": "READY"}, {"object_key": "private"}, {"manifest_sha256": "bad"}]:
            with self.subTest(patch=patch), self.assertRaises(ValidationError):
                check.validate({**release(), **patch})

    def test_nested_http_envelopes_resolve_definitions(self):
        value = {"id": ID, "project_id": ID, "created_at": "2026-10-16T00:00:00Z", "removed_at": None,
                 "state": "ACTIVE", "release": release(), "allowed_actions": {"remove": False, "read_manifest": False}}
        validator("action").validate({"action_id": ID, "existing": True, "release": release()})
        validator("mount-action").validate({"action_id": ID, "existing": False, "mount": value})
        listing = {"items": [value], "total": 1, "next_cursor": None, "allowed_actions": {"create": False}}
        validator("mounts").validate(listing)
        invalid = copy.deepcopy(listing)
        invalid["items"][0]["release"]["counts"]["tokens"] = -1
        with self.assertRaises(ValidationError):
            validator("mounts").validate(invalid)
        versions = Draft202012Validator(json.loads((ROOT / "schemas/s1-source-versions-result.schema.json").read_text(encoding="utf-8")), format_checker=FormatChecker())
        versions.validate({"items": [release()], "total": 1, "next_cursor": None})
        with self.assertRaises(ValidationError):
            versions.validate({"items": [release()], "total": 1, "next_cursor": None, "object_key": "private"})

    def test_registry_is_explicit_and_production_unavailable(self):
        entries = {item["capability_id"]: item for item in json.loads((ROOT / "capabilities.json").read_text(encoding="utf-8"))["capabilities"]}
        for name in ["policies.get", "policies.update", "releases.publish"]:
            self.assertEqual(entries[name]["scope_kind"], ["platform"])
        for name in ["mounts.list", "mounts.get", "mounts.manifest", "mounts.create", "mounts.remove"]:
            self.assertEqual(entries[name]["scope_kind"], ["project"])
            self.assertEqual(entries[name]["scope_effect"], "none")
        self.assertEqual(entries["mounts.manifest"]["operation_kind"], "read")
        self.assertTrue(all(item["availability"]["status"] == "planned" for item in entries.values()))


if __name__ == "__main__":
    unittest.main()
