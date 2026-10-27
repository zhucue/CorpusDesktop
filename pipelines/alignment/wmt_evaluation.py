"""Offline public-news document evaluation, separate from project domain gold.

References come from WMT's explicit document/segment IDs, not sentence order.
Selection and the unchanged baseline recipe are written before model inference.
Whole documents with overlong segments are rejected rather than shortened.
"""

import argparse
import hashlib
import json
import platform
import shutil
from dataclasses import asdict
from html.parser import HTMLParser
from pathlib import Path
from time import perf_counter

from pipelines.alignment.algorithm import DEFAULT_RECIPE
from pipelines.alignment.benchmark import digest, memory
from pipelines.alignment.download_model import selected_model, verify_files
from pipelines.alignment.local_model import run_local

ROOT = Path(__file__).resolve().parents[2]
SEED = "corpus-s0-wmt19-documents-v1"
SOURCE_NAME = "newstest2019-zhen-src.zh.sgm"
TARGET_NAME = "newstest2019-zhen-ref.en.sgm"


class DocumentParser(HTMLParser):
    """Read the small official SGML subset without guessing missing identities."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.documents = {}
        self.metadata = None
        self.document = None
        self.segment = None
        self.parts = []

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        if tag in {"srcset", "refset"}:
            if self.metadata is not None:
                raise ValueError("MULTIPLE_SETS")
            self.metadata = {"kind": tag, **attributes}
        elif tag == "doc":
            identifier = attributes.get("docid")
            if not identifier or identifier in self.documents or self.document is not None:
                raise ValueError("MISSING_OR_DUPLICATE_DOCUMENT_ID")
            if attributes.get("origlang") != "zh":
                raise ValueError("EXPECTED_ORIGINAL_CHINESE_DOCUMENT")
            self.document = {"id": identifier, "attributes": attributes, "segments": []}
            self.documents[identifier] = self.document
        elif tag == "seg":
            identifier = attributes.get("id")
            if self.document is None or self.segment is not None or not identifier:
                raise ValueError("INVALID_SEGMENT_STRUCTURE")
            if identifier in {item["id"] for item in self.document["segments"]}:
                raise ValueError("DUPLICATE_SEGMENT_ID")
            self.segment, self.parts = identifier, []
        elif self.segment is not None:
            raise ValueError("UNSUPPORTED_INLINE_MARKUP")

    def handle_data(self, data):
        if self.segment is not None:
            self.parts.append(data)

    def handle_endtag(self, tag):
        if tag == "seg":
            if self.segment is None:
                raise ValueError("INVALID_SEGMENT_STRUCTURE")
            text = "".join(self.parts).strip()
            if not text:
                raise ValueError("EMPTY_SEGMENT")
            self.document["segments"].append({"id": self.segment, "text": text})
            self.segment = None
        elif tag == "doc":
            if self.document is None or self.segment is not None or not self.document["segments"]:
                raise ValueError("INVALID_DOCUMENT_STRUCTURE")
            self.document = None


def parse_sgml(text):
    parser = DocumentParser()
    parser.feed(text)
    parser.close()
    if parser.metadata is None or not parser.documents or parser.document or parser.segment:
        raise ValueError("INCOMPLETE_SGML")
    return parser.metadata, parser.documents


def pair_documents(source_text, target_text):
    source_meta, source = parse_sgml(source_text)
    target_meta, target = parse_sgml(target_text)
    if source_meta["kind"] != "srcset" or target_meta["kind"] != "refset":
        raise ValueError("EXPECTED_SOURCE_AND_REFERENCE")
    if source_meta.get("setid") != target_meta.get("setid"):
        raise ValueError("SET_ID_MISMATCH")
    if source_meta.get("srclang") not in {"any", "zh"} or target_meta.get("srclang") != source_meta.get("srclang") or target_meta.get("trglang") != "en":
        raise ValueError("LANGUAGE_MISMATCH")
    if source.keys() != target.keys():
        raise ValueError("DOCUMENT_ID_MISMATCH")
    documents = []
    for identifier, original in source.items():
        translated = target[identifier]
        source_ids = [item["id"] for item in original["segments"]]
        target_ids = [item["id"] for item in translated["segments"]]
        if source_ids != target_ids:
            raise ValueError("SEGMENT_ID_OR_ORDER_MISMATCH")
        documents.append({"id": identifier, "source": original["segments"], "target": translated["segments"]})
    return documents


def select_documents(documents, limit=800):
    if type(limit) is not int or not 1 <= limit <= 1000:
        raise ValueError("LIMIT_REQUIRES_1_TO_1000")
    selected, total = [], 0
    for document in sorted(documents, key=lambda item: hashlib.sha256((SEED + item["id"]).encode()).hexdigest()):
        count = len(document["source"])
        if total + count <= limit:
            selected.append(document)
            total += count
    if len(selected) < 2:
        raise ValueError("INSUFFICIENT_WHOLE_DOCUMENTS")
    # A deterministic document split, decided before token checks or model output.
    return [{**document, "split": "calibration" if index % 5 == 0 else "test"}
            for index, document in enumerate(selected)]


def make_dataset(document, source_hash, target_hash):
    source_ids = [segment["id"] for segment in document["source"]]
    target_ids = [segment["id"] for segment in document["target"]]
    if source_ids != target_ids or len(source_ids) != len(set(source_ids)):
        raise ValueError("SEGMENT_ID_OR_ORDER_MISMATCH")
    return {
        "schema_version": "alignment-eval/v1", "dataset_kind": "public_benchmark",
        "provenance": "WMT19 real news document, upstream human reference and explicit docid/segid. Public benchmark metrics are separate from project-domain approval.",
        "snapshot_id": f"wmt19:{source_hash}:{target_hash}",
        "segmentation_recipe": "wmt19-upstream-sgml-segments/v1",
        "block_id": document["id"], "source_language": "zh", "target_language": "en",
        "reference_pairs": [[f"zh:{document['id']}:{sid}", f"en:{document['id']}:{sid}"] for sid in source_ids],
        **{side: [{"id": f"{language}:{document['id']}:{segment['id']}", "revision_id": sha,
                   "text": segment["text"]} for segment in document[side]]
           for side, language, sha in (("source", "zh", source_hash), ("target", "en", target_hash))},
    }


def overlong_segments(dataset, tokenizer, maximum):
    rejected = []
    for side in ("source", "target"):
        segments = dataset[side]
        for segment, encoding in zip(segments, tokenizer.encode_batch([item["text"] for item in segments]), strict=True):
            if len(encoding.ids) > maximum:
                rejected.append({"side": side, "id": segment["id"], "tokens": len(encoding.ids)})
    return rejected


def document_metrics(dataset, result):
    reference = {tuple(pair) for pair in dataset["reference_pairs"]}
    predicted = {(pair["source_id"], pair["target_id"]) for pair in result["pairs"]}
    source_positions = {item["id"]: i for i, item in enumerate(dataset["source"])}
    target_positions = {item["id"]: i for i, item in enumerate(dataset["target"])}
    if len(predicted) != len(result["pairs"]) or any(a not in source_positions or b not in target_positions for a, b in predicted):
        raise ValueError("INVALID_CANDIDATE_IDENTITIES")
    wrong = [{"source_id": a, "target_id": b, "ordinal_distance": target_positions[b] - source_positions[a]}
             for a, b in sorted(predicted - reference)]
    return {
        "reference_pairs": len(reference), "candidate_pairs": len(predicted),
        "correct_pairs": len(predicted & reference), "wrong_pairs": wrong,
        "adjacent_sentence_mispairs": sum(abs(item["ordinal_distance"]) == 1 for item in wrong),
        "unpaired_source": len(result["unmatched_source"]), "unpaired_target": len(result["unmatched_target"]),
        "review_candidates": sum(bool(pair["review_reasons"]) for pair in result["pairs"]),
    }


def summarize(records):
    report = {}
    for split in ("calibration", "test"):
        selected = [item for item in records if item["split"] == split]
        completed = [item for item in selected if item["status"] == "completed"]
        total = sum(item["segment_pairs"] for item in selected)
        eligible = sum(item["segment_pairs"] for item in completed)
        sums = {key: sum(item["metrics"][key] for item in completed) for key in (
            "candidate_pairs", "correct_pairs", "adjacent_sentence_mispairs", "unpaired_source",
            "unpaired_target", "review_candidates")}
        predicted, correct = sums["candidate_pairs"], sums["correct_pairs"]
        report[split] = {
            "selected_documents": len(selected), "completed_documents": len(completed),
            "rejected_documents": len(selected) - len(completed), "selected_reference_pairs": total,
            "unevaluated_reference_pairs": total - eligible,
            "overlong_segments": sum(len(item.get("overlong_segments", [])) for item in selected),
            "evaluated_reference_pairs": eligible, **sums,
            "wrong_pairs": predicted - correct,
            "candidate_precision": correct / predicted if predicted else None,
            "reference_recall_eligible": correct / eligible if eligible else None,
            "reference_recall_selected_including_rejected": correct / total if total else None,
            "candidate_coverage_eligible": predicted / eligible if eligible else None,
            "candidate_coverage_selected_including_rejected": predicted / total if total else None,
            "unpaired_rate_eligible": sums["unpaired_source"] / eligible if eligible else None,
            "fully_recovered_documents": sum(item["metrics"]["correct_pairs"] == item["segment_pairs"] for item in completed),
        }
    return report


def split_overlap(documents):
    """Report exact sentence overlap; no threshold or metric-based filtering."""
    overlaps = {}
    for side in ("source", "target"):
        values = {split: {segment["text"] for doc in documents if doc["split"] == split for segment in doc[side]}
                  for split in ("calibration", "test")}
        overlaps[side] = len(values["calibration"] & values["test"])
    return overlaps


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def run(source_directory, model_directory, output, limit=800):
    model = selected_model()
    if not verify_files(model_directory, model):
        raise ValueError("MODEL_FILE_HASH_MISMATCH")
    from tokenizers import Tokenizer

    source_path, target_path = source_directory / SOURCE_NAME, source_directory / TARGET_NAME
    source_hash, target_hash = digest(source_path), digest(target_path)
    documents = pair_documents(source_path.read_text(encoding="utf-8"), target_path.read_text(encoding="utf-8"))
    selected = select_documents(documents, limit)
    output.mkdir(parents=True, exist_ok=False)
    snapshot = output / "source"
    snapshot.mkdir()
    hashes = {}
    for name in ("wmt_evaluation.py", "local_model.py", "algorithm.py", "benchmark.py", "download_model.py", "model-candidates.json", "input.schema.json"):
        original = Path(__file__).with_name(name)
        shutil.copyfile(original, snapshot / name)
        hashes[name] = digest(original)
    plan = {
        "version": "wmt19-document-evaluation/v1", "seed": SEED, "limit": limit,
        "source_sha256": source_hash, "target_sha256": target_hash, "source_hashes": hashes,
        "available_documents": len(documents), "available_segment_pairs": sum(len(doc["source"]) for doc in documents),
        "selected": [{"id": doc["id"], "split": doc["split"], "segment_ids": [seg["id"] for seg in doc["source"]]} for doc in selected],
        "selection": "Sort whole documents by SHA256(seed + docid), greedily include within limit; every fifth selected document is calibration.",
        "overlong_policy": "Reject entire selected document if any source or target segment exceeds 128 tokens; no silent truncation, removal or resegmentation.",
        "recipe": asdict(DEFAULT_RECIPE), "threshold_tuning": "none; calibration reserved, baseline fixed before both splits",
        "model": model, "exact_sentence_overlap_between_splits": split_overlap(selected),
    }
    write_json(output / "plan.json", plan)
    tokenizer = Tokenizer.from_file(str(model_directory / "tokenizer.json"))
    tokenizer.no_truncation()
    tokenizer.no_padding()
    records = []
    started = perf_counter()
    for ordinal, document in enumerate(selected):
        dataset = make_dataset(document, source_hash, target_hash)
        item = {"id": document["id"], "split": document["split"], "segment_pairs": len(document["source"])}
        long_segments = overlong_segments(dataset, tokenizer, model["max_tokens"])
        if long_segments:
            item.update(status="rejected_overlong_document", overlong_segments=long_segments)
        else:
            filename = f"document-{ordinal:03}.json"
            began = perf_counter()
            try:
                result = run_local(dataset, model_directory)
                if result["status"] != "completed_public_benchmark" or result["quality"]["quality_status"] != "NOT_VALIDATED":
                    raise ValueError("PUBLIC_BENCHMARK_MUST_NOT_APPROVE_DOMAIN_QUALITY")
                if result["recipe"] != plan["recipe"]:
                    raise ValueError("BASELINE_RECIPE_CHANGED")
                write_json(output / filename, {"input": dataset, "result": result})
                item.update(status="completed", metrics=document_metrics(dataset, result),
                            wall_seconds=perf_counter() - began, evidence_file=filename,
                            evidence_sha256=digest(output / filename), method_sha256=result["method_sha256"])
            except (ValueError, RuntimeError, MemoryError, OSError) as error:
                item.update(status="failed", error_type=type(error).__name__, error=str(error))
        records.append(item)
        write_json(output / "progress.json", records)
        print(json.dumps({"document": ordinal + 1, "total": len(selected), "status": item["status"]}), flush=True)
    report = {
        "version": plan["version"], "plan_sha256": digest(output / "plan.json"),
        "evaluation_kind": "public_news_document_benchmark", "domain_quality_status": "NOT_VALIDATED",
        "formal_acceptance": False, "synthetic_perturbations": "none",
        "input": {"source_sha256": source_hash, "target_sha256": target_hash},
        "source_hashes": hashes, "recipe": plan["recipe"], "model": model,
        "threshold_tuning": plan["threshold_tuning"], "exact_sentence_overlap_between_splits": split_overlap(selected),
        "metrics": summarize(records), "documents": records,
        "runtime": {"wall_seconds": perf_counter() - started, "python": platform.python_version(),
                    "platform": platform.platform(), "memory": memory(), "environment": "shared Windows host; sequential documents; unchanged local_model CPU threads=2"},
        "limitations": ["Public news reference is not independent project-domain gold.",
                        "Upstream 1:1 reference measures segment correspondence; no split/merge or naturally unpaired gold.",
                        "Existing model training overlap with this public benchmark has not been ruled out.",
                        "Whole-document long-segment rejection is included in selected-set recall and coverage.",
                        "Research use permission does not establish production redistribution or model-egress rights."],
    }
    write_json(output / "report.json", report)
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-directory", type=Path, required=True)
    parser.add_argument("--model-directory", type=Path, default=Path("tmp/alignment-s0/model"))
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--limit", type=int, default=800)
    args = parser.parse_args()
    run(args.source_directory, args.model_directory, args.output, args.limit)
