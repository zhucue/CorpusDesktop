"""Actual CQP pagination against hand-enumerated spans, not self-generated gold."""

import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from pipelines.query.cwb import cqp_counts, cqp_page_spans, cqp_spans
from pipelines.query.cwb_benchmark import OFFSET, TOKEN, Coordinates
from pipelines.query.cwb_paged import page_result
from pipelines.query.engine import QueryError

ROOT = Path(__file__).resolve().parents[2]


def atom(value):
    return {"type": "term", "attr": "form", "op": "eq", "value": value}


def query(pattern):
    return {
        "dsl_version": "corpus-query/v1",
        "unit": "token",
        "within": "sentence",
        "overlap": "all",
        "pattern": pattern,
    }


class BoundaryTests(unittest.TestCase):
    def test_invalid_page_is_rejected_before_executing_cqp(self):
        for options in ({"offset": -1}, {"offset": True}, {"limit": 0}, {"limit": 51}):
            with self.subTest(options=options), self.assertRaises(ValueError):
                cqp_page_spans(query(atom("A")), "unused", **options)

    def test_paragraph_count_is_explicitly_unsupported(self):
        with self.assertRaisesRegex(QueryError, "sentence scope"):
            page_result({**query(atom("A")), "within": "paragraph"}, "unused", None)
        with self.assertRaisesRegex(QueryError, "sentence scope"):
            cqp_counts(
                {**query(atom("A")), "within": "paragraph"},
                "unused",
                document_attribute="doc",
            )


@unittest.skipUnless(
    shutil.which("cqp") and shutil.which("cwb-encode"), "CWB Linux container required"
)
class NativePagedTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        parent = ROOT / "tmp/query-s0/cwb-paged-tests"
        parent.mkdir(parents=True, exist_ok=True)
        cls.work = Path(tempfile.mkdtemp(dir=parent))
        cls.registry = cls.work / "registry"
        cls.registry.mkdir()
        data = cls.work / "data"
        data.mkdir()
        cls.fixture = json.loads(
            (ROOT / "tests/golden/query-v1.json").read_text(encoding="utf-8")
        )
        lines = []
        with (
            (cls.work / "tokens.map").open("wb") as tokens,
            (cls.work / "revisions.jsonl").open("wb") as texts,
            (cls.work / "revision-offsets.map").open("wb") as offsets,
        ):
            for ordinal, revision in enumerate(cls.fixture["revisions"]):
                lines.extend(["<doc>", "<p>"])
                for left, right in revision["sentences"]:
                    lines.append("<s>")
                    for token in revision["tokens"]:
                        if left <= token["start"] and token["end"] <= right:
                            lines.append(token["attrs"]["form"])
                            tokens.write(
                                TOKEN.pack(ordinal, token["start"], token["end"])
                            )
                    lines.append("</s>")
                lines.extend(["</p>", "</doc>"])
                offsets.write(OFFSET.pack(texts.tell()))
                texts.write(
                    (json.dumps(revision, ensure_ascii=False) + "\n").encode("utf-8")
                )
        vrt = cls.work / "input.vrt"
        vrt.write_text("\n".join(lines) + "\n", encoding="utf-8")
        for command in (
            [
                "cwb-encode",
                "-d",
                str(data),
                "-c",
                "utf8",
                "-f",
                str(vrt),
                "-R",
                str(cls.registry / "s0"),
                "-S",
                "s",
                "-S",
                "p",
                "-S",
                "doc",
            ],
            ["cwb-makeall", "-r", str(cls.registry), "-V", "S0"],
        ):
            subprocess.run(command, check=True, capture_output=True)
        cls.coordinates = Coordinates(cls.work)

    @classmethod
    def tearDownClass(cls):
        cls.coordinates.close()

    def expected_page(self, spans):
        texts = {r["revision_id"]: r["text"] for r in self.fixture["revisions"]}
        return [
            {
                "revision_id": rid,
                "start": start,
                "end": end,
                "left": texts[rid][max(0, start - 40) : start],
                "match": texts[rid][start:end],
                "right": texts[rid][end : end + 40],
            }
            for rid, start, end in spans
        ]

    def test_hand_gold_full_counts_and_exact_kwic_pages(self):
        checked = 0
        for case in self.fixture["cases"]:
            if case["unit"] != "token" or "condition" in case:
                continue
            request = query(case["pattern"])
            with self.subTest(case=case["name"]):
                page = page_result(request, self.registry, self.coordinates)
                self.assertEqual(page["page"], self.expected_page(case["expected"]))
                for name in ("total_hits", "matched_segments", "matched_documents"):
                    self.assertIsNone(page[name])
                self.assertEqual(page["count_status"], "pending")
                self.assertEqual(
                    page["spans"], sorted(cqp_spans(request, self.registry))
                )
                counts = cqp_counts(request, self.registry, document_attribute="doc")
                self.assertEqual(
                    counts,
                    {
                        "total_hits": len(case["expected"]),
                        "matched_segments": case["segments"],
                        "matched_documents": len(
                            {span[0] for span in case["expected"]}
                        ),
                    },
                )
            checked += 1
        self.assertGreaterEqual(checked, 7)

    def test_duplicate_union_nested_spans_and_nonfirst_page(self):
        request = query(
            {
                "type": "any_of",
                "patterns": [
                    atom("A"),
                    {"type": "sequence", "items": [atom("A"), atom("A")]},
                    atom("A"),
                ],
            }
        )
        expected = [["r1", 0, 1], ["r1", 0, 3], ["r1", 2, 3], ["r1", 11, 12]]
        self.assertEqual(
            page_result(request, self.registry, self.coordinates)["page"],
            self.expected_page(expected),
        )
        page = page_result(request, self.registry, self.coordinates, offset=1, limit=2)
        self.assertEqual(page["page"], self.expected_page(expected[1:3]))
        self.assertEqual(
            cqp_counts(request, self.registry, document_attribute="doc"),
            {"total_hits": 4, "matched_segments": 2, "matched_documents": 1},
        )
        self.assertEqual(
            page_result(request, self.registry, self.coordinates, offset=99)["page"], []
        )

    def test_unicode_codepoint_mapping_and_missing_structure_failure(self):
        request = query(atom("😀"))
        self.assertEqual(
            page_result(request, self.registry, self.coordinates)["page"],
            self.expected_page([["r2", 4, 5]]),
        )
        with self.assertRaises(RuntimeError):
            cqp_counts(request, self.registry, document_attribute="missing")

    def test_empty_nqr_has_empty_page_then_completed_zero_counts(self):
        request = query(atom("not-in-fixture"))
        page = page_result(request, self.registry, self.coordinates)
        self.assertEqual(page["page"], [])
        self.assertIsNone(page["total_hits"])
        self.assertEqual(
            cqp_counts(request, self.registry, document_attribute="doc"),
            {"total_hits": 0, "matched_segments": 0, "matched_documents": 0},
        )
