"""P11 search (contracts/p11.md §一): PostgreSQL-answered queries store their result set like CWB queries,
exports read the result set, 简繁通查 and the page's span marks. Real CWB index (needs cqp)."""

import csv
import io
import shutil
import threading

import pytest

from engine import cwb
from tests.api.conftest import drain, upload
from tests.api.test_search_cwb import NAMES, REAL, text, view, wait_complete

pytestmark = pytest.mark.skipif(not shutil.which("cqp"), reason="CWB not installed")


def _real(monkeypatch, fake_engine, pos="NOUN"):
    for name in NAMES:
        monkeypatch.setattr(cwb, name, REAL[name])
    from engine import nlp

    def annotate(doc, progress=None):
        fake_engine.annotate(doc)
        for s in doc.sentences:
            for t in s.tokens:
                t.pos = pos

    monkeypatch.setattr(nlp, "annotate", annotate)
    monkeypatch.setattr(
        nlp, "annotate_many", lambda docs, progress=None: [annotate(d) for d in docs]
    )


@pytest.fixture
def en(monkeypatch, fake_engine, owner, project):
    _real(monkeypatch, fake_engine)
    c = owner.post(
        f"/api/projects/{project['id']}/corpora", json={"name": "c", "language": "en"}
    ).json()
    upload(owner, c["id"], {"a.txt": text(0), "b.txt": text(1)})
    drain()
    assert owner.get(f"/api/corpora/{c['id']}").json()["status"] == "ready"
    return c


@pytest.fixture
def pg_calls(monkeypatch):
    """Calls of effective.pg_rows (the SQL of a pure attribute query); no document file is read."""
    from services.api import effective

    calls, real = [], effective.pg_rows

    def counting(*a, **kw):
        calls.append(kw.get("limit"))
        return real(*a, **kw)

    monkeypatch.setattr(effective, "pg_rows", counting)

    class NoFiles(type(effective.Path())):
        def read_text(self, *a, **kw):
            raise AssertionError(f"read a whole document: {self}")

    monkeypatch.setattr(effective, "Path", NoFiles)
    return calls


def test_pure_attribute_pages_from_the_result_set(en, owner, pg_calls):
    req = {"scope": {"corpus_id": en["id"]}, "query": "{pos=NOUN}", "page_size": 50}
    first = owner.post("/api/search", json=req).json()
    total = sum(len(text(d).split()) for d in (0, 1))
    assert first["counts"] == {
        "hits": total,
        "sentences": 60,
        "documents": 2,
        "complete": True,
    }
    assert len(pg_calls) == 1
    polled = {**req, "search_id": first["search_id"]}
    pages = [
        owner.post("/api/search", json={**polled, "page": p}).json() for p in (2, 3, 4)
    ]
    assert len(pg_calls) == 1  # paging does not run the SQL again
    once = owner.post("/api/search", json={**req, "page_size": 200}).json()
    paged = [h for p in [first, *pages] for h in view(p["items"])]
    assert paged == view(once["items"])
    hit = first["items"][3]
    assert hit["left"] and hit["right"] and hit["match"] == text(0).split()[3]


def test_pure_attribute_counts_in_the_background(en, owner, pg_calls, monkeypatch):
    """Past COUNT_TIMEOUT (PostgreSQL statement_timeout) the count runs once in the background."""
    from sqlalchemy import text as sql

    from services.api import effective
    from services.api import search as search_api

    hold, real = threading.Event(), effective.pg_rows

    def slow(db, *a, **kw):
        if threading.current_thread().name.startswith("search-count"):
            assert hold.wait(30)
        else:
            db.execute(sql("select pg_sleep(0.5)"))
        return real(db, *a, **kw)

    monkeypatch.setattr(effective, "pg_rows", slow)
    monkeypatch.setattr(search_api, "COUNT_TIMEOUT", 0.1)
    req = {"scope": {"corpus_id": en["id"]}, "query": "{pos=NOUN}", "page_size": 20}
    first = owner.post("/api/search", json=req).json()
    assert first["counts"]["complete"] is False and not first["counts"].get("failed")
    polled = {**req, "search_id": first["search_id"]}
    again = owner.post("/api/search", json=polled).json()
    assert again["counts"]["complete"] is False
    hold.set()
    done = wait_complete(owner, polled)
    assert done["counts"]["hits"] == sum(len(text(d).split()) for d in (0, 1))
    assert len(done["items"]) == 20
    monkeypatch.setattr(effective, "pg_rows", real)
    monkeypatch.setattr(search_api, "COUNT_TIMEOUT", 60)
    once = owner.post("/api/search", json={**req, "page_size": 20}).json()
    assert view(once["items"]) == view(done["items"])


def test_parallel_context_stays_in_the_sentence(
    monkeypatch, fake_engine, owner, project, pg_calls
):
    _real(monkeypatch, fake_engine)
    c = owner.post(
        f"/api/projects/{project['id']}/corpora",
        json={"name": "p", "language": "en", "parallel": True},
    ).json()
    lines = "\n".join(
        f"the red book number {i} is here\t第{i}本红色的书在这里" for i in range(6)
    )
    r = owner.post(
        f"/api/corpora/{c['id']}/documents",
        files=[("files", ("t.tmx", lines.encode(), "text/plain"))],
    )
    assert r.status_code < 300, r.text
    drain()
    body = {"scope": {"corpus_id": c["id"]}, "query": "{pos=NOUN}", "page_size": 200}
    items = owner.post("/api/search", json=body).json()["items"]
    assert items
    for h in items:
        assert "\n" not in h["left"] + h["right"]
        assert ("第" in h["match"]) == ("第" in h["left"] + h["match"] + h["right"])


def test_export_reads_the_result_set(en, owner, monkeypatch):
    from services.api import search as search_api

    calls, real = [], search_api.complete_rows

    def counting(*a, **kw):
        calls.append(1)
        return real(*a, **kw)

    monkeypatch.setattr(search_api, "complete_rows", counting)
    req = {"scope": {"corpus_id": en["id"]}, "query": "language", "page_size": 5}
    hits = owner.post("/api/search", json=req).json()["counts"]["hits"]
    assert len(calls) == 1
    job = owner.post("/api/search/export", json={**req, "format": "csv"}).json()
    drain()
    done = owner.get(f"/api/jobs/{job['id']}").json()
    assert done["state"] == "succeeded", done
    assert done["result"]["rows"] == hits
    assert len(calls) == 1  # the worker read the stored rows
    rows = list(
        csv.reader(
            io.StringIO(
                owner.get(f"/api/jobs/{job['id']}/download").content.decode("utf-8-sig")
            )
        )
    )
    assert rows[0][0].startswith(f"查询式：language；范围：c；命中：{hits}；")
    assert len(rows) - 3 == hits

    other = owner.post(
        "/api/search/export",
        json={**req, "query": "language +More", "format": "csv"},
    ).json()
    drain()
    assert owner.get(f"/api/jobs/{other['id']}").json()["state"] == "succeeded"
    assert len(calls) == 2  # no result set: computed once in the worker


@pytest.fixture
def zh(monkeypatch, fake_engine, owner, project):
    _real(monkeypatch, fake_engine, pos="n")
    c = owner.post(
        f"/api/projects/{project['id']}/corpora", json={"name": "z", "language": "zh"}
    ).json()
    upload(
        owner,
        c["id"],
        {"a.txt": "我们 学习 语言\n他們 研究 語言學\n语言 很 美\n文化 與 語言"},
    )
    drain()
    return c


def test_script_variants(zh, owner):
    """简繁通查: on by default for a Chinese corpus; hits = the simplified and traditional searches together."""

    def count(q, **kw):
        body = {"scope": {"corpus_id": zh["id"]}, "query": q, **kw}
        r = owner.post("/api/search", json=body).json()
        return r

    both = count("语言")
    assert both["script_variants"] is True and both["parse"]["anchor"] == "语言|語言"
    simp = count("语言", script_variants=False)["counts"]["hits"]
    trad = count("語言", script_variants=False)["counts"]["hits"]
    assert (simp, trad) == (2, 2)
    assert both["counts"]["hits"] == simp + trad == 4
    assert {h["match"] for h in both["items"]} == {"语言", "語言"}
    assert count("語言")["counts"]["hits"] == 4


def test_span_marks_one_request_per_page(owner, project, fake_engine):
    c = owner.post(
        f"/api/projects/{project['id']}/corpora", json={"name": "s", "language": "en"}
    ).json()
    upload(owner, c["id"], {"a.txt": "One two three.\nFour five six."})
    drain()
    from tests.api.test_p5 import label_set, make_layer

    labels = label_set(owner, "learner-errors")
    label = labels["labels"][0]["id"]
    lid = make_layer(
        owner,
        project,
        corpus_id=c["id"],
        kind="span",
        name="片段",
        label_set_id=labels["id"],
    )["id"]
    docs = owner.get(f"/api/corpora/{c['id']}/documents").json()["items"]
    doc = docs[0]["id"]
    for a, b in ((0, 3), (19, 23)):
        r = owner.post(
            f"/api/layers/{lid}/spans",
            json={"document_id": doc, "start_cp": a, "end_cp": b, "label": label},
        )
        assert r.status_code < 300, r.text
    body = {
        "layer_id": lid,
        "sentences": [
            {"document_id": doc, "sentence_index": 0},
            {"document_id": doc, "sentence_index": 1},
        ],
    }
    r = owner.post("/api/search/span-marks", json=body)
    assert r.status_code == 200, r.text
    got = {i["sentence_index"]: i["spans"] for i in r.json()["items"]}
    assert [(s["start_cp"], s["end_cp"], s["label"]) for s in got[0]] == [(0, 3, label)]
    assert [(s["start_cp"], s["end_cp"]) for s in got[1]] == [(19, 23)]


def test_frequency_merges_case_unless_asked(monkeypatch, fake_engine, owner, project):
    """英文频次 The / the 合并（默认）；case_sensitive 时分开；合并行回到例句的计数等于频次。"""
    from tests.api.test_stats_p10_api import run_stat

    _real(monkeypatch, fake_engine)
    c = owner.post(
        f"/api/projects/{project['id']}/corpora", json={"name": "e", "language": "en"}
    ).json()
    upload(owner, c["id"], {"a.txt": "The cat sat\nthe dog ran\nA cat saw the dog"})
    drain()
    scope = {"corpus_id": c["id"]}
    merged = run_stat(owner, "frequency", {"scope": scope, "dispersion": False})
    rows = {r["key"]: r for r in merged["rows"]}
    assert rows["the"]["values"]["freq"] == 3 and "The" not in rows
    q = rows["the"]["search_query"]
    hits = owner.post("/api/search", json={"scope": scope, "query": q}).json()
    assert hits["counts"]["hits"] == 3
    exact = run_stat(
        owner,
        "frequency",
        {"scope": scope, "dispersion": False, "case_sensitive": True},
    )
    rows = {r["key"]: r["values"]["freq"] for r in exact["rows"]}
    assert (rows["the"], rows["The"]) == (2, 1)


def test_frequency_rows_reopen_exact_spellings_with_script_variants(zh, owner):
    """简繁通查 does not expand quoted forms: a frequency row's `"词形"` query counts that row's tokens."""
    from tests.api.test_stats_p10_api import run_stat

    scope = {"corpus_id": zh["id"]}
    stat = run_stat(owner, "frequency", {"scope": scope, "dispersion": False})
    rows = {r["key"]: r for r in stat["rows"]}
    assert rows["语言"]["values"]["freq"] == 2 and rows["語言"]["values"]["freq"] == 1
    for key in ("语言", "語言"):
        q = rows[key]["search_query"]
        r = owner.post("/api/search", json={"scope": scope, "query": q}).json()
        assert r["script_variants"] is True
        assert r["counts"]["hits"] == rows[key]["values"]["freq"], q


def test_limited_rows_fill_up_past_a_translation_condition(en):
    """A first page with a translation condition reads on until enough rows are left."""
    from engine import query
    from services.api import effective
    from services.api.db import session
    from services.api.models import Corpus, Document

    with session() as db:
        corpus = db.get(Corpus, en["id"])
        ast = query.parse("{pos=NOUN}")
        compiled = query.compile(ast)
        layers = dict.fromkeys(effective.LAYER_KEYS)
        args = (db, corpus, {}, {}, ast.anchor.items[0][0], query.attrs(compiled)[0])
        every = effective.pg_hit_rows(*args, layers)
        first_doc = every[0][2]
        assert db.get(Document, first_doc)
        # leave out every sentence of the first document: the first rows in corpus order all go
        out = {(d, n) for _, _, d, n in every if d == first_doc}
        rows = effective.pg_hit_rows(*args, layers, keep=("-", out), limit=5)
        assert len(rows) == 5 and all(d != first_doc for _, _, d, _ in rows)
        assert rows == [r for r in every if r[2] != first_doc][:5]


def test_export_recomputes_after_a_rebuilt_index(en, owner, monkeypatch):
    from sqlalchemy import update

    from services.api import search as search_api
    from services.api.db import transaction
    from services.api.models import Corpus

    calls, real = [], search_api.complete_rows

    def counting(*a, **kw):
        calls.append(1)
        return real(*a, **kw)

    monkeypatch.setattr(search_api, "complete_rows", counting)
    req = {"scope": {"corpus_id": en["id"]}, "query": "language", "page_size": 5}
    hits = owner.post("/api/search", json=req).json()["counts"]["hits"]
    job = owner.post("/api/search/export", json={**req, "format": "csv"}).json()
    with transaction() as db:  # the index is rebuilt before the job runs
        db.execute(
            update(Corpus).where(Corpus.id == en["id"]).values(index_version="rebuilt")
        )
    drain()
    done = owner.get(f"/api/jobs/{job['id']}").json()
    assert done["state"] == "succeeded" and done["result"]["rows"] == hits
    assert len(calls) == 2  # computed again in the worker
