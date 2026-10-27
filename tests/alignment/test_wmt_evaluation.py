"""Identity, split and denominator checks; no model inference in these tests."""

import copy
import json
import unittest
from pathlib import Path
from types import SimpleNamespace

from jsonschema import ValidationError, validate

from pipelines.alignment.algorithm import evaluate
from pipelines.alignment.wmt_evaluation import (
    document_metrics,
    make_dataset,
    overlong_segments,
    pair_documents,
    select_documents,
    split_overlap,
    summarize,
)


def sgml(kind, docs):
    language = ' trglang="en"' if kind == "refset" else ""
    body = "".join(f'<doc docid="{identifier}" origlang="zh"><p>' + "".join(
        f'<seg id="{sid}">{text}</seg>' for sid, text in segments) + "</p></doc>"
        for identifier, segments in docs)
    return f'<{kind} setid="newstest2019" srclang="any"{language}>{body}</{kind}>'


def doc(identifier, count=3):
    return {"id": identifier, **{side: [{"id": str(i), "text": f"{side}-{identifier}-{i}"}
                                      for i in range(1, count + 1)] for side in ("source", "target")}}


class WmtEvaluationTests(unittest.TestCase):
    def test_pairing_uses_explicit_document_ids_not_file_order(self):
        source = sgml("srcset", [("a", [("7", "甲 &amp; 乙")]), ("b", [("3", "丙")])])
        target = sgml("refset", [("b", [("3", "B")]), ("a", [("7", "A &amp; B")])])
        paired = pair_documents(source, target)
        self.assertEqual(paired[0]["source"][0]["text"], "甲 & 乙")
        self.assertEqual(paired[0]["target"][0]["text"], "A & B")
        self.assertEqual(paired[0]["target"][0]["id"], "7")

    def test_missing_duplicate_or_reordered_ids_are_rejected(self):
        source = sgml("srcset", [("a", [("1", "甲"), ("2", "乙")])])
        for target, reason in (
            (sgml("refset", [("b", [("1", "A"), ("2", "B")])]), "DOCUMENT_ID"),
            (sgml("refset", [("a", [("1", "A")])]), "SEGMENT_ID"),
            (sgml("refset", [("a", [("2", "B"), ("1", "A")])]), "SEGMENT_ID"),
            (sgml("refset", [("a", [("1", "A"), ("1", "B")])]), "DUPLICATE_SEGMENT"),
        ):
            with self.subTest(reason=reason), self.assertRaisesRegex(ValueError, reason):
                pair_documents(source, target)

    def test_whole_document_selection_is_deterministic_and_disjoint(self):
        original = [doc(str(i), 2 + i % 4) for i in range(30)]
        selected = select_documents(original, 50)
        self.assertEqual(selected, select_documents(list(reversed(original)), 50))
        calibration = {item["id"] for item in selected if item["split"] == "calibration"}
        test = {item["id"] for item in selected if item["split"] == "test"}
        self.assertTrue(calibration and test)
        self.assertFalse(calibration & test)
        self.assertLessEqual(sum(len(item["source"]) for item in selected), 50)
        by_id = {item["id"]: item for item in original}
        for item in selected:
            self.assertEqual(item["source"], by_id[item["id"]]["source"])
        self.assertEqual(split_overlap(selected), {"source": 0, "target": 0})

    def test_public_benchmark_schema_does_not_assert_domain_gold(self):
        dataset = make_dataset(doc("news"), "s-hash", "t-hash")
        schema = json.loads(Path("pipelines/alignment/input.schema.json").read_text(encoding="utf-8"))
        validate(dataset, schema)
        result = evaluate({}, dataset)
        self.assertEqual(result["quality_status"], "NOT_VALIDATED")
        self.assertIn("Public benchmark", result["reason"])
        dataset["dataset_kind"] = "domain_gold"
        with self.assertRaises(ValidationError):
            validate(dataset, schema)
        self.assertIn("Constructed", evaluate({}, {"dataset_kind": "constructed_smoke"})["reason"])

    def test_overlong_detection_preserves_whole_document_and_exact_ids(self):
        dataset = make_dataset(doc("long"), "s", "t")
        original = copy.deepcopy(dataset)

        class Tokenizer:
            def encode_batch(self, texts):
                return [SimpleNamespace(ids=[0] * (129 if text.endswith("-2") else 128)) for text in texts]

        rejected = overlong_segments(dataset, Tokenizer(), 128)
        self.assertEqual([item["id"] for item in rejected], ["zh:long:2", "en:long:2"])
        self.assertEqual(dataset, original)

    def test_metrics_distinguish_adjacent_mismatch_and_unpaired(self):
        dataset = make_dataset(doc("news"), "s", "t")
        result = {"pairs": [
            {"source_id": "zh:news:1", "target_id": "en:news:1", "review_reasons": []},
            {"source_id": "zh:news:2", "target_id": "en:news:3", "review_reasons": ["ambiguous"]},
        ], "unmatched_source": ["zh:news:3"], "unmatched_target": ["en:news:2"]}
        metrics = document_metrics(dataset, result)
        self.assertEqual(metrics["correct_pairs"], 1)
        self.assertEqual(metrics["candidate_pairs"], 2)
        self.assertEqual(metrics["adjacent_sentence_mispairs"], 1)
        self.assertEqual(metrics["unpaired_source"], 1)
        self.assertEqual(metrics["review_candidates"], 1)

    def test_rejected_documents_remain_in_selected_denominator(self):
        records = [
            {"split": "test", "status": "completed", "segment_pairs": 3, "metrics": {
                "candidate_pairs": 2, "correct_pairs": 2, "adjacent_sentence_mispairs": 0,
                "unpaired_source": 1, "unpaired_target": 1, "review_candidates": 0}},
            {"split": "test", "status": "rejected_overlong_document", "segment_pairs": 7,
             "overlong_segments": [{"id": "long", "tokens": 129}]},
        ]
        metrics = summarize(records)["test"]
        self.assertEqual(metrics["candidate_precision"], 1)
        self.assertEqual(metrics["reference_recall_eligible"], 2 / 3)
        self.assertEqual(metrics["reference_recall_selected_including_rejected"], 2 / 10)
        self.assertEqual(metrics["unevaluated_reference_pairs"], 7)
        self.assertEqual(metrics["overlong_segments"], 1)


if __name__ == "__main__":
    unittest.main()
