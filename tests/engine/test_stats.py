"""engine.stats against the pure-Python reference (tests/golden/p2-stats.json) on UD English."""

import json

import pytest
from engine_reference import load_docs
from stats_reference import GOLDEN, golden

from engine import cwb, query, stats
from engine.model import Context

GOLD = json.loads(GOLDEN.read_text(encoding="utf-8"))
TOL = 1e-6


def test_golden_file_matches_reference():
    assert golden() == GOLD


@pytest.fixture(scope="module")
def ud(tmp_path_factory):
    d = tmp_path_factory.mktemp("stats")
    docs = load_docs()
    for i, doc in enumerate(docs):
        doc.metadata = {
            "newdoc": doc.external_id,
            "part": "a" if i < 8 else "b",
            "n": i,
        }
    cwb.build(d, "ud_en", docs, [f"d{i}" for i in range(len(docs))])
    return d


def part(d, value):
    restrict = query.compile_filter({"part": value}, {"part": "string"})
    return stats.Scope(d, "ud_en", restrict)


def compute(ud, case):
    """The golden cases count exact spellings (the reference is case-sensitive); merged case variants, the
    default since P11, are checked against them in test_case_variants_merge."""
    p = dict(case["params"])
    scope = stats.Scope(ud, "ud_en")
    m = case["method"]
    if m != "distribution":
        p.setdefault("case_sensitive", True)
    if m == "keywords":
        return stats.keywords(part(ud, "a"), part(ud, "b"), top=20, **p)
    return getattr(stats, m)(scope, top=20, **p)


def close(a, b):
    if isinstance(a, float) or isinstance(b, float):
        return abs(a - b) < TOL
    return a == b


@pytest.mark.cwb
@pytest.mark.parametrize("case", GOLD["cases"], ids=[c["name"] for c in GOLD["cases"]])
def test_stats_match_golden(ud, case):
    table = compute(ud, case)
    assert table.row_count == case["row_count"]
    assert [r["key"] for r in table.rows] == [r["key"] for r in case["rows"]]
    for got, want in zip(table.rows, case["rows"]):
        assert set(want["values"]) <= set(got["values"]), got["key"]  # P8 adds columns
        for k, v in want["values"].items():
            assert close(got["values"][k], v), (got["key"], k, got["values"][k], v)


@pytest.mark.cwb
def test_search_queries_parse_and_count(ud):
    """Every generated query parses; a word row's query finds exactly its frequency."""
    scope = stats.Scope(ud, "ud_en")
    tables = [compute(ud, c) for c in GOLD["cases"]]
    tables.append(stats.frequency(scope, unit="lemma", pos="v", top=20))
    tables.append(stats.frequency(scope, unit="pos", top=20))
    tables.append(
        stats.ngrams(
            scope, n=3, unit="lemma", pos_pattern=["DET", None, "n"], min_freq=1, top=20
        )
    )
    for t in tables:
        for r in t.rows:
            for q in (r["search_query"], r.get("search_query_reverse")):
                if q:
                    query.parse(q)

    def hits(q):
        r = cwb.search(
            ud,
            "ud_en",
            query.compile(query.parse(q)),
            restrict=None,
            sort="position",
            seed=None,
            page=1,
            page_size=1,
            context=Context(),
        )
        return r.counts.hits

    freq = tables[0]
    for r in freq.rows[:5]:
        assert hits(r["search_query"]) == r["values"]["freq"], r["search_query"]
    pos = tables[-2]
    assert hits(pos.rows[0]["search_query"]) == pos.rows[0]["values"]["freq"]
    bigram = tables[1].rows[0]
    assert hits(bigram["search_query"]) == bigram["values"]["freq"]
    coll = tables[2].rows[0]
    assert coll["search_query"].startswith("the $4 ") and coll[
        "search_query_reverse"
    ].endswith(" $4 the")


@pytest.mark.cwb
def test_scope_restrict_and_totals(ud):
    a = stats.frequency(part(ud, "a"), top=5)
    whole = stats.frequency(stats.Scope(ud, "ud_en"), top=5)
    assert a.totals["documents"] == 8 and whole.totals["documents"] == 16
    assert a.totals["tokens"] < whole.totals["tokens"]
    by_n = stats.distribution(stats.Scope(ud, "ud_en"), None, "n", numeric=True)
    assert [r["bin_value"] for r in by_n.rows] == list(range(16))
    assert by_n.rows[0]["values"]["hits"] is None
    assert sum(r["values"]["tokens"] for r in by_n.rows) == whole.totals["tokens"]


@pytest.mark.cwb
def test_jieba_tagset(tmp_path):
    from engine import nlp
    from engine.model import Document

    text = "语言是文化的载体。我们研究语言和翻译。翻译促进文化交流。"
    doc = Document("zh", "zh", text, {}, [])
    nlp.annotate(doc)
    assert cwb.build(tmp_path, "zh", [doc], ["d1"]).tagset == "jieba"
    scope = stats.Scope(tmp_path, "zh")
    toks = [t for s in doc.sentences for t in s.tokens]
    nouns = [t.form for t in toks if t.pos in query.resolve_pos("n", "jieba")]
    for tag in ("n", "NOUN", "nr"):
        stats.frequency(scope, pos=tag)  # accepted on a jieba corpus
    t = stats.frequency(scope, unit="word", pos="n")
    assert sum(r["values"]["freq"] for r in t.rows) == len(nouns)
    by_pos = {r["key"]: r for r in stats.frequency(scope, unit="pos").rows}
    assert by_pos["uj"]["search_query"] == "/uj"  # exact tag
    assert by_pos["n"]["search_query"] is None  # `/n` would also match nr, ns …
    big = stats.ngrams(scope, n=2, pos_pattern=["n", "uj"], min_freq=1)
    assert [r["key"] for r in big.rows] == ["文化\t的"]
    with pytest.raises(query.QueryError):
        stats.frequency(scope, pos="DET")
    with pytest.raises(query.QueryError):
        stats.frequency(stats.Scope(tmp_path, "zh", tagset="upos"), pos="nr")


@pytest.mark.cwb
def test_distribution_from_positions_matches_query(ud):
    """Span queries pass hit positions (document id, token offset) instead of a CQP query."""
    from bisect import bisect_right

    scope = stats.Scope(ud, "ud_en")
    c = stats._Corpus(scope)
    firsts = sorted((a, d) for a, _, d in c.docs)
    positions = []
    for m, _ in c.hits("the"):
        a, d = firsts[bisect_right([x for x, _ in firsts], m) - 1]
        positions.append((d, m - a))
    assert positions
    for field in ("position", "part"):
        want = stats.distribution(scope, "the", field, 5)
        got = stats.distribution(scope, "[x]", field, 5, positions=positions)
        assert [r["values"] for r in got.rows] == [r["values"] for r in want.rows]
        assert got.totals == want.totals


@pytest.mark.cwb
def test_position_rows_keep_the_hits_of_a_distribution_part(ud):
    """B06: cwb.position_rows keeps the hits a 文档位置 distribution row counts, for CWB rows and for
    PostgreSQL rows in document code points alike."""
    scope = stats.Scope(ud, "ud_en")
    rows = cwb.query_rows(ud, "ud_en", query.compile(query.parse("the")), restrict=None)
    hits = cwb.hits(ud, "ud_en", query.compile(query.parse("the")), rows[:], Context())
    cps = [(h.start_cp, h.end_cp, h.doc_id, h.sentence_index) for h in hits]
    dist = stats.distribution(scope, "the", "position", 7)
    assert len({r["values"]["hits"] for r in dist.rows}) > 1
    for k, r in enumerate(dist.rows):
        assert r["bin_index"] == k
        assert (
            len(cwb.position_rows(ud, "ud_en", rows, k, 7, "cwb"))
            == r["values"]["hits"]
        )
        assert (
            len(cwb.position_rows(ud, "ud_en", cps, k, 7, "pg")) == r["values"]["hits"]
        )


def test_is_punct():
    for v in ("，", "。", "(", "1990", "3.5%", "——", "_"):
        assert stats.is_punct(v), v
    for v in ("语言", "1990年", "二〇一〇", "a", "x1"):
        assert not stats.is_punct(v), v


@pytest.mark.cwb
def test_exclude_punct_and_ngram_contains(ud):
    scope = stats.Scope(ud, "ud_en")
    full = stats.frequency(scope, top=10000)
    clean = stats.frequency(scope, top=10000, exclude_punct=True)
    punct = {
        r["key"]: r["values"]["freq"] for r in full.rows if stats.is_punct(r["key"])
    }
    assert punct  # UD English has punctuation and numbers
    assert not any(stats.is_punct(r["key"]) for r in clean.rows)
    assert clean.row_count == full.row_count - len(punct)
    assert clean.totals["excluded_tokens"] == sum(punct.values())
    assert clean.totals["tokens"] == full.totals["tokens"]  # N still counts every token
    kept = {r["key"]: r["values"] for r in clean.rows}
    for r in full.rows:
        if r["key"] in kept:
            assert kept[r["key"]] == r["values"]  # per million on the same N

    bi = stats.ngrams(scope, n=2, min_freq=1, top=10000)
    with_the = stats.ngrams(scope, n=2, min_freq=1, top=10000, contains="the")
    assert with_the.rows and all(
        "the" in r["key"].lower().split("\t") for r in with_the.rows
    )
    assert with_the.row_count == sum(
        "the" in r["key"].lower().split("\t") for r in bi.rows
    )
    clean_bi = stats.ngrams(scope, n=2, min_freq=1, top=10000, exclude_punct=True)
    assert not any(
        stats.is_punct(v) for r in clean_bi.rows for v in r["key"].split("\t")
    )


def _hits(ud, q, restrict=None):
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
    return r.counts.hits


@pytest.mark.cwb
def test_case_variants_merge(ud):
    """Default case_sensitive=False (contracts/p11.md §一): `The` and `the` are one row whose frequency is the
    sum of the spellings; its query finds exactly that many hits, as the unquoted word does in search."""
    scope = stats.Scope(ud, "ud_en")
    exact = stats.frequency(scope, top=100000, case_sensitive=True).rows
    exact = {r["key"]: r["values"]["freq"] for r in exact}
    assert exact["The"] and exact["the"]
    merged = {r["key"].lower(): r for r in stats.frequency(scope, top=100000).rows}
    lowered = {}
    for k, f in exact.items():
        lowered[k.lower()] = lowered.get(k.lower(), 0) + f
    assert {k: r["values"]["freq"] for k, r in merged.items()} == lowered
    the = merged["the"]
    assert the["key"] == "the" and the["values"]["freq"] == exact["The"] + exact["the"]
    assert set(the["search_query"].split("|")) == {'"the"', '"The"'}
    assert (
        _hits(ud, the["search_query"])
        == _hits(ud, "the")
        == exact["The"] + exact["the"]
    )

    bi = stats.ngrams(scope, n=2, min_freq=1, top=100000)
    bi_exact = stats.ngrams(scope, n=2, min_freq=1, top=100000, case_sensitive=True)
    assert sum(r["values"]["freq"] for r in bi.rows) == sum(
        r["values"]["freq"] for r in bi_exact.rows
    )
    top = bi.rows[0]
    assert _hits(ud, top["search_query"]) == top["values"]["freq"]

    a, b = part(ud, "a"), part(ud, "b")
    kw = stats.keywords(a, b, items=["THE"], min_freq=1)
    kw_exact = stats.keywords(a, b, items=["The", "the"], case_sensitive=True)
    assert kw.rows[0]["key"] == "THE"  # items: as given
    assert kw.rows[0]["values"]["target_freq"] == sum(
        r["values"]["target_freq"] for r in kw_exact.rows
    )

    coll = stats.collocations(scope, "of", window=2, min_freq=1, top=100000)
    coll_exact = stats.collocations(
        scope, "of", window=2, min_freq=1, top=100000, case_sensitive=True
    )
    the_coll = next(r for r in coll.rows if r["key"] == "the")
    assert the_coll["values"]["freq"] == sum(
        r["values"]["freq"] for r in coll_exact.rows if r["key"].lower() == "the"
    )

    by_word = stats.breakdown(scope, "th?", "word", top=1000)
    row = next(r for r in by_word.rows if r["key"] == "the")
    assert row["values"]["hits"] == exact["The"] + exact["the"]
    assert _hits(ud, row["search_query"]) == row["values"]["hits"]
    left = stats.breakdown(scope, "of", "right1", top=50)
    for r in [r for r in left.rows if r["search_query"]][:3]:
        assert _hits(ud, r["search_query"]) == r["values"]["hits"], r
