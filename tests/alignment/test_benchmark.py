"""Selection and reporting rules; these tests do not load or validate a model."""

import json
import subprocess
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from pipelines.alignment.benchmark import (
    ROOT,
    correspondence,
    make_dataset,
    prepare_pairs,
    run_process,
)


def pair(source, target):
    return {"edge_id": f"{source}:{target}", "relation": "upstream_direct_link",
            "source": {"id": source, "language": "cmn", "text": "中文。"},
            "target": {"id": target, "language": "eng", "text": "English."}}


def test_long_pairs_are_explicitly_excluded_before_endpoint_selection():
    rows = [pair(1, 10), pair(1, 11), pair(2, 11), pair(3, 12)]
    selected, excluded = prepare_pairs(rows, [129, 3, 128, 4, 3, 4, 4, 130], 128)
    assert [row["edge_id"] for row in selected] == ["1:11"]
    assert excluded == [
        {"edge_id": "1:10", "reason": "SEGMENT_TOO_LONG", "source_tokens": 129, "target_tokens": 3},
        {"edge_id": "2:11", "reason": "REUSED_ENDPOINT", "source_tokens": 3, "target_tokens": 4},
        {"edge_id": "3:12", "reason": "SEGMENT_TOO_LONG", "source_tokens": 4, "target_tokens": 130},
    ]
    assert rows[0]["source"]["text"] == "中文。"


def test_only_direct_pairs_and_complete_token_counts_are_accepted():
    with pytest.raises(ValueError, match="TOKEN_LENGTH_SHAPE"):
        prepare_pairs([pair(1, 2)], [4], 128)
    indirect = pair(1, 2)
    indirect["relation"] = "indirect"
    with pytest.raises(ValueError, match="EXPECTED_DIRECT"):
        prepare_pairs([indirect], [4, 4], 128)


def test_dataset_prefix_and_existing_cell_limit_are_preserved():
    pairs = [pair(1, 10), pair(2, 20)]
    smaller = make_dataset(pairs, 1, "sample-sha")
    larger = make_dataset(pairs, 2, "sample-sha")
    assert larger["source"][:1] == smaller["source"]
    assert larger["target"][:1] == smaller["target"]
    assert larger["dataset_kind"] == "constructed_smoke"
    assert larger["source"][0]["revision_id"] == "sample-sha"
    for invalid in (0, 3, 1001, True):
        with pytest.raises(ValueError, match="SIZE_REQUIRES"):
            make_dataset(pairs, invalid, "sample-sha")


def test_candidate_correspondence_never_becomes_domain_quality():
    result = {"pairs": [
        {"source_id": "s1", "target_id": "t1", "review_reasons": []},
        {"source_id": "s2", "target_id": "t3", "review_reasons": ["ambiguous"]},
    ], "unmatched_source": ["s3"], "unmatched_target": ["t2"]}
    report = correspondence(result, {("s1", "t1"), ("s2", "t2"), ("s3", "t3")})
    assert report["candidate_matches_selected_direct_pair"] == 1
    assert report["candidate_other_than_selected_direct_pair"] == 1
    assert report["selected_direct_pair_recovery_fraction"] == 1 / 3
    assert report["candidates_requiring_review"] == 1
    assert report["quality_status"] == "NOT_VALIDATED"


def test_child_timeout_preserves_failure_evidence():
    directory = ROOT / "tmp/alignment-s0"
    directory.mkdir(parents=True, exist_ok=True)
    output = Path(tempfile.mkdtemp(prefix="benchmark-failure-test-", dir=directory))
    with (
        patch("pipelines.alignment.benchmark.subprocess.run", side_effect=subprocess.TimeoutExpired(["fixture"], 1)),
        pytest.raises(subprocess.TimeoutExpired),
    ):
        run_process(["fixture"], {}, output, 100, 1)
    report = json.loads((output / "failure-100.json").read_text(encoding="utf-8"))
    assert report["status"] == "failed"
    assert report["error_type"] == "TimeoutExpired"
    assert (output / report["stderr"]).exists()
