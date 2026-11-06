"""Pure-Python reference for the P8 statistics (contracts/p8.md §一~§四) on the UD English fixture, independent
of CQP, cwb-scan-corpus and engine.stats: dispersion (DP, DPnorm, Juilland D, range), keyword effect sizes
(%DIFF, odds ratio, log ratio CI, Bonferroni, direction, items), collocation MI3 / ΔP / z, hit breakdown, and
translation Dice / LL on a small hand-made alignment.

Regenerate tests/golden/p8-stats.json (needs only Python):
    PYTHONPATH=. uv run --frozen python tests/engine/stats_p8_reference.py
"""

import json
import math
import statistics
from collections import Counter
from pathlib import Path

from engine_reference import load_docs, matches
from stats_reference import rank, value

from engine.query import parse

ROOT = Path(__file__).resolve().parents[2]
GOLDEN = ROOT / "tests/golden/p8-stats.json"
TOP = 20

CASES = [
    {
        "name": "dispersion-document",
        "method": "frequency",
        "params": {"parts": "document"},
    },
    {
        "name": "dispersion-segments",
        "method": "frequency",
        "params": {"parts": "segments"},
    },
    {
        "name": "dispersion-field",
        "method": "frequency",
        "params": {"parts": "field:part"},
    },
    {
        "name": "keywords-positive-pct-diff",
        "method": "keywords",
        "params": {"measure": "pct_diff", "direction": "positive", "min_freq": 3},
    },
    {
        "name": "keywords-negative-log-ratio",
        "method": "keywords",
        "params": {"measure": "log_ratio", "direction": "negative", "min_freq": 3},
    },
    {
        "name": "keywords-both-odds-ratio",
        "method": "keywords",
        "params": {"measure": "odds_ratio", "direction": "both", "min_freq": 3},
    },
    {
        "name": "keywords-items",
        "method": "keywords",
        "params": {"measure": "ll", "items": ["Google", "the", "zzz-absent", "of"]},
    },
    {
        "name": "collocations-the-mi3",
        "method": "collocations",
        "params": {
            "node": "the",
            "window": 5,
            "measures": ["mi3", "delta_p", "z"],
            "min_freq": 3,
        },
    },
    {
        "name": "collocations-verb-delta-p",
        "method": "collocations",
        "params": {
            "node": "/v",
            "window": 3,
            "measures": ["delta_p", "z", "mi"],
            "min_freq": 2,
        },
    },
    {
        "name": "breakdown-v-word",
        "method": "breakdown",
        "params": {"query": "/v", "by": "word"},
    },
    {
        "name": "breakdown-the-n-lemma",
        "method": "breakdown",
        "params": {"query": "the /n", "by": "lemma"},
    },
    {
        "name": "breakdown-the-pos",
        "method": "breakdown",
        "params": {"query": "the $1 /n", "by": "pos"},
    },
    {
        "name": "breakdown-of-left1",
        "method": "breakdown",
        "params": {"query": "of", "by": "left1"},
    },
    {
        "name": "breakdown-the-right1",
        "method": "breakdown",
        "params": {"query": "the", "by": "right1"},
    },
    {
        "name": "breakdown-cond-left1",
        "method": "breakdown",
        "params": {"query": "I +/v -not", "by": "left1"},
    },
    {
        "name": "breakdown-the-meta",
        "method": "breakdown",
        "params": {"query": "the", "by": "meta:part"},
    },
]

# translations: hit sentence → aligned target sentences; target sentence → tokens; the scope's other aligned
# sentences (source → targets) for N and b
TR_TOKENS = {
    "t1": ["I", "translate", "books", "."],
    "t2": ["She", "translated", "the", "book", "."],
    "t3": ["Translation", "is", "hard", "."],
    "t4": ["I", "translate", "poems", "."],
    "t5": ["The", "book", "is", "red", "."],
    "t6": ["I", "like", "the", "translation", "."],
    "t7": ["He", "reads", "books", "."],
    "t8": ["translate", "this", "."],
    "t9": ["The", "sky", "is", "blue", "."],
}
TR_HITS = {"s1": ["t1", "t4"], "s2": ["t2"], "s3": ["t6"], "s4": [], "s5": ["t8"]}
TR_OTHERS = {"s6": ["t3"], "s7": ["t5"], "s8": ["t7"], "s9": ["t9"], "s10": ["t2"]}


def part_of(d):
    return "a" if d < 8 else "b"


def tokens(docs):
    """[(doc_no, sentence_no, [token])] for sentences with tokens, in corpus order."""
    out = []
    for d, doc in enumerate(docs):
        for n, s in enumerate(doc.sentences):
            if s.tokens:
                out.append((d, n, s.tokens))
    return out


def ref_dispersion(f_parts, sizes):
    names = list(sizes)
    n = len(names)
    total = sum(sizes.values())
    f = sum(f_parts.get(p, 0) for p in names)
    r = sum(1 for p in names if f_parts.get(p, 0) > 0)
    out = {"range": r, "range_pct": 100.0 * r / n}
    if n < 2:
        return dict.fromkeys(["range", "range_pct", "dp", "dp_norm", "juilland_d"])
    if f == 0:
        return {**out, "dp": None, "dp_norm": None, "juilland_d": None}
    s = {p: sizes[p] / total for p in names}
    dp = sum(abs(f_parts.get(p, 0) / f - s[p]) for p in names) / 2
    rel = [f_parts.get(p, 0) / sizes[p] for p in names]
    cv = statistics.pstdev(rel) / statistics.fmean(rel)
    return {
        **out,
        "dp": dp,
        "dp_norm": dp / (1 - min(s.values())),
        "juilland_d": 1 - cv / math.sqrt(n - 1),
    }


def frequency_dispersion(docs, parts):
    sents = tokens(docs)
    forms = [(d, value(t.form)) for d, _, toks in sents for t in toks]
    big_n = len(forms)
    freq, dfs = Counter(), {}
    per_part, sizes = {}, Counter()
    for p, (d, w) in enumerate(forms):
        freq[w] += 1
        dfs.setdefault(w, set()).add(d)
        if parts == "document":
            key = d
        elif parts == "segments":
            key = p * 10 // big_n
        else:
            key = part_of(d)
        sizes[key] += 1
        per_part.setdefault(w, Counter())[key] += 1
    keys = sorted(freq, key=lambda k: (-freq[k], k))
    rows = []
    for k in keys:
        rows.append(
            {
                "key": k,
                "values": {
                    "item": k,
                    "freq": freq[k],
                    "per_million": freq[k] * 1e6 / big_n,
                    "doc_freq": len(dfs[k]),
                    **ref_dispersion(per_part[k], sizes),
                },
            }
        )
    return rows, {"parts": len(sizes)}


def keyword_row(w, a, b, c, d, m):
    e1 = c * (a + b) / (c + d)
    e2 = d * (a + b) / (c + d)
    ll = 2 * (
        (a * math.log(a / e1) if a else 0.0) + (b * math.log(b / e2) if b else 0.0)
    )
    sa, sb = (a if a else 0.5), (b if b else 0.5)
    lr = math.log2(sa / c) - math.log2(sb / d)
    se = math.sqrt(1 / sa + 1 / sb)
    z = 1.959963984540054
    p = (1 - math.erf(math.sqrt(ll / 2))) * m
    bon = "***" if p < 0.001 else "**" if p < 0.01 else "*" if p < 0.05 else ""
    sig = (
        "***"
        if ll >= 10.827566
        else "**"
        if ll >= 6.634897
        else "*"
        if ll >= 3.841459
        else ""
    )
    return {
        "word": w,
        "target_freq": a,
        "ref_freq": b,
        "target_pm": a * 1e6 / c,
        "ref_pm": b * 1e6 / d,
        "ll": ll,
        "log_ratio": lr,
        "log_ratio_ci_low": lr - z * se / math.log(2),
        "log_ratio_ci_high": lr + z * se / math.log(2),
        "pct_diff": 100 * (a * 1e6 / c - sb * 1e6 / d) / (sb * 1e6 / d),
        "odds_ratio": (sa * (d - sb)) / (sb * (c - sa)),
        "significance": sig,
        "bonferroni": bon,
        "smoothed": a == 0 or b == 0,
    }


def keywords(target, reference, measure, direction="positive", min_freq=3, items=None):
    ft = Counter(value(t.form) for _, _, toks in tokens(target) for t in toks)
    fr = Counter(value(t.form) for _, _, toks in tokens(reference) for t in toks)
    c, d = sum(ft.values()), sum(fr.values())
    m = len(set(ft) | set(fr))
    if items is not None:
        words = list(dict.fromkeys(items))
        rows = [keyword_row(w, ft[w], fr[w], c, d, m) for w in words]
        return [{"key": r["word"], "values": r} for r in rows]
    rows = {}
    for w in set(ft) | set(fr):
        a, b = ft[w], fr[w]
        pos = a * d > b * c and a >= min_freq
        neg = b * c > a * d and b >= min_freq
        if (direction in ("positive", "both") and pos) or (
            direction in ("negative", "both") and neg
        ):
            rows[w] = keyword_row(w, a, b, c, d, m)

    def size(r):
        v = r[measure]
        return abs(math.log(v)) if measure == "odds_ratio" else abs(v)

    keys = sorted(
        rows, key=lambda w: (-rank(size(rows[w])), -rows[w]["target_freq"], w)
    )
    return [{"key": w, "values": rows[w]} for w in keys]


def collocations(docs, node, window, measures, min_freq):
    ast = parse(node)
    freq, in_window, n, f_node = Counter(), set(), 0, 0
    for sno, (_, _, toks) in enumerate(tokens(docs)):
        for t in toks:
            freq[value(t.form)] += 1
        n += len(toks)
        for i, j in matches(ast.anchor.items, toks):
            f_node += 1
            around = list(range(max(0, i - window), i)) + list(
                range(j, min(len(toks), j + window))
            )
            for k in around:
                in_window.add((sno, k, value(toks[k].form)))
    o = Counter(w for _, _, w in in_window)
    r = len(in_window)
    rows = {}
    for w, o11 in o.items():
        if o11 < min_freq:
            continue
        c = freq[w]
        e11 = r * c / n
        cells = [
            (o11, e11),
            (r - o11, r * (n - c) / n),
            (c - o11, (n - r) * c / n),
            (n - r - c + o11, (n - r) * (n - c) / n),
        ]
        row = {
            "collocate": w,
            "freq": o11,
            "coll_freq": c,
            "mi": math.log2(o11 * n / (r * c)),
            "logdice": 14 + math.log2(2 * o11) - math.log2(f_node + c),
            "t": (o11 - e11) / math.sqrt(o11),
            "ll": 2 * sum(x * math.log(x / y) for x, y in cells if x),
            "mi3": 3 * math.log2(o11) - math.log2(e11),
            "z": (o11 - e11) / math.sqrt(e11),
            # rows: in a node window or not; columns: the collocate or another word
            "delta_p_node": o11 / r - (c - o11) / (n - r),
            "delta_p_coll": o11 / c - (r - o11) / (n - c),
        }
        shown = ["collocate", "freq", "coll_freq"]
        for m in ("mi", "logdice", "t", "ll", "mi3", "delta_p", "z"):
            if m in measures:
                shown += ["delta_p_node", "delta_p_coll"] if m == "delta_p" else [m]
        rows[w] = {k: row[k] for k in shown}
    first = "delta_p_node" if measures[0] == "delta_p" else measures[0]
    keys = sorted(rows, key=lambda w: (-rank(rows[w][first]), -rows[w]["freq"], w))
    return [{"key": w, "values": rows[w]} for w in keys]


def breakdown(docs, text, by):
    ast = parse(text)
    sents = tokens(docs)
    big_n = sum(len(toks) for _, _, toks in sents)
    counts = Counter()
    for d, _, toks in sents:
        if not all(
            bool(matches(c.query.items, toks)) == (c.op == "+") for c in ast.conditions
        ):
            continue
        for i, j in matches(ast.anchor.items, toks):
            if by in ("word", "lemma", "pos"):
                attr = {"word": "form", "lemma": "lemma", "pos": "pos"}[by]
                key = " ".join(value(getattr(t, attr)) for t in toks[i:j])
            elif by == "left1":
                key = value(toks[i - 1].form) if i > 0 else "（句首）"
            elif by == "right1":
                key = value(toks[j].form) if j < len(toks) else "（句末）"
            else:
                key = part_of(d)
            counts[key] += 1
    total = sum(counts.values())
    keys = sorted(counts, key=lambda k: (-counts[k], k))
    return [
        {
            "key": k if by.startswith("meta:") else k.replace(" ", "\t"),
            "values": {
                "item": k,
                "hits": counts[k],
                "pct": 100 * counts[k] / total,
                "per_million": counts[k] * 1e6 / big_n,
            },
        }
        for k in keys
    ], {"hits": total}


def g2(cells):
    """G² of a 2x2 table [[a, b], [c, d]] from row and column sums."""
    (a, b), (c, d) = cells
    n = a + b + c + d
    rows, cols = (a + b, c + d), (a + c, b + d)
    total = 0.0
    for i, row in enumerate(cells):
        for j, o in enumerate(row):
            if o:
                total += o * math.log(o * n / (rows[i] * cols[j]))
    return 2 * total


def translations(measure, min_freq):
    def words(targets):
        return {
            w for t in targets for w in TR_TOKENS[t] if any(ch.isalpha() for ch in w)
        }

    aligned_hits = {s: words(ts) for s, ts in TR_HITS.items() if ts}
    universe = {**aligned_hits, **{s: words(ts) for s, ts in TR_OTHERS.items()}}
    n, big_n = len(aligned_hits), len(universe)
    a = Counter(w for ws in aligned_hits.values() for w in ws)
    b = Counter(w for ws in universe.values() for w in ws)
    rows = {}
    for w, o in a.items():
        if o < min_freq or o / n <= b[w] / big_n:
            continue
        rows[w] = {
            "item": w,
            "cooc": o,
            "pct": 100 * o / n,
            "target_freq": b[w],
            "dice": 2 * o / (n + b[w]),
            "ll": g2([[o, n - o], [b[w] - o, big_n - n - b[w] + o]]),
        }
    keys = sorted(rows, key=lambda w: (-rank(rows[w][measure]), -rows[w]["cooc"], w))
    return [{"key": w, "values": rows[w]} for w in keys], {
        "n": n,
        "N": big_n,
        "b": dict(sorted(b.items())),
    }


def run(case, docs):
    p, m = case["params"], case["method"]
    if m == "frequency":
        return frequency_dispersion(docs, p["parts"])
    if m == "keywords":
        rows = keywords(
            docs[:8],
            docs[8:],
            p["measure"],
            p.get("direction", "positive"),
            p.get("min_freq", 3),
            p.get("items"),
        )
        return rows, {}
    if m == "collocations":
        return collocations(
            docs, p["node"], p["window"], p["measures"], p["min_freq"]
        ), {}
    if m == "breakdown":
        return breakdown(docs, p["query"], p["by"])
    return translations(p["measure"], p["min_freq"])


def golden():
    docs = load_docs()
    out = {
        "fixture": "tests/fixtures/ud-en-ewt-sample.conllu",
        "notes": "part = a for documents 1-8, b for 9-16; keywords: target = part a, reference = part b; "
        "translations: hand-made alignment in stats_p8_reference.py",
        "cases": [],
    }
    cases = CASES + [
        {
            "name": "translations-dice",
            "method": "translations",
            "params": {"measure": "dice", "min_freq": 1},
        },
        {
            "name": "translations-ll",
            "method": "translations",
            "params": {"measure": "ll", "min_freq": 2},
        },
    ]
    for case in cases:
        rows, extra = run(case, docs)
        out["cases"].append(
            {**case, "row_count": len(rows), "extra": extra, "rows": rows[:TOP]}
        )
    return out


if __name__ == "__main__":
    data = golden()
    GOLDEN.write_text(
        json.dumps(data, ensure_ascii=False, indent=1) + "\n", encoding="utf-8"
    )
    for c in data["cases"]:
        print(c["name"], c["row_count"], [r["key"] for r in c["rows"][:5]])
