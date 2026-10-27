import json
import tempfile
import unittest
from pathlib import Path
from uuid import uuid4

from pydantic import ValidationError

from contracts.outcomes import (
    EvidenceInput,
    ExportInput,
    ExportView,
    NoteAccept,
    NoteInput,
    NoteView,
)
from tests.contracts.validate_outcomes_report import validate_outcomes_reports

ID = str(uuid4())
NOW = "2026-10-17T00:00:00Z"


def note():
    return {
        "id": ID, "project_id": ID, "created_by": ID,
        "created_at": NOW, "updated_at": NOW, "revision": 2,
        "title": "Method", "body": "Zero matches still provide a method.",
        "evidence_ids": [], "query_run_ids": [ID],
        "authorization_evidence_ids": [], "authorization_query_run_ids": [ID],
        "status": "draft", "accepted_by": None, "accepted_at": None,
        "allowed_actions": {"update": True, "accept": True, "export": False},
    }


class OutcomeContracts(unittest.TestCase):
    def test_capture_validator_requires_real_families_and_checks_note_invariants(self):
        root = Path(__file__).resolve().parents[2] / "tmp"
        root.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=root) as directory:
            path = Path(directory) / "capture.json"
            path.write_text(json.dumps({"notes": [note()]}), encoding="utf-8")
            partial = validate_outcomes_reports([path])
            self.assertEqual(partial["status"], "passed")
            self.assertEqual(partial["validated_response_counts"]["notes"], 1)
            self.assertEqual(validate_outcomes_reports([path], True)["status"], "failed")
            invalid = {**note(), "status": "accepted"}
            path.write_text(json.dumps({"notes": [invalid]}), encoding="utf-8")
            rejected = validate_outcomes_reports([path])
            self.assertEqual(rejected["status"], "failed")
            self.assertNotIn(invalid["body"], json.dumps(rejected))

    def test_evidence_accepts_only_server_resolved_complete_hit_reference(self):
        EvidenceInput(result_set_id=ID, ordinal=0)
        for patch in [{"ordinal": -1}, {"text": "forged"}, {"start_cp": 0},
                      {"project_id": ID}, {"evidence_id": ID}]:
            with self.subTest(patch=patch), self.assertRaises(ValidationError):
                EvidenceInput.model_validate({"result_set_id": ID, "ordinal": 0, **patch})

    def test_note_zero_hit_method_references_and_dependency_limit(self):
        NoteInput(title="Method", body="No results", query_run_ids=[ID])
        NoteView.model_validate(note())
        for patch in [
            {"query_run_ids": [ID, ID]},
            {"evidence_ids": [uuid4() for _ in range(100)], "query_run_ids": [ID]},
            {"confirmed": True}, {"status": "accepted"},
        ]:
            with self.subTest(patch=patch), self.assertRaises(ValidationError):
                NoteInput.model_validate({"title": "Method", "body": "Text", **patch})

    def test_displayed_references_cannot_escape_authorization_dependencies(self):
        value = note()
        value["authorization_evidence_ids"] = [ID]
        NoteView.model_validate(value)  # Removed displayed reference remains inherited.
        value["authorization_query_run_ids"] = []
        with self.assertRaises(ValidationError):
            NoteView.model_validate(value)

    def test_acceptance_is_exact_revision_and_not_a_model_boolean(self):
        NoteAccept(expected_revision=2)
        with self.assertRaises(ValidationError):
            NoteAccept(expected_revision=2, confirmed=True)
        with self.assertRaises(ValidationError):
            NoteView.model_validate({**note(), "status": "accepted"})
        NoteView.model_validate({**note(), "status": "accepted", "accepted_by": ID,
                                 "accepted_at": NOW})
        with self.assertRaises(ValidationError):
            NoteView.model_validate({**note(), "accepted_by": ID, "accepted_at": NOW})

    def test_export_union_binds_ordered_complete_runs_or_fixed_revision(self):
        ids = [str(uuid4()), ID]
        value = ExportInput(target={"kind": "query_runs", "query_run_ids": ids}, format="csv")
        self.assertEqual([str(i) for i in value.target.query_run_ids], ids)
        ExportInput(target={"kind": "note_revision", "note_id": ID, "revision": 1}, format="json")
        for target in [
            {"kind": "query_runs", "query_run_ids": []},
            {"kind": "query_runs", "query_run_ids": [ID, ID]},
            {"kind": "query_runs", "query_run_ids": [uuid4() for _ in range(17)]},
            {"kind": "note_revision", "note_id": ID, "revision": 0},
            {"kind": "query_runs", "query_run_ids": [ID], "cursor": "page-two"},
        ]:
            with self.subTest(target=target), self.assertRaises(ValidationError):
                ExportInput(target=target, format="csv")

    def test_csv_artifact_is_real_zip_and_not_an_unfinished_result(self):
        value = {
            "id": ID, "job_id": ID, "project_id": ID, "actor_id": ID,
            "target": {"kind": "query_runs", "query_run_ids": [ID]}, "format": "csv",
            "state": "SUCCEEDED", "stage": "COMPLETE", "attempt": 1,
            "progress": {"processed_bytes": 0, "total_bytes": None, "processed_records": 0,
                         "total_records": 0, "file_name": None}, "error": None,
            "result": {"filename": "results.zip", "media_type": "application/zip",
                       "container": "zip", "byte_size": 400, "sha256": "a" * 64,
                       "manifest_sha256": "b" * 64, "row_count": 0},
            "created_at": NOW, "updated_at": NOW,
            "allowed_actions": {"cancel": False, "retry": False, "download": True},
        }
        ExportView.model_validate(value)
        for patch in [{"state": "RUNNING"}, {"job_id": str(uuid4())},
                      {"result": {**value["result"], "filename": "results.csv"}},
                      {"result": {**value["result"], "media_type": "text/csv"}}]:
            with self.subTest(patch=patch), self.assertRaises(ValidationError):
                ExportView.model_validate({**value, **patch})
