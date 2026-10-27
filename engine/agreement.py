"""Inter-annotator agreement (contracts/p5.md §三): Cohen's kappa for two annotators and nominal
Krippendorff's alpha for any number, with missing values.

Values are hashable category labels; None means "no value" (missing) for alpha. Kappa takes two equally long
lists of values for the same items. Both return None when undefined (no items, or chance agreement 1).
"""

from collections import Counter
from itertools import combinations


def cohen_kappa(a: list, b: list) -> float | None:
    """κ = (p_o − p_e) / (1 − p_e) with p_e from each annotator's own marginal distribution."""
    if len(a) != len(b):
        raise ValueError("两位标注者的条目数不同")
    n = len(a)
    if n == 0:
        return None
    observed = sum(x == y for x, y in zip(a, b)) / n
    ca, cb = Counter(a), Counter(b)
    expected = sum(ca[k] * cb[k] for k in ca) / (n * n)
    if expected == 1:
        return None
    return (observed - expected) / (1 - expected)


def krippendorff_alpha(units: list[list]) -> float | None:
    """Nominal α over units (each a list of the coders' values, None = missing).

    Coincidences: each unit with m ≥ 2 values adds 1 / (m − 1) for every ordered pair of its values;
    α = 1 − (n − 1) · Σ_{c≠k} o_ck / Σ_{c≠k} n_c · n_k.
    """
    o = Counter()
    for unit in units:
        values = [v for v in unit if v is not None]
        m = len(values)
        if m < 2:
            continue
        for i, j in ((i, j) for i in range(m) for j in range(m) if i != j):
            o[(values[i], values[j])] += 1 / (m - 1)
    totals = Counter()
    for (c, _), w in o.items():
        totals[c] += w
    n = sum(totals.values())
    disagree = sum(w for (c, k), w in o.items() if c != k)
    expected = sum(totals[c] * totals[k] for c in totals for k in totals if c != k)
    if n <= 1 or expected == 0:
        return None
    return 1 - (n - 1) * disagree / expected


def pairwise(values: dict) -> list[dict]:
    """values: {annotator: [value per item]} (same items, same order) → [{a, b, kappa, n}]."""
    out = []
    for a, b in combinations(values, 2):
        out.append(
            {
                "a": a,
                "b": b,
                "kappa": cohen_kappa(values[a], values[b]),
                "n": len(values[a]),
            }
        )
    return out


def per_label(values: dict) -> list[dict]:
    """One-vs-rest κ per label, averaged over annotator pairs (None when undefined for every pair)."""
    labels = sorted({v for vs in values.values() for v in vs}, key=str)
    out = []
    for label in labels:
        ks = [
            k
            for a, b in combinations(values, 2)
            if (
                k := cohen_kappa(
                    [v == label for v in values[a]], [v == label for v in values[b]]
                )
            )
            is not None
        ]
        out.append({"label": label, "kappa": sum(ks) / len(ks) if ks else None})
    return out


def summary(values: dict) -> dict:
    """{pairwise, alpha, per_label} for {annotator: [value per item]} over complete items."""
    annotators = list(values)
    n = len(values[annotators[0]]) if annotators else 0
    units = [[values[a][i] for a in annotators] for i in range(n)]
    return {
        "pairwise": pairwise(values),
        "alpha": krippendorff_alpha(units) if len(annotators) >= 2 else None,
        "per_label": per_label(values) if len(annotators) >= 2 else [],
        "n": n,
    }
