"""Bounded local-model capacity experiment on concatenated real sentence pairs.

Independent Tatoeba pairs are not document alignment gold. Each size runs in a
fresh process and uses the unchanged local_model path, including batch size 16.
"""

import argparse
import ctypes
import hashlib
import json
import os
import platform
import subprocess
import sys
from pathlib import Path
from time import perf_counter
from unittest.mock import patch

from pipelines.alignment import local_model
from pipelines.alignment.download_model import selected_model, verify_files

ROOT = Path(__file__).resolve().parents[2]


def digest(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def memory():
    """OS process high-water mark, not tracemalloc (which misses ONNX memory)."""
    if os.name == "nt":
        from ctypes import wintypes

        class Counters(ctypes.Structure):
            _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD)] + [
                (name, ctypes.c_size_t) for name in (
                    "PeakWorkingSetSize", "WorkingSetSize", "QuotaPeakPagedPoolUsage",
                    "QuotaPagedPoolUsage", "QuotaPeakNonPagedPoolUsage", "QuotaNonPagedPoolUsage",
                    "PagefileUsage", "PeakPagefileUsage",
                )
            ]

        value = Counters()
        value.cb = ctypes.sizeof(value)
        ctypes.windll.kernel32.GetCurrentProcess.restype = wintypes.HANDLE
        get_info = ctypes.windll.psapi.GetProcessMemoryInfo
        get_info.argtypes = [wintypes.HANDLE, ctypes.POINTER(Counters), wintypes.DWORD]
        if not get_info(ctypes.windll.kernel32.GetCurrentProcess(), ctypes.byref(value), value.cb):
            raise OSError("Cannot measure process memory")
        return {"rss_bytes": value.WorkingSetSize, "peak_rss_bytes": value.PeakWorkingSetSize,
                "peak_commit_bytes": value.PeakPagefileUsage}
    import resource

    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    current = None
    if Path("/proc/self/statm").exists():
        current = int(Path("/proc/self/statm").read_text().split()[1]) * os.sysconf("SC_PAGE_SIZE")
    return {"rss_bytes": current, "peak_rss_bytes": peak * (1 if sys.platform == "darwin" else 1024)}


def prepare_pairs(rows, token_lengths, max_tokens):
    """Keep input order; no truncation or endpoint reuse in the monotonic block."""
    if len(token_lengths) != len(rows) * 2:
        raise ValueError("TOKEN_LENGTH_SHAPE")
    accepted, excluded = [], []
    seen_source, seen_target = set(), set()
    for i, row in enumerate(rows):
        if row["relation"] != "upstream_direct_link" or row["source"]["language"] != "cmn" or row["target"]["language"] != "eng":
            raise ValueError("EXPECTED_DIRECT_CMN_ENG_SAMPLE")
        lengths = token_lengths[2*i:2*i+2]
        if any(length > max_tokens for length in lengths):
            reason = "SEGMENT_TOO_LONG"
        elif row["source"]["id"] in seen_source or row["target"]["id"] in seen_target:
            reason = "REUSED_ENDPOINT"
        else:
            accepted.append(row)
            seen_source.add(row["source"]["id"])
            seen_target.add(row["target"]["id"])
            continue
        excluded.append({"edge_id": row["edge_id"], "reason": reason,
                         "source_tokens": lengths[0], "target_tokens": lengths[1]})
    return accepted, excluded


def make_dataset(pairs, size, sample_sha256):
    if type(size) is not int or not 1 <= size <= 1000 or len(pairs) < size:
        raise ValueError("SIZE_REQUIRES_1_TO_1000_AVAILABLE_PAIRS")
    return {
        "schema_version": "alignment-eval/v1", "dataset_kind": "constructed_smoke",
        "provenance": "Real Tatoeba direct pairs concatenated in fixed sample order. Artificial document; no independent document/domain gold.",
        "snapshot_id": "tatoeba-sample:" + sample_sha256,
        "segmentation_recipe": "upstream-sentence-pairs-concatenated/v1",
        "block_id": f"capacity-{size}", "source_language": "zh", "target_language": "en",
        **{side: [{"id": f"tatoeba:{row[side]['id']}", "revision_id": sample_sha256,
                   "text": row[side]["text"]} for row in pairs[:size]] for side in ("source", "target")},
    }


def correspondence(result, reference):
    predicted = {(pair["source_id"], pair["target_id"]) for pair in result["pairs"]}
    correct = len(predicted & reference)
    return {"quality_status": "NOT_VALIDATED", "comparison": "selected upstream direct pairs in artificial monotonic order",
            "candidate_count": len(predicted), "selected_direct_pair_count": len(reference),
            "candidate_matches_selected_direct_pair": correct,
            "candidate_other_than_selected_direct_pair": len(predicted - reference),
            "selected_direct_pair_recovery_fraction": correct / len(reference) if reference else None,
            "candidates_requiring_review": sum(bool(pair["review_reasons"]) for pair in result["pairs"]),
            "unmatched_source": len(result["unmatched_source"]), "unmatched_target": len(result["unmatched_target"])}


def run_process(command, environment, output, size, timeout):
    started = perf_counter()
    stdout_path, stderr_path = output / f"stdout-{size}.log", output / f"stderr-{size}.log"
    with stdout_path.open("w", encoding="utf-8") as stdout, stderr_path.open("w", encoding="utf-8") as stderr:
        try:
            subprocess.run(command, cwd=ROOT, env=environment, stdout=stdout, stderr=stderr,
                           check=True, timeout=timeout)
        except (subprocess.SubprocessError, OSError) as error:
            failure = {"status": "failed", "size": size, "error_type": type(error).__name__,
                       "error": str(error), "seconds": perf_counter() - started,
                       "stdout": stdout_path.name, "stderr": stderr_path.name}
            (output / f"failure-{size}.json").write_text(json.dumps(failure, indent=2) + "\n", encoding="utf-8")
            raise
    return perf_counter() - started


def child_run(input_path, model_directory, output):
    dataset = json.loads(input_path.read_text(encoding="utf-8"))
    samples = {"before_run": memory()}
    dp = {}
    original = local_model.align

    def measured_align(*args, **kwargs):
        samples["before_dp"] = memory()
        started = perf_counter()
        result = original(*args, **kwargs)
        dp["seconds"] = perf_counter() - started
        samples["after_dp"] = memory()
        return result

    started = perf_counter()
    # Instrument the function boundary; the production function and inputs are
    # unchanged. Avoid a separate implementation of batching, pooling or DP.
    with patch.object(local_model, "align", measured_align):
        result = local_model.run_local(dataset, model_directory)
    wall = perf_counter() - started
    samples["after_run"] = memory()
    reference = {(source["id"], target["id"]) for source, target in zip(dataset["source"], dataset["target"], strict=True)}
    report = {
        "status": "completed", "formal_acceptance": False, "input_sha256": result["input_sha256"],
        "input_file_sha256": digest(input_path), "method_manifest": result["method_manifest"],
        "method_sha256": result["method_sha256"], "segments_per_side": len(dataset["source"]),
        "dp_cells": len(dataset["source"]) * len(dataset["target"]),
        "timing": {"run_local_wall_seconds": wall, "model_load_seconds": result["runtime"]["model_load_seconds"],
                   "encode_seconds": result["runtime"]["encode_seconds"], "dp_seconds": dp["seconds"],
                   "other_seconds": wall - dp["seconds"] - result["runtime"]["model_load_seconds"] - result["runtime"]["encode_seconds"]},
        "memory": samples, "memory_interpretation": "OS process lifetime peak; stages are snapshots, not isolated stage allocations. Each size uses a fresh process.",
        "reference_comparison": correspondence(result, reference),
        "runtime": {**result["runtime"], "peak_memory": "OS measurements in memory section"},
        "network_mode": result["network_mode"], "network_capture_verified": False,
        "batch_size": 16, "truncated_segments": result["truncated_segments"],
        "pairs": result["pairs"], "unmatched_source": result["unmatched_source"], "unmatched_target": result["unmatched_target"],
    }
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--sample", type=Path, default=ROOT / "tmp/sources-s0/20261016-tatoeba-curl/tatoeba-sample.json")
    parser.add_argument("--model-directory", type=Path, default=ROOT / "tmp/alignment-s0/model")
    parser.add_argument("--sizes", type=int, nargs="+", default=[100, 500, 1000])
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--timeout", type=int, default=600, help="Per-size process limit, 1..1800 seconds")
    parser.add_argument("--child-input", type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args()
    if not args.output.resolve().is_relative_to(ROOT / "tmp"):
        parser.error("Raw experiments must remain under repository tmp/")
    if args.output.exists():
        parser.error("Existing evidence is never overwritten")
    if not 1 <= args.timeout <= 1800:
        parser.error("Timeout must be between 1 and 1800 seconds")
    if args.child_input:
        child_run(args.child_input, args.model_directory, args.output)
        return
    if not args.sizes or any(not 1 <= size <= 1000 for size in args.sizes) or len(set(args.sizes)) != len(args.sizes):
        parser.error("Unique sizes between 1 and 1000 required (at most 1 million DP cells)")
    model = selected_model()
    if not verify_files(args.model_directory, model):
        raise local_model.ModelUnavailable("MODEL_UNAVAILABLE: missing or checksum-mismatched local files")
    os.environ["TOKENIZERS_PARALLELISM"] = "false"
    from tokenizers import Tokenizer

    args.output.mkdir(parents=True)
    snapshot = args.output / "sources"
    snapshot.mkdir()
    for name in ("benchmark.py", "local_model.py", "algorithm.py", "model-candidates.json"):
        (snapshot / name).write_bytes((Path(__file__).parent / name).read_bytes())
    rows = json.loads(args.sample.read_text(encoding="utf-8"))
    tokenizer = Tokenizer.from_file(str(args.model_directory / "tokenizer.json"))
    tokenizer.no_truncation()
    tokenizer.no_padding()
    texts = [row[side]["text"] for row in rows for side in ("source", "target")]
    started = perf_counter()
    lengths = []
    for offset in range(0, len(texts), 256):
        lengths.extend(len(item.ids) for item in tokenizer.encode_batch(texts[offset:offset+256]))
    selected, excluded = prepare_pairs(rows, lengths, model["max_tokens"])
    sample_hash = digest(args.sample)
    report = {"status": "running", "formal_acceptance": False, "quality_status": "NOT_VALIDATED",
              "sample_file_sha256": sample_hash, "input_pairs": len(rows), "eligible_unique_pairs": len(selected),
              "exclusions": excluded, "excluded_long_pairs": sum(row["reason"] == "SEGMENT_TOO_LONG" for row in excluded),
              "overlength_segments": sum(length > model["max_tokens"] for length in lengths),
              "max_observed_tokens": max(lengths), "max_tokens_limit": model["max_tokens"],
              "preflight_tokenize_and_select_seconds": perf_counter() - started,
              "selection": "existing deterministic sample order; remove overlength pairs, then greedily keep distinct endpoints; nested prefixes by size",
              "source_sha256": {path.name: digest(path) for path in snapshot.iterdir()},
              "hardware": {"platform": platform.platform(), "python": platform.python_version(), "processor": platform.processor(), "logical_cpus": os.cpu_count(), "dedicated_host": False},
              "limits": {"dp_cells": 1000000, "onnx_intra_op_threads": 2, "onnx_inter_op_threads": 1, "blas_threads": 2, "memory_hard_limit": None, "timeout_per_size_seconds": args.timeout},
              "interpretation": "Fresh-process local CPU capacity on artificial documents concatenated from real independent sentences. Upstream pair recovery is restricted engineering evidence, not domain precision/recall acceptance.",
              "runs": []}
    if len(selected) < max(args.sizes):
        report.update({"status": "failed", "error": "Not enough distinct non-overlength pairs"})
        (args.output / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        raise ValueError(report["error"])
    (args.output / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    for size in args.sizes:
        dataset = make_dataset(selected, size, sample_hash)
        input_path = args.output / f"input-{size}.json"
        input_path.write_text(json.dumps(dataset, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        child_output = args.output / f"result-{size}.json"
        environment = {**os.environ, "OMP_NUM_THREADS": "2", "OPENBLAS_NUM_THREADS": "2", "MKL_NUM_THREADS": "2", "TOKENIZERS_PARALLELISM": "false"}
        command = [sys.executable, "-m", "pipelines.alignment.benchmark", "--child-input", str(input_path),
                   "--model-directory", str(args.model_directory), "--output", str(child_output)]
        try:
            process_wall = run_process(command, environment, args.output, size, args.timeout)
        except (subprocess.SubprocessError, OSError) as error:
            report.update({"status": "failed", "failed_size": size, "error": str(error), "failure_evidence": f"failure-{size}.json"})
            (args.output / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            raise
        run = json.loads(child_output.read_text(encoding="utf-8"))
        run["subprocess_wall_seconds"] = process_wall
        run["raw_result_sha256"] = digest(child_output)
        run.pop("pairs")
        run.pop("unmatched_source")
        run.pop("unmatched_target")
        report["runs"].append(run)
        (args.output / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(json.dumps({"size": size, "timing": run["timing"], "memory": run["memory"]["after_run"], "reference": run["reference_comparison"]}), flush=True)
    report["status"] = "completed"
    (args.output / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
