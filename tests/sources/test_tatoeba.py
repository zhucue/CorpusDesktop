import bz2
import hashlib
import io
import json
import os
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

from pipelines.sources import tatoeba as t

ROOT = Path(__file__).resolve().parents[2]


class Response(io.BytesIO):
    def __init__(self, body, url, size=None, etag='"v1"'):
        super().__init__(body)
        self.status = 200
        self.url = url
        self.headers = {"Content-Length": str(len(body) if size is None else size),
                        "ETag": etag, "Last-Modified": "Sat, 10 Oct 2026 06:29:32 GMT"}

    def geturl(self):
        return self.url


class FakeHTTP:
    def __init__(self, mode="normal"):
        self.mode, self.gets, self.heads = mode, 0, 0

    def open(self, request, timeout):
        url = request.full_url
        body = b"official-body"
        if request.method == "HEAD":
            self.heads += 1
            etag = '"v2"' if self.mode == "post-change" and self.heads > 3 else '"v1"'
            return Response(body, url, etag=etag)
        self.gets += 1
        if self.mode == "short" and url in t.FILES.values():
            return Response(b"short", url, size=len(body))
        if self.mode == "get-change":
            return Response(body, url, etag='"v2"')
        return Response(body, url)


class TatoebaTests(unittest.TestCase):
    def setUp(self):
        self.environment = patch.dict(os.environ, {"TMP": str(ROOT / "tmp"), "TEMP": str(ROOT / "tmp")})
        self.environment.start()
        self.temp = tempfile.TemporaryDirectory(dir=ROOT / "tmp", prefix="tatoeba-test-")
        self.root = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()
        self.environment.stop()

    def receipt(self, name="input", cmn=None, eng=None, links=None):
        directory = self.root / name
        directory.mkdir()
        bodies = [cmn or "1\tcmn\t你好。\tAlice\t2020-01-01 00:00:00\t\\N\n2\tcmn\t你好。\t\\N\t\\N\t\\N\n",
                  eng or "3\teng\tHello.\tBob\t\\N\t\\N\n4\teng\tUnlinked.\tBob\t\\N\t\\N\n",
                  links or "1\t3\n3\t1\n1\t3\n2\t999\n1\t2\n"]
        records = []
        for (filename, url), body in zip(t.FILES.items(), bodies, strict=True):
            path = directory / filename
            raw = bz2.compress(body.encode())
            path.write_bytes(raw)
            records.append({"name": filename, "url": url, "path": str(path), "bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()})
        return {"schema": "tatoeba-acquisition/v1", "files": records, "license_evidence": [], "export_date": "2026-10-10"}

    def test_full_records_direct_edges_quality_and_preserved_attribution(self):
        receipt = self.receipt()
        result = t.parse(receipt, self.root / "output")
        q = result["manifest"]["quality"]
        self.assertEqual((q["cmn_sentences"], q["eng_sentences"], q["direct_edges"]), (2, 2, 1))
        self.assertEqual(q["duplicate_or_reciprocal_edge_rows"], 2)
        self.assertEqual(q["missing_endpoint_rows"], 1)
        self.assertEqual(q["wrong_language_edge_rows"], 1)
        self.assertEqual(q["same_text_distinct_ids"], 1)
        self.assertEqual(q["unlinked_sentences"], 2)
        with closing(sqlite3.connect(self.root / "output/corpus.sqlite3")) as db:
            self.assertEqual(db.execute("SELECT text,owner FROM sentences WHERE id=1").fetchone(), ("你好。", "Alice"))
            self.assertIsNone(db.execute("SELECT owner FROM sentences WHERE id=2").fetchone()[0])
        self.assertFalse(result["manifest"]["published"])
        self.assertTrue(set(t.FILES).issubset({x["name"] for x in result["artifacts"]}))

    def test_duplicate_id_identical_deduplicates_conflict_fails(self):
        row = "1\tcmn\t一\tA\t\\N\t\\N\n"
        receipt = self.receipt(cmn=row * 2)
        self.assertEqual(t.parse(receipt, self.root / "out")["manifest"]["quality"]["duplicate_sentence_rows"], 1)
        other = self.receipt("second", cmn=row + row.replace("一", "二"))
        with self.assertRaisesRegex(t.SourceError, "Conflicting"):
            t.parse(other, self.root / "failed")

    def test_bad_bzip_and_encoding_not_reported_validated(self):
        for index, raw in enumerate((b"not-bzip", bz2.compress(b"\xff\n"), bz2.compress(b"1\tcmn\ttext\tA\t\\N\t\\N\n")[:-5])):
            with self.subTest(index=index):
                receipt = self.receipt(str(index))
                record = receipt["files"][0]
                Path(record["path"]).write_bytes(raw)
                record.update(bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest())
                with self.assertRaises((OSError, UnicodeDecodeError, EOFError)):
                    t.parse(receipt, self.root / f"bad-{index}")
                self.assertFalse((self.root / f"bad-{index}/manifest.json").exists())

    def test_diff_uses_full_ids_text_and_metadata(self):
        prior = t.parse(self.receipt(), self.root / "prior")
        receipt = self.receipt("next", cmn="1\tcmn\t您好。\tAlice\t2020-01-01 00:00:00\t\\N\n5\tcmn\t新增\tA\t\\N\t\\N\n", links="5\t3\n")
        result = t.parse(receipt, self.root / "next-output", previous_database=prior["manifest_path"].parent / "corpus.sqlite3")
        diff = result["manifest"]["diff"]
        self.assertEqual([diff[x] for x in ("sentence_added", "sentence_removed", "sentence_changed", "text_changed", "edge_added", "edge_removed")], [1, 1, 1, 1, 1, 1])
        self.assertEqual(diff["status"], "compared")

    def test_cancel_callback_propagates_and_prevents_manifest(self):
        class Cancelled(Exception):
            pass
        def cancel(_):
            raise Cancelled()
        with self.assertRaises(Cancelled):
            t.parse(self.receipt(), self.root / "cancel", cancel)
        self.assertFalse((self.root / "cancel/manifest.json").exists())

    def test_sql_progress_cancellation_preserves_original_exception(self):
        class Cancelled(Exception):
            pass
        def cancel_sql(event):
            if event['stage'] == 'quality_or_diff':
                raise Cancelled('lease fenced during SQL')
        sentence_rows = ''.join(f'{i}\tcmn\t句{i}\tA\t\\N\t\\N\n' for i in range(10, 8010))
        receipt = self.receipt(cmn=sentence_rows)
        clock = iter(range(10000))
        with patch.object(t.time, 'monotonic', side_effect=lambda: next(clock)), self.assertRaises(Cancelled):
            t.parse(receipt, self.root / 'sql-cancel', cancel_sql)
        self.assertFalse((self.root / 'sql-cancel/manifest.json').exists())

    def test_acquisition_pins_before_get_and_after_get(self):
        events = []
        client = FakeHTTP()
        receipt = t.acquire(self.root / "ok", events.append, _opener=client)
        self.assertEqual(client.heads, 6)
        self.assertEqual(len(receipt["files"]), 3)
        pinned = next(event for event in events if event["stage"] == "pinned")
        self.assertEqual(pinned["expected"], receipt["expected"])
        with self.assertRaises(t.SourceError) as caught:
            t.acquire(self.root / "expected", expected={}, _opener=FakeHTTP())
        self.assertEqual(caught.exception.code, "SOURCE_VERSION_CHANGED")

    def test_metadata_change_never_retries_or_succeeds(self):
        for mode in ("get-change", "post-change"):
            client = FakeHTTP(mode)
            with self.subTest(mode=mode), self.assertRaises(t.SourceError) as caught:
                t.acquire(self.root / mode, _opener=client)
            self.assertEqual(caught.exception.code, "SOURCE_VERSION_CHANGED")
            if mode == "get-change":
                self.assertEqual(client.gets, 1)
            self.assertFalse((self.root / mode / "acquisition.json").exists())

    def test_incomplete_network_body_only_one_retry(self):
        client = FakeHTTP("short")
        with self.assertRaises(t.SourceError):
            t.acquire(self.root / "short", _opener=client)
        self.assertEqual(client.gets, 2)
        error = json.loads((self.root / "short/acquisition-error.json").read_text())
        self.assertEqual(len(error["attempts"]), 2)


if __name__ == "__main__":
    unittest.main()
