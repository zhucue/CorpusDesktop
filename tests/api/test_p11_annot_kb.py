"""P11 batch 5a, annotation and knowledge base (contracts/p11.md §二): incremental layer progress, layer scope by
subcorpus and model-call estimate, paged target sentences, Chinese dependency progress, long-text summaries and
term extraction by segment, debounced note re-index and save conflicts, unique evidence."""

import json
import math
import threading
import time
import uuid

import pytest
from sqlalchemy import text

from tests.api.conftest import drain, upload
from tests.api.test_annotations import label_set


@pytest.fixture(autouse=True)
def fake_embed(monkeypatch):
    from engine.kb import embed

    def vector(t):
        v = [0.0] * 384
        v[len(t) % 384] = 1.0
        return v

    monkeypatch.setattr(
        embed, "embed", lambda texts, download=True: [vector(t) for t in texts]
    )
    monkeypatch.setattr(embed, "load", lambda download=True: None)
    monkeypatch.setattr(embed, "model_name", lambda: "fake-embed")


@pytest.fixture
def chat(monkeypatch):
    from services.worker import llm

    calls = []

    def fake(system, user, temperature=0.2):
        calls.append(user)
        if system.startswith("你是术语学"):
            n = len(calls)
            return json.dumps(
                [
                    {"term": "语料库", "language": "zh"},
                    {"term": f"术语{n}", "language": "zh"},
                ],
                ensure_ascii=False,
            )
        return f"要点 {len(calls)}"

    monkeypatch.setattr(llm, "chat", fake)
    monkeypatch.setattr(llm, "model_id", lambda: "fake-chat")
    return calls


def sql(query, **params):
    from services.api.db import transaction

    with transaction() as db:
        result = db.execute(text(query), params)
        return result.all() if result.returns_rows else []


def new_corpus(owner, project, files, language="en", **form):
    c = owner.post(
        f"/api/projects/{project['id']}/corpora",
        json={"name": f"语料{uuid.uuid4().hex[:4]}", "language": language},
    ).json()
    upload(owner, c["id"], files, **form)
    drain()
    c["docs"] = owner.get(f"/api/corpora/{c['id']}/documents").json()["items"]
    return c


def new_layer(owner, project, **body):
    r = owner.post(f"/api/projects/{project['id']}/layers", json=body)
    assert r.status_code == 200, r.text
    drain()
    return owner.get(f"/api/layers/{r.json()['id']}").json()


def assert_counts(owner, layer_id):
    """The incrementally kept counters equal a full recount (refresh_progress, not committed)."""
    from services.api.annotations import refresh_progress
    from services.api.db import session
    from services.api.models import AnnotationLayer

    got = owner.get(f"/api/layers/{layer_id}").json()
    with session() as db:
        layer = db.get(AnnotationLayer, uuid.UUID(layer_id))
        refresh_progress(db, layer)
        want = layer.progress
        db.rollback()
    keys = ("total", "suggested", "confirmed", "modified", "rejected")
    assert {k: got["progress"][k] for k in keys} == {k: want[k] for k in keys}
    assert got["documents"]["done"] == want["documents_done"]
    return got


# ---- incremental progress ----


def test_token_layer_progress_is_incremental(owner, project):
    c = new_corpus(
        owner, project, {"a.txt": "One two three.\nFour five.", "b.txt": "Six seven."}
    )
    a = next(d["id"] for d in c["docs"] if d["title"] == "a")
    b = next(d["id"] for d in c["docs"] if d["title"] == "b")
    layer = new_layer(
        owner,
        project,
        corpus_id=c["id"],
        kind="pos",
        name="词性",
        label_set_id=label_set(owner, "upos")["id"],
    )
    lid = layer["id"]
    got = assert_counts(owner, lid)
    assert got["progress"]["suggested"] == got["progress"]["total"] == 7

    def act(doc, s, t, action, **kw):
        r = owner.post(
            f"/api/layers/{lid}/annotations",
            json={
                "document_id": doc,
                "sentence_index": s,
                "token_index": t,
                "action": action,
                **kw,
            },
        )
        assert r.status_code == 200, r.text
        return assert_counts(owner, lid)

    act(a, 0, 1, "confirm")
    act(a, 0, 2, "modify", label="NOUN")
    act(a, 1, 1, "reject")
    got = act(a, 1, 1, "modify", label="VERB")  # rejected → modified
    assert got["progress"]["rejected"] == 0 and got["documents"]["done"] == 0
    for doc, s in ((b, 0), (a, 0), (a, 1)):
        r = owner.post(f"/api/layers/{lid}/sentences/{doc}/{s}/confirm", json={})
        assert r.status_code == 200, r.text
        got = assert_counts(owner, lid)
    assert got["progress"]["suggested"] == 0 and got["documents"]["done"] == 2
    owner.post(f"/api/layers/{lid}/sentences/{a}/1/reset", json={})
    got = assert_counts(owner, lid)
    assert got["documents"]["done"] == 1 and got["progress"]["suggested"] == 2


def test_span_and_relation_progress_is_incremental(owner, project):
    c = new_corpus(owner, project, {"e.txt": "She have many book .\nWe was happy ."})
    doc = c["docs"][0]["id"]
    spans = new_layer(
        owner,
        project,
        corpus_id=c["id"],
        kind="span",
        name="偏误",
        label_set_id=label_set(owner, "learner-errors")["id"],
        preannotate=False,
    )
    sid = spans["id"]
    labels = [x["id"] for x in label_set(owner, "learner-errors")["labels"]]

    def span(start, end):
        r = owner.post(
            f"/api/layers/{sid}/spans",
            json={
                "document_id": doc,
                "start_cp": start,
                "end_cp": end,
                "label": labels[0],
            },
        )
        assert r.status_code == 200, r.text
        assert_counts(owner, sid)
        return r.json()

    s1, s2, s3 = span(4, 8), span(14, 18), span(21, 24)
    assert assert_counts(owner, sid)["documents"]["done"] == 1
    r = owner.patch(
        f"/api/layers/{sid}/spans/{s1['id']}",
        json={"action": "modify", "label": labels[1]},
    )
    assert r.status_code == 200, r.text
    assert_counts(owner, sid)
    owner.patch(f"/api/layers/{sid}/spans/{s3['id']}", json={"action": "reject"})
    assert_counts(owner, sid)
    # agent suggestions are pending: the document is no longer done
    r = owner.post(
        f"/api/layers/{sid}/spans/suggest",
        json={
            "document_id": doc,
            "sentence_index": 1,
            "spans": [{"start_cp": 24, "end_cp": 29, "label": labels[0]}],
        },
    )
    assert r.status_code == 200, r.text
    assert assert_counts(owner, sid)["documents"]["done"] == 0
    owner.post(f"/api/layers/{sid}/sentences/{doc}/1/confirm", json={})
    assert assert_counts(owner, sid)["documents"]["done"] == 1

    rel_set = label_set(owner, "error-correction")
    rels = new_layer(
        owner,
        project,
        kind="relation",
        name="更正",
        base_layer_id=sid,
        label_set_id=rel_set["id"],
        preannotate=False,
    )
    r = owner.post(
        f"/api/layers/{rels['id']}/relations",
        json={
            "from_span_id": s1["id"],
            "to_span_id": s2["id"],
            "label": rel_set["labels"][0]["id"],
        },
    )
    assert r.status_code == 200, r.text
    assert assert_counts(owner, rels["id"])["progress"]["confirmed"] == 1
    owner.patch(
        f"/api/layers/{rels['id']}/relations/{r.json()['id']}",
        json={"action": "reject"},
    )
    assert_counts(owner, rels["id"])
    # deleting a hand-made span also removes its relations: the relation layer is recounted
    assert owner.delete(f"/api/layers/{sid}/spans/{s1['id']}").status_code == 204
    assert_counts(owner, sid)
    assert assert_counts(owner, rels["id"])["progress"]["total"] == 0


def test_alignment_progress_is_incremental(owner, project, fake_engine):
    c = new_corpus(
        owner, project, {"t.tmx": "\n".join(f"s{i} .\t句{i} 。" for i in range(4))}
    )
    en = next(d["id"] for d in c["docs"] if d["language"] == "en")
    zh = next(d["id"] for d in c["docs"] if d["language"] == "zh")
    layer = new_layer(
        owner,
        project,
        corpus_id=c["id"],
        kind="alignment",
        name="句对",
        level="sentence",
    )
    lid = layer["id"]
    assert assert_counts(owner, lid)["progress"]["suggested"] == 4
    owner.post(f"/api/layers/{lid}/sentences/{en}/0/confirm", json={})
    assert_counts(owner, lid)
    r = owner.post(
        f"/api/layers/{lid}/alignments",
        json={
            "src_document_id": en,
            "src_sentence_index": 1,
            "tgt_document_id": zh,
            "tgt_sentence_index": 3,
        },
    )
    assert r.status_code == 200, r.text
    assert_counts(owner, lid)
    row = r.json()
    owner.patch(f"/api/layers/{lid}/alignments/{row['id']}", json={"action": "reject"})
    assert_counts(owner, lid)


# ---- scope, estimate, target sentences ----


def test_layer_by_subcorpus_and_model_call_estimate(owner, project):
    pid = project["id"]
    c = owner.post(
        f"/api/projects/{pid}/corpora", json={"name": "作文", "language": "en"}
    ).json()
    upload(
        owner,
        c["id"],
        {"a.txt": "\n".join(f"Line {i} ." for i in range(23))},
        metadata=json.dumps({"level": "B1"}),
    )
    upload(owner, c["id"], {"b.txt": "Other ."}, metadata=json.dumps({"level": "C1"}))
    drain()
    docs = owner.get(f"/api/corpora/{c['id']}/documents").json()["items"]
    a = next(d["id"] for d in docs if d["title"] == "a")
    sub = owner.post(
        f"/api/projects/{pid}/subcorpora",
        json={"name": "B1", "corpus_id": c["id"], "filter": {"level": "B1"}},
    ).json()
    est = owner.post(
        f"/api/projects/{pid}/layers/estimate",
        json={"corpus_id": c["id"], "kind": "span", "subcorpus_id": sub["id"]},
    ).json()
    assert est == {
        "documents": 1,
        "sentences": 23,
        "units": 23,
        "batch_size": 10,
        "model_calls": 3,
        "basis": "按句数估算",
    }
    whole = owner.post(
        f"/api/projects/{pid}/layers/estimate",
        json={"corpus_id": c["id"], "kind": "span"},
    ).json()
    assert (whole["sentences"], whole["model_calls"]) == (24, 3)
    pos = owner.post(
        f"/api/projects/{pid}/layers/estimate",
        json={"corpus_id": c["id"], "kind": "pos"},
    ).json()
    assert pos["model_calls"] == 0
    r = owner.post(
        f"/api/projects/{pid}/layers/estimate",
        json={
            "corpus_id": c["id"],
            "kind": "span",
            "subcorpus_id": sub["id"],
            "document_ids": [a],
        },
    )
    assert r.status_code == 422
    layer = new_layer(
        owner,
        project,
        corpus_id=c["id"],
        kind="pos",
        name="B1 词性",
        label_set_id=label_set(owner, "upos")["id"],
        subcorpus_id=sub["id"],
    )
    assert layer["documents"]["total"] == 1
    assert layer["meta"]["subcorpus"] == {"id": sub["id"], "name": "B1"}
    docs_of = owner.get(f"/api/layers/{layer['id']}/documents").json()["items"]
    assert [d["document_id"] for d in docs_of] == [a]


def test_target_sentences_by_position_and_text(owner, project, fake_engine):
    lines = [f"s{i} .\t句子{i} 。" for i in range(250)]
    c = new_corpus(owner, project, {"t.tmx": "\n".join(lines)})
    zh = next(d["id"] for d in c["docs"] if d["language"] == "zh")
    layer = new_layer(
        owner,
        project,
        corpus_id=c["id"],
        kind="alignment",
        name="句对",
        level="sentence",
    )
    url = f"/api/layers/{layer['id']}/target-sentences"
    first = owner.get(url, params={"document_id": zh}).json()
    assert len(first["items"]) == 100 and first["total"] == 250
    assert first["next_start"] == 100
    last = owner.get(url, params={"document_id": zh, "start": 200}).json()
    assert [x["sentence_index"] for x in last["items"]][-1] == 249
    assert last["next_start"] is None
    # a number jumps to that sentence (1-based); text matches sentences containing it
    jump = owner.get(url, params={"document_id": zh, "q": "240", "page_size": 5}).json()
    assert [x["sentence_index"] for x in jump["items"]] == [239, 240, 241, 242, 243]
    found = owner.get(url, params={"document_id": zh, "q": "句子24"}).json()
    assert found["total"] == 11  # 句子24, 句子240–249
    assert found["items"][0]["text"].startswith("句子24")


# ---- Chinese dependency progress ----


def test_chinese_dependency_progress_counts_sentences(owner, project, monkeypatch):
    from engine import nlp

    seen = []

    def fake_parse(doc):
        for s in doc.sentences:
            for i, t in enumerate(s.tokens):
                t.head, t.deprel = (0, "root") if i == 0 else (1, "dep")

    monkeypatch.setattr(nlp, "annotate_dependencies_zh", fake_parse)
    monkeypatch.setattr(nlp, "BATCH", 2)
    from services.worker.main import Run

    real = Run.progress

    def spy(self, done, total=None, message="", unit=None):
        seen.append((done, total, message, unit))
        return real(self, done, total, message, unit)

    monkeypatch.setattr(Run, "progress", spy)
    c = new_corpus(
        owner,
        project,
        {"z.txt": "\n".join(f"我们 研究 语言{i}" for i in range(5))},
        "zh",
    )
    seen.clear()
    layer = new_layer(
        owner,
        project,
        corpus_id=c["id"],
        kind="dep",
        name="依存",
        label_set_id=label_set(owner, "ud-deprel")["id"],
    )
    assert layer["status"] == "ready"
    assert [s for s in seen if s[2] == "依存分析"] == [
        (2, 5, "依存分析", "句"),
        (4, 5, "依存分析", "句"),
        (5, 5, "依存分析", "句"),
    ]
    assert_counts(owner, layer["id"])


# ---- knowledge base ----


def note(owner, project, body, title="笔记"):
    r = owner.post(
        f"/api/projects/{project['id']}/kb/documents",
        json={"kind": "note", "title": title, "body": body},
    )
    assert r.status_code == 200, r.text
    return r.json()


def test_long_summary_by_parts(owner, project, chat):
    from services.worker.kb_tasks import segments

    long_text = "\n".join(
        "语料库研究的方法与材料。" * 10 for _ in range(1250)
    )  # ≈ 15 万字
    doc = note(owner, project, long_text)
    drain()
    job = owner.post(f"/api/kb/documents/{doc['id']}/summarize").json()
    drain()
    result = owner.get(f"/api/jobs/{job['id']}").json()["result"]
    parts = len(segments(long_text))
    assert (
        parts == math.ceil(len(long_text) / 12000)
        or parts == math.ceil(len(long_text) / 12000) + 1
    )
    assert result["parts"] == parts and not result["truncated"]
    assert result["message"] == f"按 {parts} 段摘要"
    assert len(chat) == parts + 1  # one call per part, one to merge
    meta = owner.get(f"/api/kb/documents/{doc['id']}").json()["meta"]
    assert meta["summary_parts"] == parts and meta["summary_truncated"] is False

    chat.clear()
    huge = note(owner, project, "研究" * 150_000, title="专著")  # 30 万字 → 25 段
    drain()
    job = owner.post(f"/api/kb/documents/{huge['id']}/summarize").json()
    drain()
    result = owner.get(f"/api/jobs/{job['id']}").json()["result"]
    assert result["parts"] == 20 and result["total_parts"] == 25 and result["truncated"]
    assert "只读取前 20 段" in result["message"] and len(chat) == 21


def test_literature_terms_by_segment(owner, project, chat):
    doc = note(owner, project, "术" * 30_000, title="文献")
    drain()
    job = owner.post(
        f"/api/projects/{project['id']}/kb/terms/extract",
        json={
            "source": "literature",
            "document_ids": [doc["id"]],
            "method": "model",
            "top": 10,
        },
    )
    assert job.status_code == 200, job.text
    drain()
    result = owner.get(f"/api/jobs/{job.json()['id']}").json()["result"]
    assert result["segments"] == 3 and result["truncated"] == [] and len(chat) == 3
    terms = {
        t["term"]
        for t in owner.get(f"/api/projects/{project['id']}/kb/terms").json()["items"]
    }
    assert {"语料库", "术语1", "术语2", "术语3"} <= terms


def test_note_reindex_waits_for_quiet_and_conflicts(owner, project, member):
    from services.worker.main import claim

    doc = note(owner, project, "初稿")
    drain()
    url = f"/api/kb/documents/{doc['id']}"
    version = owner.get(url).json()["updated_at"]
    for i in range(10):  # autosave ten times
        r = owner.patch(url, json={"body": f"第 {i} 稿", "base_updated_at": version})
        assert r.status_code == 200, r.text
        version = r.json()["updated_at"]
    queued = sql(
        "SELECT params FROM jobs WHERE kind = 'kb_import' AND state = 'queued'"
        " AND params->>'document_id' = :d",
        d=doc["id"],
    )
    assert len(queued) == 1
    assert queued[0][0]["not_before"] > time.time() + 25
    assert claim(["kb_import"]) is None  # not due yet
    # 重新导入 during the quiet period runs the queued re-index now (202, same job)
    r = owner.post(f"{url}/reimport")
    assert r.status_code == 202 and r.json()["kind"] == "kb_import"
    drain()
    chunks = owner.get(f"{url}/chunks").json()["items"]
    assert [c["text"] for c in chunks] == ["第 9 稿"]

    # two editors start from the same version: the later save gets 409 and nothing changes
    editor = member("editor")
    base = owner.get(url).json()["updated_at"]
    assert (
        owner.patch(url, json={"body": "甲", "base_updated_at": base}).status_code
        == 200
    )
    r = editor.patch(url, json={"body": "乙", "base_updated_at": base})
    assert r.status_code == 409 and r.json()["error"]["code"] == "NOTE_CONFLICT"
    assert owner.get(url).json()["body"] == "甲"
    # without a version (the assistant appending) there is no check
    assert editor.patch(url, json={"body": "丙"}).status_code == 200


# ---- evidence ----


def hit_body(doc_id):
    return {
        "kind": "hit",
        "ref": {"document_id": doc_id, "start_cp": 0, "end_cp": 3},
        "text": "One",
        "source": "a",
    }


def test_concurrent_pins_keep_one_item(owner, project, make_user):
    c = new_corpus(owner, project, {"a.txt": "One two three."})
    doc = c["docs"][0]["id"]
    url = f"/api/projects/{project['id']}/evidence"
    barrier = threading.Barrier(4)
    results = []

    def pin():
        barrier.wait()
        results.append(owner.post(url, json=hit_body(doc)))

    threads = [threading.Thread(target=pin) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert all(r.status_code == 200 for r in results), [r.text for r in results]
    assert len({r.json()["id"] for r in results}) == 1
    assert sum(not r.json()["existing"] for r in results) == 1
    assert owner.get(url).json()["total"] == 1
    stat_row = {
        "kind": "stat_row",
        "ref": {"row_key": "行" * 2000},
        "text": "x",
        "source": "s",
    }
    assert (
        owner.post(url, json=stat_row).status_code == 200
    )  # no stat id: never a duplicate key


def test_migration_merges_duplicate_evidence(owner, project):
    import importlib

    c = new_corpus(owner, project, {"a.txt": "One two three."})
    doc = c["docs"][0]["id"]
    pid = project["id"]
    first = owner.post(f"/api/projects/{pid}/evidence", json=hit_body(doc)).json()
    n = note(owner, project, "")
    r = owner.post(
        f"/api/kb/documents/{n['id']}/refs",
        json={"kind": "evidence", "ref": {"evidence_id": first["id"]}, "append": False},
    )
    assert r.status_code == 200, r.text
    # a duplicate from before the index (written later, referenced by the note)
    dup = str(uuid.uuid4())
    sql("DROP INDEX uq_evidence_hit")
    sql(
        "INSERT INTO evidence (id, project_id, kind, ref, text, source, created_by, created_at)"
        " SELECT CAST(:dup AS uuid), project_id, kind, ref, text, source, created_by,"
        " created_at + interval '1 minute' FROM evidence WHERE id = CAST(:id AS uuid)",
        dup=dup,
        id=first["id"],
    )
    owner.post(
        f"/api/kb/documents/{n['id']}/refs",
        json={"kind": "evidence", "ref": {"evidence_id": dup}, "append": False},
    )
    sql("UPDATE evidence SET note = '后来的备注' WHERE id = CAST(:d AS uuid)", d=dup)
    sql(
        "UPDATE evidence SET note = '最早的备注' WHERE id = CAST(:d AS uuid)",
        d=first["id"],
    )
    sql("DROP INDEX uq_evidence_stat_row")

    migration = importlib.import_module(
        "services.api.migrations.versions.0013_evidence_unique"
    )

    class Op:
        @staticmethod
        def execute(statement):
            sql(statement)

    real_op, migration.op = migration.op, Op
    try:
        migration.upgrade()
    finally:
        migration.op = real_op
    rows = sql("SELECT id::text, note FROM evidence")
    assert rows == [(first["id"], "最早的备注\n后来的备注")]
    refs = sql(
        "SELECT ref->>'evidence_id' FROM note_refs WHERE note_id = CAST(:n AS uuid)",
        n=n["id"],
    )
    assert [r[0] for r in refs] == [first["id"], first["id"]]
    names = {
        r[0]
        for r in sql("SELECT indexname FROM pg_indexes WHERE tablename = 'evidence'")
    }
    assert {"uq_evidence_hit", "uq_evidence_stat_row"} <= names


def test_cancelled_span_preannotation_recounts_progress(owner, project, monkeypatch):
    """Batches written after the last periodic recount still count when the run is cancelled."""
    from services.worker import llm

    c = new_corpus(
        owner, project, {"e.txt": "\n".join(f"word{i} here ." for i in range(30))}
    )
    labels = [x["id"] for x in label_set(owner, "learner-errors")["labels"]]
    calls = []

    def fake(system, user, temperature=0.2):
        calls.append(user)
        if len(calls) == 2:  # cancel while the second batch is with the model
            sql("UPDATE jobs SET state = 'cancelled' WHERE kind = 'preannotate'")
        sentences = json.loads(user.split("句子：\n", 1)[1])
        out = []
        for s in sentences:
            word = s["text"].split()[0]
            out.append(
                {
                    "id": s["id"],
                    "text": word,
                    "start": 0,
                    "end": len(word),
                    "label": labels[0],
                }
            )
        return json.dumps(out, ensure_ascii=False)

    monkeypatch.setattr(llm, "chat", fake)
    monkeypatch.setattr(llm, "model_id", lambda: "fake-chat")
    r = owner.post(
        f"/api/projects/{project['id']}/layers",
        json={
            "corpus_id": c["id"],
            "kind": "span",
            "name": "偏误",
            "label_set_id": label_set(owner, "learner-errors")["id"],
        },
    )
    assert r.status_code == 200, r.text
    drain()
    got = assert_counts(owner, r.json()["id"])
    assert (
        got["progress"]["suggested"] == 20
    )  # both written batches, not only the first
