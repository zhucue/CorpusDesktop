"""Search counting with the real CWB engine (contracts/p7.md §1): a count past COUNT_TIMEOUT runs once in the
background; afterwards pages are slices of the stored result set, equal to a one-shot full search."""

import re
import shutil
import threading
import time

import pytest

from engine import cwb
from tests.api.conftest import drain, upload

pytestmark = pytest.mark.skipif(not shutil.which("cqp"), reason="CWB not installed")

NAMES = ("build", "search", "query_rows", "prefix_rows", "hits")
REAL = {n: getattr(cwb, n) for n in (*NAMES, "_cqp_lines")}
WORDS = ["alpha", "Beta", "gamma", "delta", "Epsilon", "zeta", "eta"]


def text(doc):
    lines = []
    for i in range(30):
        w = WORDS[(i * 3 + doc) % len(WORDS)]
        line = f"Line {i} has language {w} here."
        if i % 4 == 0:
            line += f" More language {WORDS[i % len(WORDS)]} again."
        lines.append(line)
    return "\n".join(lines)


@pytest.fixture
def real_cwb(monkeypatch, fake_engine, owner, project):
    for name in NAMES:
        monkeypatch.setattr(cwb, name, REAL[name])
    from engine import nlp

    def annotate(doc, progress=None):
        fake_engine.annotate(doc)
        for s in doc.sentences:
            for t in s.tokens:
                t.pos = "NOUN"

    monkeypatch.setattr(nlp, "annotate", annotate)
    monkeypatch.setattr(
        nlp, "annotate_many", lambda docs, progress=None: [annotate(d) for d in docs]
    )
    c = owner.post(
        f"/api/projects/{project['id']}/corpora", json={"name": "c", "language": "en"}
    ).json()
    upload(owner, c["id"], {"a.txt": text(0), "b.txt": text(1)})
    drain()
    assert owner.get(f"/api/corpora/{c['id']}").json()["status"] == "ready"
    return c


def wait_complete(client, body, timeout=30):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        r = client.post("/api/search", json=body).json()
        if r["counts"]["complete"]:
            return r
        assert not r["counts"].get("failed"), r["counts"]
        time.sleep(0.05)
    raise AssertionError("count did not finish")


def view(items):
    return [
        (h["hit_id"], h["sentence_index"], h["left"], h["match"], h["right"])
        for h in items
    ]


@pytest.mark.parametrize("sort", ["position", "right", "random"])
def test_background_count_and_paging(real_cwb, owner, monkeypatch, sort):
    from services.api import search as search_api

    calls, hold = [], threading.Event()

    def counting(index_dir, key, commands, timeout, cancel=None):
        calls.append(timeout)
        if timeout == search_api.FULL_TIMEOUT:
            assert hold.wait(30)
        return REAL["_cqp_lines"](index_dir, key, commands, timeout, cancel)

    monkeypatch.setattr(cwb, "_cqp_lines", counting)
    monkeypatch.setattr(search_api, "COUNT_TIMEOUT", 0.0001)
    req = {
        "scope": {"corpus_id": real_cwb["id"]},
        "query": "language",
        "sort": sort,
        "seed": 5,
        "page_size": 7,
    }
    first = owner.post("/api/search", json=req).json()
    assert first["counts"]["complete"] is False and len(first["items"]) == 7
    assert first["sort_applied"] is (sort == "position")
    polled = {**req, "search_id": first["search_id"]}
    n = len(calls)
    for _ in range(3):
        again = owner.post("/api/search", json=polled).json()
        assert again["counts"]["complete"] is False and again["items"] == first["items"]
    assert len(calls) == n  # polls do not run CQP
    hold.set()
    done = wait_complete(owner, polled)
    assert calls.count(search_api.FULL_TIMEOUT) == 1

    expected = sum(len(re.findall(r"\blanguage\b", text(d))) for d in (0, 1))
    assert expected > 35
    assert done["counts"] == {
        "hits": expected,
        "sentences": 60,
        "documents": 2,
        "complete": True,
    }
    n = len(calls)
    pages = [
        owner.post("/api/search", json={**polled, "page": p}).json()
        for p in range(1, 6)
    ]
    assert len(calls) == n  # pages come from the stored result set
    assert all(p["sort_applied"] for p in pages)
    paged = [h for p in pages for h in view(p["items"])]

    monkeypatch.setattr(search_api, "COUNT_TIMEOUT", 60)
    once = owner.post("/api/search", json={**req, "page_size": 200}).json()
    assert once["counts"] == done["counts"]
    assert paged == view(once["items"])[:35] and len(set(paged)) == 35


def test_condition_pages_full_before_count(real_cwb, owner, monkeypatch):
    """Before the count, a same-sentence condition drops anchor hits: the prefix grows until the page is
    full, and pages equal the pages after the count."""
    from services.api import search as search_api

    hold = threading.Event()

    def held(index_dir, key, commands, timeout, cancel=None):
        if timeout == search_api.FULL_TIMEOUT:
            assert hold.wait(30)
        return REAL["_cqp_lines"](index_dir, key, commands, timeout, cancel)

    monkeypatch.setattr(cwb, "_cqp_lines", held)
    monkeypatch.setattr(search_api, "COUNT_TIMEOUT", 0.0001)
    req = {
        "scope": {"corpus_id": real_cwb["id"]},
        "query": "language +More",
        "page_size": 3,
    }
    first = owner.post("/api/search", json=req).json()
    polled = {**req, "search_id": first["search_id"]}
    before = [first] + [
        owner.post("/api/search", json={**polled, "page": p}).json() for p in (2, 3, 4)
    ]
    assert all(not r["counts"]["complete"] and len(r["items"]) == 3 for r in before)
    hold.set()
    wait_complete(owner, polled)
    after = [
        owner.post("/api/search", json={**polled, "page": p}).json()
        for p in (1, 2, 3, 4)
    ]
    assert [view(r["items"]) for r in before] == [view(r["items"]) for r in after]


def test_hit_limit_stops_the_count(real_cwb, owner, monkeypatch):
    from services.api import search as search_api

    monkeypatch.setattr(search_api, "MAX_HITS", 10)
    req = {"scope": {"corpus_id": real_cwb["id"]}, "query": "language", "page_size": 7}
    r = owner.post("/api/search", json=req).json()
    assert r["counts"]["failed"] is True
    assert r["counts"]["message"] == "命中超过 10，请缩小范围或加条件"
    assert len(r["items"]) == 7
    page2 = owner.post(
        "/api/search", json={**req, "page": 2, "search_id": r["search_id"]}
    ).json()
    assert len(page2["items"]) == 3  # the prefix stops at the limit
