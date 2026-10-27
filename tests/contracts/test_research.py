import copy
import json
import unittest
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker, ValidationError
from pydantic import ValidationError as ModelError

from contracts.research import ContextView, HitPage, QueryInput, SnapshotInput

ROOT = Path(__file__).resolve().parents[2] / "contracts"
ID = "ba89a93f-58e3-4f1c-a745-d10caf2f0b11"
SORT = ["document_ordinal", "start", "end"]


def validator(name):
    return Draft202012Validator(
        json.loads(
            (ROOT / f"schemas/s3-research-{name}.schema.json").read_text("utf-8")
        ),
        format_checker=FormatChecker(),
    )


def query(unit="character"):
    pattern = (
        {"type": "literal", "value": "😀汉"}
        if unit == "character"
        else {"type": "term", "attr": "form", "op": "eq", "value": "hello"}
    )
    return {
        "dsl_version": "corpus-query/v1",
        "unit": unit,
        "pattern": pattern,
        "within": "sentence",
        "overlap": "all",
    }


def coordinates():
    return {
        "hit_ref": {"result_set_id": ID, "ordinal": 0},
        "revision_id": "tatoeba:1:actual-text-digest",
        "segment_id": "tatoeba:1:actual-text-digest:sentence",
        "source_sentence_id": "1",
        "source_id": "D12",
        "origin_kind": "source",
        "document_id": "tatoeba:1",
        "document_name": "1",
        "material_id": None,
        "material_revision_id": None,
        "context_start_cp": 0,
        "start_cp": 1,
        "end_cp": 3,
        "token_start": None,
        "token_end": None,
        "global_token_start": None,
        "global_token_end": None,
        "source_url": "https://tatoeba.org/en/sentences/show/1",
        "evidence_id": None,
    }


def page():
    return {
        "project_id": ID,
        "snapshot_id": ID,
        "query_run_id": ID,
        "result_set_id": ID,
        "hits": [{**coordinates(), "left": "a", "match": "😀汉", "right": "b"}],
        "next_cursor": None,
        "has_more": True,
        "page_state": "ready",
        "count_state": "pending",
        "completeness": "preview",
        "total_hits": None,
        "matched_segments": None,
        "matched_documents": None,
        "document_count_unit": "imported_sentence_record",
        "matched_document_units": None,
        "sort": SORT,
        "context": {"unit": "codepoint", "before": 40, "after": 40},
    }


class ResearchContracts(unittest.TestCase):
    def test_snapshot_fixed_members_without_authority(self):
        check = validator("snapshot-create")
        check.validate({"mount_ids": [ID]})
        for value in [
            {"mount_ids": []},
            {"mount_ids": [ID, ID]},
            {"mount_ids": ["latest"]},
            {"mount_ids": [ID], "project_id": ID},
            {"mount_ids": [ID], "filters": {}},
        ]:
            with self.subTest(value=value):
                with self.assertRaises(ValidationError):
                    check.validate(value)
                with self.assertRaises(ModelError):
                    SnapshotInput.model_validate(value)

    def test_query_units_and_actual_context_are_strict(self):
        check = validator("query-create")
        for unit in ["character", "token"]:
            value = {"snapshot_id": ID, "query": query(unit)}
            check.validate(value)
            self.assertEqual(QueryInput.model_validate(value).context_codepoints, 40)
            for patch in [
                {"context_tokens": 40},
                {"context_codepoints": 201},
                {"context_codepoints": -1},
                {"page_size": 51},
                {"recipe": "user-choice"},
                {"actor_id": ID},
            ]:
                with (
                    self.subTest(unit=unit, patch=patch),
                    self.assertRaises(ValidationError),
                ):
                    check.validate({**value, **patch})
        for patch in [
            {"within": "paragraph"},
            {"condition": {"op": "and"}},
            {"filters": {"language": ["zh"]}},
            {"unit": "token"},
            {"pattern": {"type": "regex", "value": ".*"}},
        ]:
            with self.subTest(patch=patch), self.assertRaises(ModelError):
                QueryInput.model_validate(
                    {"snapshot_id": ID, "query": {**query(), **patch}}
                )

    def test_sequences_require_positive_bounded_gap_anchors(self):
        for unit in ["character", "token"]:
            atom = query(unit)["pattern"]
            valid = {
                **query(unit),
                "pattern": {
                    "type": "sequence",
                    "items": [atom, {"type": "gap", "min": 0, "max": 2}, atom],
                },
            }
            QueryInput.model_validate({"snapshot_id": ID, "query": valid})
            for items in [
                [{"type": "gap", "min": 0, "max": 2}, atom],
                [atom, {"type": "gap", "min": 3, "max": 2}, atom],
                [
                    atom,
                    {"type": "gap", "min": 0, "max": 1},
                    {"type": "gap", "min": 0, "max": 1},
                    atom,
                ],
            ]:
                with (
                    self.subTest(unit=unit, items=items),
                    self.assertRaises(ModelError),
                ):
                    QueryInput.model_validate(
                        {
                            "snapshot_id": ID,
                            "query": {
                                **valid,
                                "pattern": {"type": "sequence", "items": items},
                            },
                        }
                    )

    def test_preview_does_not_claim_zero_or_complete_counts(self):
        check = validator("hits")
        check.validate(page())
        HitPage.model_validate(page())
        for patch in [
            {"total_hits": 0},
            {"matched_documents": 1},
            {"count_state": "complete"},
        ]:
            with self.subTest(patch=patch):
                with self.assertRaises(ValidationError):
                    check.validate({**page(), **patch})
                with self.assertRaises(ModelError):
                    HitPage.model_validate({**page(), **patch})
        empty = {
            **page(),
            "hits": [],
            "has_more": False,
            "count_state": "complete",
            "completeness": "complete",
            "total_hits": 0,
            "matched_segments": 0,
            "matched_documents": 0,
            "matched_document_units": {"source_records": 0, "private_files": 0},
        }
        check.validate(empty)
        HitPage.model_validate(empty)

    def test_stable_hit_reference_and_null_evidence(self):
        check = validator("hits")
        for patch in [{"evidence_id": ID}, {"object_key": "private"}, {"start_cp": -1}]:
            value = page()
            value["hits"][0].update(patch)
            with self.subTest(patch=patch), self.assertRaises(ValidationError):
                check.validate(value)
        for patch in [
            {"result_set_id": "0a89a93f-58e3-4f1c-a745-d10caf2f0b11"},
            {"next_cursor": "unready"},
            {"page_state": "pending"},
        ]:
            with self.subTest(patch=patch), self.assertRaises(ModelError):
                HitPage.model_validate({**page(), **patch})
        duplicate = page()
        duplicate["hits"] *= 2
        with self.assertRaises(ModelError):
            HitPage.model_validate(duplicate)

    def test_unicode_context_and_real_token_coordinates(self):
        value = {
            **coordinates(),
            "project_id": ID,
            "snapshot_id": ID,
            "result_set_id": ID,
            "text": "a😀汉b",
        }
        result = ContextView.model_validate(value)
        self.assertEqual(result.text[result.start_cp : result.end_cp], "😀汉")
        token = {
            **value,
            "token_start": 1,
            "token_end": 3,
            "global_token_start": 101,
            "global_token_end": 103,
        }
        ContextView.model_validate(token)
        for patch in [
            {"end_cp": 5},
            {"end_cp": 1},
            {"token_end": None},
            {"global_token_end": 104},
        ]:
            with self.subTest(patch=patch), self.assertRaises(ModelError):
                ContextView.model_validate({**token, **patch})
        wrong_match = copy.deepcopy(page())
        wrong_match["hits"][0]["match"] = "😀"
        with self.assertRaises(ModelError):
            HitPage.model_validate(wrong_match)

    def test_registry_preserves_production_boundary(self):
        entries = {
            v["capability_id"]: v
            for v in json.loads((ROOT / "capabilities.json").read_text("utf-8"))[
                "capabilities"
            ]
        }
        for name in [
            "snapshots.create",
            "snapshots.get",
            "corpus.describe",
            "corpus.search",
            "results.get",
            "results.context",
        ]:
            self.assertEqual(entries[name]["availability"]["status"], "planned")
            self.assertIn("s3-research-", entries[name]["input_schema"])
        self.assertEqual(entries["snapshots.create"]["scope_effect"], "produces_scope")
        self.assertEqual(
            json.loads((ROOT / "status.json").read_text("utf-8"))[
                "available_business_capabilities"
            ],
            0,
        )
