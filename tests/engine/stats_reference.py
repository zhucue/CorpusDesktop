"""Pure-Python reference for engine.stats on the UD English fixture (independent of CQP / cwb-scan-corpus).

Works on parsed tokens; node hits use engine_reference.matches. Definitions follow the engine.stats docstring:
window union per position, 2x2 LL, Rayson LL and Hardie log ratio for keywords.

Regenerate tests/golden/p2-stats.json (needs only Python):
    PYTHONPATH=. python tests/engine/stats_reference.py
"""

import json
import math
import re
import unicodedata
from collections import Counter
from pathlib import Path

from engine_reference import load_docs, matches

from engine.query import parse

ROOT = Path(__file__).resolve().parents[2]
GOLDEN = ROOT / "tests/golden/p2-stats.json"
TOP = 20

CASES = [
    {
        "name": "frequency-word",
        "method": "frequency",
        "params": {"unit": "word", "min_freq": 1},
    },
    {
        "name": "bigrams-word",
        "method": "ngrams",
        "params": {"n": 2, "unit": "word", "min_freq": 2},
    },
    {
        "name": "collocations-the",
        "method": "collocations",
        "params": {
            "node": "the",
            "window": 5,
            "unit": "word",
            "measures": ["mi", "logdice", "t", "ll"],
            "min_freq": 3,
        },
    },
    {
        "name": "collocations-verb",
        "method": "collocations",
        "params": {
            "node": "/v",
            "window": 5,
            "unit": "word",
            "measures": ["ll", "mi", "logdice", "t"],
            "min_freq": 3,
        },
    },
    {
        "name": "keywords-ll",
        "method": "keywords",
        "params": {"unit": "word", "measure": "ll", "min_freq": 3},
    },
    {
        "name": "keywords-log-ratio",
        "method": "keywords",
        "params": {"unit": "word", "measure": "log_ratio", "min_freq": 3},
    },
    {
        "name": "distribution-newdoc",
        "method": "distribution",
        "params": {"query_text": "the", "field": "newdoc"},
    },
    {
        "name": "distribution-position",
        "method": "distribution",
        "params": {"query_text": "the", "field": "position", "bins": 10},
    },
]


def value(v):
    """Token value as stored in CWB: NFC, tabs/newlines as spaces, empty → "_"."""
    if v is None or not v.strip():
        return "_"
    return unicodedata.normalize("NFC", re.sub(r"[\t\r\n]", " ", v))


def sentences(docs):
    """[(doc_no, [forms])] for sentences with tokens."""
    return [
        (d, [value(t.form) for t in s.tokens])
        for d, doc in enumerate(docs)
        for s in doc.sentences
        if s.tokens
    ]


def rank(v):
    return round(v, 10)


def frequency(docs):
    freq, dfs = Counter(), {}
    for d, forms in sentences(docs):
        for f in forms:
            freq[f] += 1
            dfs.setdefault(f, set()).add(d)
    n = sum(freq.values())
    keys = sorted(freq, key=lambda k: (-freq[k], k))
    return n, [
        {
            "key": k,
            "values": {
                "item": k,
                "freq": freq[k],
                "per_million": freq[k] * 1e6 / n,
                "doc_freq": len(dfs[k]),
            },
        }
        for k in keys
    ]


def bigrams(docs, min_freq):
    grams, n = Counter(), 0
    for _, forms in sentences(docs):
        n += len(forms)
        for i in range(len(forms) - 1):
            grams[(forms[i], forms[i + 1])] += 1
    keys = sorted(
        (k for k in grams if grams[k] >= min_freq), key=lambda k: (-grams[k], k)
    )
    return [
        {
            "key": "\t".join(k),
            "values": {
                "ngram": " ".join(k),
                "freq": grams[k],
                "per_million": grams[k] * 1e6 / n,
            },
        }
        for k in keys
    ]


def collocations(docs, node, window, measures, min_freq):
    ast = parse(node)
    freq, in_window, n, f_node = Counter(), set(), 0, 0
    for sno, sent in enumerate(s for doc in docs for s in doc.sentences):
        toks = sent.tokens
        if not toks:
            continue
        for f in toks:
            freq[value(f.form)] += 1
        n += len(toks)
        for i, j in matches(ast.anchor.items, toks):  # [i, j)
            f_node += 1
            for k in list(range(max(0, i - window), i)) + list(
                range(j, min(len(toks), j + window))
            ):
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
        ll = 2 * sum(x * math.log(x / y) for x, y in cells if x)
        rows[w] = {
            "collocate": w,
            "freq": o11,
            "coll_freq": c,
            "mi": math.log2(o11 * n / (r * c)),
            "logdice": 14 + math.log2(2 * o11) - math.log2(f_node + c),
            "t": (o11 - e11) / math.sqrt(o11),
            "ll": ll,
        }
    first = measures[0]
    keys = sorted(rows, key=lambda w: (-rank(rows[w][first]), -rows[w]["freq"], w))
    return [{"key": w, "values": rows[w]} for w in keys]


def keywords(target, reference, measure, min_freq):
    ft = Counter(f for _, forms in sentences(target) for f in forms)
    fr = Counter(f for _, forms in sentences(reference) for f in forms)
    c, d = sum(ft.values()), sum(fr.values())
    rows = {}
    for w, a in ft.items():
        b = fr[w]
        if a < min_freq or a * d <= b * c:
            continue
        e1 = c * (a + b) / (c + d)
        e2 = d * (a + b) / (c + d)
        ll = 2 * (a * math.log(a / e1) + (b * math.log(b / e2) if b else 0.0))
        lr = math.log2(a / c) - math.log2((b if b else 0.5) / d)
        sig = (
            "***"
            if ll >= 10.827566
            else "**"
            if ll >= 6.634897
            else "*"
            if ll >= 3.841459
            else ""
        )
        rows[w] = {
            "word": w,
            "target_freq": a,
            "ref_freq": b,
            "target_pm": a * 1e6 / c,
            "ref_pm": b * 1e6 / d,
            "ll": ll,
            "log_ratio": lr,
            "significance": sig,
        }
    keys = sorted(
        rows, key=lambda w: (-rank(rows[w][measure]), -rows[w]["target_freq"], w)
    )
    return [{"key": w, "values": rows[w]} for w in keys]


def distribution(docs, node, field, bins=10):
    ast = parse(node)
    hits, tokens = Counter(), Counter()
    for doc in docs:
        toks = [t for s in doc.sentences for t in s.tokens]
        starts, pos = [], 0
        for s in doc.sentences:
            starts.append(pos)
            pos += len(s.tokens)
        size = len(toks)
        for s, base in zip(doc.sentences, starts):
            for i, _ in matches(ast.anchor.items, s.tokens):
                p = base + i
                key = doc.external_id if field == "newdoc" else int(p * bins / size)
                hits[key] += 1
        if field == "newdoc":
            tokens[doc.external_id] += size
        else:
            for p in range(size):
                tokens[int(p * bins / size)] += 1

    def label(k):
        return (
            k if field == "newdoc" else f"{100 * k / bins:g}–{100 * (k + 1) / bins:g}%"
        )

    keys = sorted(tokens) if field == "newdoc" else list(range(bins))
    return [
        {
            "key": label(k),
            "values": {
                "bin": label(k),
                "hits": hits[k],
                "tokens": tokens[k],
                "per_million": hits[k] / tokens[k] * 1e6,
            },
        }
        for k in keys
    ]


def run(case, docs):
    p = case["params"]
    m = case["method"]
    if m == "frequency":
        return frequency(docs)[1]
    if m == "ngrams":
        return bigrams(docs, p["min_freq"])
    if m == "collocations":
        return collocations(docs, p["node"], p["window"], p["measures"], p["min_freq"])
    if m == "keywords":
        return keywords(docs[:8], docs[8:], p["measure"], p["min_freq"])
    return distribution(docs, p["query_text"], p["field"], p.get("bins", 10))


def golden():
    docs = load_docs()
    out = {
        "fixture": "tests/fixtures/ud-en-ewt-sample.conllu",
        "notes": "keywords: target = documents 1-8, reference = documents 9-16; distribution field newdoc = `# newdoc id`",
        "cases": [],
    }
    for case in CASES:
        rows = run(case, docs)
        out["cases"].append({**case, "row_count": len(rows), "rows": rows[:TOP]})
    return out


if __name__ == "__main__":
    data = golden()
    GOLDEN.write_text(
        json.dumps(data, ensure_ascii=False, indent=1) + "\n", encoding="utf-8"
    )
    for c in data["cases"]:
        print(c["name"], c["row_count"], [r["key"] for r in c["rows"][:5]])
