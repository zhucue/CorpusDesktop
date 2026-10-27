import json
import tempfile
import unittest
from pathlib import Path

from validate_sync_report import ROOT, validate_reports


class SyncReportValidation(unittest.TestCase):
    def setUp(self):
        (ROOT / "tmp").mkdir(exist_ok=True)
        self.directory = tempfile.TemporaryDirectory(dir=ROOT / "tmp", prefix="sync-contract-")
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "capture.json"

    def write(self, value):
        self.path.write_text(json.dumps(value), encoding="utf-8")

    def test_missing_evidence_is_reported_and_require_all_fails(self):
        self.write({"lists": [{"items": [], "total": 0, "next_cursor": None,
                               "allowed_actions": {"start": True}}]})
        partial = validate_reports([self.path])
        self.assertEqual(partial["status"], "passed")
        self.assertEqual(partial["validated_response_counts"], {"run": 0, "action": 0, "list": 1})
        self.assertEqual(partial["not_recorded"], ["run", "action"])
        self.assertEqual(validate_reports([self.path], True)["status"], "failed")

    def test_malformed_recorded_body_fails_without_echoing_contents(self):
        self.write({"runs": [{"run": {"private": "do-not-echo"}, "start": {},
                              "list": {"items": [], "total": 0, "next_cursor": None,
                                       "allowed_actions": {"start": True}}}]})
        result = validate_reports([self.path])
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["validated_response_counts"], {"run": 1, "action": 1, "list": 1})
        self.assertEqual(result["not_recorded"], [])
        self.assertTrue(result["failures"])
        self.assertNotIn("do-not-echo", json.dumps(result))
        self.write({"runs": {}})
        with self.assertRaises(TypeError):
            validate_reports([self.path])


if __name__ == "__main__":
    unittest.main()
