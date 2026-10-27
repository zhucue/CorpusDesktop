"""Corpus statistics over a built CWB index (contracts/p2.md §三).

A scope is an index plus an optional CQP restrict expression (engine.query.compile_filter): the documents whose
tokens satisfy it. Frequencies come from cwb-scan-corpus over the scope's document ranges (`-w s` keeps n-grams
inside one sentence); query hits come from CQP as in cwb.search (anchor within s, same-sentence +/- conditions).
Word units are exact CWB forms (NFC, case-sensitive), so a row's `"form"` query finds exactly the counted tokens.
A missing lemma or POS ("_") is not listed but counts in the token total.

Measures (N = tokens in scope):
  per_million = f / N * 1e6
  collocations: window = up to `window` tokens left of a node hit and right of it, inside the hit's sentence,
    excluding the hit itself; W = union of all windows (each corpus position once).
    O = f(collocate in W), R = |W|, C = f(collocate in scope), E = R*C/N, f_node = number of node hits
    MI = log2(O/E); t = (O-E)/sqrt(O); logDice = 14 + log2(2O/(f_node+C));
    LL = 2 Σ O_ij ln(O_ij/E_ij) over the 2x2 table window/outside × collocate/other, E_ij = R_i C_j / N
  keywords (a, b = target / reference frequency, c, d = target / reference tokens; only a/c > b/d is listed):
    LL = 2 (a ln(a/E1) + b ln(b/E2)), E1 = c(a+b)/(c+d), E2 = d(a+b)/(c+d)        (Rayson & Garside 2000)
    log ratio = log2((a/c) / (b/d)), a zero frequency counted as 0.5             (Hardie 2014)
    significance: LL ≥ 3.84 / 6.63 / 10.83 → * / ** / ***  (p < 0.05 / 0.01 / 0.001, 1 d.f.)
  Rows sort by the measure (rounded to 1e-10 so equal values tie), then frequency desc, then key.

search_query (engine.query.parse accepts every generated string):
  word `"form"` (+ `/tag` with a POS filter); lemma: alternation of the scope's forms of that lemma
  (`"run"|"ran"`, may also match homographs of other lemmas); pos `/TAG`; n-gram slots joined by spaces.
  collocation: search_query = `node $K "coll"` (collocate right of the node, K = window-1) and
  search_query_reverse = `"coll" $K node` (left); the grammar has no top-level alternation, so the two
  directions are two queries. A form containing `"` cannot be quoted: search_query is null.
"""

import math
from bisect import bisect_right
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from engine import cwb, query

TIMEOUT = 3600
MISSING = "_"
MEASURES = ("mi", "logdice", "t", "ll")
MEASURE_LABELS = {"mi": "MI", "logdice": "logDice", "t": "t", "ll": "LL"}
SIGNIFICANCE = ((10.827566, "***"), (6.634897, "**"), (3.841459, "*"))


@dataclass
class Scope:
    index_dir: Path
    corpus_key: str
    restrict: str | None = None


@dataclass
class Table:
    columns: list[dict]
    rows: list[dict]  # {key, values, search_query[, search_query_reverse | bin_value]}
    row_count: int  # rows passing min_freq before the top cut
    totals: dict


def _col(key, label, type="number"):
    return {"key": key, "label": label, "type": type}


def _rank(v):
    return round(v, 10)


def pos_tags(tag: str) -> tuple[str, ...]:
    """Query-style POS (`v`, `VERB`) → UPOS tags; raises query.QueryError."""
    return query._resolve_pos(tag, 0)


def _pos_keys(tags) -> list[str]:
    keys = []
    for i, tag in enumerate(tags):
        if tag:
            att = "pos" if i == 0 else f"pos+{i}"
            keys.append(f"?{att}=/({'|'.join(pos_tags(tag))})/")
    return keys


def _merge(spans):
    out = []
    for a, b in sorted(spans):
        if out and a <= out[-1][1] + 1:
            out[-1][1] = max(out[-1][1], b)
        else:
            out.append([a, b])
    return out


class _Corpus:
    """One scope: its document ranges, totals, scans and query hits."""

    def __init__(self, scope: Scope):
        self.key = cwb._key(scope.corpus_key)
        self.index_dir = Path(scope.index_dir)
        self.restrict = scope.restrict
        self.reg = str(self.index_dir / "registry")
        ix = cwb._open(str(cwb._home(self.index_dir, self.key)))
        docs = []
        if not ix.empty:
            docs = [
                (int(a), int(b), i) for a, b, i in self._decode("doc_id", values=True)
            ]
            if self.restrict:
                firsts = {
                    int(r[0])
                    for r in self._cqp(
                        [f"D = <doc> [] :: {self.restrict};", "tabulate D match;"]
                    )[0]
                }
                docs = [d for d in docs if d[0] in firsts]
        self.docs = docs
        self.ranges = [(a, b) for a, b, _ in docs]
        self.tokens = sum(b - a + 1 for a, b in self.ranges)
        self.totals = {
            "tokens": self.tokens,
            "sentences": sum(ix.doc(i)[5] for _, _, i in docs),
            "documents": len(docs),
        }
        self._forms = {}

    def _decode(self, att, values=False):
        args = ["cwb-s-decode", "-r", self.reg] + ([] if values else ["-v"])
        out = cwb._run([*args, self.key.upper(), "-S", att])
        return [line.split("\t") for line in out.split("\n") if line]

    def _cqp(self, commands):
        cmds = []
        for c in commands:
            cmds.append(c)
            if c.startswith("tabulate"):
                cmds.append(".EOL.;")
        return cwb._cqp(self.index_dir, self.key, cmds, TIMEOUT)

    def pm(self, f):
        return f / self.tokens * 1e6 if self.tokens else 0.0

    def scan(self, keys, ranges=None, within_s=False) -> Counter:
        """cwb-scan-corpus over ranges (default: the scope) → Counter{(values...): f}."""
        ranges = self.ranges if ranges is None else ranges
        counts = Counter()
        if not ranges:
            return counts
        args = ["cwb-scan-corpus", "-q", "-r", self.reg, "-R", "/dev/stdin"]
        args += ["-w", "s"] if within_s else []
        out = cwb._run(
            [*args, self.key.upper(), *keys],
            input="".join(f"{a}\t{b}\n" for a, b in ranges),
        )
        for line in out.split("\n"):
            if line:
                f, *vals = line.split("\t")
                counts[tuple(vals)] += int(f)
        return counts

    def sentences(self):
        rows = self._decode("s")
        return [int(r[0]) for r in rows], [int(r[1]) for r in rows]

    def hits(self, text) -> list[tuple[int, int]]:
        """(match, matchend) of every hit of a query in the scope, in corpus order."""
        anchor, conds, _ = cwb._split(query.compile(query.parse(text)))
        if not self.docs:
            return []
        cmds = []
        for i, (_, q) in enumerate(conds):
            cmds += [
                f"C{i} = {q} within s;",
                f"S{i} = C{i} expand to s;",
                f"tabulate S{i} match doc_id, match s_n;",
            ]
        where = f" :: {self.restrict}" if self.restrict else ""
        cmds += [
            f"A = {anchor}{where} within s;",
            "tabulate A match, matchend, match doc_id, match s_n;",
        ]
        sections = self._cqp(cmds)
        rows = sections[-1]
        for (op, _), sents in zip(conds, sections):
            found = {(r[0], r[1]) for r in sents}
            rows = [r for r in rows if ((r[2], r[3]) in found) == (op == "+")]
        return [(int(r[0]), int(r[1])) for r in rows]

    def forms(self, tag=None) -> dict[str, list[str]]:
        """lemma → its word forms in the scope (most frequent first)."""
        if tag not in self._forms:
            counts = self.scan(["lemma", "word", *_pos_keys([tag])])
            by_lemma = {}
            for (lemma, form), f in sorted(counts.items(), key=lambda x: (-x[1], x[0])):
                by_lemma.setdefault(lemma, []).append(form)
            self._forms[tag] = by_lemma
        return self._forms[tag]


def _slot(c: _Corpus, unit, value, tag=None):
    """One query slot matching a unit value, or None when it cannot be written."""
    if unit == "pos":
        return f"/{value}" if value in query.UPOS else None
    words = [value] if unit == "word" else c.forms(tag).get(value, [])
    words = [w for w in words if '"' not in w]
    suffix = f"/{tag}" if tag else ""
    return "|".join(f'"{w}"{suffix}' for w in words) or None


def _row(key, values, search_query, **extra):
    return {"key": key, "values": values, "search_query": search_query, **extra}


def _check_unit(unit, allowed):
    if unit not in allowed:
        raise ValueError(f"未知统计单位：{unit}")


# ---------------------------------------------------------------- methods


def frequency(scope: Scope, unit="word", pos=None, top=200, min_freq=1) -> Table:
    _check_unit(unit, ("word", "lemma", "pos"))
    c = _Corpus(scope)
    freq, docs = Counter(), Counter()
    for (value, _), f in c.scan([unit, "doc_id", *_pos_keys([pos])]).items():
        if unit == "word" or value != MISSING:
            freq[value] += f
            docs[value] += 1
    items = sorted(
        (v for v in freq if freq[v] >= min_freq), key=lambda v: (-freq[v], v)
    )
    rows = [
        _row(
            v,
            {
                "item": v,
                "freq": freq[v],
                "per_million": c.pm(freq[v]),
                "doc_freq": docs[v],
            },
            _slot(c, unit, v, pos),
        )
        for v in items[:top]
    ]
    columns = [
        _col("item", "项", "string"),
        _col("freq", "频次"),
        _col("per_million", "每百万词"),
        _col("doc_freq", "文档频率"),
    ]
    return Table(columns, rows, len(items), c.totals)


def ngrams(
    scope: Scope, n=2, unit="word", pos_pattern=None, top=200, min_freq=2
) -> Table:
    _check_unit(unit, ("word", "lemma"))
    if not 2 <= n <= 4:
        raise ValueError("n 须为 2 至 4")
    tags = list(pos_pattern or [None] * n)
    if len(tags) != n:
        raise ValueError("词性模式长度须等于 n")
    tags = [t or None for t in tags]
    c = _Corpus(scope)
    keys = [unit if i == 0 else f"{unit}+{i}" for i in range(n)] + _pos_keys(tags)
    counts = {
        k: f
        for k, f in c.scan(keys, within_s=True).items()
        if f >= min_freq and (unit == "word" or MISSING not in k)
    }
    items = sorted(counts, key=lambda k: (-counts[k], k))
    rows = []
    for k in items[:top]:
        slots = [_slot(c, unit, v, t) for v, t in zip(k, tags)]
        q = None if None in slots else " ".join(slots)
        f = counts[k]
        rows.append(
            _row(
                "\t".join(k),
                {"ngram": " ".join(k), "freq": f, "per_million": c.pm(f)},
                q,
            )
        )
    columns = [
        _col("ngram", "n-gram", "string"),
        _col("freq", "频次"),
        _col("per_million", "每百万词"),
    ]
    return Table(columns, rows, len(items), c.totals)


def _ll2x2(o11, r1, c1, n):
    obs = (o11, r1 - o11, c1 - o11, n - r1 - c1 + o11)
    exp = (r1 * c1 / n, r1 * (n - c1) / n, (n - r1) * c1 / n, (n - r1) * (n - c1) / n)
    return 2 * sum(o * math.log(o / e) for o, e in zip(obs, exp) if o > 0)


def collocations(
    scope: Scope,
    node: str,
    window=5,
    unit="word",
    pos=None,
    measures=MEASURES,
    min_freq=3,
    top=200,
) -> Table:
    _check_unit(unit, ("word", "lemma"))
    measures = list(measures) or list(MEASURES)
    if set(measures) - set(MEASURES) or window < 1:
        raise ValueError("搭配参数不正确")
    ast = query.parse(node)
    c = _Corpus(scope)
    hits = c.hits(node)
    starts, ends = c.sentences() if hits else ([], [])
    spans = []
    for m, me in hits:
        k = bisect_right(starts, m) - 1
        if m > starts[k]:
            spans.append((max(starts[k], m - window), m - 1))
        if me < ends[k]:
            spans.append((me + 1, min(ends[k], me + window)))
    union = _merge(spans)
    r1 = sum(b - a + 1 for a, b in union)
    keys = [unit, *_pos_keys([pos])]
    observed = c.scan(keys, union) if union else Counter()
    totals = c.scan(keys) if observed else Counter()
    n, f_node = c.tokens, len(hits)
    stats = {}
    for (y,), o in observed.items():
        if o < min_freq or (unit == "lemma" and y == MISSING):
            continue
        c1 = totals[(y,)]
        e = r1 * c1 / n
        stats[y] = {
            "collocate": y,
            "freq": o,
            "coll_freq": c1,
            "mi": math.log2(o / e),
            "logdice": 14 + math.log2(2 * o / (f_node + c1)),
            "t": (o - e) / math.sqrt(o),
            "ll": _ll2x2(o, r1, c1, n),
        }
    first = measures[0]
    items = sorted(stats, key=lambda y: (-_rank(stats[y][first]), -stats[y]["freq"], y))
    gap = f" ${window - 1} " if window > 1 else " "
    tail = "".join(f" {cond.op}{cond.query.text}" for cond in ast.conditions)
    shown = [m for m in MEASURES if m in measures]
    rows = []
    for y in items[:top]:
        s = stats[y]
        slot = _slot(c, unit, y, pos)
        rows.append(
            _row(
                y,
                {k: s[k] for k in ("collocate", "freq", "coll_freq", *shown)},
                slot and f"{ast.anchor.text}{gap}{slot}{tail}",
                search_query_reverse=slot and f"{slot}{gap}{ast.anchor.text}{tail}",
            )
        )
    columns = [
        _col("collocate", "搭配词", "string"),
        _col("freq", "共现频次"),
        _col("coll_freq", "搭配词频次"),
    ]
    columns += [_col(m, MEASURE_LABELS[m]) for m in shown]
    totals_ = {**c.totals, "node_hits": f_node, "window_tokens": r1}
    return Table(columns, rows, len(items), totals_)


def significance(ll):
    return next((mark for crit, mark in SIGNIFICANCE if ll >= crit), "")


def keywords(
    target: Scope, reference: Scope, unit="word", measure="ll", min_freq=3, top=200
) -> Table:
    _check_unit(unit, ("word", "lemma"))
    if measure not in ("ll", "log_ratio"):
        raise ValueError(f"未知关键词指标：{measure}")
    t, r = _Corpus(target), _Corpus(reference)
    if not r.tokens:
        raise ValueError("参照范围没有词")
    ft, fr = t.scan([unit]), r.scan([unit])
    c, d = t.tokens, r.tokens
    stats = {}
    for (w,), a in ft.items():
        b = fr.get((w,), 0)
        if a < min_freq or (unit == "lemma" and w == MISSING) or a / c <= b / d:
            continue
        e1, e2 = c * (a + b) / (c + d), d * (a + b) / (c + d)
        ll = 2 * (a * math.log(a / e1) + (b * math.log(b / e2) if b else 0))
        stats[w] = {
            "word": w,
            "target_freq": a,
            "ref_freq": b,
            "target_pm": a / c * 1e6,
            "ref_pm": b / d * 1e6,
            "ll": ll,
            "log_ratio": math.log2((a / c) / ((b or 0.5) / d)),
            "significance": significance(ll),
        }
    items = sorted(
        stats, key=lambda w: (-_rank(stats[w][measure]), -stats[w]["target_freq"], w)
    )
    rows = [_row(w, stats[w], _slot(t, unit, w)) for w in items[:top]]
    columns = [
        _col("word", "词", "string"),
        _col("target_freq", "目标频次"),
        _col("ref_freq", "参照频次"),
        _col("target_pm", "目标每百万"),
        _col("ref_pm", "参照每百万"),
        _col("ll", "LL"),
        _col("log_ratio", "log ratio"),
        _col("significance", "显著性", "string"),
    ]
    totals = {**t.totals, "reference": r.totals}
    return Table(columns, rows, len(items), totals)


def _number(s):
    try:
        return int(s)
    except ValueError:
        try:
            return float(s)
        except ValueError:
            return s


def _pct(x):
    return f"{x:g}"


def distribution(
    scope: Scope, query_text=None, field="position", bins=10, numeric=False, top=1000
) -> Table:
    """Hits, tokens and hits per million per bin; bins are relative document position or values of a
    metadata field (documents without the field are left out). Without a query, hits are null."""
    c = _Corpus(scope)
    hits = c.hits(query_text) if query_text else []
    starts = [a for a, _, _ in c.docs]
    tokens, counts, labels, bin_values = Counter(), Counter(), {}, {}
    if field == "position":
        if not 1 <= bins <= 100:
            raise ValueError("区间数须为 1 至 100")
        for a, b, _ in c.docs:
            n = b - a + 1
            for k in range(bins):
                tokens[k] += -(-(k + 1) * n // bins) - -(-k * n // bins)
        for m, _ in hits:
            a, b, _ = c.docs[bisect_right(starts, m) - 1]
            counts[(m - a) * bins // (b - a + 1)] += 1
        order = list(range(bins))
        for k in order:
            labels[k] = f"{_pct(100 * k / bins)}–{_pct(100 * (k + 1) / bins)}%"
    else:
        decoded = {}
        if c.docs:
            try:
                att = "doc_" + cwb.meta_attr(field)
                decoded = {int(a): v for a, _, v in c._decode(att, values=True)}
            except cwb.CQPError:
                raise ValueError(f"语料中没有字段：{field}") from None
        doc_bin = {}
        for a, b, _ in c.docs:
            raw = decoded.get(a, "")
            if raw == "":
                continue
            value = _number(raw) if numeric else raw
            doc_bin[a] = raw
            bin_values[raw], labels[raw] = value, str(value)
            tokens[raw] += b - a + 1
        for m, _ in hits:
            a = starts[bisect_right(starts, m) - 1]
            if a in doc_bin:
                counts[doc_bin[a]] += 1
        order = sorted(
            bin_values,
            key=lambda k: (isinstance(bin_values[k], str), bin_values[k]),
        )
    rows = []
    for k in order:
        h = counts[k] if query_text else None
        values = {
            "bin": labels[k],
            "hits": h,
            "tokens": tokens[k],
            "per_million": None
            if h is None
            else (h / tokens[k] * 1e6 if tokens[k] else 0.0),
        }
        extra = {"bin_value": bin_values[k]} if field != "position" else {}
        rows.append(_row(labels[k], values, query_text, **extra))
    columns = [
        _col("bin", "区间或字段值", "string"),
        _col("hits", "命中数"),
        _col("tokens", "词数"),
        _col("per_million", "每百万"),
    ]
    totals = {**c.totals, "hits": len(hits) if query_text else None}
    return Table(columns, rows[:top], len(rows), totals)
