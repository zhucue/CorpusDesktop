import json
import tempfile
import unittest
from pathlib import Path

from test_releases import release
from validate_release_report import validate_release_reports

ROOT = Path(__file__).resolve().parents[2]


class ReleaseReportTests(unittest.TestCase):
    def test_absent_http_evidence_is_not_manufactured_and_bad_counts_fail(self):
        directory = ROOT / "tmp/release-contract-tests"
        directory.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=directory) as tmp:
            path = Path(tmp) / "capture.json"
            path.write_text(json.dumps({"releases": [release()]}), encoding="utf-8")
            result = validate_release_reports([path])
            self.assertEqual(result["status"], "passed")
            self.assertEqual(result["validated_response_counts"]["releases"], 1)
            self.assertEqual(result["validated_response_counts"]["policy_actions"], 0)
            self.assertEqual(validate_release_reports([path], True)["status"], "failed")
            body = release(); body["counts"]["tokens"] = "sensitive-invalid-value"
            path.write_text(json.dumps({"releases": [body]}), encoding="utf-8")
            result = validate_release_reports([path])
            self.assertEqual(result["status"], "failed")
            self.assertNotIn("sensitive-invalid-value", json.dumps(result))
