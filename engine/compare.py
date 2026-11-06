"""Comparison of several query × scope items (contracts/p10.md §四). Pure computation: the worker passes each
item's hits and tokens per document and the documents' metadata.

Without `by`: one row per item: hits, tokens (scope tokens, punctuation included), per_million, documents,
  doc_freq_pct (documents with a hit / documents × 100); with exactly two items totals.comparison holds LL, log
  ratio and the significance mark of the keyword formulas (engine.stats.keyword_values, a / b = hits, c / d =
  tokens).
With `by`: one row per field value (documents without the field are left out); columns hits_i, per_million_i
  per item (the value's documents pooled).
Tests take one observation per document: its hits per million tokens (documents with tokens only).
  mann_whitney (two items): U = U₁ of the first item = R₁ − n₁(n₁ + 1)/2 (average ranks for ties);
    μ = n₁n₂/2, σ = √(n₁n₂/12 · ((n + 1) − Σ(t³ − t)/(n(n − 1)))); z = sign(U₁ − μ) · max(|U₁ − μ| − ½, 0) / σ
    (continuity correction); p = min(1, 2 · P(Z ≥ (|U₁ − μ| − ½)/σ)); r = z / √n. Equal to SciPy
    mannwhitneyu(x, y, method="asymptotic") (U = its statistic, p = its p value). σ = 0: z, p, r null.
  spearman (numeric `by`): per item, ρ = Pearson correlation of the average ranks of (field value, per million)
    over the documents with the field; p two-sided from t = ρ √((n − 2)/(1 − ρ²)) with n − 2 d.f. (SciPy
    spearmanr). n < 3 or a constant variable: ρ and p null; |ρ| = 1: p = 0.
"""

import math

from engine.stats import Table, _col, _number, _row, keyword_values

TESTS = ("none", "mann_whitney", "spearman")


def ranks(values) -> list[float]:
    """Average ranks (1-based) of values."""
    order = sorted(range(len(values)), key=lambda i: values[i])
    out = [0.0] * len(values)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and values[order[j + 1]] == values[order[i]]:
            j += 1
        for k in range(i, j + 1):
            out[order[k]] = (i + j) / 2 + 1
        i = j + 1
    return out


def _norm_sf(z):
    return 0.5 * math.erfc(z / math.sqrt(2))


def mann_whitney(x, y) -> dict:
    n1, n2 = len(x), len(y)
    out = {"u": None, "z": None, "p": None, "r": None, "n1": n1, "n2": n2}
    if not n1 or not n2:
        return out
    r = ranks(list(x) + list(y))
    u1 = sum(r[:n1]) - n1 * (n1 + 1) / 2
    out["u"] = u1
    n = n1 + n2
    counts = {}
    for v in list(x) + list(y):
        counts[v] = counts.get(v, 0) + 1
    tie = sum(t**3 - t for t in counts.values())
    var = n1 * n2 / 12 * ((n + 1) - tie / (n * (n - 1)))
    if var <= 0:
        return out
    s, d = math.sqrt(var), u1 - n1 * n2 / 2
    z = math.copysign(max(abs(d) - 0.5, 0.0), d) / s
    out.update(
        z=z,
        p=min(1.0, 2 * _norm_sf((abs(d) - 0.5) / s)),
        r=z / math.sqrt(n),
    )
    return out


def _betacf(a, b, x):
    """Continued fraction of the regularized incomplete beta function (Lentz)."""
    tiny, eps = 1e-300, 1e-16
    qab, qap, qam = a + b, a + 1, a - 1
    c, d = 1.0, 1 - qab * x / qap
    d = 1 / (d if abs(d) > tiny else tiny)
    h = d
    for m in range(1, 1000):
        m2 = 2 * m
        aa = m * (b - m) * x / ((qam + m2) * (a + m2))
        d = 1 + aa * d
        d = 1 / (d if abs(d) > tiny else tiny)
        c = 1 + aa / c
        c = c if abs(c) > tiny else tiny
        h *= d * c
        aa = -(a + m) * (qab + m) * x / ((a + m2) * (qap + m2))
        d = 1 + aa * d
        d = 1 / (d if abs(d) > tiny else tiny)
        c = 1 + aa / c
        c = c if abs(c) > tiny else tiny
        delta = d * c
        h *= delta
        if abs(delta - 1) < eps:
            break
    return h


def betainc(a, b, x) -> float:
    """Regularized incomplete beta I_x(a, b)."""
    if x <= 0:
        return 0.0
    if x >= 1:
        return 1.0
    ln = (
        math.lgamma(a + b)
        - math.lgamma(a)
        - math.lgamma(b)
        + a * math.log(x)
        + b * math.log1p(-x)
    )
    front = math.exp(ln)
    if x < (a + 1) / (a + b + 2):
        return front * _betacf(a, b, x) / a
    return 1 - front * _betacf(b, a, 1 - x) / b


def t_two_sided(t, df) -> float:
    """P(|T| ≥ |t|) for Student's t with df degrees of freedom."""
    return betainc(df / 2, 0.5, df / (df + t * t))


def spearman(x, y) -> dict:
    n = len(x)
    out = {"rho": None, "p": None, "n": n}
    if n < 3:
        return out
    rx, ry = ranks(x), ranks(y)
    mx, my = sum(rx) / n, sum(ry) / n
    sxy = sum((a - mx) * (b - my) for a, b in zip(rx, ry))
    sxx = sum((a - mx) ** 2 for a in rx)
    syy = sum((b - my) ** 2 for b in ry)
    if not sxx or not syy:
        return out
    rho = max(-1.0, min(1.0, sxy / math.sqrt(sxx * syy)))
    out["rho"] = rho
    if abs(rho) == 1:
        out["p"] = 0.0
    else:
        out["p"] = t_two_sided(rho * math.sqrt((n - 2) / (1 - rho * rho)), n - 2)
    return out


def doc_pm(hits: dict, sizes: dict) -> dict:
    """Hits per million tokens of each document with tokens."""
    return {d: hits.get(d, 0) / n * 1e6 for d, n in sizes.items() if n}


def _field_value(meta, field, numeric):
    v = (meta or {}).get(field)
    if v in (None, ""):
        return None
    if numeric:
        n = (
            v
            if isinstance(v, int | float) and not isinstance(v, bool)
            else _number(str(v))
        )
        return n if isinstance(n, int | float) else None
    return str(v)


def table(items, by=None, numeric=False, test="none") -> Table:
    """items: [{label, scope_name, query, hits {doc: n}, sizes {doc: tokens}, meta {doc: metadata},
    search_query, search_scope, corpus_id, base_filter}] in request order; a `by` row's searches narrow the
    item's corpus to the field value (base_filter = the item scope's metadata filter)."""
    if test not in TESTS:
        raise ValueError(f"未知检验：{test}")
    if test == "mann_whitney" and len(items) != 2:
        raise ValueError("Mann-Whitney 检验需要恰好两项")
    if test == "spearman" and not (by and numeric):
        raise ValueError("Spearman 检验需要按数值字段对比")
    totals = {"items": len(items)}
    rows = []
    if not by:
        for i, it in enumerate(items, 1):
            hits, sizes = it["hits"], it["sizes"]
            h, n = sum(hits.get(d, 0) for d in sizes), sum(sizes.values())
            docs = len(sizes)
            values = {
                "label": it["label"],
                "scope": it["scope_name"],
                "query": it["query"],
                "hits": h,
                "tokens": n,
                "per_million": h / n * 1e6 if n else 0.0,
                "documents": docs,
                "doc_freq_pct": sum(1 for d in sizes if hits.get(d)) / docs * 100
                if docs
                else 0.0,
            }
            rows.append(
                _row(
                    str(i), values, it["search_query"], search_scope=it["search_scope"]
                )
            )
        if len(items) == 2:
            (a, c), (b, d) = (
                (r["values"]["hits"], r["values"]["tokens"]) for r in rows
            )
            if c and d and (a or b):
                kv = keyword_values(a, b, c, d)
                totals["comparison"] = {
                    k: kv[k] for k in ("ll", "log_ratio", "significance", "smoothed")
                }
        columns = [
            _col("label", "项", "string"),
            _col("scope", "范围", "string"),
            _col("query", "查询式", "string"),
            _col("hits", "命中数"),
            _col("tokens", "词数"),
            _col("per_million", "每百万词"),
            _col("documents", "文档数"),
            _col("doc_freq_pct", "文档频率 %"),
        ]
    else:
        per_value = {}  # value → item index → [hits, tokens]
        for i, it in enumerate(items):
            for d, n in it["sizes"].items():
                v = _field_value(it["meta"].get(d), by, numeric)
                if v is None:
                    continue
                cell = per_value.setdefault(v, {}).setdefault(i, [0, 0])
                cell[0] += it["hits"].get(d, 0)
                cell[1] += n
        order = sorted(per_value, key=lambda v: (isinstance(v, str), v))
        for v in order:
            values, searches = {"value": v}, []
            for i, it in enumerate(items):
                h, n = per_value[v].get(i, [0, 0])
                values[f"hits_{i + 1}"] = h
                values[f"per_million_{i + 1}"] = h / n * 1e6 if n else None
                searches.append(
                    {
                        "label": it["label"],
                        "search_query": it["search_query"],
                        "search_scope": {
                            "corpus_id": it["corpus_id"],
                            "filter": {**(it.get("base_filter") or {}), by: v},
                        },
                    }
                )
            rows.append(_row(str(v), values, None, searches=searches))
        columns = [_col("value", by, "number" if numeric else "string")]
        for i, it in enumerate(items, 1):
            columns += [
                _col(f"hits_{i}", f"{it['label']} 命中数"),
                _col(f"per_million_{i}", f"{it['label']} 每百万词"),
            ]
    if test == "mann_whitney":
        x, y = (list(doc_pm(it["hits"], it["sizes"]).values()) for it in items)
        totals["test"] = {"method": "mann_whitney", **mann_whitney(x, y)}
    elif test == "spearman":
        results = []
        for it in items:
            pairs = [
                (v, pm)
                for d, pm in doc_pm(it["hits"], it["sizes"]).items()
                if (v := _field_value(it["meta"].get(d), by, True)) is not None
            ]
            res = spearman([p[0] for p in pairs], [p[1] for p in pairs])
            results.append({"label": it["label"], **res})
        totals["test"] = {"method": "spearman", "field": by, "items": results}
    return Table(columns, rows, len(rows), totals)
