"""Corpus statistics over a built CWB index (contracts/p2.md §三).

A scope is an index plus an optional CQP restrict expression (engine.query.compile_filter): the documents whose
tokens satisfy it. Frequencies come from cwb-scan-corpus over the scope's document ranges (`-w s` keeps n-grams
inside one sentence); query hits come from CQP as in cwb.search (anchor within s, same-sentence +/- conditions).
Word units are exact CWB forms (NFC, case-sensitive), so a row's `"form"` query finds exactly the counted tokens.
A missing lemma or POS ("_") is not listed but counts in the token total. POS filters resolve against the
index tagset (cwb.tagset: UPOS, jieba or mixed), as query POS does.

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
    effect sizes (contracts/p8.md §三; a' = a or 0.5, b' = b or 0.5 when a frequency is 0, values.smoothed):
      %DIFF = (a/c − b'/d) / (b'/d) × 100                                          (Gabrielatos & Marchi 2012)
      odds ratio = (a'/(c − a')) / (b'/(d − b'))
      log ratio 95% CI = log2((a'/c)/(b'/d)) ± 1.959964 × √(1/a' + 1/b') / ln 2  (SE of ln RR, on the log2 scale)
      bonferroni: p = P(χ²₁ ≥ LL) multiplied by m = word types compared (target ∪ reference after the unit,
        lemma and punctuation exclusions); p·m < 0.05 / 0.01 / 0.001 → * / ** / ***
    direction: positive lists a/c > b/d (min_freq on a), negative b/d > a/c (min_freq on b), both = either;
      rows sort by |measure| (ll as is; odds ratio by |ln OR|), so the positive order is unchanged.
    items: only these words (given order), whatever min_freq and direction.
  collocations, further measures on the same table (Oakes 1998; Gries 2013):
    MI3 = log2(O³/E); z = (O − E)/√E;
    ΔP node→collocate = O/R − (C − O)/(N − R); ΔP collocate→node = O/C − (R − O)/(N − C)
  frequency dispersion (contracts/p8.md §二), parts: document | segments (10 equal token segments of the scope
    in corpus order) | field:<name> (one part per value; documents without it are left out, and f, the part
    sizes and their total then count only the documents in some part):
    sᵢ = part tokens / Σ part tokens, vᵢ = fᵢ / f, DP = ½ Σ|vᵢ − sᵢ| (Gries 2008), DPnorm = DP / (1 − min sᵢ)
    (Lijffijt & Gries 2012); Juilland D = 1 − CV/√(n − 1), CV = population SD / mean of pᵢ = fᵢ / part tokens;
    range = parts with fᵢ > 0. Fewer than 2 parts: these values are null.
  breakdown (contracts/p8.md §一): hits come from cwb.query_rows exactly as search counts them; word / lemma /
    pos values of the hit tokens are read from the CWB attribute files.
  Rows sort by the measure (rounded to 1e-10 so equal values tie), then frequency desc, then key.

search_query (engine.query.parse accepts every generated string):
  word `"form"` (+ `/tag` with a POS filter); lemma: alternation of the scope's forms of that lemma
  (`"run"|"ran"`, may also match homographs of other lemmas); pos `/TAG`; n-gram slots joined by spaces.
  collocation: search_query = `node $K "coll"` (collocate right of the node, K = window-1) and
  search_query_reverse = `"coll" $K node` (left); the grammar has no top-level alternation, so the two
  directions are two queries. A form containing `"` cannot be quoted: search_query is null.

exclude_punct (word / lemma units): leave out items made only of punctuation, symbols and digits (`，`, `(`,
  `1990`, `3.5%`); an n-gram is left out when any slot is such an item. N and every measure still count all tokens,
  punctuation included (totals.tokens); frequency reports the left-out tokens as totals.excluded_tokens.
"""

import contextlib
import math
import mmap
import re
import struct
from bisect import bisect_right
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from engine import cwb, query

TIMEOUT = 3600
MISSING = "_"
MEASURES = ("mi", "logdice", "t", "ll", "mi3", "delta_p", "z")
MEASURE_LABELS = {
    "mi": "MI",
    "logdice": "logDice",
    "t": "t",
    "ll": "LL",
    "mi3": "MI3",
    "z": "z",
    "delta_p_node": "ΔP 节点→搭配词",
    "delta_p_coll": "ΔP 搭配词→节点",
}
KEYWORD_MEASURES = ("ll", "log_ratio", "pct_diff", "odds_ratio")
DIRECTIONS = ("positive", "negative", "both")
SIGNIFICANCE = ((10.827566, "***"), (6.634897, "**"), (3.841459, "*"))
P_LEVELS = ((0.001, "***"), (0.01, "**"), (0.05, "*"))
Z95 = 1.959963984540054
SEGMENTS = 10
BREAKDOWN_BY = ("word", "lemma", "pos", "left1", "right1")
SENT_START, SENT_END, NO_VALUE = "（句首）", "（句末）", "（无）"
_PUNCT = re.compile(r"[\W\d_]+")
_ATTR_UNSAFE = set(' ,{}[]|=/"')


def is_punct(value: str) -> bool:
    """Only punctuation, symbols, spaces and digits (no letter or CJK character)."""
    return bool(_PUNCT.fullmatch(value))


@dataclass
class Scope:
    index_dir: Path
    corpus_key: str
    restrict: str | None = None
    tagset: str | None = None  # POS tag set; None = read from the index (cwb.tagset)


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


def pos_tags(tag: str, tagset: str = "upos") -> tuple[str, ...]:
    """Query-style POS (`v`, `VERB`, `nr`) → index tags of a tagset; raises query.QueryError."""
    return query.resolve_pos(tag, tagset)


def _pos_keys(tags, tagset) -> list[str]:
    keys = []
    for i, tag in enumerate(tags):
        if tag:
            att = "pos" if i == 0 else f"pos+{i}"
            keys.append(f"?{att}=/({'|'.join(pos_tags(tag, tagset))})/")
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
        self.tagset = scope.tagset or cwb.tagset(self.index_dir, self.key)
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
        compiled = query.compile(query.parse(text, self.tagset))
        if query.attrs(compiled) or query.spans(compiled):
            raise ValueError("统计中的查询式不支持 {…} 属性约束与带词的 […] 片段标签")
        anchor, conds, _ = cwb._split(compiled)
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

    def rows(self, text, attr_filter=None, max_hits=None):
        """Hit rows (match, matchend, doc_id, sentence) of a query in the scope, in corpus order, as search
        counts them (cwb.query_rows; attr_filter answers `{…}` / `[…]` slots). More than max_hits anchor hits
        raise ValueError."""
        if not self.docs:
            return []
        compiled = query.compile(query.parse(text, self.tagset))
        try:
            return cwb.query_rows(
                self.index_dir,
                self.key,
                compiled,
                restrict=self.restrict,
                timeout=TIMEOUT,
                attr_filter=attr_filter,
                max_hits=max_hits,
            )
        except cwb.TooManyHits as e:
            raise ValueError(f"命中超过 {e.limit}，请缩小范围或加条件") from None

    def doc_values(self, field) -> dict[str, str]:
        """doc_id → raw index value of a metadata field, for the scope's documents that have it."""
        if not self.docs:
            return {}
        try:
            att = "doc_" + cwb.meta_attr(field)
            by_start = {int(a): v for a, _, v in self._decode(att, values=True)}
        except cwb.CQPError:
            raise ValueError(f"语料中没有字段：{field}") from None
        return {d: by_start[a] for a, _, d in self.docs if by_start.get(a, "") != ""}

    def attr(self, att) -> "_Attr":
        return _Attr(cwb._home(self.index_dir, self.key) / "data", att)

    def forms(self, tag=None) -> dict[str, list[str]]:
        """lemma → its word forms in the scope (most frequent first)."""
        if tag not in self._forms:
            counts = self.scan(["lemma", "word", *_pos_keys([tag], self.tagset)])
            by_lemma = {}
            for (lemma, form), f in sorted(counts.items(), key=lambda x: (-x[1], x[0])):
                by_lemma.setdefault(lemma, []).append(form)
            self._forms[tag] = by_lemma
        return self._forms[tag]


class _Attr:
    """Values of a positional attribute by corpus position, read from the CWB data files: <att>.corpus holds
    int32 big-endian lexicon ids (cwb-makeall leaves it uncompressed), <att>.lexicon.idx int32 big-endian byte
    offsets into <att>.lexicon (NUL-terminated strings). Use as a context manager."""

    def __init__(self, data: Path, att: str):
        self._paths = [
            data / f"{att}{ext}" for ext in (".corpus", ".lexicon.idx", ".lexicon")
        ]
        self._cache = {}

    def __enter__(self):
        self._stack = contextlib.ExitStack()
        self._maps = []
        for path in self._paths:
            f = self._stack.enter_context(open(path, "rb"))
            m = mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ)
            self._maps.append(self._stack.enter_context(m))
        return self

    def __exit__(self, *exc):
        self._stack.close()

    def __call__(self, cpos: int) -> str:
        ids, idx, lex = self._maps
        i = struct.unpack_from(">i", ids, 4 * cpos)[0]
        v = self._cache.get(i)
        if v is None:
            off = struct.unpack_from(">i", idx, 4 * i)[0]
            v = self._cache[i] = lex[off : lex.find(b"\0", off)].decode("utf-8")
        return v


def _slot(c: _Corpus, unit, value, tag=None):
    """One query slot matching a unit value, or None when it cannot be written."""
    if (
        unit == "pos"
    ):  # only when `/value` matches exactly this tag (jieba `n` would also match nr, ns …)
        try:
            exact = query.resolve_pos(value, c.tagset) == (value,)
        except query.QueryError:
            exact = False
        return f"/{value}" if exact else None
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


def dispersion_measures(freqs: dict, sizes: dict) -> dict:
    """range, range_pct, dp, dp_norm, juilland_d of one item; freqs {part: f}, sizes {part: tokens} (all
    parts, sizes > 0). Fewer than 2 parts: all None; f = 0 in the parts: range 0 and the measures None."""
    n = len(sizes)
    keys = ("range", "range_pct", "dp", "dp_norm", "juilland_d")
    if n < 2:
        return dict.fromkeys(keys)
    occ = {p: f for p, f in freqs.items() if f and p in sizes}
    f, total, r = sum(occ.values()), sum(sizes.values()), len(occ)
    out = {"range": r, "range_pct": r / n * 100, "dp": None, "dp_norm": None}
    out["juilland_d"] = None
    if not f:
        return out
    s = {p: sizes[p] / total for p in occ}
    dp = 0.5 * (sum(abs(occ[p] / f - s[p]) for p in occ) + 1 - sum(s.values()))
    out["dp"] = dp
    out["dp_norm"] = dp / (1 - min(sizes.values()) / total)
    rel = [occ[p] / sizes[p] for p in occ]
    mean = sum(rel) / n
    var = (sum((x - mean) ** 2 for x in rel) + (n - r) * mean**2) / n
    out["juilland_d"] = 1 - math.sqrt(var) / mean / math.sqrt(n - 1)
    return out


def _parts(parts) -> tuple[str, str | None]:
    if parts in ("document", "segments"):
        return parts, None
    if parts.startswith("field:") and parts[6:]:
        return "field", parts[6:]
    raise ValueError(f"未知部分划分：{parts}")


def segments(ranges, total, k=SEGMENTS) -> list[list[tuple[int, int]]]:
    """The scope's tokens in corpus order cut into k parts of ⌈i·total/k⌉ boundaries, as corpus ranges."""
    bounds = [-(-i * total // k) for i in range(k + 1)]
    out, offset = [[] for _ in range(k)], 0
    for a, b in ranges:
        n = b - a + 1
        for s in range(k):
            lo, hi = max(bounds[s], offset), min(bounds[s + 1], offset + n)
            if lo < hi:
                out[s].append((a + lo - offset, a + hi - 1 - offset))
        offset += n
    return out


def _part_counts(c: _Corpus, keys, parts, shown, scanned):
    """(sizes {part: tokens}, {value: {part: f}}) of the shown values; scanned = the (value, doc_id) scan."""
    kind, field = _parts(parts)
    want = set(shown)
    counts = {v: Counter() for v in want}
    if kind == "segments":
        sizes = {}
        for k, ranges in enumerate(segments(c.ranges, c.tokens)):
            size = sum(b - a + 1 for a, b in ranges)
            if not size:
                continue
            sizes[k] = size
            for (value,), f in c.scan(keys, ranges).items():
                if value in want:
                    counts[value][k] += f
        return sizes, counts
    if kind == "document":
        doc_part = {d: d for _, _, d in c.docs}
    else:
        doc_part = c.doc_values(field)
    sizes = Counter()
    for a, b, d in c.docs:
        if d in doc_part:
            sizes[doc_part[d]] += b - a + 1
    for (value, d), f in scanned.items():
        if value in want and d in doc_part:
            counts[value][doc_part[d]] += f
    return dict(sizes), counts


def frequency(
    scope: Scope,
    unit="word",
    pos=None,
    top=200,
    min_freq=1,
    exclude_punct=False,
    parts="document",
    dispersion=False,
) -> Table:
    """dispersion: add range, range_pct, dp, dp_norm, juilland_d over `parts` (module docstring)."""
    _check_unit(unit, ("word", "lemma", "pos"))
    _parts(parts)
    c = _Corpus(scope)
    skip = exclude_punct and unit != "pos"
    freq, docs, excluded = Counter(), Counter(), 0
    pos_keys = _pos_keys([pos], c.tagset)
    scanned = c.scan([unit, "doc_id", *pos_keys])
    for (value, _), f in scanned.items():
        if skip and is_punct(value):
            excluded += f
        elif unit == "word" or value != MISSING:
            freq[value] += f
            docs[value] += 1
    items = sorted(
        (v for v in freq if freq[v] >= min_freq), key=lambda v: (-freq[v], v)
    )
    shown = items[:top]
    if dispersion:
        sizes, counts = _part_counts(c, [unit, *pos_keys], parts, shown, scanned)
    rows = []
    for v in shown:
        values = {
            "item": v,
            "freq": freq[v],
            "per_million": c.pm(freq[v]),
            "doc_freq": docs[v],
        }
        if dispersion:
            values.update(dispersion_measures(counts[v], sizes))
        rows.append(_row(v, values, _slot(c, unit, v, pos)))
    columns = [
        _col("item", "项", "string"),
        _col("freq", "频次"),
        _col("per_million", "每百万词"),
        _col("doc_freq", "文档频率"),
    ]
    totals = {**c.totals, "excluded_tokens": excluded} if skip else dict(c.totals)
    if dispersion:
        columns += [
            _col("range", "分布部分数"),
            _col("range_pct", "分布部分 %"),
            _col("dp", "DP"),
            _col("dp_norm", "DPnorm"),
            _col("juilland_d", "Juilland D"),
        ]
        totals["parts"] = len(sizes)
    return Table(columns, rows, len(items), totals)


def ngrams(
    scope: Scope,
    n=2,
    unit="word",
    pos_pattern=None,
    top=200,
    min_freq=2,
    contains=None,
    exclude_punct=False,
) -> Table:
    """contains: keep only n-grams with this unit value (exact word form or lemma) in some slot."""
    _check_unit(unit, ("word", "lemma"))
    if not 2 <= n <= 4:
        raise ValueError("n 须为 2 至 4")
    tags = list(pos_pattern or [None] * n)
    if len(tags) != n:
        raise ValueError("词性模式长度须等于 n")
    tags = [t or None for t in tags]
    contains = (contains or "").strip() or None
    c = _Corpus(scope)
    keys = [unit if i == 0 else f"{unit}+{i}" for i in range(n)] + _pos_keys(
        tags, c.tagset
    )
    counts = {
        k: f
        for k, f in c.scan(keys, within_s=True).items()
        if f >= min_freq
        and (unit == "word" or MISSING not in k)
        and (contains is None or contains in k)
        and not (exclude_punct and any(is_punct(v) for v in k))
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
    exclude_punct=False,
) -> Table:
    _check_unit(unit, ("word", "lemma"))
    measures = list(measures) or list(MEASURES)
    if set(measures) - set(MEASURES) or window < 1:
        raise ValueError("搭配参数不正确")
    c = _Corpus(scope)
    ast = query.parse(node, c.tagset)
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
    keys = [unit, *_pos_keys([pos], c.tagset)]
    observed = c.scan(keys, union) if union else Counter()
    totals = c.scan(keys) if observed else Counter()
    n, f_node = c.tokens, len(hits)
    stats = {}
    for (y,), o in observed.items():
        if (
            o < min_freq
            or (unit == "lemma" and y == MISSING)
            or (exclude_punct and is_punct(y))
        ):
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
            "mi3": math.log2(o**3 / e),
            "z": (o - e) / math.sqrt(e),
            "delta_p_node": o / r1 - ((c1 - o) / (n - r1) if n > r1 else 0.0),
            "delta_p_coll": o / c1 - ((r1 - o) / (n - c1) if n > c1 else 0.0),
        }
    first = "delta_p_node" if measures[0] == "delta_p" else measures[0]
    items = sorted(stats, key=lambda y: (-_rank(stats[y][first]), -stats[y]["freq"], y))
    gap = f" ${window - 1} " if window > 1 else " "
    tail = "".join(f" {cond.op}{cond.query.text}" for cond in ast.conditions)
    shown = [
        k
        for m in MEASURES
        if m in measures
        for k in (("delta_p_node", "delta_p_coll") if m == "delta_p" else (m,))
    ]
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


def _p_chi1(x):
    """Upper tail of χ² with 1 d.f."""
    return math.erfc(math.sqrt(max(x, 0.0) / 2))


def keyword_values(a, b, c, d, m=1) -> dict:
    """Keyword measures of a word with frequency a / b in target / reference of c / d tokens; m = number
    of word types compared (Bonferroni). Formulas in the module docstring."""
    e1, e2 = c * (a + b) / (c + d), d * (a + b) / (c + d)
    ll = 2 * ((a * math.log(a / e1) if a else 0) + (b * math.log(b / e2) if b else 0))
    a1, b1 = a or 0.5, b or 0.5
    lr = math.log2((a1 / c) / (b1 / d))
    half = Z95 * math.sqrt(1 / a1 + 1 / b1) / math.log(2)
    p = _p_chi1(ll) * m
    return {
        "target_freq": a,
        "ref_freq": b,
        "target_pm": a / c * 1e6,
        "ref_pm": b / d * 1e6,
        "ll": ll,
        "log_ratio": lr,
        "log_ratio_ci_low": lr - half,
        "log_ratio_ci_high": lr + half,
        "pct_diff": (a / c - b1 / d) / (b1 / d) * 100,
        "odds_ratio": (a1 / (c - a1)) / (b1 / (d - b1)) if c > a1 and d > b1 else None,
        "significance": significance(ll),
        "bonferroni": next((mark for lim, mark in P_LEVELS if p < lim), ""),
        "smoothed": not (a and b),
    }


def _keyword_rank(values, measure):
    v = values[measure]
    if v is None:  # odds ratio of a word that makes up a whole corpus
        return math.inf
    return abs(math.log(v)) if measure == "odds_ratio" else abs(v)


def keywords(
    target: Scope,
    reference: Scope,
    unit="word",
    measure="ll",
    min_freq=3,
    top=200,
    exclude_punct=False,
    direction="positive",
    items=None,
) -> Table:
    """direction: positive (a/c > b/d), negative (b/d > a/c) or both; items: only these words."""
    _check_unit(unit, ("word", "lemma"))
    if measure not in KEYWORD_MEASURES:
        raise ValueError(f"未知关键词指标：{measure}")
    if direction not in DIRECTIONS:
        raise ValueError(f"未知方向：{direction}")
    t, r = _Corpus(target), _Corpus(reference)
    if not r.tokens:
        raise ValueError("参照范围没有词")
    if not t.tokens:
        raise ValueError("目标范围没有词")
    ft, fr = t.scan([unit]), r.scan([unit])
    c, d = t.tokens, r.tokens
    types = {
        w
        for (w,) in (*ft, *fr)
        if not (unit == "lemma" and w == MISSING)
        and not (exclude_punct and is_punct(w))
    }
    m = max(len(types), 1)
    stats = {}
    if items is not None:
        words = list(dict.fromkeys(items))
    else:
        words = []
        for w in types:
            a, b = ft.get((w,), 0), fr.get((w,), 0)
            pos_ok = a / c > b / d and a >= min_freq
            neg_ok = b / d > a / c and b >= min_freq
            if (direction != "negative" and pos_ok) or (
                direction != "positive" and neg_ok
            ):
                words.append(w)
    for w in words:
        a, b = ft.get((w,), 0), fr.get((w,), 0)
        stats[w] = {"word": w, **keyword_values(a, b, c, d, m)}
    if items is None:
        words.sort(
            key=lambda w: (
                -_rank(_keyword_rank(stats[w], measure)),
                -stats[w]["target_freq"],
                w,
            )
        )
    rows = [_row(w, stats[w], _slot(t, unit, w)) for w in words[:top]]
    columns = [
        _col("word", "词", "string"),
        _col("target_freq", "目标频次"),
        _col("ref_freq", "参照频次"),
        _col("target_pm", "目标每百万"),
        _col("ref_pm", "参照每百万"),
        _col("ll", "LL"),
        _col("log_ratio", "log ratio"),
        _col("log_ratio_ci_low", "log ratio 95% 下限"),
        _col("log_ratio_ci_high", "log ratio 95% 上限"),
        _col("pct_diff", "%DIFF"),
        _col("odds_ratio", "odds ratio"),
        _col("significance", "显著性", "string"),
        _col("bonferroni", "Bonferroni 显著性", "string"),
    ]
    totals = {**t.totals, "reference": r.totals, "types_compared": m}
    return Table(columns, rows, len(words), totals)


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
    scope: Scope,
    query_text=None,
    field="position",
    bins=10,
    numeric=False,
    top=1000,
    positions=None,
) -> Table:
    """Hits, tokens and hits per million per bin; bins are relative document position or values of a
    metadata field (documents without the field are left out). Without a query, hits are null.
    positions: hits given by the caller instead of running query_text, as (document id, token offset in the
    document) pairs (pure span queries, answered in PostgreSQL); documents outside the scope are ignored."""
    c = _Corpus(scope)
    if positions is not None:
        first = {d: a for a, _, d in c.docs}
        hits = sorted((first[d] + k, first[d] + k) for d, k in positions if d in first)
    else:
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


def hit_rows(scope: Scope, query_text, attr_filter=None, max_hits=None):
    """(hit rows as search counts them, scope totals); see _Corpus.rows."""
    c = _Corpus(scope)
    return c.rows(query_text, attr_filter, max_hits), c.totals


def _plain_value(v):
    return bool(v) and v != MISSING and not any(ch in _ATTR_UNSAFE for ch in v)


def _breakdown_query(c: _Corpus, ast, kind, values, tail):
    """search_query of a breakdown row (contracts/p8.md §一), None when it cannot be written."""
    anchor = ast.anchor.text
    if kind == "word":
        if any('"' in v for v in values):
            return None
        return " ".join(f'"{v}"' for v in values) + tail
    if kind == "lemma":
        if len(values) == 1 and not tail and _plain_value(values[0]):
            return f"{{lemma={values[0]}}}"
        # several slots or conditions: `{lemma=}` slots would make CWB scan every position, so each slot
        # is the alternation of the scope's forms of that lemma (as frequency rows)
        slots = [_slot(c, "lemma", v) if v != MISSING else None for v in values]
        return None if None in slots else " ".join(slots) + tail
    if kind == "pos":
        slots = [_slot(c, "pos", v) for v in values]
        return None if None in slots else " ".join(slots) + tail
    (v,) = values
    if v in (SENT_START, SENT_END) or '"' in v:
        return None
    return f'"{v}" {anchor}{tail}' if kind == "left1" else f'{anchor} "{v}"{tail}'


def breakdown(
    scope: Scope,
    query_text: str,
    by="word",
    top=200,
    min_freq=1,
    numeric=False,
    attr_filter=None,
    max_hits=None,
) -> Table:
    """Hits of a query split by the hit's word forms / lemmas / POS (multi-token hits joined by spaces), the
    word left / right of it in its sentence, or a metadata field of its document (`meta:<field>`). The hits
    are those search counts (cwb.query_rows with attr_filter); totals.hits = all of them. meta rows carry
    bin_value (the field value) for a temporary filter scope; documents without the field: "（无）"."""
    if by in BREAKDOWN_BY:
        kind, field = by, None
    elif by.startswith("meta:") and by[5:]:
        kind, field = "meta", by[5:]
    else:
        raise ValueError(f"未知分解方式：{by}")
    c = _Corpus(scope)
    ast = query.parse(query_text, c.tagset)
    hits = c.rows(query_text, attr_filter, max_hits)
    counts = Counter()
    if kind in ("word", "lemma", "pos"):
        with c.attr(kind) as att:
            for m, me, _, _ in hits:
                counts[tuple(att(p) for p in range(m, me + 1))] += 1
    elif kind in ("left1", "right1"):
        starts, ends = c.sentences() if len(hits) else ([], [])
        with c.attr("word") as att:
            for m, me, _, _ in hits:
                k = bisect_right(starts, m) - 1
                if kind == "left1":
                    v = att(m - 1) if m > starts[k] else SENT_START
                else:
                    v = att(me + 1) if me < ends[k] else SENT_END
                counts[(v,)] += 1
    else:
        doc_value = c.doc_values(field)
        for _, _, d, _ in hits:
            counts[(doc_value.get(d),)] += 1
    total = len(hits)
    tail = "".join(f" {cond.op}{cond.query.text}" for cond in ast.conditions)

    def label(k):
        if kind != "meta":
            return " ".join(k)
        if k[0] is None:
            return NO_VALUE
        return str(_number(k[0])) if numeric else k[0]

    keys = sorted(
        (k for k in counts if counts[k] >= min_freq),
        key=lambda k: (-counts[k], label(k)),
    )
    rows = []
    for k in keys[:top]:
        h, item = counts[k], label(k)
        values = {
            "item": item,
            "hits": h,
            "pct": h / total * 100,
            "per_million": c.pm(h),
        }
        if kind == "meta":
            extra = (
                {}
                if k[0] is None
                else {"bin_value": _number(k[0]) if numeric else k[0]}
            )
            q = query_text if extra else None
            rows.append(_row(item, values, q, **extra))
        else:
            rows.append(
                _row("\t".join(k), values, _breakdown_query(c, ast, kind, k, tail))
            )
    columns = [
        _col("item", "项", "string"),
        _col("hits", "命中数"),
        _col("pct", "占比 %"),
        _col("per_million", "每百万词"),
    ]
    return Table(columns, rows, len(keys), {**c.totals, "hits": total})
