import csv
import io
import json
import threading
import time

import pytest
from openpyxl import load_workbook

from tests.api.conftest import drain, upload

TEXT_A = "Language is a system.\nThe language of science."
TEXT_B = "Grammar rules apply.\nA language again."


@pytest.fixture
def corpus(owner, project):
    c = owner.post(
        f"/api/projects/{project['id']}/corpora",
        json={"name": "作文", "language": "en"},
    ).json()
    upload(owner, c["id"], {"a.txt": TEXT_A}, metadata=json.dumps({"year": 2001}))
    upload(owner, c["id"], {"b.txt": TEXT_B}, metadata=json.dumps({"year": 2010}))
    drain()
    return c


def search(client, scope, query="language", **kw):
    return client.post("/api/search", json={"scope": scope, "query": query, **kw})


def test_parse_endpoint(owner):
    ok = owner.post("/api/search/parse", json={"query": "语言 +文化"}).json()
    assert ok["ok"] is True and ok["error"] is None
    assert ok["anchor"] == "语言"
    assert ok["conditions"] == [{"op": "+", "text": "文化"}]
    assert ok["tokens"]
    attr = owner.post("/api/search/parse", json={"query": "学生{dep=nsubj}"}).json()
    assert attr["ok"] and [t["kind"] for t in attr["tokens"]] == ["word", "attr"]
    bad = owner.post("/api/search/parse", json={"query": "{dep=nsubj"}).json()
    assert (
        bad["ok"] is False and bad["error"]["position"] == 0 and bad["error"]["message"]
    )


def test_search_hits_counts_and_paging(owner, corpus, fake_engine, member):
    r = search(member("viewer"), {"corpus_id": corpus["id"]}, page_size=2)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["counts"] == {
        "hits": 3,
        "sentences": 2 + 1,
        "documents": 2,
        "complete": True,
    }
    assert body["parse"]["ok"] and body["page"] == 1 and body["page_size"] == 2
    hit = body["items"][1]
    assert hit["document_title"] == "a" and hit["metadata"] == {"year": 2001}
    assert (
        hit["match"] == "language"
        and hit["sentence_index"] == 1
        and hit["aligned"] == []
    )
    assert hit["hit_id"] == f"{hit['document_id']}:{hit['start_cp']}-{hit['end_cp']}"

    assert body["sort_applied"] is True
    call = fake_engine.calls[-1]
    assert call["restrict"] is None and call["cut"] is None
    ctx = fake_engine.contexts[-1]
    assert ctx.unit == "char" and ctx.size == 40

    page2 = search(
        owner,
        {"corpus_id": corpus["id"]},
        page=2,
        page_size=2,
        search_id=body["search_id"],
    ).json()
    assert page2["search_id"] == body["search_id"] and len(page2["items"]) == 1
    assert len(fake_engine.calls) == 1  # page 2 is a slice of the stored result set

    # a search_id only matches the same query and scope
    r = search(
        owner, {"corpus_id": corpus["id"]}, query="grammar", search_id=body["search_id"]
    )
    assert r.status_code == 409 and r.json()["error"]["code"] == "SEARCH_EXPIRED"


def test_random_sort_pins_seed(owner, corpus, fake_engine):
    first = search(
        owner, {"corpus_id": corpus["id"]}, sort="random", page_size=2
    ).json()
    seed = fake_engine.calls[-1]["seed"]
    assert seed is not None
    second = search(
        owner,
        {"corpus_id": corpus["id"]},
        sort="random",
        page=2,
        page_size=2,
        search_id=first["search_id"],
    ).json()
    full = search(owner, {"corpus_id": corpus["id"]}, sort="random", seed=seed).json()
    ids = [h["hit_id"] for h in first["items"] + second["items"]]
    assert ids == [h["hit_id"] for h in full["items"]] and len(set(ids)) == 3


def test_search_errors(owner, project, corpus, make_user):
    r = search(owner, {"corpus_id": corpus["id"]}, query="{dep=nsubj")
    assert r.status_code == 422 and r.json()["error"]["code"] == "QUERY_INVALID"
    empty = owner.post(
        f"/api/projects/{project['id']}/corpora", json={"name": "空", "language": "en"}
    ).json()
    r = search(owner, {"corpus_id": empty["id"]})
    assert r.status_code == 409 and r.json()["error"]["code"] == "CORPUS_NOT_READY"
    assert (
        search(make_user("x@example.edu"), {"corpus_id": corpus["id"]}).status_code
        == 404
    )
    r = owner.post("/api/search", json={"scope": {}, "query": "x"})
    assert r.status_code == 422


def test_subcorpus_scope_passes_restrict(owner, project, corpus, fake_engine):
    sub = owner.post(
        f"/api/projects/{project['id']}/subcorpora",
        json={
            "name": "2001",
            "corpus_id": corpus["id"],
            "filter": {"year": {"gte": 2000, "lte": 2005}},
        },
    ).json()
    r = search(owner, {"subcorpus_id": sub["id"]})
    assert r.status_code == 200, r.text
    restrict = fake_engine.calls[-1]["restrict"]
    assert restrict and "year" in restrict


def test_parallel_hits_carry_aligned_sentences(owner, project, fake_engine):
    c = owner.post(
        f"/api/projects/{project['id']}/corpora",
        json={"name": "双语", "language": "en"},
    ).json()
    upload(
        owner, c["id"], {"pair.tmx": "I study language.\t我研究语言。\nHello.\t你好。"}
    )
    drain()
    corpus = owner.get(f"/api/corpora/{c['id']}").json()
    assert corpus["parallel"] is True and corpus["status"] == "ready"
    hit = search(owner, {"corpus_id": c["id"]}).json()["items"][0]
    assert hit["aligned"] == [{"language": "zh", "text": "我研究语言。"}]


def test_context(owner, corpus):
    hit = search(owner, {"corpus_id": corpus["id"]}).json()["items"][1]
    r = owner.get(
        "/api/search/context",
        params={
            "document_id": hit["document_id"],
            "sentence_index": hit["sentence_index"],
            "start_cp": hit["start_cp"],
            "end_cp": hit["end_cp"],
        },
    ).json()
    assert r["document"]["title"] == "a"
    assert [s["index"] for s in r["sentences"]] == [0, 1]
    target = r["sentences"][1]
    a, b = target["highlight"]
    assert target["text"][a:b] == "language"
    assert r["sentences"][0]["highlight"] is None


def test_export_csv_and_xlsx(owner, project, corpus, member):
    viewer = member("viewer")
    job = viewer.post(
        "/api/search/export",
        json={
            "scope": {"corpus_id": corpus["id"]},
            "query": "language",
            "format": "csv",
        },
    ).json()
    assert job["kind"] == "export" and job["project_id"] == project["id"]
    assert viewer.get(f"/api/jobs/{job['id']}/download").status_code == 409
    drain()
    done = viewer.get(f"/api/jobs/{job['id']}").json()
    assert done["state"] == "succeeded", done
    assert done["result"]["rows"] == done["result"]["hits"] == 3
    r = viewer.get(f"/api/jobs/{job['id']}/download")
    assert r.status_code == 200 and "attachment" in r.headers["content-disposition"]
    rows = list(csv.reader(io.StringIO(r.content.decode("utf-8-sig"))))
    assert rows[0][:3] == ["命中 ID", "文档", "文档 ID"] and rows[0][-1] == "year"
    assert len(rows) - 1 == 3

    job = owner.post(
        "/api/search/export",
        json={
            "scope": {"corpus_id": corpus["id"]},
            "query": "language",
            "format": "xlsx",
        },
    ).json()
    drain()
    r = owner.get(f"/api/jobs/{job['id']}/download")
    ws = load_workbook(io.BytesIO(r.content)).active
    header = next(ws.iter_rows(min_row=1, max_row=1))
    assert all(c.font.name == "宋体" for c in header)
    assert all(c.fill.fill_type is None for row in ws.iter_rows() for c in row)
    assert ws.max_row == 4


def test_export_builtin_corpus_into_project(owner, project, make_user):
    admin = make_user("admin@example.edu", admin=True)
    builtin = admin.post(
        "/api/corpora", json={"name": "UD 英文", "language": "en"}
    ).json()
    upload(admin, builtin["id"], {"ud.txt": TEXT_A})
    drain()
    body = {"scope": {"corpus_id": builtin["id"]}, "query": "language", "format": "csv"}
    job = owner.post(
        "/api/search/export", json={**body, "project_id": project["id"]}
    ).json()
    assert job["project_id"] == project["id"]
    outsider = make_user("x@example.edu")
    assert (
        outsider.post(
            "/api/search/export", json={**body, "project_id": project["id"]}
        ).status_code
        == 404
    )


def test_saved_queries(owner, project, corpus, member):
    pid = project["id"]
    body = {
        "name": "language",
        "query": "language",
        "scope": {"corpus_id": corpus["id"]},
    }
    assert (
        member("viewer").post(f"/api/projects/{pid}/queries", json=body).status_code
        == 403
    )
    saved = owner.post(f"/api/projects/{pid}/queries", json=body).json()
    assert (
        saved["scope"] == {"corpus_id": corpus["id"]} and saved["query"] == "language"
    )
    assert owner.get(f"/api/projects/{pid}/queries").json()["total"] == 1
    assert owner.delete(f"/api/queries/{saved['id']}").status_code == 204
    assert owner.get(f"/api/projects/{pid}/queries").json()["total"] == 0


def test_include_tokens(owner, corpus):
    plain = search(owner, {"corpus_id": corpus["id"]}).json()
    assert "tokens" not in plain["items"][0]
    items = search(owner, {"corpus_id": corpus["id"]}, include_tokens=True).json()[
        "items"
    ]
    assert items[0]["tokens"] == [
        {"part": "match", "form": "Language", "pos": None},
        {"part": "right", "form": "is", "pos": None},
        {"part": "right", "form": "a", "pos": None},
        {"part": "right", "form": "system.", "pos": None},
    ]
    assert [(t["part"], t["form"]) for t in items[1]["tokens"]] == [
        ("left", "The"),
        ("match", "language"),
        ("right", "of"),
        ("right", "science."),
    ]


def test_parallel_context_and_evidence_stay_in_sentence(owner, project, fake_engine):
    """QA Q20/Q60: parallel corpora search with sentence-only context; a pinned hit keeps its own
    sentence, the aligned translation and the sentence number, with the match in bold."""
    c = owner.post(
        f"/api/projects/{project['id']}/corpora",
        json={"name": "双语", "language": "en"},
    ).json()
    upload(
        owner,
        c["id"],
        {"pair.tmx": "Hello.\t你好。\nI study language.\t我研究语言。\nBye.\t再见。"},
    )
    drain()
    hit = search(owner, {"corpus_id": c["id"]}).json()["items"][0]
    assert fake_engine.contexts[-1].sentence_only is True
    ref = {
        "hit_id": hit["hit_id"],
        "document_id": hit["document_id"],
        "start_cp": hit["start_cp"],
        "end_cp": hit["end_cp"],
        "search_query": "language",
    }
    ev = owner.post(
        f"/api/projects/{project['id']}/evidence",
        json={"kind": "hit", "ref": ref, "text": "x", "source": "y"},
    ).json()
    assert ev["text"] == "I study **language**.\nZH：我研究语言。"
    assert ev["source"] == "pair-en · 句 2 · 双语"
    assert ev["ref"]["sentence"] == "I study language." and ev["ref"]["match"] == [
        8,
        16,
    ]
    assert ev["ref"]["aligned"] == [{"language": "zh", "text": "我研究语言。"}]


def test_parse_with_scope_checks_layers(owner, corpus, monkeypatch):
    """QA Q21/Q22: parse against the corpus (tagset, POS tags) and report a missing layer before searching."""
    from engine import cwb

    scope = {"corpus_id": corpus["id"]}
    r = owner.post("/api/search/parse", json={"query": "language/n", "scope": scope})
    body = r.json()
    assert body["ok"] and body["corpus"]["tagset"] in ("upos", "jieba", "mixed")
    assert body["corpus"]["layers"] == {"dep": False, "span": False}
    monkeypatch.setattr(cwb, "has_values", lambda ix, key, attr: False)
    bad = owner.post(
        "/api/search/parse", json={"query": "language{dep=nsubj}", "scope": scope}
    ).json()
    assert bad["ok"] is False and bad["error"]["position"] == 8
    assert "依存" in bad["error"]["message"]
    span = owner.post(
        "/api/search/parse", json={"query": "[时态]", "scope": scope}
    ).json()
    assert span["ok"] is False and "片段" in span["error"]["message"]
    r = search(owner, scope, "{dep=nsubj}")
    assert r.status_code == 422 and r.json()["error"]["code"] == "INVALID_LAYER"


# ---- counting after COUNT_TIMEOUT (contracts/p7.md §1) ----


def wait_counts(client, body, timeout=10):
    """Poll with the search_id until counts are complete or failed; returns the last response."""
    deadline = time.monotonic() + timeout
    while True:
        r = client.post("/api/search", json=body)
        assert r.status_code == 200, r.text
        counts = r.json()["counts"]
        if counts["complete"] or counts.get("failed") or time.monotonic() > deadline:
            return r.json()
        time.sleep(0.02)


def full_calls(fake):
    return [c for c in fake.calls if c["cut"] is None]


def test_timeout_counts_in_background_once(owner, corpus, fake_engine):
    fake_engine.delay = 50  # > COUNT_TIMEOUT (20 s), < SEARCH_FULL_TIMEOUT (300 s)
    fake_engine.gate = threading.Event()
    req = {"scope": {"corpus_id": corpus["id"]}, "query": "language", "page_size": 2}
    first = owner.post("/api/search", json=req).json()
    assert first["counts"] == {
        "hits": None,
        "sentences": None,
        "documents": None,
        "complete": False,
    }
    assert first["sort_applied"] is True and len(first["items"]) == 2
    polled = {**req, "search_id": first["search_id"]}
    calls = len(fake_engine.calls)
    for _ in range(3):
        again = owner.post("/api/search", json=polled).json()
        assert again["counts"]["complete"] is False
        assert again["items"] == first["items"]
    assert len(fake_engine.calls) == calls  # polling only reads the state
    fake_engine.gate.set()
    done = wait_counts(owner, polled)
    assert done["counts"] == {
        "hits": 3,
        "sentences": 3,
        "documents": 2,
        "complete": True,
    }
    # one foreground attempt (COUNT_TIMEOUT) and exactly one background run
    assert [c["timeout"] for c in full_calls(fake_engine)] == [20, 300]
    page2 = owner.post("/api/search", json={**polled, "page": 2}).json()
    fake_engine.delay = 0
    full = owner.post("/api/search", json={**req, "page_size": 50})
    ids = [h["hit_id"] for h in done["items"] + page2["items"]]
    assert ids == [h["hit_id"] for h in full.json()["items"]]


def test_sort_applies_after_count(owner, corpus, fake_engine):
    fake_engine.delay = 50
    fake_engine.gate = threading.Event()
    req = {
        "scope": {"corpus_id": corpus["id"]},
        "query": "language",
        "sort": "right",
        "page_size": 1,
    }
    first = owner.post("/api/search", json=req).json()
    assert first["sort_applied"] is False and first["counts"]["complete"] is False
    polled = {**req, "search_id": first["search_id"]}
    # before the count: corpus order, the same as sort=position
    unsorted = [
        owner.post("/api/search", json={**polled, "page": p}).json() for p in (1, 2, 3)
    ]
    assert all(r["sort_applied"] is False for r in unsorted)
    fake_engine.gate.set()
    wait_counts(owner, polled)
    fake_engine.gate = None
    fake_engine.delay = 0
    position = owner.post(
        "/api/search", json={**req, "sort": "position", "page_size": 50}
    ).json()
    assert [r["items"][0]["hit_id"] for r in unsorted] == [
        h["hit_id"] for h in position["items"]
    ]
    pages = [
        owner.post("/api/search", json={**polled, "page": p}).json() for p in (1, 2, 3)
    ]
    assert all(r["sort_applied"] is True for r in pages)
    rights = [r["items"][0]["right"] for r in pages]
    assert rights == sorted(rights, key=str.casefold)
    again = [
        owner.post("/api/search", json={**polled, "page": p}).json()["items"]
        for p in (1, 2, 3)
    ]
    assert again == [r["items"] for r in pages]  # stable paging


def test_background_timeout_fails(owner, corpus, fake_engine, monkeypatch):
    from services.api import search as search_api

    monkeypatch.setattr(search_api, "FULL_TIMEOUT", 30)
    fake_engine.delay = 50
    req = {"scope": {"corpus_id": corpus["id"]}, "query": "language"}
    first = owner.post("/api/search", json=req).json()
    failed = wait_counts(owner, {**req, "search_id": first["search_id"]})
    assert failed["counts"] == {
        "hits": None,
        "sentences": None,
        "documents": None,
        "complete": False,
        "failed": True,
        "message": "计数超时（30 秒），请缩小范围或加条件",
    }
    assert len(failed["items"]) == 3


def test_new_count_cancels_previous_of_same_user(owner, corpus, fake_engine):
    fake_engine.delay = 50
    fake_engine.gate = threading.Event()
    scope = {"corpus_id": corpus["id"]}
    a = owner.post("/api/search", json={"scope": scope, "query": "language"}).json()
    b = owner.post(
        "/api/search", json={"scope": scope, "query": "language", "sort": "left"}
    ).json()
    fake_engine.gate.set()
    ra = wait_counts(
        owner, {"scope": scope, "query": "language", "search_id": a["search_id"]}
    )
    rb = wait_counts(
        owner,
        {
            "scope": scope,
            "query": "language",
            "sort": "left",
            "search_id": b["search_id"],
        },
    )
    assert ra["counts"]["failed"] is True and "取消" in ra["counts"]["message"]
    assert rb["counts"]["complete"] is True and rb["counts"]["hits"] == 3


def test_evicted_search_loses_result_set(owner, corpus, monkeypatch):
    from services.api.db import data_dir
    from services.api.search import searches

    monkeypatch.setattr(searches, "LIMIT", 2)
    scope = {"corpus_id": corpus["id"]}
    first = search(owner, scope).json()
    stored = data_dir() / "search-cache" / first["search_id"]
    assert (stored / "rows.bin").exists()
    search(owner, scope)
    search(owner, scope)
    assert not stored.exists()
    r = search(owner, scope, page=2, search_id=first["search_id"])
    assert r.status_code == 409 and r.json()["error"]["code"] == "SEARCH_EXPIRED"


def test_too_many_hits_fail_the_count(owner, corpus, fake_engine, monkeypatch):
    from services.api import search as search_api

    monkeypatch.setattr(search_api, "MAX_HITS", 2)
    req = {"scope": {"corpus_id": corpus["id"]}, "query": "language"}
    first = owner.post("/api/search", json=req).json()  # within COUNT_TIMEOUT
    assert first["counts"]["failed"] is True
    assert first["counts"]["message"] == "命中超过 2，请缩小范围或加条件"
    assert len(first["items"]) == 3  # the page still comes from the corpus-order prefix
    fake_engine.delay = 50  # past COUNT_TIMEOUT: the background count hits the limit
    later = owner.post("/api/search", json={**req, "sort": "left"}).json()
    failed = wait_counts(
        owner, {**req, "sort": "left", "search_id": later["search_id"]}
    )
    assert failed["counts"]["message"] == "命中超过 2，请缩小范围或加条件"
    monkeypatch.setattr(search_api, "MAX_HITS", 2_000_000)
    assert search_api.too_many_message() == "命中超过 200 万，请缩小范围或加条件"


def test_background_error_hides_details(owner, corpus, fake_engine, monkeypatch):
    from engine import cwb

    fake_engine.delay = 50
    real = cwb.query_rows

    def broken(*args, **kw):
        if kw.get("timeout") == 300:
            raise RuntimeError("SELECT secret FROM /data/x")
        return real(*args, **kw)

    monkeypatch.setattr(cwb, "query_rows", broken)
    req = {"scope": {"corpus_id": corpus["id"]}, "query": "language"}
    first = owner.post("/api/search", json=req).json()
    failed = wait_counts(owner, {**req, "search_id": first["search_id"]})
    assert failed["counts"]["message"] == "计数失败，请重试"


def test_result_sets_kept_under_byte_limit(owner, corpus, monkeypatch):
    from services.api import search as search_api
    from services.api.search import searches

    monkeypatch.setattr(
        search_api, "CACHE_MAX_BYTES", 100
    )  # one result set here is ~130 bytes
    scope = {"corpus_id": corpus["id"]}
    ids = [search(owner, scope).json()["search_id"] for _ in range(3)]
    stored = [searches.root() / sid for sid in ids]
    assert [p.exists() for p in stored] == [False, False, True]
    assert searches.bytes == searches.entries[ids[2]]["bytes"] > 100
    r = search(owner, scope, page=2, search_id=ids[0])
    assert r.status_code == 409 and r.json()["error"]["code"] == "SEARCH_EXPIRED"
    assert search(owner, scope, page=1, search_id=ids[2]).status_code == 200


def _cache_entries(cache, n):
    from types import SimpleNamespace
    from uuid import uuid4

    from services.api.search import SearchInput

    corpus = SimpleNamespace(id=uuid4(), index_version="v1")
    req = SearchInput(scope={"corpus_id": str(corpus.id)}, query="x")
    return [cache.open(corpus, None, f"q{i}", req)[1] for i in range(n)]


def test_background_counts_run_two_at_a_time():
    from services.api.search import SearchCache

    cache = SearchCache()
    gate, lock = threading.Event(), threading.Lock()
    active, peak = [0], [0]

    def job(cancel):
        with lock:
            active[0] += 1
            peak[0] = max(peak[0], active[0])
        gate.wait(10)
        with lock:
            active[0] -= 1
        return [(0, 1, "d", 0)]

    entries = _cache_entries(cache, 3)
    for i, e in enumerate(entries):
        cache.start(e, (f"user{i}", "session"), job)
    deadline = time.monotonic() + 5
    while active[0] < 2 and time.monotonic() < deadline:
        time.sleep(0.01)
    time.sleep(0.1)
    assert active[0] == 2  # the third waits for a free worker
    gate.set()
    cache.pool.shutdown(wait=True)
    assert peak[0] == 2 and [e["state"] for e in entries] == ["done"] * 3


def test_one_background_count_per_user_and_sign_in_kind():
    from services.api.search import SearchCache

    cache = SearchCache()
    gate = threading.Event()

    def job(cancel):
        gate.wait(10)
        return [(0, 1, "d", 0)]

    browser, agent, browser2 = _cache_entries(cache, 3)
    cache.start(browser, ("u", "session"), job)
    cache.start(
        agent, ("u", "token"), job
    )  # the assistant does not cancel the page's count
    assert not browser["cancel"].is_set()
    cache.start(browser2, ("u", "session"), job)  # a new search in the browser does
    assert browser["cancel"].is_set() and not agent["cancel"].is_set()
    gate.set()
    cache.pool.shutdown(wait=True)
    assert [e["state"] for e in (browser, agent, browser2)] == [
        "failed",
        "done",
        "done",
    ]
