import bz2
import io
import time
import unittest
from unittest.mock import patch

from pipelines.sources.probe import (
    ROOT,
    Probe,
    parse_detailed,
    parse_sha256sums,
    read_bounded,
    select_pairs,
    unpack_bz2,
)


class SourceProbeTests(unittest.TestCase):
    def test_whole_download_rejects_oversize(self):
        with self.assertRaisesRegex(ValueError, "byte limit"):
            read_bounded(io.BytesIO(b"12345"), 4, prefix=False, deadline=time.monotonic() + 1)

    def test_prefix_download_stops_at_cap(self):
        stream = io.BytesIO(b"1234567")
        self.assertEqual(read_bounded(stream, 4, prefix=True, deadline=time.monotonic() + 1), b"1234")
        self.assertEqual(stream.tell(), 4)

    def test_timeout_prevents_read(self):
        with self.assertRaises(TimeoutError):
            read_bounded(io.BytesIO(b"1"), 4, prefix=False, deadline=time.monotonic() - 1)

    def test_truncated_compressed_file_rejected(self):
        with self.assertRaisesRegex(ValueError, "incomplete"):
            unpack_bz2(bz2.compress(b"hello\n")[:-3])

    def test_expansion_limit(self):
        with self.assertRaisesRegex(ValueError, "decompressed"):
            unpack_bz2(bz2.compress(b"x" * 100), maximum=10)

    def test_detailed_owner_and_unicode_preserved(self):
        data = "4\tcmn\t汉字😀\talice\t2020-01-01\t2021-01-01\n".encode()
        row = parse_detailed(data, "cmn")[4]
        self.assertEqual(row["owner"], "alice")
        self.assertEqual(row["text"], "汉字😀")
        with self.assertRaisesRegex(ValueError, "duplicate"):
            parse_detailed(data + data, "cmn")

    def test_sample_deduplicates_and_keeps_only_direct_endpoints(self):
        links = b"1\t10\n1\t10\n1\t11\n2\t12\n3\t10\n"
        pairs, count = select_pairs(links, {1: {}, 2: {}}, {10: {}, 11: {}}, count=10)
        self.assertEqual(count, 2)
        self.assertEqual(set(pairs), {(1, 10), (1, 11)})
        reverse = b"\n".join(reversed(links.strip().splitlines())) + b"\n"
        self.assertEqual(select_pairs(links, {1: {}}, {10: {}, 11: {}}, 1),
                         select_pairs(reverse, {1: {}}, {10: {}, 11: {}}, 1))

    def test_failed_network_never_claims_download(self):
        probe = Probe(ROOT / "tmp/sources-s0/tests")
        with patch("pipelines.sources.probe.urlopen", side_effect=OSError("offline")), self.assertRaises(OSError):
            probe.get("unavailable.bin", "https://example.invalid/source")
        self.assertEqual(probe.requests[0]["status"], "failed")
        self.assertNotIn("sha256", probe.requests[0])

    def test_current_checksum_parse_preserves_full_hash(self):
        body = ("a" * 64 + "  ./zhwiki-2026-10-01-p1p42.xml.bz2\n").encode()
        rows = parse_sha256sums(body, "https://dumps.wikimedia.org/current/", "zhwiki", "2026-10-01")
        self.assertEqual(rows[0]["sha256"], "a" * 64)
        self.assertTrue(rows[0]["url"].endswith("/zhwiki-2026-10-01-p1p42.xml.bz2"))

    def test_current_checksum_rejects_external_path_and_duplicates(self):
        for name in ["https://bad.invalid/a.xml.bz2", "../zhwiki-2026-10-01-p1p42.xml.bz2"]:
            with self.assertRaises(ValueError):
                parse_sha256sums(("a" * 64 + "  " + name).encode(), "https://dumps.wikimedia.org/", "zhwiki", "2026-10-01")
        row = ("a" * 64 + "  zhwiki-2026-10-01-p1p42.xml.bz2\n").encode()
        with self.assertRaises(ValueError):
            parse_sha256sums(row + row, "https://dumps.wikimedia.org/", "zhwiki", "2026-10-01")


if __name__ == "__main__":
    unittest.main()
