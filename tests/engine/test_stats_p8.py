"""P8 statistics (contracts/p8.md §一~§四) against the pure-Python reference (tests/golden/p8-stats.json)."""

import json
from collections import Counter

import pytest
from engine_reference import load_docs
from stats_p8_reference import GOLDEN, TR_HITS, TR_OTHERS, TR_TOKENS, golden

from engine import cwb, query, stats, translations
from engine.model import Context, Document, Sentence, Token

GOLD = json.loads(GOLDEN.read_text(encoding="utf-8"))
TOL = 1e-6
CWB_CASES = [c for c in GOLD["cases"] if c["method"] != "translations"]
TR_CASES = [c for c in GOLD["cases"] if c["method"] == "translations"]


def same(a, b):
    """Equal up to 1e-12 relative on floats (math.log2 differs by an ulp between platforms)."""
    if isinstance(a, dict):
        return (
            isinstance(b, dict)
            and a.keys() == b.keys()
            and all(same(a[k], b[k]) for k in a)
        )
    if isinstance(a, list):
        return isinstance(b, list) and len(a) == len(b) and all(map(same, a, b))
    if isinstance(a, float) or isinstance(b, float):
        return b is not None and abs(a - b) <= 1e-12 * max(1, abs(a))
    return a == b


def test_golden_file_matches_reference():
    assert same(golden(), GOLD)


@pytest.fixture(scope="module")
def ud(tmp_path_factory):
    d = tmp_path_factory.mktemp("stats_p8")
    docs = load_docs()
    for i, doc in enumerate(docs):
        doc.metadata = {"part": "a" if i < 8 else "b", "n": i}
    cwb.build(d, "ud_en", docs, [f"d{i}" for i in range(len(docs))])
    return d


def part(d, value):
    restrict = query.compile_filter({"part": value}, {"part": "string"})
    return stats.Scope(d, "ud_en", restrict)


def compute(ud, case):
    p, m = dict(case["params"]), case["method"]
    scope = stats.Scope(ud, "ud_en")
    if m == "frequency":
        return stats.frequency(scope, top=20, parts=p["parts"], dispersion=True)
    if m == "keywords":
        return stats.keywords(part(ud, "a"), part(ud, "b"), top=20, **p)
    if m == "collocations":
        return stats.collocations(scope, top=20, **p)
    return stats.breakdown(scope, p["query"], p["by"], top=20)


def close(a, b):
    if isinstance(a, float) or isinstance(b, float):
        return a is not None and b is not None and abs(a - b) < TOL
    return a == b


def same_rows(got, want):
    assert [r["key"] for r in got] == [r["key"] for r in want]
    for g, w in zip(got, want):
        assert set(g["values"]) == set(w["values"]), g["key"]
        for k, v in w["values"].items():
            assert close(g["values"][k], v), (g["key"], k, g["values"][k], v)


def search_counts(ud, q, restrict=None):
    r = cwb.search(
        ud,
        "ud_en",
        query.compile(query.parse(q)),
        restrict=restrict,
        sort="position",
        seed=None,
        page=1,
        page_size=1,
        context=Context(),
    )
    return r.counts


@pytest.mark.cwb
@pytest.mark.parametrize("case", CWB_CASES, ids=[c["name"] for c in CWB_CASES])
def test_p8_stats_match_golden(ud, case):
    table = compute(ud, case)
    assert table.row_count == case["row_count"]
    same_rows(table.rows, case["rows"])
    for k, v in case["extra"].items():
        assert table.totals[k] == v


@pytest.mark.parametrize("case", TR_CASES, ids=[c["name"] for c in TR_CASES])
def test_translations_match_golden(case):
    values = {t: set(ws) for t, ws in TR_TOKENS.items()}
    a, n = translations.cooccurrence(TR_HITS, values)
    universe = {**{s: ts for s, ts in TR_HITS.items() if ts}, **TR_OTHERS}
    b, big_n = translations.cooccurrence(universe, values)
    extra = case["extra"]
    assert (n, big_n, dict(sorted(b.items()))) == (extra["n"], extra["N"], extra["b"])
    p = case["params"]
    t = translations.table(
        a, n, b, big_n, query_text="翻译", measure=p["measure"], min_freq=p["min_freq"]
    )
    assert t.row_count == case["row_count"]
    same_rows(t.rows, case["rows"])
    row = next(r for r in t.rows if r["key"] == "translate")
    assert row["search_query"] == "翻译"
    assert row["search_aligned"] == {"op": "+", "query": '"translate"'}
    lemma = translations.table(a, n, b, big_n, query_text="翻译", unit="lemma")
    assert lemma.rows[0]["search_aligned"]["query"].startswith("{lemma=")


@pytest.mark.cwb
def test_dispersion_uniform_and_concentrated(tmp_path):
    """20 equal documents: `even` once in each (DP 0, D 1), `lump` 20 times in one (DP 0.95, DPnorm 1)."""
    docs = []
    for i in range(20):
        words = ["even", "filler", "filler", "filler"] + (
            ["lump"] * 20 if i == 3 else ["pad"] * 20
        )
        text = " ".join(words)
        toks, pos = [], 0
        for w in words:
            toks.append(Token(pos, pos + len(w), w, "NOUN", w))
            pos += len(w) + 1
        docs.append(
            Document(
                f"d{i}",
                "en",
                text,
                {"g": "x" if i < 10 else "y"},
                [Sentence(0, len(text), toks)],
            )
        )
    cwb.build(tmp_path, "disp", docs, [f"d{i}" for i in range(20)])
    scope = stats.Scope(tmp_path, "disp")
    rows = {
        r["key"]: r["values"]
        for r in stats.frequency(scope, dispersion=True, top=10).rows
    }
    assert rows["even"]["dp"] == pytest.approx(0, abs=1e-12)
    assert rows["even"]["juilland_d"] == pytest.approx(1)
    assert rows["even"]["range"] == 20 and rows["even"]["range_pct"] == 100
    assert rows["lump"]["dp"] == pytest.approx(0.95)
    assert rows["lump"]["dp_norm"] == pytest.approx(1)
    assert rows["lump"]["juilland_d"] == pytest.approx(0, abs=1e-12)
    assert rows["lump"]["doc_freq"] == rows["lump"]["range"] == 1
    seg = stats.frequency(scope, dispersion=True, parts="segments", top=10)
    assert seg.totals["parts"] == 10
    by_g = stats.frequency(scope, dispersion=True, parts="field:g", top=10)
    assert by_g.totals["parts"] == 2
    assert {r["key"]: r["values"]["dp"] for r in by_g.rows}["lump"] == pytest.approx(
        0.5
    )
    one = stats.frequency(part_scope(tmp_path), dispersion=True, top=3)
    assert one.totals["parts"] == 1
    assert all(
        r["values"]["dp"] is None and r["values"]["range"] is None for r in one.rows
    )
    with pytest.raises(ValueError):
        stats.frequency(scope, dispersion=True, parts="field:nope")
    plain = stats.frequency(scope, top=3)
    assert "dp" not in plain.rows[0]["values"] and "parts" not in plain.totals


def part_scope(d):
    restrict = query.compile_filter({"g": "x"}, {"g": "string"})
    one_doc = restrict + ' & match.doc_id = "d0"'
    return stats.Scope(d, "disp", one_doc)


@pytest.mark.cwb
def test_breakdown_counts_equal_search(ud):
    """Row hits sum to the search count; left1 / right1 / word rows reopen exactly their hits."""
    scope = stats.Scope(ud, "ud_en")
    for q in ("the", "/v", "of", "I +/v -not", "the $1 /n"):
        t = stats.breakdown(scope, q, "word", top=10000)
        assert t.totals["hits"] == search_counts(ud, q).hits
        assert sum(r["values"]["hits"] for r in t.rows) == t.totals["hits"]
    for q, by in (
        ("of", "left1"),
        ("the", "right1"),
        ("I +/v -not", "left1"),
        # word rows are exact forms: equal to the hits when the query has no POS
        ("th??", "word"),
    ):
        t = stats.breakdown(scope, q, by, top=50)
        rows = [r for r in t.rows if r["search_query"]][:3]
        assert len(rows) == 3
        for r in rows:
            assert search_counts(ud, r["search_query"]).hits == r["values"]["hits"], r
    pos = stats.breakdown(scope, "the /n", "pos")
    for r in pos.rows:
        query.parse(r["search_query"])
    lemma = stats.breakdown(scope, "/v", "lemma", top=5)
    assert lemma.rows[0]["search_query"].startswith("{lemma=")
    multi = stats.breakdown(scope, "the /n", "lemma", top=3)
    assert multi.rows[0]["search_query"].startswith(
        '"the"'
    )  # forms, not {lemma=} slots
    start = stats.breakdown(scope, "What", "left1")
    assert {r["key"]: r["search_query"] for r in start.rows}["（句首）"] is None
    meta = stats.breakdown(scope, "the", "meta:part")
    assert {r["key"]: r["bin_value"] for r in meta.rows} == {"a": "a", "b": "b"}
    restrict = query.compile_filter({"part": "a"}, {"part": "string"})
    a_row = next(r for r in meta.rows if r["key"] == "a")
    assert search_counts(ud, "the", restrict).hits == a_row["values"]["hits"]
    by_n = stats.breakdown(scope, "the", "meta:n", numeric=True)
    assert all(isinstance(r["bin_value"], int) for r in by_n.rows)
    with pytest.raises(ValueError, match="命中超过 5"):
        stats.breakdown(scope, "the", "word", max_hits=5)
    with pytest.raises(ValueError):
        stats.breakdown(scope, "the", "left2")


@pytest.mark.cwb
def test_keywords_items_and_direction(ud):
    a, b = part(ud, "a"), part(ud, "b")
    neg = stats.keywords(a, b, direction="negative", top=10000)
    assert neg.rows and all(
        r["values"]["ref_pm"] > r["values"]["target_pm"] for r in neg.rows
    )
    pos = stats.keywords(a, b, top=10000)
    assert all(r["values"]["target_pm"] > r["values"]["ref_pm"] for r in pos.rows)
    both = stats.keywords(a, b, direction="both", top=10000)
    assert both.row_count == pos.row_count + neg.row_count
    rare = stats.keywords(a, b, items=["Google", "nope"], min_freq=1000)
    assert [r["key"] for r in rare.rows] == ["Google", "nope"]
    assert (
        rare.rows[1]["values"]["target_freq"] == 0
        and rare.rows[1]["values"]["smoothed"]
    )


@pytest.mark.cwb
def test_dispersion_field_leaves_out_documents_without_it(tmp_path):
    """parts=field:g: documents without g count neither in f nor in the part sizes (reference ref_dispersion)."""
    from stats_p8_reference import ref_dispersion

    plan = [  # (g or None, number of `w`, number of `pad`)
        ("x", 3, 5),
        ("x", 0, 7),
        ("y", 1, 2),
        ("y", 2, 9),
        (None, 6, 1),
        (None, 4, 4),
    ]
    docs = []
    for i, (g, w, pad) in enumerate(plan):
        words = ["w"] * w + ["pad"] * pad
        toks, pos = [], 0
        for word in words:
            toks.append(Token(pos, pos + len(word), word, "NOUN", word))
            pos += len(word) + 1
        text = " ".join(words)
        meta = {"g": g} if g else {}
        docs.append(Document(f"d{i}", "en", text, meta, [Sentence(0, len(text), toks)]))
    cwb.build(tmp_path, "gaps", docs, [f"d{i}" for i in range(len(docs))])
    t = stats.frequency(stats.Scope(tmp_path, "gaps"), dispersion=True, parts="field:g")
    assert t.totals["parts"] == 2
    sizes, f_parts = Counter(), {}
    for g, w, pad in plan:
        if g:
            sizes[g] += w + pad
            f_parts.setdefault("w", Counter())[g] += w
            f_parts.setdefault("pad", Counter())[g] += pad
    for row in t.rows:
        want = ref_dispersion(f_parts[row["key"]], sizes)
        for k, v in want.items():
            assert close(row["values"][k], v), (row["key"], k, row["values"][k], v)
    w = next(r["values"] for r in t.rows if r["key"] == "w")
    assert w["freq"] == 16  # the frequency column still counts the whole scope
    assert w["dp"] == pytest.approx(0.5 * (abs(3 / 6 - 15 / 29) + abs(3 / 6 - 14 / 29)))
