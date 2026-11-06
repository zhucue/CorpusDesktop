"""Pure-Python reference for the P10 statistics (contracts/p10.md §一、二、四、五) on the UD English fixture, written
independently of engine.metrics / vocab / compare / sketch: text metrics (TTR, STTR, MTLD, lexical density,
mean dependency distance, Flesch), NGSL level profile, comparison (per-document hits of a query; Mann-Whitney and
Spearman values from SciPy) and Word Sketch relations with logDice.

Regenerate tests/golden/p10-stats.json (SciPy only for the test values):
    uv run --frozen --with scipy python tests/engine/stats_p10_reference.py
"""

import csv
import json
import math
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(Path(__file__).resolve().parent)]

from engine_reference import load_docs, matches
from stats_reference import value

from engine.query import parse

GOLDEN = ROOT / "tests/golden/p10-stats.json"
NGSL = ROOT / "engine/data/ngsl.csv"
LETTER = re.compile(r"[^\W\d_]")  # a letter or CJK character


def part_of(d):
    return "a" if d < 8 else "b"


def with_meta(docs):
    for i, doc in enumerate(docs):
        doc.metadata = {"part": part_of(i), "n": i}
    return docs


def words_of(doc):
    return [
        value(t.form).lower()
        for s in doc.sentences
        for t in s.tokens
        if LETTER.search(value(t.form))
    ]


# ---- §一 text metrics


def ref_mtld_one(words, limit=0.72):
    factor_count, start = 0.0, 0
    ttr_now = 1.0
    for i in range(len(words)):
        segment = words[start : i + 1]
        ttr_now = len(set(segment)) / len(segment)
        if ttr_now <= limit:
            factor_count += 1
            start = i + 1
            ttr_now = 1.0
    if start < len(words):
        factor_count += (1 - ttr_now) / (1 - limit)
    return None if factor_count == 0 else len(words) / factor_count


def ref_syllables(word):
    groups, prev = 0, False
    for ch in word:
        v = ch in "aeiouy"
        if v and not prev:
            groups += 1
        prev = v
    if word[-1:] == "e" and word[-2:] != "le" and groups > 1:
        groups -= 1
    return groups if groups > 0 else 1


def ref_metrics(doc, window):
    words = words_of(doc)
    toks = [t for s in doc.sentences for t in s.tokens if LETTER.search(value(t.form))]
    n = len(words)
    sents = sum(1 for s in doc.sentences if s.tokens)
    pieces = [words[i : i + window] for i in range(0, n - n % window, window)]
    content = sum(
        1
        for t in toks
        if t.pos in ("NOUN", "PROPN", "VERB", "ADJ", "ADV")
        or (t.pos or " ")[0] in "nvad"
    )
    dist = [
        abs(t.head - i)
        for s in doc.sentences
        for i, t in enumerate(s.tokens, 1)
        if t.head not in (None, 0)
    ]
    fwd, bwd = ref_mtld_one(words), ref_mtld_one(list(reversed(words)))
    syl = sum(ref_syllables(w) for w in words)
    return {
        "words": n,
        "sentences": sents,
        "ttr": len(set(words)) / n if n else None,
        "sttr": sum(len(set(p)) / window for p in pieces) / len(pieces)
        if n >= 100 and pieces
        else None,
        "mtld": (fwd + bwd) / 2 if n >= 100 and fwd and bwd else None,
        "lexical_density": content / n if n else None,
        "mean_sentence_length": n / sents if sents else None,
        "mean_dependency_distance": sum(dist) / len(dist) if dist else None,
        "flesch_reading_ease": 206.835 - 1.015 * n / sents - 84.6 * syl / n
        if n and sents
        else None,
        "flesch_kincaid_grade": 0.39 * n / sents + 11.8 * syl / n - 15.59
        if n and sents
        else None,
    }


def ref_groups(per_doc, docs):
    out = {}
    keys = list(next(iter(per_doc.values())))
    for k in keys:
        out[k] = []
        for g in ("a", "b"):
            vals = [per_doc[f"d{i}"][k] for i in range(len(docs)) if part_of(i) == g]
            vals = [v for v in vals if v is not None]
            mean = sum(vals) / len(vals) if vals else None
            sd = (
                math.sqrt(sum((v - mean) ** 2 for v in vals) / (len(vals) - 1))
                if len(vals) > 1
                else None
            )
            out[k].append({"value": g, "documents": len(vals), "mean": mean, "sd": sd})
    return out


def text_metrics(docs, window):
    per_doc = {f"d{i}": ref_metrics(doc, window) for i, doc in enumerate(docs)}
    return {"window": window, "documents": per_doc, "groups": ref_groups(per_doc, docs)}


# ---- §二 NGSL profile


def ngsl():
    rows = [
        line
        for line in NGSL.read_text(encoding="utf-8").splitlines()
        if not line.startswith("#")
    ]
    table = {}
    for r in list(csv.DictReader(rows)):
        rank = int(r["sfi_rank"])
        band = (
            "频率排名 1–1000"
            if rank <= 1000
            else "频率排名 1001–2000"
            if rank <= 2000
            else "频率排名 2001–2809"
        )
        table.setdefault(r["word"].lower(), band)
    return table


def vocab_profile(docs):
    table = ngsl()
    levels = ["频率排名 1–1000", "频率排名 1001–2000", "频率排名 2001–2809", "表外"]
    tok, typ = Counter(), defaultdict(set)
    per_doc = {}
    for i, doc in enumerate(docs):
        c = Counter()
        for s in doc.sentences:
            for t in s.tokens:
                form = value(t.form)
                if not LETTER.search(form):
                    continue
                key = (
                    (t.lemma or form).lower()
                    if t.lemma not in (None, "_")
                    else form.lower()
                )
                band = table.get(key, "表外")
                tok[band] += 1
                typ[band].add(key)
                c[band] += 1
        n = sum(c.values())
        per_doc[f"d{i}"] = {lv: c[lv] / n * 100 for lv in levels}
    total = sum(tok.values())
    corpus = {
        lv: {
            "tokens": tok[lv],
            "types": len(typ[lv]),
            "coverage": tok[lv] / total * 100,
        }
        for lv in levels
    }
    return {"words": total, "corpus": corpus, "documents": per_doc}


# ---- §四 comparison


def doc_hits(docs, text):
    items = parse(text).anchor.items
    return {
        f"d{i}": sum(len(matches(items, s.tokens)) for s in doc.sentences)
        for i, doc in enumerate(docs)
    }


def compare(docs):
    from scipy import stats as ss

    hits = doc_hits(docs, "the")
    sizes = {
        f"d{i}": sum(len(s.tokens) for s in doc.sentences) for i, doc in enumerate(docs)
    }
    groups = {
        g: [f"d{i}" for i in range(len(docs)) if part_of(i) == g] for g in ("a", "b")
    }
    items = []
    for g in ("a", "b"):
        h = sum(hits[d] for d in groups[g])
        n = sum(sizes[d] for d in groups[g])
        items.append(
            {
                "hits": h,
                "tokens": n,
                "per_million": h / n * 1e6,
                "documents": len(groups[g]),
                "doc_freq_pct": sum(1 for d in groups[g] if hits[d])
                / len(groups[g])
                * 100,
            }
        )
    a, b, c, d = (
        items[0]["hits"],
        items[1]["hits"],
        items[0]["tokens"],
        items[1]["tokens"],
    )
    e1, e2 = c * (a + b) / (c + d), d * (a + b) / (c + d)
    ll = 2 * (a * math.log(a / e1) + b * math.log(b / e2))
    pm = {k: {dd: hits[dd] / sizes[dd] * 1e6 for dd in groups[k]} for k in groups}
    mw = ss.mannwhitneyu(
        list(pm["a"].values()), list(pm["b"].values()), method="asymptotic"
    )
    spear = []
    for g in ("a", "b"):
        ns = [int(dd[1:]) for dd in groups[g]]
        r = ss.spearmanr(ns, [pm[g][dd] for dd in groups[g]])
        spear.append({"rho": float(r.statistic), "p": float(r.pvalue), "n": len(ns)})
    return {
        "query": "the",
        "doc_hits": hits,
        "items": items,
        "ll": ll,
        "log_ratio": math.log2((a / c) / (b / d)),
        "mann_whitney": {"u": float(mw.statistic), "p": float(mw.pvalue)},
        "spearman": spear,
    }


# ---- §五 Word Sketch


def sketch_pairs(docs):
    """[(relation, node lemma, collocate lemma)] over all dependencies (independent of engine.sketch)."""
    out = []
    for doc in docs:
        for s in doc.sentences:
            toks = s.tokens
            lem = [
                t.lemma if t.lemma not in (None, "_") else value(t.form) for t in toks
            ]
            for d, t in enumerate(toks):
                if not t.head or not t.deprel:
                    continue
                h = t.head - 1
                rel = t.deprel.split(":")[0]
                pairs = []
                if rel == "nsubj":
                    pairs += [("subject", h, d), ("subject_of", d, h)]
                if rel in ("obj", "iobj"):
                    pairs.append(("object", h, d))
                if rel == "conj":
                    pairs += [("conj", h, d), ("conj", d, h)]
                if rel in ("amod", "advmod", "nmod", "compound"):
                    pairs += [(rel, h, d), (rel + "_of", d, h)]
                if rel in ("obl", "nmod"):
                    for c, ct in enumerate(toks):
                        if (
                            ct.head == d + 1
                            and (ct.deprel or "").split(":")[0] == "case"
                        ):
                            p = lem[c].lower()
                            if LETTER.search(p):
                                pairs.append(("pp:" + p, h, d))
                for r, n, c in pairs:
                    if LETTER.search(lem[c]):
                        out.append((r, lem[n].lower(), lem[c]))
    return out


def word_sketch(docs, lemma, min_freq):
    pairs = sketch_pairs(docs)
    by_coll = Counter((r, c) for r, _, c in pairs)
    mine = Counter((r, c) for r, n, c in pairs if n == lemma)
    per_rel = Counter()
    for (r, _), f in mine.items():
        per_rel[r] += f
    rows = {}
    for (r, c), f in mine.items():
        if f >= min_freq:
            rows[f"{r}\t{c}"] = {
                "freq": f,
                "coll_freq": by_coll[(r, c)],
                "logdice": 14 + math.log2(2 * f / (per_rel[r] + by_coll[(r, c)])),
            }
    node = sum(
        1
        for doc in docs
        for s in doc.sentences
        for t in s.tokens
        if (t.lemma if t.lemma not in (None, "_") else value(t.form)).lower() == lemma
    )
    return {
        "lemma": lemma,
        "min_freq": min_freq,
        "node_freq": node,
        "relations": dict(per_rel),
        "rows": rows,
    }


def golden():
    docs = with_meta(load_docs())
    return {
        "fixture": "tests/fixtures/ud-en-ewt-sample.conllu",
        "notes": "part = a for documents 1-8 (d0-d7), b for 9-16; n = document number; compare: `the` in part a "
        "vs part b; Mann-Whitney / Spearman values from SciPy (mannwhitneyu method=asymptotic, spearmanr)",
        "text_metrics": [text_metrics(docs, 1000), text_metrics(docs, 50)],
        "vocab": vocab_profile(docs),
        "compare": compare(docs),
        "sketch": [
            word_sketch(docs, "make", 1),
            word_sketch(docs, "say", 1),
            word_sketch(docs, "people", 1),
        ],
    }


if __name__ == "__main__":
    GOLDEN.write_text(
        json.dumps(golden(), ensure_ascii=False, indent=1) + "\n", encoding="utf-8"
    )
    print("written", GOLDEN)
