"""Translation statistics of a query in a parallel corpus (contracts/p8.md §四). Pure computation: the worker
reads the hits' aligned sentences and the target-side counts from PostgreSQL and passes them in.

Units are source-side sentences, so that the 2x2 table is consistent and a row's count equals the sentences
found by opening the search with its translation condition (Tatoeba links one sentence to several):
  U = scope sentences with at least one aligned sentence (either direction) in the target language, N = |U|
  n = hit sentences in U; a(w) = hit sentences whose aligned target sentences contain w
  b(w) = sentences of U whose aligned target sentences contain w
  Dice = 2a / (n + b); LL = 2 Σ O ln(O/E) over the table a, n − a, b − a, N − n − b + a (E = row × col / N)
Only words positively associated with the hits are listed (a/n > b/N); rows sort by the measure, then a, then
the word. Word units are token forms; lemma units skip tokens without a lemma. Case variants merge by default
(contracts/p11.md §一: the worker passes lower-cased values and `spellings`); a row then shows the most frequent
spelling and its translation condition is the alternation of every spelling (`"The"|"the"`); case_sensitive
counts forms as stored.
"""

from collections import Counter

from engine.stats import Table, _col, _ll2x2, _rank, _row, is_punct

MEASURES = ("dice", "ll")
_ATTR_UNSAFE = set(' ,{}[]|=/"')


def cooccurrence(
    hit_targets: dict, target_values: dict, exclude_punct=True
) -> tuple[Counter, int]:
    """(a: {value: hit sentences whose aligned sentences contain it}, n: hit sentences with an aligned
    sentence). hit_targets: {hit sentence: [aligned target sentences]}; target_values: {target sentence:
    unit values of its tokens}."""
    a, n = Counter(), 0
    for targets in hit_targets.values():
        if not targets:
            continue
        n += 1
        seen = set()
        for t in targets:
            seen.update(target_values.get(t, ()))
        a.update(v for v in seen if v and not (exclude_punct and is_punct(v)))
    return a, n


def candidates(a: Counter, min_freq: int) -> list[str]:
    """Values whose background count b is needed."""
    return [w for w, f in a.items() if f >= min_freq]


def dice(a, n, b):
    return 2 * a / (n + b) if n + b else 0.0


def aligned_query(unit, value, spellings=None):
    """The translation condition query of a row (word: the alternation of its spellings); None when the value
    cannot be written."""
    if unit == "word":
        forms = spellings or [value]
        return (
            None if any('"' in v for v in forms) else "|".join(f'"{v}"' for v in forms)
        )
    if any(ch in _ATTR_UNSAFE for ch in value):
        return None
    return f"{{lemma={value}}}"


def table(
    a: Counter,
    n: int,
    b: dict,
    N: int,
    *,
    query_text: str,
    unit="word",
    measure="dice",
    top=100,
    min_freq=2,
    totals: dict | None = None,
    spellings: dict | None = None,
) -> Table:
    """spellings: {merged value: its spellings, most frequent first} when case variants were merged."""
    spellings = spellings or {}
    if measure not in MEASURES:
        raise ValueError(f"未知译法指标：{measure}")
    stats = {}
    for w in candidates(a, min_freq):
        o = a[w]
        bw = max(b.get(w, 0), o)  # b counts the hit sentences too
        if o * N <= n * bw:  # not more frequent among the hits than overall
            continue
        stats[w] = {
            "item": spellings[w][0] if spellings.get(w) else w,
            "cooc": o,
            "pct": o / n * 100 if n else 0.0,
            "target_freq": bw,
            "dice": dice(o, n, bw),
            "ll": _ll2x2(o, n, bw, N),
        }
    items = sorted(
        stats,
        key=lambda w: (-_rank(stats[w][measure]), -stats[w]["cooc"], stats[w]["item"]),
    )
    rows = []
    for w in items[:top]:
        item = stats[w]["item"]
        q = aligned_query(unit, item, spellings.get(w))
        cond = {"op": "+", "query": q} if q else None
        rows.append(
            _row(item, stats[w], query_text if cond else None, search_aligned=cond)
        )
    columns = [
        _col("item", "译文词", "string"),
        _col("cooc", "共现句数"),
        _col("pct", "占命中句 %"),
        _col("target_freq", "目标侧句数"),
        _col("dice", "Dice"),
        _col("ll", "LL"),
    ]
    return Table(columns, rows, len(items), dict(totals or {}))
