"""Semantic sentence search (contracts/p10.md §六): index build, cancel, limit, search with scope filters, stale
after document changes, permissions. The embedding model is faked (character bag vectors)."""

import json
import math
import zlib

import pytest
from sqlalchemy import func, select, update

from tests.api.conftest import drain, upload

TEXT_A = "我喜欢读书。\n今天天气很好。\n他在图书馆看书。"
TEXT_B = "我爱看书和读报。\n股票市场下跌了。"


def fake_vector(text):
    v = [0.0] * 384
    for ch in text:
        if not ch.isspace() and ch not in "。，":
            v[zlib.crc32(ch.encode()) % 384] += 1.0
    n = math.sqrt(sum(x * x for x in v)) or 1.0
    return [x / n for x in v]


@pytest.fixture(autouse=True)
def fake_embed(monkeypatch):
    from engine.kb import embed

    state = {"calls": 0, "hook": None}

    def fake(texts, download=True):
        state["calls"] += 1
        if state["hook"]:
            state["hook"]()
        return [fake_vector(t) for t in texts]

    monkeypatch.setattr(embed, "embed", fake)
    monkeypatch.setattr(embed, "load", lambda download=True: None)
    monkeypatch.setattr(embed, "model_name", lambda: "fake-model")
    return state


@pytest.fixture
def corpus(owner, project):
    c = owner.post(
        f"/api/projects/{project['id']}/corpora",
        json={"name": "作文", "language": "zh"},
    ).json()
    upload(owner, c["id"], {"a.txt": TEXT_A}, metadata=json.dumps({"year": 2001}))
    upload(owner, c["id"], {"b.txt": TEXT_B}, metadata=json.dumps({"year": 2010}))
    drain()
    return c


def build(client, corpus_id):
    return client.post(f"/api/corpora/{corpus_id}/semantic-index")


def status(client, corpus_id):
    r = client.get(f"/api/corpora/{corpus_id}/semantic-index")
    assert r.status_code == 200, r.text
    return r.json()


def semantic(client, scope, text="我喜欢读书", **kw):
    return client.post(
        "/api/search/semantic", json={"scope": scope, "text": text, **kw}
    )


def test_build_and_search(owner, project, corpus, member):
    before = status(owner, corpus["id"])
    assert before["status"] == "none" and before["sentences"] == 5
    assert before["can_build"] is True and before["estimate_seconds"] >= 0
    assert (
        semantic(owner, {"corpus_id": corpus["id"]}).json()["error"]["code"]
        == "SEMANTIC_NOT_READY"
    )

    r = build(owner, corpus["id"])
    assert r.status_code == 200 and r.json()["kind"] == "embed_corpus", r.text
    assert status(owner, corpus["id"])["status"] == "building"
    assert build(owner, corpus["id"]).json()["error"]["code"] == "JOB_IN_PROGRESS"
    drain()
    after = status(owner, corpus["id"])
    assert after["status"] == "ready" and after["indexed"] == 5
    assert after["model"] == "fake-model" and after["job"]["state"] == "succeeded"

    viewer = member("viewer")
    body = semantic(viewer, {"corpus_id": corpus["id"]}, top=3).json()
    items = body["items"]
    assert items[0]["match"] == "我喜欢读书。"
    assert (
        len(items) == 3 and items[0]["score"] > items[1]["score"] >= items[2]["score"]
    )
    assert "股票市场下跌了。" not in [i["match"] for i in items[:2]]
    hit = items[0]
    assert hit["left"] == "" and hit["right"] == "" and hit["document_title"] == "a"
    assert hit["hit_id"] == f"{hit['document_id']}:{hit['start_cp']}-{hit['end_cp']}"
    assert hit["metadata"] == {"year": 2001} and hit["sentence_index"] == 0

    # the whole sentence is the hit: context and evidence take it as any search hit
    ctx = viewer.get(
        "/api/search/context",
        params={
            "document_id": hit["document_id"],
            "sentence_index": hit["sentence_index"],
            "start_cp": hit["start_cp"],
            "end_cp": hit["end_cp"],
        },
    ).json()
    assert ctx["sentences"][0]["highlight"] == [0, len("我喜欢读书。")]
    pin = owner.post(
        f"/api/projects/{project['id']}/evidence",
        json={
            "kind": "hit",
            "text": hit["match"],
            "source": hit["document_title"],
            "ref": {
                "document_id": hit["document_id"],
                "start_cp": hit["start_cp"],
                "end_cp": hit["end_cp"],
                "sentence_index": hit["sentence_index"],
            },
        },
    )
    assert pin.status_code in (200, 201), pin.text
    assert pin.json()["text"] == "**我喜欢读书。**"


def test_scope_filter_in_sql(owner, project, corpus):
    build(owner, corpus["id"])
    drain()
    scoped = semantic(
        owner, {"corpus_id": corpus["id"], "filter": {"year": [2010]}}, top=10
    ).json()["items"]
    assert {i["document_title"] for i in scoped} == {"b"} and len(scoped) == 2
    assert scoped[0]["match"] == "我爱看书和读报。"
    sub = owner.post(
        f"/api/projects/{project['id']}/subcorpora",
        json={"name": "2001", "corpus_id": corpus["id"], "filter": {"year": [2001]}},
    ).json()
    items = semantic(owner, {"subcorpus_id": sub["id"]}, top=10).json()["items"]
    assert {i["document_title"] for i in items} == {"a"} and len(items) == 3


def test_text_limits(owner, corpus):
    build(owner, corpus["id"])
    drain()
    scope = {"corpus_id": corpus["id"]}
    assert semantic(owner, scope, text="字" * 501).status_code == 422
    assert semantic(owner, scope, text="   ").status_code == 422
    assert semantic(owner, scope, text="字" * 500).status_code == 200


def test_too_large(owner, corpus, monkeypatch):
    monkeypatch.setenv("SEMANTIC_MAX_SENTENCES", "4")
    r = build(owner, corpus["id"])
    assert r.status_code == 422 and r.json()["error"]["code"] == "TOO_LARGE"
    assert status(owner, corpus["id"])["max_sentences"] == 4


def test_cancel_keeps_previous_state(owner, corpus, fake_embed, monkeypatch):
    from services.api.db import transaction
    from services.api.models import Job, SentenceEmbedding
    from services.worker import embed_tasks

    monkeypatch.setattr(embed_tasks, "BLOCK", 2)
    job = build(owner, corpus["id"]).json()

    def cancel():
        with transaction() as db:
            db.execute(update(Job).where(Job.id == job["id"]).values(state="cancelled"))

    fake_embed["hook"] = cancel
    drain()
    assert owner.get(f"/api/jobs/{job['id']}").json()["state"] == "cancelled"
    assert fake_embed["calls"] == 1  # stopped before the second block
    assert status(owner, corpus["id"])["status"] == "none"

    fake_embed["hook"] = None
    build(owner, corpus["id"])
    drain()
    assert status(owner, corpus["id"])["status"] == "ready"
    with transaction() as db:
        n = db.scalar(select(func.count()).select_from(SentenceEmbedding))
    assert n == 5


def test_failure_stored(owner, corpus, fake_embed):
    from engine.kb import embed

    def boom():
        raise embed.EmbedUnavailable("向量模型不可用：测试")

    fake_embed["hook"] = boom
    job = build(owner, corpus["id"]).json()
    drain()
    assert (
        owner.get(f"/api/jobs/{job['id']}").json()["error"]["code"]
        == "EMBED_UNAVAILABLE"
    )
    s = status(owner, corpus["id"])
    assert s["status"] == "failed" and "向量模型不可用" in s["error"]


def test_stale_after_document_changes(owner, corpus):
    build(owner, corpus["id"])
    drain()
    docs = owner.get(f"/api/corpora/{corpus['id']}/documents").json()["items"]
    b = next(d for d in docs if d["title"] == "b")
    # metadata edits re-index but keep the semantic index ready
    owner.patch(
        f"/api/corpora/{corpus['id']}/documents/{b['id']}",
        json={"metadata": {"year": 2011}},
    )
    drain()
    assert status(owner, corpus["id"])["status"] == "ready"

    assert (
        owner.delete(f"/api/corpora/{corpus['id']}/documents/{b['id']}").status_code
        == 204
    )
    drain()
    s = status(owner, corpus["id"])
    assert s["status"] == "stale" and s["sentences"] == 3
    # a stale index still answers; deleted sentences are gone with their vectors
    items = semantic(owner, {"corpus_id": corpus["id"]}, top=10).json()["items"]
    assert {i["document_title"] for i in items} == {"a"}

    upload(owner, corpus["id"], {"c.txt": "新的句子。"})
    drain()
    build(owner, corpus["id"])
    drain()
    assert status(owner, corpus["id"])["status"] == "ready"
    assert status(owner, corpus["id"])["indexed"] == 4


def test_permissions(owner, corpus, member, make_user):
    for role in ("viewer", "annotator"):
        client = member(role)
        assert status(client, corpus["id"])["can_build"] is False
        assert build(client, corpus["id"]).status_code == 403
    editor = member("editor")
    assert build(editor, corpus["id"]).status_code == 200
    outsider = make_user("outsider@example.edu")
    assert build(outsider, corpus["id"]).status_code == 404
    assert semantic(outsider, {"corpus_id": corpus["id"]}).status_code == 404


def test_builtin_admin_only(owner, make_user):
    admin = make_user("admin@example.edu", admin=True)
    builtin = admin.post(
        "/api/corpora", json={"name": "Tatoeba", "language": "zh"}
    ).json()
    upload(admin, builtin["id"], {"t.txt": TEXT_A})
    drain()
    assert status(owner, builtin["id"])["can_build"] is False
    assert build(owner, builtin["id"]).status_code == 403
    assert status(admin, builtin["id"])["can_build"] is True
    assert build(admin, builtin["id"]).status_code == 200
    drain()
    items = semantic(owner, {"corpus_id": builtin["id"]}, top=1).json()["items"]
    assert items[0]["match"] == "我喜欢读书。"


def test_one_language_of_a_parallel_corpus(owner, project):
    c = owner.post(
        f"/api/projects/{project['id']}/corpora",
        json={"name": "双语", "language": "zh"},
    ).json()
    tmx = "I like reading.\t我喜欢读书。\nThe weather is fine.\t天气很好。\nStocks fell.\t股票下跌了。"
    upload(owner, c["id"], {"pair.tmx": tmx})
    drain()
    s = status(owner, c["id"])
    assert s["languages"] == {"en": 3, "zh": 3} and s["sentences"] == 6
    r = owner.post(f"/api/corpora/{c['id']}/semantic-index", json={"language": "fr"})
    assert r.status_code == 422
    owner.post(f"/api/corpora/{c['id']}/semantic-index", json={"language": "zh"})
    drain()
    s = status(owner, c["id"])
    assert s["status"] == "ready" and s["indexed"] == 3 and s["language"] == "zh"
    items = semantic(owner, {"corpus_id": c["id"]}, top=10).json()["items"]
    assert len(items) == 3 and items[0]["match"] == "我喜欢读书。"
    assert items[0]["aligned"] == [{"language": "en", "text": "I like reading."}]
    # an index build that changes no zh sentence keeps it ready
    owner.post(f"/api/corpora/{c['id']}/reindex")
    drain()
    assert status(owner, c["id"])["status"] == "ready"


def test_hnsw_path_with_filter(owner, corpus, monkeypatch):
    from services.api import semantic as sem

    build(owner, corpus["id"])
    drain()
    monkeypatch.setattr(sem, "EXACT_MAX", 0)  # large scopes go through the HNSW index
    items = semantic(
        owner, {"corpus_id": corpus["id"], "filter": {"year": [2010]}}, top=10
    ).json()["items"]
    assert {i["document_title"] for i in items} == {"b"} and len(items) == 2


def test_failed_rebuild_keeps_the_index(owner, corpus, fake_embed):
    from engine.kb import embed

    build(owner, corpus["id"])
    drain()

    def boom():
        raise embed.EmbedUnavailable("向量模型不可用：测试")

    fake_embed["hook"] = boom
    build(owner, corpus["id"])
    drain()
    s = status(owner, corpus["id"])
    assert s["status"] == "ready" and s["searchable"] is True and s["indexed"] == 5
    assert s["error"].startswith("上次重建失败：") and "向量模型不可用" in s["error"]
    fake_embed["hook"] = None
    r = semantic(owner, {"corpus_id": corpus["id"]}, top=5)
    assert r.status_code == 200 and len(r.json()["items"]) == 5
    build(owner, corpus["id"])
    drain()
    s = status(owner, corpus["id"])
    assert s["status"] == "ready" and s["error"] is None


def test_documents_added_during_build_end_stale(owner, corpus, fake_embed):
    import uuid

    from services.api.db import transaction
    from services.api.models import Document

    def import_meanwhile():
        fake_embed["hook"] = None
        with transaction() as db:
            db.add(
                Document(
                    corpus_id=uuid.UUID(corpus["id"]),
                    title="新文档",
                    language="zh",
                    text_path="/nonexistent",
                    char_count=3,
                    sentence_count=1,
                    token_count=1,
                )
            )

    fake_embed["hook"] = import_meanwhile
    build(owner, corpus["id"])
    drain()
    s = status(owner, corpus["id"])
    assert s["status"] == "stale" and s["indexed"] == 5
