import hashlib
import io
import json
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from pipelines.sources import wiki_ranges as ranges


class Response(io.BytesIO):
    status = 206

    def __init__(self, body, **headers):
        super().__init__(body)
        self.headers = {"Content-Range": f"bytes 0-3/{ranges.TOTAL}",
                        "Content-Length": "4", "ETag": '"fixed"', "Last-Modified": "fixed-date", **headers}

    def geturl(self):
        return ranges.BASE + ranges.NAME


class RangeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=ranges.ROOT / "tmp/sources-s0")
        self.addCleanup(self.temp.cleanup)
        self.output = Path(self.temp.name)
        self.state = {"network_bytes_received": 0, "deadline_monotonic": time.monotonic() + 60,
                      "validators": {"etag": '"fixed"', "last-modified": "fixed-date"},
                      "attempts": [], "segments": []}

    def test_changed_version_or_range_is_not_retried(self):
        for headers in ({"ETag": '"changed"'}, {"Content-Range": f"bytes 1-4/{ranges.TOTAL}"}):
            with self.subTest(headers=headers):
                opener = Mock(return_value=Response(b"abcd", **headers))
                with self.assertRaises(ranges.VersionMismatch):
                    ranges.acquire_segment(self.output, self.state, 0, 3, opener)
                self.assertEqual(opener.call_count, 1)
                self.assertEqual(self.state["network_bytes_received"], 0)
                self.assertFalse(list(self.output.glob("*.part")))

    def test_full_response_to_range_is_rejected(self):
        response = Response(b"abcd")
        response.status = 200
        opener = Mock(return_value=response)
        with self.assertRaises(ranges.VersionMismatch):
            ranges.acquire_segment(self.output, self.state, 0, 3, opener)
        self.assertEqual(opener.call_count, 1)

    def test_truncated_body_retries_once_in_separate_file(self):
        opener = Mock(side_effect=[Response(b"ab"), Response(b"abcd")])
        ranges.acquire_segment(self.output, self.state, 0, 3, opener)
        self.assertEqual(opener.call_count, 2)
        self.assertEqual([a["status"] for a in self.state["attempts"]], ["failed", "range_received_unverified"])
        self.assertEqual([p.read_bytes() for p in sorted(self.output.glob("*.part"))], [b"ab", b"abcd"])
        self.assertEqual(self.state["network_bytes_received"], 6)
        self.assertEqual(self.state["segments"][0]["sha256"], hashlib.sha256(b"abcd").hexdigest())

    def test_second_truncation_stops_and_preserves_both_attempts(self):
        opener = Mock(side_effect=[Response(b"a"), Response(b"abc")])
        with self.assertRaisesRegex(OSError, "incomplete"):
            ranges.acquire_segment(self.output, self.state, 0, 3, opener)
        self.assertEqual(opener.call_count, 2)
        self.assertEqual(len(list(self.output.glob("*.part"))), 2)
        self.assertEqual(self.state["segments"], [])

    def test_budget_rejects_before_network(self):
        self.state["network_bytes_received"] = ranges.MAXIMUM - 3
        opener = Mock()
        with self.assertRaisesRegex(ValueError, "budget"):
            ranges.acquire_segment(self.output, self.state, 0, 3, opener)
        opener.assert_not_called()

    def test_mutated_prefix_never_reaches_sampling(self):
        prefix = self.output / "prefix"
        prefix.write_bytes(b"changed")
        state = {"status": "all_ranges_received_unverified", "prefixes": [
            {"local_file": str(prefix.relative_to(ranges.ROOT)), "start": 0,
             "end_inclusive": 6, "bytes": 7, "sha256": hashlib.sha256(b"initial").hexdigest()}], "segments": []}
        (self.output / "range-state.json").write_text(json.dumps(state))
        with patch.object(ranges, "verify_sample") as sample:
            with self.assertRaisesRegex(ValueError, "integrity"):
                ranges.assemble(self.output)
            sample.assert_not_called()


if __name__ == "__main__":
    unittest.main()
