import json
import tempfile
import unittest
from pathlib import Path

from test_research import page
from validate_research_report import validate_research_reports

ROOT = Path(__file__).resolve().parents[2]


class ResearchReportTests(unittest.TestCase):
    def test_report_requires_actual_bodies_and_checks_semantic_spans(self):
        directory = ROOT / "tmp/research-contract-tests"
        directory.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=directory) as temporary:
            path = Path(temporary) / "capture.json"
            path.write_text(json.dumps({"hit_pages": [page()]}), encoding="utf-8")
            result = validate_research_reports([path])
            self.assertEqual(result["status"], "passed")
            self.assertEqual(result["validated_response_counts"]["hit_pages"], 1)
            self.assertEqual(
                validate_research_reports([path], True)["status"], "failed"
            )
            invalid = page()
            invalid["hits"][0]["match"] = "PRIVATE-MATERIAL-WRONG-LENGTH"
            path.write_text(json.dumps({"hit_pages": [invalid]}), encoding="utf-8")
            result = validate_research_reports([path])
            self.assertEqual(result["status"], "failed")
            self.assertNotIn("PRIVATE-MATERIAL", json.dumps(result))
