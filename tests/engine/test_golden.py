"""20 golden queries on UD English (tests/golden/p1-queries.json), counts from engine_reference.py."""

import json

import pytest
from engine_reference import GOLDEN, counts, load_docs

from engine import cwb, query
from engine.model import Context

GOLD = json.loads(GOLDEN.read_text(encoding="utf-8"))["queries"]


def test_golden_matches_reference():
    docs = load_docs()
    assert len(GOLD) == 20
    for q in GOLD:
        assert counts(q["query"], docs) == {
            k: q[k] for k in ("hits", "sentences", "documents")
        }, q["query"]


@pytest.fixture(scope="module")
def ud_index(tmp_path_factory):
    d = tmp_path_factory.mktemp("idx")
    docs = load_docs()
    info = cwb.build(d, "ud_en", docs, [f"d{i}" for i in range(len(docs))])
    assert (info.documents, info.sentences) == (16, 221)
    assert info.tokens == sum(len(s.tokens) for doc in docs for s in doc.sentences)
    return d


@pytest.mark.cwb
@pytest.mark.parametrize("q", GOLD, ids=[q["query"] for q in GOLD])
def test_golden_cwb(ud_index, q):
    r = cwb.search(
        ud_index,
        "ud_en",
        query.compile(query.parse(q["query"])),
        restrict=None,
        sort="position",
        seed=None,
        page=1,
        page_size=10,
        context=Context(),
    )
    assert r.counts.complete
    assert (r.counts.hits, r.counts.sentences, r.counts.documents) == (
        q["hits"],
        q["sentences"],
        q["documents"],
    )
    assert len(r.items) == min(10, q["hits"])
