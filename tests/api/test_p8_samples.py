"""P8 (contracts/p8.md §四 translation condition, §五 sampling): aligned search with the real CWB engine,
export / distribution with the same condition, sample layers, coding summary and label "" exclusion."""

import csv
import io
import json
import math
import shutil

import pytest

from engine import cwb
from tests.api.conftest import drain, upload

REAL = {
    n: getattr(cwb, n) for n in ("build", "search", "query_rows", "prefix_rows", "hits")
}
needs_cwb = pytest.mark.skipif(not shutil.which("cqp"), reason="CWB not installed")

PAIRS = [
    ("I translate books.", "我翻译书。"),
    ("I read books.", "我看书。"),
    ("Translate this book.", "翻译这本书。"),
    ("The book is old.", "书很旧。"),
    ("No book here.", "这里没有书。"),
    ("Good translation.", "好译文。"),
]


@pytest.fixture
def parallel(monkeypatch, fake_engine, owner, project):
    for name, fn in REAL.items():
        monkeypatch.setattr(cwb, name, fn)
    c = owner.post(
        f"/api/projects/{project['id']}/corpora",
        json={"name": "双语", "language": "en"},
    ).json()
    upload(owner, c["id"], {"pair.tmx": "\n".join(f"{e}\t{z}" for e, z in PAIRS)})
    drain()
    c = owner.get(f"/api/corpora/{c['id']}").json()
    assert c["status"] == "ready" and c["parallel"] is True
    return c


def count(client, scope, q, aligned=None):
    body = {"scope": scope, "query": q, "page_size": 200}
    if aligned:
        body["aligned"] = aligned
    r = client.post("/api/search", json=body)
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["counts"]["complete"]
    return data


@needs_cwb
def test_aligned_condition_splits_hits(owner, parallel):
    scope = {"corpus_id": parallel["id"]}
    plain = count(owner, scope, "书")
    with_ = count(owner, scope, "书", {"op": "+", "query": "translate"})
    without = count(owner, scope, "书", {"op": "-", "query": "translate"})
    assert plain["counts"]["hits"] == 5
    assert with_["counts"]["hits"] == 2  # 我翻译书。 / 翻译这本书。
    assert (
        with_["counts"]["hits"] + without["counts"]["hits"] == plain["counts"]["hits"]
    )
    assert {h["aligned"][0]["text"] for h in with_["items"]} == {
        "I translate books.",
        "Translate this book.",
    }
    # cache key includes the condition: paging the + search keeps its own result set
    again = owner.post(
        "/api/search",
        json={
            "scope": scope,
            "query": "书",
            "aligned": {"op": "+", "query": "translate"},
            "search_id": with_["search_id"],
        },
    )
    assert again.status_code == 200 and again.json()["counts"]["hits"] == 2
    expired = owner.post(
        "/api/search",
        json={"scope": scope, "query": "书", "search_id": with_["search_id"]},
    )
    assert expired.status_code == 409
    # either direction: an English query with a Chinese condition
    assert (
        count(owner, scope, "book", {"op": "+", "query": "旧"})["counts"]["hits"] == 1
    )


@needs_cwb
def test_aligned_errors(owner, project, parallel):
    scope = {"corpus_id": parallel["id"]}
    r = owner.post(
        "/api/search",
        json={"scope": scope, "query": "书", "aligned": {"op": "+", "query": '"open'}},
    )
    assert r.status_code == 422 and r.json()["error"]["code"] == "QUERY_INVALID"
    assert r.json()["error"]["message"].startswith("译文条件")


def test_aligned_needs_parallel_corpus(owner, project):
    c = owner.post(
        f"/api/projects/{project['id']}/corpora", json={"name": "c", "language": "en"}
    ).json()
    upload(owner, c["id"], {"a.txt": "I study language."})
    drain()
    r = owner.post(
        "/api/search",
        json={
            "scope": {"corpus_id": c["id"]},
            "query": "language",
            "aligned": {"op": "+", "query": "x"},
        },
    )
    assert r.status_code == 422 and r.json()["error"]["code"] == "NOT_PARALLEL"


@needs_cwb
def test_aligned_export_and_distribution(owner, project, parallel):
    scope = {"corpus_id": parallel["id"]}
    aligned = {"op": "-", "query": "translate"}
    r = owner.post(
        "/api/search/export",
        json={"scope": scope, "query": "书", "aligned": aligned, "format": "csv"},
    )
    assert r.status_code == 200, r.text
    drain()
    job = owner.get(f"/api/jobs/{r.json()['id']}").json()
    assert job["state"] == "succeeded", job
    assert job["result"]["rows"] == job["result"]["hits"] == 3
    d = owner.get(f"/api/jobs/{job['id']}/download")
    rows = list(csv.reader(io.StringIO(d.content.decode("utf-8-sig"))))
    assert sum(1 for row in rows if row and "书" in row[7:8][0]) == 3

    # distribution with the same condition
    r = owner.post(
        "/api/stats/distribution",
        json={
            "scope": scope,
            "query": "书",
            "field": "position",
            "bins": 2,
            "aligned": aligned,
        },
    )
    assert r.status_code == 200, r.text
    drain()
    job = owner.get(f"/api/jobs/{r.json()['id']}").json()
    assert job["state"] == "succeeded", job
    stat = owner.get(f"/api/stats/{job['result']['stat_id']}").json()
    assert stat["totals"]["hits"] == 3
    assert sum(row["values"]["hits"] for row in stat["rows"]) == 3


# ---- sampling (fake engine: hits are the occurrences of "language") ----


@pytest.fixture
def corpus(owner, project):
    c = owner.post(
        f"/api/projects/{project['id']}/corpora", json={"name": "c", "language": "en"}
    ).json()
    lines = [f"Line {i} on language." for i in range(30)]
    upload(
        owner, c["id"], {"a.txt": "\n".join(lines[:15]), "b.txt": "\n".join(lines[15:])}
    )
    drain()
    return c


@pytest.fixture
def span_set(owner, project):
    r = owner.post(
        f"/api/projects/{project['id']}/label-sets",
        json={
            "name": "用法",
            "kind": "span",
            "labels": [{"id": "lit", "name": "字面"}, {"id": "fig", "name": "比喻"}],
        },
    )
    assert r.status_code == 200, r.text
    return r.json()


def sample(client, project, corpus, span_set, **kw):
    body = {
        "scope": {"corpus_id": corpus["id"]},
        "query": "language",
        "n": 25,
        "layer": {"name": "抽样", "label_set_id": span_set["id"]},
        **kw,
    }
    return client.post(f"/api/projects/{project['id']}/samples", json=body)


def items(client, layer_id):
    r = client.get(f"/api/layers/{layer_id}/sample-items")
    assert r.status_code == 200, r.text
    return r.json()["items"]


def test_same_seed_same_sample(owner, project, corpus, span_set):
    a = sample(owner, project, corpus, span_set, seed=7).json()
    b = sample(owner, project, corpus, span_set, seed=7).json()
    c = sample(owner, project, corpus, span_set, seed=8).json()
    assert a["total"] == 30 and a["sampled"] == 25 and a["seed"] == 7
    key = lambda x: [
        (i["span"]["document_id"], i["span"]["start_cp"], i["span"]["end_cp"])
        for i in items(owner, x["layer_id"])
    ]
    assert key(a) == key(b) != key(c)
    first = items(owner, a["layer_id"])[0]
    assert first["span"]["label"] == "" and first["span"]["status"] == "suggested"
    assert first["span"]["text"] == "language"
    assert "language" in first["sentence"]["text"]
    layer = owner.get(f"/api/layers/{a['layer_id']}").json()
    assert layer["meta"]["sample"]["total_hits"] == 30
    assert layer["meta"]["sample"]["seed"] == 7
    # n beyond the hits takes all; no seed: one is drawn and recorded
    d = sample(owner, project, corpus, span_set, n=500).json()
    assert d["sampled"] == 30 and isinstance(d["seed"], int)


def wilson(k, n, z=1.959963984540054):
    p = k / n
    c = (p + z * z / (2 * n)) / (1 + z * z / n)
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / (1 + z * z / n)
    return c - h, c + h


def test_coding_summary_and_label_exclusion(owner, project, corpus, span_set):
    s = sample(owner, project, corpus, span_set, seed=1).json()
    lid = s["layer_id"]
    its = items(owner, lid)
    # confirming an uncoded hit needs a label
    r = owner.patch(
        f"/api/layers/{lid}/spans/{its[0]['span']['id']}", json={"action": "confirm"}
    )
    assert r.status_code == 422 and r.json()["error"]["code"] == "LABEL_REQUIRED"
    # so does changing only its range or attributes (it would become an effective span without label)
    first = its[0]["span"]
    for body in (
        {"action": "modify", "end_cp": first["end_cp"] - 1},
        {"action": "modify", "attrs": {"k": "v"}},
    ):
        r = owner.patch(f"/api/layers/{lid}/spans/{first['id']}", json=body)
        assert r.status_code == 422 and r.json()["error"]["code"] == "LABEL_REQUIRED"
    assert items(owner, lid)[0]["span"]["status"] == "suggested"
    # pre-annotation would delete the uncoded hits
    r = owner.post(f"/api/layers/{lid}/preannotate", json={})
    assert r.status_code == 422 and r.json()["error"]["code"] == "SAMPLE_LAYER"
    # code 20: 14 lit, 4 fig, 2 rejected; 5 left uncoded
    for i, it in enumerate(its[:20]):
        sid = it["span"]["id"]
        if i < 2:
            body = {"action": "reject"}
        else:
            body = {"action": "modify", "label": "lit" if i < 16 else "fig"}
        r = owner.patch(f"/api/layers/{lid}/spans/{sid}", json=body)
        assert r.status_code == 200, r.text
    summ = owner.get(f"/api/layers/{lid}/sample-summary").json()
    assert (summ["total_hits"], summ["sampled"], summ["coded"], summ["rejected"]) == (
        30,
        25,
        18,
        2,
    )
    by = {x["label"]: x for x in summ["labels"]}
    assert by["lit"]["count"] == 14 and by["fig"]["count"] == 4
    assert by["lit"]["pct"] == pytest.approx(14 / 18)
    lo, hi = wilson(14, 18)
    assert by["lit"]["ci_low"] == pytest.approx(lo) and by["lit"][
        "ci_high"
    ] == pytest.approx(hi)
    assert by["fig"]["estimate"] == round(4 / 18 * 30)
    assert by["lit"]["name"] == "字面"

    # whole-sentence confirm leaves uncoded hits open
    left = its[20]["span"]
    r = owner.post(
        f"/api/layers/{lid}/sentences/{left['document_id']}/{left['sentence_index']}/confirm"
    )
    assert r.status_code == 200, r.text
    assert items(owner, lid)[20]["span"]["status"] == "suggested"

    # layer stats and exports leave label "" out
    stats = owner.get(f"/api/layers/{lid}/stats").json()
    assert {x["label"] for x in stats["labels"]} == {"lit", "fig"}
    r = owner.post(f"/api/layers/{lid}/export", json={"format": "json"})
    assert r.status_code == 200, r.text
    drain()
    job = owner.get(f"/api/jobs/{r.json()['id']}").json()
    assert job["state"] == "succeeded", job
    data = json.loads(owner.get(f"/api/jobs/{job['id']}/download").content)
    text = json.dumps(data, ensure_ascii=False)
    assert '"label": ""' not in text


def test_agreement_skips_uncoded_spans(owner, project, corpus, span_set):
    from services.api import agreement
    from services.api.db import session
    from services.api.models import AnnotationLayer

    lid = sample(owner, project, corpus, span_set, seed=3, n=5).json()["layer_id"]
    its = items(owner, lid)
    owner.patch(
        f"/api/layers/{lid}/spans/{its[0]['span']['id']}",
        json={"action": "modify", "label": "lit"},
    )
    with session() as db:
        layer = db.get(AnnotationLayer, __import__("uuid").UUID(lid))
        rows = agreement._span_rows(db, layer, [layer.created_by])
    assert [r["label"] for r in rows] == ["lit"]


def test_sample_permissions_and_errors(
    owner, project, corpus, span_set, member, fake_engine
):
    viewer = member("viewer")
    assert sample(viewer, project, corpus, span_set).status_code in (403, 404)
    fake_engine.needle = "nothinghere"
    r = sample(owner, project, corpus, span_set, query="nothinghere")
    assert r.status_code == 422 and r.json()["error"]["code"] == "NO_HITS"
    fake_engine.needle = "language"
    pos_set = next(
        s for s in owner.get("/api/label-sets").json()["items"] if s["kind"] == "pos"
    )
    r = sample(owner, project, corpus, {"id": pos_set["id"]})
    assert r.status_code == 422
    lid = sample(owner, project, corpus, span_set, n=3).json()["layer_id"]
    assert viewer.get(f"/api/layers/{lid}/sample-summary").status_code == 200
    # summary of an ordinary span layer
    plain = owner.post(
        f"/api/projects/{project['id']}/layers",
        json={
            "corpus_id": corpus["id"],
            "kind": "span",
            "name": "普通",
            "label_set_id": span_set["id"],
            "preannotate": False,
        },
    ).json()
    r = owner.get(f"/api/layers/{plain['id']}/sample-summary")
    assert r.status_code == 422 and r.json()["error"]["code"] == "NOT_SAMPLE"


@needs_cwb
def test_aligned_background_count(owner, parallel, monkeypatch):
    """First request past COUNT_TIMEOUT: the condition sentences and the rows are computed in the
    background count; the result equals the direct count."""
    import time

    from services.api import search as search_api

    scope = {"corpus_id": parallel["id"]}
    aligned = {"op": "+", "query": "translate"}
    monkeypatch.setattr(search_api, "COUNT_TIMEOUT", 0)
    body = {"scope": scope, "query": "书", "aligned": aligned}
    first = owner.post("/api/search", json=body).json()
    body["search_id"] = first["search_id"]
    deadline = time.monotonic() + 30
    while True:
        r = owner.post("/api/search", json=body).json()
        if r["counts"]["complete"] or time.monotonic() > deadline:
            break
        assert not r["counts"].get("failed"), r["counts"]
        time.sleep(0.05)
    assert r["counts"]["hits"] == 2 and len(r["items"]) == 2


def test_agent_token_can_create_sample(owner, project, corpus, span_set):
    """contracts/p8.md §五: same rule as creating layers; the assistant's write gate confirms it."""
    from fastapi.testclient import TestClient

    from services.api.main import app

    token = owner.post("/api/auth/agent-token", json={"project_id": project["id"]})
    agent = TestClient(
        app, headers={"Authorization": f"Bearer {token.json()['token']}"}
    )
    r = sample(agent, project, corpus, span_set, n=2, seed=5)
    assert r.status_code == 200, r.text
    assert r.json()["sampled"] == 2


@needs_cwb
def test_aligned_condition_runs_on_the_other_language(owner, parallel, monkeypatch):
    """The condition query runs only on the languages outside the scope, with the hit limit."""
    from services.api import search as search_api
    from services.api.db import session
    from services.api.models import Corpus

    with session() as db:
        corpus = db.get(Corpus, __import__("uuid").UUID(parallel["id"]))
        user = None
        plan = search_api.plan_aligned(
            db, corpus, user, search_api.AlignedInput(op="+", query="书"), {}
        )
        zh = search_api.aligned_keep(db, corpus, {**plan, "languages": ["zh"]}, 20)[1]
        en = search_api.aligned_keep(db, corpus, {**plan, "languages": ["en"]}, 20)[1]
        assert len(zh) == 5 and en == set()  # 书 is only in the Chinese side
        monkeypatch.setattr(search_api, "MAX_HITS", 2)
        with pytest.raises(search_api.AlignedTooManyHits):
            search_api.aligned_keep(db, corpus, plan, 20)
    r = owner.post(
        "/api/search",
        json={
            "scope": {"corpus_id": parallel["id"]},
            "query": "book",
            "aligned": {"op": "+", "query": "书"},
        },
    ).json()
    assert (
        r["counts"]["failed"] and r["counts"]["message"] == "译文条件命中过多，请加条件"
    )
