"""Hand-labelled source mapping and real CWB attribute/boundary checks."""

import json
import shutil
import tempfile
import unittest
from pathlib import Path

from pipelines.query.cwb import cqp_counts, cqp_page_spans
from pipelines.query.cwb_benchmark import Coordinates
from pipelines.query.cwb_paged import page_result
from pipelines.query.engine import QueryError
from pipelines.query.real_corpus import (
    ATTRIBUTES,
    build_index,
    import_conllu,
    map_sentence,
    request,
    term,
    verify_roundtrip,
    write_index_input,
)
from pipelines.query.real_reference import raw_reference

ROOT = Path(__file__).resolve().parents[2]


def row(identifier, form, lemma=None, upos="NOUN"):
    return "\t".join(
        [
            str(identifier),
            form,
            form.lower() if lemma is None else lemma,
            upos,
            "_",
            "_",
            "0",
            "root",
            "_",
            "_",
        ]
    )


def sentence(sid, text, rows, doc=None):
    return (
        (["# newdoc id = " + doc] if doc else [])
        + ["# sent_id = " + sid, "# text = " + text]
        + rows
    )


def fixture():
    blocks = [
        sentence(
            "s1",
            "A A B 😀 &amp; <x>",
            [
                row(1, "A"),
                row(2, "A"),
                row(3, "B", upos="VERB"),
                row(4, "😀", upos="SYM"),
                row(5, "&amp;", upos="SYM"),
                row(6, "<x>", upos="SYM"),
            ],
            "d1",
        ),
        sentence("s2", "A B", [row(1, "A"), row(2, "B", upos="VERB")]),
        sentence("s3", "A", [row(1, "A")], "d2"),
    ]
    return ("\n\n".join("\n".join(block) for block in blocks) + "\n\n").encode()


class SourceMappingTests(unittest.TestCase):
    def test_exact_text_unicode_mwt_empty_nodes_and_byte_anchors(self):
        lines = sentence(
            "s1",
            "  can't  go.😀",
            [
                row("1-2", "can't"),
                row(1, "ca", "can"),
                row(2, "n't", "not"),
                row("2.1", "phantom"),
                row(3, "go"),
                row(4, "."),
                row(5, "😀"),
            ],
            "d",
        )
        raw = ("\n".join(lines) + "\n\n").encode()
        records, ledger, stats = import_conllu(raw, "fixture", "explicit_newdoc")
        self.assertEqual(stats["rejected_sentences"], 0)
        self.assertEqual(records[0]["text"], "  can't  go.😀")
        self.assertEqual(
            [(t["start"], t["end"]) for t in records[0]["tokens"]],
            [(2, 4), (4, 7), (9, 11), (11, 12), (12, 13)],
        )
        self.assertEqual(records[0]["empty_node_rows"][0][0], "2.1")
        self.assertEqual(stats["syntactic_word_tokens"], 5)
        self.assertEqual(stats["multiword_rows_retained"], 1)
        self.assertEqual(
            raw[ledger[0]["raw_byte_start"] : ledger[0]["raw_byte_end"]]
            .decode()
            .splitlines(),
            lines,
        )

    def test_unmappable_or_nonconcatenative_sentence_is_wholly_rejected(self):
        for text, rows in [
            ("du", [row("1-2", "du"), row(1, "de"), row(2, "le")]),
            ("A!B", [row(1, "A"), row(2, "B")]),
            ("A B", [row("1-2", "AB"), row(1, "A"), row(2, "B")]),
        ]:
            with self.subTest(text=text):
                raw = ("\n".join(sentence("x", text, rows)) + "\n\n").encode()
                records, ledger, stats = import_conllu(raw, "fixture", "unavailable")
                self.assertEqual(records, [])
                self.assertEqual(stats["input_blocks"], 1)
                self.assertEqual(stats["rejected_sentences"], 1)
                self.assertIsNotNone(ledger[0]["reason"])

    def test_missing_metadata_duplicate_ids_and_missing_surface_are_reported(self):
        for lines in (
            ["# sent_id = s", row(1, "A")],
            sentence("s", "A A", [row(1, "A"), row(1, "A")]),
            sentence("s", "_", [row(1, "_")]),
        ):
            with self.subTest(lines=lines), self.assertRaises(ValueError):
                map_sentence(lines)
        raw = ("\n".join(sentence("x", "A", [row(1, "A")])) + "\n\n") * 2
        records, ledger, _ = import_conllu(raw.encode(), "fixture", "unavailable")
        self.assertEqual(len(records), 1)
        self.assertEqual(ledger[1]["reason"], "duplicate_sentence_id")

    def test_gsd_records_do_not_invent_document_boundaries(self):
        raw = "\n\n".join(
            "\n".join(sentence(sid, "A", [row(1, "A")])) for sid in ("s1", "s2")
        ).encode()
        records, _, stats = import_conllu(raw, "gsd", "unavailable")
        self.assertEqual(stats["imported_document_units"], 2)
        self.assertEqual(stats["source_document_boundaries"], "unavailable")
        self.assertNotEqual(records[0]["document_id"], records[1]["document_id"])

    def test_raw_oracle_hand_gold_and_sentence_boundary(self):
        work = self.make_work()
        raw = work / "fixture.conllu"
        raw.write_bytes(fixture())
        a = term("form", "A")
        ab = {"type": "sequence", "items": [a, term("form", "B")]}
        oracle = raw_reference(
            raw,
            "fixture",
            "explicit_newdoc",
            {0, 1, 2},
            request({"type": "any_of", "patterns": [a, ab, a]}),
        )
        self.assertEqual(
            oracle["spans"], [(0, 1), (1, 2), (1, 3), (6, 7), (6, 8), (8, 9)]
        )
        self.assertEqual(
            oracle["counts"],
            {"total_hits": 6, "matched_segments": 3, "matched_documents": 2},
        )
        # Last B of s2 and first A of s3 are adjacent globally but never a sentence match.
        ba = request({"type": "sequence", "items": [term("form", "B"), a]})
        self.assertEqual(
            raw_reference(raw, "fixture", "explicit_newdoc", {0, 1, 2}, ba)["spans"], []
        )

    def make_work(self):
        parent = ROOT / "tmp/query-s0/real-tests"
        parent.mkdir(parents=True, exist_ok=True)
        return Path(tempfile.mkdtemp(dir=parent))

    def test_missing_lemma_does_not_remove_sentence_or_become_available(self):
        work = self.make_work()
        raw = "\n".join(sentence("s", "A", [row(1, "A", "_")])).encode()
        records, ledger, _ = import_conllu(raw, "fixture", "unavailable")
        write_index_input(work, records, ledger)
        availability = json.loads((work / "attribute-availability.json").read_text())
        self.assertEqual(len(records), 1)
        self.assertEqual(availability["missing_values"]["lemma"], 1)
        self.assertNotIn("lemma", availability["available_attributes"])
        with self.assertRaisesRegex(QueryError, "ATTRIBUTE_UNAVAILABLE"):
            cqp_page_spans(
                request(term("lemma", "_")),
                "unused",
                allowed_attributes=availability["available_attributes"],
            )


@unittest.skipUnless(
    shutil.which("cqp") and shutil.which("cwb-encode"), "CWB Linux container required"
)
class RealNativeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        parent = ROOT / "tmp/query-s0/real-tests"
        parent.mkdir(parents=True, exist_ok=True)
        cls.work = Path(tempfile.mkdtemp(dir=parent))
        records, ledger, _ = import_conllu(fixture(), "fixture", "explicit_newdoc")
        write_index_input(cls.work, records, ledger)
        build_index(cls.work)
        raw_path = cls.work / "fixture.conllu"
        raw_path.write_bytes(fixture())
        cls.roundtrip = verify_roundtrip(cls.work, raw_path, {0, 1, 2})
        cls.coordinates = Coordinates(cls.work)

    @classmethod
    def tearDownClass(cls):
        cls.coordinates.close()

    def test_real_index_hand_labelled_pos_lemma_unicode_entities(self):
        self.assertEqual(self.roundtrip["decoded_tokens"], 9)
        self.assertTrue(self.roundtrip["all_word_lemma_upos_equal"])
        for attr, value, spans in [
            ("lemma", "a", [(0, 1), (1, 2), (6, 7), (8, 9)]),
            ("upos", "VERB", [(2, 3), (7, 8)]),
            ("form", "😀", [(3, 4)]),
        ]:
            with self.subTest(attr=attr, value=value):
                page = page_result(
                    request(term(attr, value)),
                    self.work / "registry",
                    self.coordinates,
                    allowed_attributes=ATTRIBUTES,
                )
                self.assertEqual(page["spans"], spans)
                self.assertIsNone(page["total_hits"])
                if value == "😀":
                    self.assertEqual(
                        page["page"][0],
                        {
                            "revision_id": "fixture:s1",
                            "start": 6,
                            "end": 7,
                            "left": "A A B ",
                            "match": "😀",
                            "right": " &amp; <x>",
                        },
                    )

        # Numbered VRT preserves both literals in roundtrip; existing S0 query
        # quoting restrictions remain explicit rather than broadening this task.
        for value in ("&amp;", "<x>"):
            with self.assertRaisesRegex(QueryError, "QUERY_UNSUPPORTED"):
                cqp_page_spans(
                    request(term("form", value)),
                    self.work / "registry",
                    allowed_attributes=ATTRIBUTES,
                )

    def test_gap_or_dedup_full_counts_and_sentence_boundary(self):
        a, b = term("form", "A"), term("form", "B")
        gap = {"type": "sequence", "items": [a, {"type": "gap", "min": 0, "max": 1}, b]}
        two = {
            "type": "sequence",
            "items": [
                a,
                {"type": "gap", "min": 0, "max": 1},
                b,
                {"type": "gap", "min": 0, "max": 1},
                term("form", "😀"),
            ],
        }
        cases = [
            (gap, [(0, 3), (1, 3), (6, 8)], (3, 2, 1)),
            (two, [(0, 4), (1, 4)], (2, 1, 1)),
            (
                {"type": "any_of", "patterns": [a, gap, a]},
                [(0, 1), (0, 3), (1, 2), (1, 3), (6, 7), (6, 8), (8, 9)],
                (7, 3, 2),
            ),
            ({"type": "sequence", "items": [b, a]}, [], (0, 0, 0)),
        ]
        for pattern, spans, counts in cases:
            with self.subTest(pattern=pattern):
                query = request(pattern)
                self.assertEqual(
                    cqp_page_spans(
                        query, self.work / "registry", allowed_attributes=ATTRIBUTES
                    ),
                    spans,
                )
                self.assertEqual(
                    cqp_counts(
                        query,
                        self.work / "registry",
                        document_attribute="doc",
                        allowed_attributes=ATTRIBUTES,
                    ),
                    dict(
                        zip(
                            ("total_hits", "matched_segments", "matched_documents"),
                            counts,
                            strict=True,
                        )
                    ),
                )
        with self.assertRaisesRegex(QueryError, "sentence scope"):
            page_result(
                {**request(a), "within": "paragraph"},
                self.work / "registry",
                self.coordinates,
            )


if __name__ == "__main__":
    unittest.main()
