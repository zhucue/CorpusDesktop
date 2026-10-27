import json
import tempfile
import unittest
from pathlib import Path
from uuid import uuid4

from pydantic import ValidationError

from contracts.materials import ImportInput, MaterialCounts, MaterialQuality
from contracts.research import ContextView, QueryCounts, SnapshotInput
from tests.contracts.test_research import ID, coordinates
from tests.contracts.validate_private_report import validate_private_reports


class PrivateContracts(unittest.TestCase):
    def test_fixed_members_bound_and_unique(self):
        SnapshotInput(material_revision_ids=[uuid4()])
        SnapshotInput(mount_ids=[uuid4()], material_revision_ids=[uuid4()])
        for args in [
            {},
            {"material_revision_ids": [ID, ID]},
            {
                "mount_ids": [uuid4() for _ in range(16)],
                "material_revision_ids": [uuid4()],
            },
        ]:
            with self.subTest(args=args), self.assertRaises(ValidationError):
                SnapshotInput(**args)

    def test_parser_uses_explicit_fixed_language_without_transport_authority(self):
        for language in ["cmn", "eng"]:
            ImportInput(upload_id=ID, language=language)
        for patch in [
            {"language": "auto"},
            {"url": "https://example.org"},
            {"recipe": "user"},
            {"project_id": ID},
        ]:
            with self.subTest(patch=patch), self.assertRaises(ValidationError):
                ImportInput.model_validate(
                    {"upload_id": ID, "language": "eng", **patch}
                )
        with self.assertRaises(ValidationError):
            MaterialCounts(documents=2, segments=12, characters=100)

    def test_document_units_are_exact_and_pending_is_not_zero(self):
        value = {
            "count_state": "complete",
            "total_hits": 8,
            "matched_segments": 5,
            "matched_documents": 3,
            "document_count_unit": "mixed_document_units",
            "matched_document_units": {"source_records": 1, "private_files": 2},
        }
        QueryCounts.model_validate(value)
        for patch in [
            {"matched_documents": 5},
            {"matched_document_units": None},
            {"document_count_unit": "uploaded_file"},
            {"count_state": "pending"},
            {"count_state": "failed"},
        ]:
            with self.subTest(patch=patch), self.assertRaises(ValidationError):
                QueryCounts.model_validate({**value, **patch})

    def test_quality_and_actual_capture_validation(self):
        MaterialQuality(
            complete_text_preserved=True,
            rejected_segments=0,
            segmentation="deterministic_rules_not_linguistic_gold",
        )
        with self.assertRaises(ValidationError):
            MaterialQuality(
                complete_text_preserved=True, rejected_segments=1, segmentation="gold"
            )
        directory = Path(__file__).resolve().parents[2] / "tmp/private-contract-tests"
        directory.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=directory) as temporary:
            path = Path(temporary) / "capture.json"
            path.write_text(
                json.dumps({"material_lists": [{"items": [], "next_cursor": None}]}),
                encoding="utf-8",
            )
            result = validate_private_reports([path])
            self.assertEqual(result["status"], "passed")
            self.assertEqual(result["validated_response_counts"]["material_lists"], 1)
            self.assertEqual(validate_private_reports([path], True)["status"], "failed")
            path.write_text(
                json.dumps(
                    {
                        "material_lists": [
                            {"items": [], "next_cursor": None, "text": "PRIVATE"}
                        ]
                    }
                ),
                encoding="utf-8",
            )
            result = validate_private_reports([path])
            self.assertEqual(result["status"], "failed")
            self.assertNotIn("PRIVATE", json.dumps(result))

    def test_private_context_offsets_reference_complete_document(self):
        value = {
            **coordinates(),
            "origin_kind": "private",
            "document_id": ID,
            "document_name": "example.txt",
            "material_id": ID,
            "material_revision_id": ID,
            "source_id": None,
            "source_sentence_id": None,
            "source_url": None,
            "revision_id": ID,
            "segment_id": ID + ":segment:1",
            "context_start_cp": 20,
            "start_cp": 21,
            "end_cp": 23,
            "project_id": ID,
            "snapshot_id": ID,
            "result_set_id": ID,
            "text": "a😀汉b",
        }
        result = ContextView.model_validate(value)
        self.assertEqual(
            result.text[
                result.start_cp - result.context_start_cp : result.end_cp
                - result.context_start_cp
            ],
            "😀汉",
        )
        for patch in [
            {"start_cp": 1},
            {"end_cp": 25},
            {"source_url": "https://example.org/fake"},
            {"material_revision_id": None},
        ]:
            with self.subTest(patch=patch), self.assertRaises(ValidationError):
                ContextView.model_validate({**value, **patch})
