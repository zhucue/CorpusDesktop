"""Constructed similarity matrices test algorithm behavior, never model quality."""

import itertools
import json
import subprocess
import sys
from pathlib import Path
from uuid import uuid4

import pytest
from jsonschema import validate

from pipelines.alignment.algorithm import Recipe, align, evaluate, pair_score
from pipelines.alignment.local_model import ModelUnavailable, run_local


def segments(count, prefix):
    return [{"id": f"{prefix}-{i}", "text": "test."} for i in range(count)]


RECIPE = Recipe(cosine_weight=1, length_weight=0, number_weight=0, punctuation_weight=0, min_score=0.5)


def test_constructed_omission_is_left_unpaired():
    result = align(segments(3, "s"), segments(2, "t"), [[0.9, 0.1], [0.1, 0.1], [0.1, 0.9]], RECIPE)
    assert [(pair["source_id"], pair["target_id"]) for pair in result["pairs"]] == [("s-0", "t-0"), ("s-2", "t-1")]
    assert result["unmatched_source"] == ["s-1"]
    assert result["score_is_probability"] is False
    assert all(pair["confirmation"] == "proposed" for pair in result["pairs"])


def test_constructed_reordering_never_produces_crossing_edges():
    result = align(segments(2, "s"), segments(2, "t"), [[0.1, 0.95], [0.95, 0.1]], RECIPE)
    assert len(result["pairs"]) == 1
    assert len(result["unmatched_source"]) == len(result["unmatched_target"]) == 1


def test_dp_objective_matches_independently_enumerated_monotonic_matchings():
    # Enumerate every permitted pair subset, not another dynamic program.
    matrix = [[0.9, 0.6, 0.1], [0.7, 0.2, 0.8], [0.1, 0.6, 0.95]]
    candidates = [(i, j) for i in range(3) for j in range(3) if matrix[i][j] >= RECIPE.min_score]
    best = -6 * RECIPE.skip_cost
    for size in range(1, 4):
        for subset in itertools.combinations(candidates, size):
            ordered = sorted(subset)
            if any(a[0] >= b[0] or a[1] >= b[1] for a, b in itertools.pairwise(ordered)):
                continue
            best = max(best, sum(matrix[i][j] for i, j in subset) - (6 - 2 * size) * RECIPE.skip_cost)
    result = align(segments(3, "s"), segments(3, "t"), matrix, RECIPE)
    assert result["objective"] == pytest.approx(best)


def test_numeric_anchors_and_length_outliers_require_review():
    score, reasons = pair_score("20人。", "This is an exceptionally long English sentence mentioning 30 participants.", 0.8, Recipe())
    assert 0 < score < 1
    assert "numeric_anchor_mismatch" in reasons
    assert "length_ratio_outlier" in reasons


def test_missing_model_never_falls_back_to_length_or_remote_inference():
    missing_directory = Path(__file__).resolve().parents[2] / "tmp/alignment-s0/absent-model-fixture"
    with pytest.raises(ModelUnavailable, match="MODEL_UNAVAILABLE"):
        run_local({}, missing_directory)


def test_missing_model_cli_returns_failure_and_saves_explicit_status():
    root = Path(__file__).resolve().parents[2]
    output = root / "tmp/alignment-s0" / f"missing-model-test-{uuid4().hex}.json"
    result = subprocess.run(
        [sys.executable, "-m", "pipelines.alignment.local_model", "--input", "pipelines/alignment/smoke-input.json", "--model-directory", "tmp/alignment-s0/absent-model-fixture", "--output", str(output)],
        cwd=root, capture_output=True, text=True, timeout=30, check=False,
    )
    assert result.returncode == 2
    assert json.loads(output.read_text(encoding="utf-8"))["status"] == "MODEL_UNAVAILABLE"


@pytest.mark.parametrize("matrix", [[[float('nan')]], [[2]], [[]]])
def test_invalid_similarity_inputs_are_rejected(matrix):
    with pytest.raises(ValueError):
        align(segments(1, "s"), segments(1, "t"), matrix)


def test_duplicate_ids_and_empty_inputs():
    with pytest.raises(ValueError, match="DUPLICATE"):
        align(segments(1, "s") * 2, [], [[], []])
    assert align([], [], [])['pairs'] == []


def test_smoke_input_schema_and_quality_status():
    directory = Path(__file__).resolve().parents[2] / "pipelines/alignment"
    dataset = json.loads((directory / "smoke-input.json").read_text(encoding="utf-8"))
    validate(dataset, json.loads((directory / "input.schema.json").read_text(encoding="utf-8")))
    assert evaluate({}, dataset)["quality_status"] == "NOT_VALIDATED"


def test_gold_requires_provenance_and_one_to_one_endpoints():
    dataset = {"dataset_kind": "domain_gold", "source": segments(1, "s"), "target": segments(2, "t"), "reference_pairs": [["s-0", "t-0"], ["s-0", "t-1"]]}
    with pytest.raises(ValueError, match="PROVENANCE"):
        evaluate({}, dataset)
    dataset["annotation"] = {"independent_domain_annotators": ["unit-test-only"], "protocol": "Constructed validation test"}
    with pytest.raises(ValueError, match="GOLD_NOT_ONE_TO_ONE"):
        evaluate({}, dataset)
