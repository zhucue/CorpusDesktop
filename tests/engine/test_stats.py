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
    p = dict(case["params"])
    scope = stats.Scope(ud, "ud_en")
    m = case["method"]
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
        assert set(got["values"]) == set(want["values"]), got["key"]
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
