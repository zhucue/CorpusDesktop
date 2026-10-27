"""Versioned one-to-one monotonic S0 alignment; similarity is supplied explicitly."""

import hashlib
import json
import math
import re
from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class Recipe:
    version: str = "alignment-s0/v1"
    cosine_weight: float = 0.85
    length_weight: float = 0.10
    number_weight: float = 0.04
    punctuation_weight: float = 0.01
    source_target_length_ratio: float = 0.5
    min_score: float = 0.55
    skip_cost: float = 0.15
    review_score: float = 0.70
    ambiguity_margin: float = 0.10


def validate_segments(source, target):
    for side in (source, target):
        ids = [segment["id"] for segment in side]
        if any(not isinstance(identifier, str) or not identifier for identifier in ids):
            raise ValueError("EMPTY_SEGMENT_ID")
        if len(ids) != len(set(ids)):
            raise ValueError("DUPLICATE_SEGMENT_ID")
        if any(not isinstance(segment["text"], str) or not segment["text"].strip() for segment in side):
            raise ValueError("EMPTY_SEGMENT")
    if len(source) * len(target) > 1_000_000:
        raise ValueError("S0_ALIGNMENT_CELL_LIMIT")


def pair_score(source: str, target: str, cosine: float, recipe: Recipe):
    if not math.isfinite(cosine) or not -1 <= cosine <= 1:
        raise ValueError("INVALID_SIMILARITY")
    source_length = len(re.sub(r"\s", "", source))
    target_length = len(re.sub(r"\s", "", target))
    expected = max(1, target_length) * recipe.source_target_length_ratio
    length = math.exp(-abs(math.log(max(1, source_length) / expected)))
    source_numbers, target_numbers = re.findall(r"\d+(?:\.\d+)?", source), re.findall(r"\d+(?:\.\d+)?", target)
    numbers = 1.0 if sorted(source_numbers) == sorted(target_numbers) else 0.0
    terminal = lambda value: value.rstrip()[-1:].translate(str.maketrans("。？！", ".?!"))
    punctuation = 1.0 if terminal(source) == terminal(target) else 0.0
    score = recipe.cosine_weight * max(0, cosine) + recipe.length_weight * length + recipe.number_weight * numbers + recipe.punctuation_weight * punctuation
    reasons = []
    if numbers == 0:
        reasons.append("numeric_anchor_mismatch")
    if length < 0.25:
        reasons.append("length_ratio_outlier")
    return score, reasons


DEFAULT_RECIPE = Recipe()


def align(source, target, similarities, recipe=DEFAULT_RECIPE):
    validate_segments(source, target)
    n, m = len(source), len(target)
    if len(similarities) != n or any(len(row) != m for row in similarities):
        raise ValueError("SIMILARITY_SHAPE_MISMATCH")
    if recipe.skip_cost < 0 or recipe.source_target_length_ratio <= 0:
        raise ValueError("INVALID_RECIPE")
    weighted = [[pair_score(source[i]["text"], target[j]["text"], similarities[i][j], recipe) for j in range(m)] for i in range(n)]
    dp = [[0.0] * (m + 1) for _ in range(n + 1)]
    moves = [[""] * (m + 1) for _ in range(n + 1)]
    for i in range(1, n + 1):
        dp[i][0], moves[i][0] = -i * recipe.skip_cost, "source"
    for j in range(1, m + 1):
        dp[0][j], moves[0][j] = -j * recipe.skip_cost, "target"
    for i in range(1, n + 1):
        for j in range(1, m + 1):
            choices = [(dp[i - 1][j] - recipe.skip_cost, "source"), (dp[i][j - 1] - recipe.skip_cost, "target")]
            if weighted[i - 1][j - 1][0] >= recipe.min_score:
                choices.insert(0, (dp[i - 1][j - 1] + weighted[i - 1][j - 1][0], "match"))
            dp[i][j], moves[i][j] = max(choices, key=lambda choice: choice[0])
    matched, unmatched_source, unmatched_target = [], [], []
    i, j = n, m
    while i or j:
        move = moves[i][j]
        if move == "match":
            score, reasons = weighted[i - 1][j - 1]
            reasons = list(reasons)
            if score < recipe.review_score:
                reasons.append("low_score")
            alternatives = [value[0] for k, value in enumerate(weighted[i - 1]) if k != j - 1]
            if alternatives and score - max(alternatives) < recipe.ambiguity_margin:
                reasons.append("ambiguous_or_reordered")
            matched.append({"source_id": source[i - 1]["id"], "target_id": target[j - 1]["id"], "score": score, "review_reasons": reasons, "confirmation": "proposed"})
            i -= 1
            j -= 1
        elif move == "source":
            unmatched_source.append(source[i - 1]["id"])
            i -= 1
        else:
            unmatched_target.append(target[j - 1]["id"])
            j -= 1
    recipe_json = json.dumps(asdict(recipe), sort_keys=True, separators=(",", ":"))
    return {"pairs": list(reversed(matched)), "unmatched_source": list(reversed(unmatched_source)), "unmatched_target": list(reversed(unmatched_target)), "objective": dp[n][m], "recipe": asdict(recipe), "recipe_sha256": hashlib.sha256(recipe_json.encode()).hexdigest(), "score_is_probability": False}


def evaluate(result, dataset):
    """Domain metrics require declared independent human provenance; smoke is never accepted."""
    if dataset.get("dataset_kind") != "domain_gold":
        reason = "Public benchmark data is not independent project-domain gold." if dataset.get("dataset_kind") == "public_benchmark" else "Constructed smoke data is not independent domain gold."
        return {"quality_status": "NOT_VALIDATED", "reason": reason}
    provenance = dataset.get("annotation", {})
    if not provenance.get("independent_domain_annotators") or not provenance.get("protocol"):
        raise ValueError("MISSING_DOMAIN_ANNOTATION_PROVENANCE")
    source_ids = {item["id"] for item in dataset["source"]}
    target_ids = {item["id"] for item in dataset["target"]}
    gold = {tuple(pair) for pair in dataset["reference_pairs"]}
    if len({pair[0] for pair in gold}) != len(gold) or len({pair[1] for pair in gold}) != len(gold):
        raise ValueError("GOLD_NOT_ONE_TO_ONE: preserve complex relations separately; do not force them into this evaluator")
    if any(source not in source_ids or target not in target_ids for source, target in gold):
        raise ValueError("GOLD_ENDPOINT_OUT_OF_SCOPE")
    predicted = {(pair["source_id"], pair["target_id"]) for pair in result["pairs"]}
    correct = len(predicted & gold)
    return {"quality_status": "MEASURED_NOT_ACCEPTED", "correct_pairs": correct, "candidate_precision": correct / len(predicted) if predicted else None, "gold_pair_recall": correct / len(gold) if gold else None, "source_coverage": len(predicted) / len(source_ids) if source_ids else None, "source_unpaired_rate": len(result["unmatched_source"]) / len(source_ids) if source_ids else None, "target_unpaired_rate": len(result["unmatched_target"]) / len(target_ids) if target_ids else None}
