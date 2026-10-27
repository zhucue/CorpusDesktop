"""Real CQP bounded pages under concurrent independent complete-count load.

Reuses a completed cwb_benchmark corpus byte for byte. Each of five request
workers launches a page call and an independent count task, then waits for both
before accepting its next request. No performance result is formal acceptance.
"""

import argparse
import hashlib
import heapq
import json
import platform
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from pipelines.query.benchmark import read_if_exists
from pipelines.query.cwb import cqp_counts, cqp_spans
from pipelines.query.cwb_benchmark import (
    Coordinates,
    DiskSampler,
    create_measured_executable,
    digest,
    expected_count,
    percentile95,
)
from pipelines.query.cwb_paged import page_result
from pipelines.query.reference_counts import count as independent_count

ROOT = Path(__file__).resolve().parents[2]
SOURCE_PATHS = [
    "pipelines/query/cwb.py",
    "pipelines/query/cwb_paged.py",
    "pipelines/query/cwb_paged_benchmark.py",
    "pipelines/query/cwb_benchmark.py",
    "pipelines/query/benchmark.py",
    "pipelines/query/reference_counts.py",
    "contracts/semantics.py",
    "contracts/schemas/corpus-query.schema.json",
]


def page_hash(page):
    return hashlib.sha256(json.dumps(page, sort_keys=True).encode()).hexdigest()


def _replace_report(pending, destination):
    # A Windows reader may briefly deny replacement through the Docker bind mount.
    # Retry only this observed transient error; keep the previous report intact.
    for attempt in range(5):
        try:
            pending.replace(destination)
            return
        except PermissionError:
            if attempt == 4:
                raise
            time.sleep(0.05 * (2**attempt))  # At most 0.75 seconds in total.


def exact_reference(query, directory, coordinates, templates, size, previous):
    """Full dump is an untimed correctness reference, not the bounded-page metric."""
    started = time.perf_counter()
    spans = cqp_spans(query, directory / "registry", timeout=125)
    result = coordinates.page_and_counts(spans)
    expected_hits = expected_count(query, templates, size)
    expected_documents = sum(
        independent_count(query, item) > 0 for item in templates
    ) * (size // 2000)
    expected = {
        "total_hits": expected_hits,
        "matched_segments": expected_documents,
        "matched_documents": expected_documents,
    }
    if any(result[name] != value for name, value in expected.items()):
        raise AssertionError(
            "Full reference differs from independent raw-template counts"
        )
    if page_hash(result["page"]) != previous["first_page_sha256"]:
        raise AssertionError(
            "Complete result first 50 differs from historical full-dump baseline"
        )
    return {
        **expected,
        "spans": heapq.nsmallest(50, spans),
        "page": result["page"],
        "page_sha256": page_hash(result["page"]),
        "reference_seconds_excluded_from_measurement": time.perf_counter() - started,
    }


def summarize(rows):
    return {
        "requests": len(rows),
        "first_page_p95_seconds": percentile95(
            [row["first_page_seconds"] for row in rows]
        ),
        "count_completion_p95_seconds": percentile95(
            [row["count_completion_seconds"] for row in rows]
        ),
        "max_count_completion_seconds": max(
            row["count_completion_seconds"] for row in rows
        ),
        "page_raw_cqp_p95_seconds": percentile95(
            [row["page_raw_cqp"]["wall_seconds"] for row in rows]
        ),
        "count_raw_cqp_p95_seconds": percentile95(
            [row["count_raw_cqp"]["wall_seconds"] for row in rows]
        ),
        "requests_with_actual_page_count_overlap": sum(
            row["page_count_overlap_seconds"] > 0 for row in rows
        ),
        "count_finished_before_page": sum(
            row["count_finished_before_page"] for row in rows
        ),
    }


def main():
    import resource

    parser = argparse.ArgumentParser()
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--repeats", type=int, default=20)
    parser.add_argument("--concurrency", type=int, default=5)
    args = parser.parse_args()
    baseline_directory, target = args.baseline.resolve(), args.output.resolve()
    temp = (ROOT / "tmp").resolve()
    if (
        not all(path.is_relative_to(temp) for path in (baseline_directory, target))
        or min(args.repeats, args.concurrency) < 1
    ):
        parser.error(
            "Both directories must be under repository tmp/; counts must be positive"
        )
    baseline_path = baseline_directory / "report.json"
    baseline = json.loads(baseline_path.read_text(encoding="utf-8"))
    size = baseline["actual"]["tokens"]
    if (
        baseline["status"] != "completed"
        or len(baseline["queries"]) != 20
        or size % 2000
    ):
        parser.error(
            "A completed 20-query full-template-cycle CWB baseline is required"
        )
    target.mkdir(parents=True, exist_ok=False)
    timing = target / "timing"
    timing.mkdir()
    for name in SOURCE_PATHS:
        snapshot = target / "source" / name
        snapshot.parent.mkdir(parents=True, exist_ok=True)
        snapshot.write_bytes((ROOT / name).read_bytes())
    started = time.perf_counter()
    sampler = DiskSampler(target)
    sampler.thread.start()
    report = {
        "status": "verifying_inputs",
        "formal_acceptance": False,
        "engine": "CWB/CQP 3.5.0 bounded NQR dump plus independent native exact counts",
        "baseline_report": str(baseline_path),
        "baseline_report_sha256": digest(baseline_path),
        "original_baseline_preserved": True,
        "tokens": size,
        "queries": baseline["queries"],
        "repeats": args.repeats,
        "concurrency": args.concurrency,
        "code_sha256": {
            name: digest(target / "source" / name) for name in SOURCE_PATHS
        },
        "hardware": {
            "platform": platform.platform(),
            "python": platform.python_version(),
            "cpu_max": read_if_exists("/sys/fs/cgroup/cpu.max"),
            "memory_max": read_if_exists("/sys/fs/cgroup/memory.max"),
            "independent_host": False,
            "storage": "Windows workspace bind mount; disk type not verified",
        },
        "scheduling": "Closed-loop request pool: each of 5 workers submits one independent count task to a separate 5-worker pool, executes its page call concurrently, then waits for count before taking the next request. Thus at most 5 page and 5 count CQP processes contend on 4 CPUs; actual overlap is recorded per request. Concurrency values are configurable for smoke only.",
        "first_page_measurement": "Full internal NQR matching and union, bounded dump of first 50 spans, persisted Unicode coordinate mapping and actual KWIC. Public counts stay null/pending. No query cut or match limit is used.",
        "count_measurement": "Independent CQP subprocess re-matches all branches, unions full spans, obtains size plus unique sentence/document expansions. Completion time includes count queue delay from the same request start. No spans are exported for counting.",
        "timing_notes": [
            "Fresh subprocess startup and instrumentation wrapper startup are included; wrapper script creation occurs before request start.",
            "First-execution runs occur after correctness preparation; OS page cache is not evicted and this is not cold-disk latency.",
            "Each raw CQP child metric includes output and any pipe backpressure; parent API wall time includes scheduling.",
            "No deployed API, permissions, network, or job queue is measured. Background count work here is a real separate subprocess coordinated by a local thread pool.",
        ],
        "data_scope": "Identical prebuilt synthetic baseline: 20 repeated 100-token templates, seed 20261016, one revision=document=sentence. p is explicitly the document structural attribute only for this recipe.",
        "scope_limit": "Combined paged/count interface supports positive token queries within sentence only; paragraph counts explicitly rejected. Golden fixture separately verifies multiple sentences per document.",
        "references": [],
        "first_execution_runs": [],
        "warmup_runs": [],
        "runs": [],
        "official_references": [
            "https://cwb.sourceforge.io/files/CQP_Manual/3_3.html",
            "https://cwb.sourceforge.io/files/CQP_Manual/3_5.html",
            "https://cwb.sourceforge.io/files/CQP_Tutorial/3_1.html",
            "https://cwb.sourceforge.io/files/CQP_Tutorial/4_2.html",
            "https://cwb.sourceforge.io/files/CQP_Tutorial/7_1.html",
        ],
    }

    def save():
        usage = resource.getrusage(resource.RUSAGE_SELF)
        report["wall_seconds"] = time.perf_counter() - started
        report["memory"] = {
            "parent_max_rss_bytes": usage.ru_maxrss * 1024,
            "child_max_rss_bytes": resource.getrusage(
                resource.RUSAGE_CHILDREN
            ).ru_maxrss
            * 1024,
            "cgroup_peak_bytes_including_file_cache": read_if_exists(
                "/sys/fs/cgroup/memory.peak"
            ),
        }
        report["parent_cpu_seconds_including_references"] = (
            usage.ru_utime + usage.ru_stime
        )
        report["sampled_new_experiment_disk_peak_bytes"] = sampler.peak
        report["disk_sampling_interval_seconds"] = 0.25
        report["disk_peak_is_exact"] = False
        pending = target / "report.next.json"
        pending.write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        _replace_report(pending, target / "report.json")

    coordinates = None
    try:
        for name, info in baseline["files"].items():
            if digest(baseline_directory / name) != info["sha256"]:
                raise AssertionError(f"Baseline input/index changed: {name}")
        report["input_and_index_files"] = baseline["files"]
        report["identical_input_index_hashes_verified"] = True
        report["prebuilt_index_and_mapping_disk_bytes"] = baseline["built_disk_bytes"]
        report["original_index_build_seconds"] = baseline["total_build_seconds"]
        templates = []
        with (baseline_directory / "revisions.jsonl").open(encoding="utf-8") as source:
            for _ in range(20):
                revision = json.loads(next(source))
                templates.append(
                    {
                        "text": revision["text"],
                        "tokens": [
                            {"attrs": {"form": word}}
                            for word in revision["text"].split()
                        ],
                    }
                )
        coordinates = Coordinates(baseline_directory)
        report["status"] = "preparing_full_correctness_references"
        save()
        for qid, query in enumerate(report["queries"]):
            reference = exact_reference(
                query,
                baseline_directory,
                coordinates,
                templates,
                size,
                baseline["cold_runs"][qid],
            )
            report["references"].append(reference)
            print(
                json.dumps(
                    {"stage": "references", "completed": qid + 1, "requested": 21}
                ),
                flush=True,
            )
        high = baseline["high_frequency_gap"]["query"]
        report["high_frequency_reference"] = exact_reference(
            high,
            baseline_directory,
            coordinates,
            templates,
            size,
            baseline["high_frequency_gap"]["run"],
        )
        report["correctness_preparation_seconds_excluded"] = (
            time.perf_counter() - started
        )
        report["status"] = "measuring"
        save()

        with ThreadPoolExecutor(
            max_workers=args.concurrency, thread_name_prefix="exact-count"
        ) as count_pool:

            def run_request(query, reference, name, count_timeout=30):
                page_wrapper, page_log = create_measured_executable(
                    timing, name + "-page", 30
                )
                count_wrapper, count_log = create_measured_executable(
                    timing, name + "-count", count_timeout
                )
                request_started = time.perf_counter()
                count_submitted = request_started

                def count_task():
                    count_started = time.perf_counter()
                    counts = cqp_counts(
                        query,
                        baseline_directory / "registry",
                        document_attribute="p",
                        executable=str(count_wrapper),
                        timeout=count_timeout + 5,
                    )
                    count_ended = time.perf_counter()
                    expected = {
                        key: reference[key]
                        for key in (
                            "total_hits",
                            "matched_segments",
                            "matched_documents",
                        )
                    }
                    if counts != expected:
                        raise AssertionError(
                            "Background exact counts differ from independent complete reference"
                        )
                    return counts, count_started, count_ended

                future = count_pool.submit(count_task)
                page_started = time.perf_counter()
                try:
                    page = page_result(
                        query,
                        baseline_directory / "registry",
                        coordinates,
                        executable=str(page_wrapper),
                        timeout=35,
                    )
                    page_ended = time.perf_counter()
                except BaseException:
                    future.result()  # Observe/finish the bounded sibling; do not leave work behind.
                    raise
                counts, count_started, count_ended = future.result()
                if (
                    page["page"] != reference["page"]
                    or page["spans"] != reference["spans"]
                ):
                    raise AssertionError(
                        "Bounded page differs span-by-span or KWIC-by-KWIC from full result"
                    )
                if any(
                    page[key] is not None
                    for key in ("total_hits", "matched_segments", "matched_documents")
                ):
                    raise AssertionError("Unfinished page published a total")
                return {
                    "name": name,
                    "first_page_seconds": page_ended - request_started,
                    "count_completion_seconds": count_ended - request_started,
                    "count_queue_seconds": count_started - count_submitted,
                    "count_compute_seconds": count_ended - count_started,
                    "page_started_at_seconds": page_started - started,
                    "page_finished_at_seconds": page_ended - started,
                    "count_started_at_seconds": count_started - started,
                    "count_finished_at_seconds": count_ended - started,
                    "page_count_overlap_seconds": max(
                        0,
                        min(page_ended, count_ended) - max(page_started, count_started),
                    ),
                    "count_finished_before_page": count_ended <= page_ended,
                    "page_raw_cqp": json.loads(page_log.read_text()),
                    "count_raw_cqp": json.loads(count_log.read_text()),
                    "page_rows": len(page["page"]),
                    "page_sha256": page_hash(page["page"]),
                    "page_counts_before_completion": {
                        key: page[key]
                        for key in (
                            "total_hits",
                            "matched_segments",
                            "matched_documents",
                        )
                    },
                    "complete_counts": counts,
                    "count_status": "completed",
                    "page_exactly_matches_complete_result": True,
                    "all_counts_match_independent_reference": True,
                }

            for qid, query in enumerate(report["queries"]):
                report["first_execution_runs"].append(
                    run_request(query, report["references"][qid], f"first-{qid}")
                )
                report["warmup_runs"].append(
                    run_request(query, report["references"][qid], f"warm-{qid}")
                )
            report["high_frequency_gap"] = run_request(
                high, report["high_frequency_reference"], "high-frequency", 120
            )
            save()
            with ThreadPoolExecutor(
                max_workers=args.concurrency, thread_name_prefix="request"
            ) as request_pool:
                futures = {
                    request_pool.submit(
                        run_request,
                        query,
                        report["references"][qid],
                        f"repeat-{repeat}-query-{qid}",
                    ): qid
                    for repeat in range(args.repeats)
                    for qid, query in enumerate(report["queries"])
                }
                try:
                    for future in as_completed(futures):
                        report["runs"].append(
                            {"query_id": futures[future], **future.result()}
                        )
                        save()
                        if len(report["runs"]) % 20 == 0:
                            print(
                                json.dumps(
                                    {
                                        "stage": "requests",
                                        "completed": len(report["runs"]),
                                        "requested": args.repeats * 20,
                                    }
                                ),
                                flush=True,
                            )
                except BaseException:
                    for future in futures:
                        future.cancel()
                    raise
        report["per_query"] = [
            {
                "query_id": qid,
                **summarize([row for row in report["runs"] if row["query_id"] == qid]),
            }
            for qid in range(20)
        ]
        report["worst_query_first_page_p95_seconds"] = max(
            row["first_page_p95_seconds"] for row in report["per_query"]
        )
        report["max_complete_count_seconds"] = max(
            row["count_completion_seconds"] for row in report["runs"]
        )
        report["pooled_summary_auxiliary_only"] = summarize(report["runs"])
        report["exploratory_threshold_observation"] = {
            "all_query_first_page_p95_within_3s": report[
                "worst_query_first_page_p95_seconds"
            ]
            <= 3,
            "ordinary_complete_counts_within_30s": report["max_complete_count_seconds"]
            <= 30,
            "high_frequency_complete_within_120s": report["high_frequency_gap"][
                "count_completion_seconds"
            ]
            <= 120,
        }
        report["status"] = "completed"
    except BaseException as error:
        report["status"] = "failed"
        report["error"] = f"{type(error).__name__}: {error}"
        raise
    finally:
        if coordinates:
            coordinates.close()
        sampler.stop.set()
        sampler.thread.join()
        save()
    print(
        json.dumps(
            {
                "status": report["status"],
                "report": str(target / "report.json"),
                "worst_query_first_page_p95_seconds": report[
                    "worst_query_first_page_p95_seconds"
                ],
                "max_complete_count_seconds": report["max_complete_count_seconds"],
            }
        ),
        flush=True,
    )


if __name__ == "__main__":
    main()
