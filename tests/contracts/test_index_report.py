import json
import tempfile
import unittest
from pathlib import Path
from uuid import uuid4

from validate_index_report import validate_index_reports
from validate_sync_report import ROOT


class IndexReportValidation(unittest.TestCase):
    def test_captured_index_action_must_match_its_run_and_cannot_fill_missing_evidence(self):
        ident = str(uuid4())
        run = {"id": ident, "source_id": "D12", "acquisition_id": str(uuid4()),
               "source_identity": {"name": "Tatoeba", "publisher": "Tatoeba", "entry_kind": "dataset", "official_url": "https://tatoeba.org"},
               "recipe": {"id": "fixed-v1", "sha256": "b" * 64}, "state": "QUEUED", "stage": "QUEUED", "attempt": 1,
               "created_at": "2026-10-16T12:00:00Z", "updated_at": "2026-10-16T12:00:00Z",
               "progress": {"processed_bytes": 0, "total_bytes": None, "processed_records": 0, "total_records": None, "file_name": None},
               "result": None, "error": None, "allowed_actions": {"cancel": True, "retry": False}}
        action = {"action_id": str(uuid4()), "index_run_id": ident, "job_id": ident, "state": "QUEUED", "existing": False, "run": run}
        listing = {"items": [run], "total": 1, "next_cursor": None, "allowed_actions": {"start": False}}
        (ROOT / "tmp").mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=ROOT / "tmp", prefix="index-contract-") as folder:
            path = Path(folder) / "capture.json"
            path.write_text(json.dumps({"runs": [{"run": run, "start": action, "list": listing}]}), encoding="utf-8")
            valid = validate_index_reports([path], True)
            self.assertEqual(valid["status"], "passed")
            self.assertEqual(valid["validated_response_counts"], {"run": 1, "action": 1, "list": 1})
            action["job_id"] = str(uuid4())
            path.write_text(json.dumps({"actions": [action]}), encoding="utf-8")
            invalid = validate_index_reports([path], True)
            self.assertEqual(invalid["status"], "failed")
            self.assertEqual(invalid["not_recorded"], ["run", "list"])
            self.assertEqual(invalid["failures"][0]["rule"], "ACTION_RUN_ID_STATE_EQUAL")


if __name__ == "__main__":
    unittest.main()
