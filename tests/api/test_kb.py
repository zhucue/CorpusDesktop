"""P4 knowledge base API: document lifecycle, hybrid search, terms, note refs, exports, permissions.

Real parsers and chunker run on tests/fixtures; the embedder, the chat model and CWB term counts are faked.
"""

import csv
import io
import json
import math
from pathlib import Path

import pytest
from docx import Document as DocxDocument
from lxml import etree
from openpyxl import load_workbook

from tests.api.conftest import drain, upload
from tests.api.test_stats_evidence import bearer_client

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
AXES = {
    "corpus": 0,
    "corpora": 0,
    "语料": 0,
    "translation": 1,
    "翻译": 1,
    "banana": 2,
    "香蕉": 2,
}


def fake_vector(text):
    v = [0.0] * 384
    low = text.lower()
    for word, axis in AXES.items():
        v[axis] += low.count(word)
    v[3] = 0.1
    n = math.sqrt(sum(x * x for x in v))
    return [x / n for x in v]


@pytest.fixture(autouse=True)
def fake_embed(monkeypatch):
    from engine.kb import embed

    state = {"available": True, "calls": 0}

    def fake(texts, download=True):
        if not state["available"]:
            raise embed.EmbedUnavailable("向量模型不可用：测试")
        state["calls"] += 1
        return [fake_vector(t) for t in texts]

    def load(download=True):
        if not state["available"]:
            raise embed.EmbedUnavailable("向量模型不可用：测试")

    monkeypatch.setattr(embed, "embed", fake)
    monkeypatch.setattr(embed, "load", load)
    monkeypatch.setattr(embed, "model_name", lambda: "fake-model")
    return state


@pytest.fixture
def fake_llm(monkeypatch):
    from services.worker import llm

    calls = []
    answers = []

    def chat(system, user, temperature=0.2):
        calls.append(user)
        return answers.pop(0) if answers else "这是一段模型摘要。"

    monkeypatch.setattr(llm, "chat", chat)
    monkeypatch.setattr(llm, "model_id", lambda: "fake-chat")
    return {"calls": calls, "answers": answers}


def files_payload(*names, content=None):
    return [
        (
            "files",
            (
                name,
                content or (FIXTURES / name).read_bytes(),
                "application/octet-stream",
            ),
        )
        for name in names
    ]


def create_note(client, project, body, title="笔记", kind="note"):
    r = client.post(
        f"/api/projects/{project['id']}/kb/documents",
        json={"kind": kind, "title": title, "body": body},
    )
    assert r.status_code == 200, r.text
    return r.json()


def search(client, project, q, **kw):
    r = client.post(f"/api/projects/{project['id']}/kb/search", json={"q": q, **kw})
    assert r.status_code == 200, r.text
    return r.json()


# ---- documents ----


def test_document_lifecycle(owner, project, fake_llm):
    from services.api.storage import kb_dir

    pid = project["id"]
    r = owner.post(
        f"/api/projects/{pid}/kb/documents",
        files=files_payload("kb-sample.pdf", "kb-sample.docx", "kb-sample.md"),
    )
    assert r.status_code == 200, r.text
    items = r.json()["items"]
    assert r.json()["total"] == 3
    busy = owner.get(f"/api/projects/{pid}/kb/documents").json()["items"]
    assert {d["job_id"] for d in busy} == {d["job_id"] for d in items}
    assert [(d["kind"], d["status"], d["title"]) for d in items] == [
        ("literature", "queued", "kb-sample")
    ] * 3
    assert all(d["job_id"] for d in items)
    drain()
    listed = owner.get(f"/api/projects/{pid}/kb/documents").json()
    assert listed["total"] == 3
    assert {d["status"] for d in listed["items"]} == {"ready"}
    pdf = owner.get(f"/api/kb/documents/{items[0]['id']}").json()
    assert pdf["meta"]["pages"] == 2 and pdf["meta"]["title"] == "Corpus sample"
    assert pdf["text_preview"].startswith("Corpus linguistics") and pdf["error"] is None
    chunks = owner.get(f"/api/kb/documents/{items[0]['id']}/chunks").json()
    assert [c["locator"] for c in chunks["items"]] == [{"page": 1}, {"page": 2}]
    docx_chunks = owner.get(f"/api/kb/documents/{items[1]['id']}/chunks").json()[
        "items"
    ]
    assert docx_chunks[1]["locator"] == {"heading_path": ["标注规范", "名词"]}
    md_chunks = owner.get(f"/api/kb/documents/{items[2]['id']}/chunks").json()["items"]
    assert md_chunks[0]["locator"] == {"heading_path": ["Corpus methods"], "line": 3}

    r = owner.patch(
        f"/api/kb/documents/{items[0]['id']}",
        json={"title": "语料库入门", "meta": {"year": 2024, "author": None}},
    )
    assert r.status_code == 200, r.text
    assert r.json()["title"] == "语料库入门"
    assert r.json()["meta"] == {"pages": 2, "title": "Corpus sample", "year": 2024}
    assert (
        owner.patch(
            f"/api/kb/documents/{items[0]['id']}", json={"body": "x"}
        ).status_code
        == 422
    )

    job = owner.post(f"/api/kb/documents/{items[0]['id']}/summarize").json()
    assert job["kind"] == "kb_summarize"
    drain()
    assert owner.get(f"/api/jobs/{job['id']}").json()["state"] == "succeeded"
    meta = owner.get(f"/api/kb/documents/{items[0]['id']}").json()["meta"]
    assert meta["summary"] == "这是一段模型摘要。" and meta["summary_source"] == "model"
    assert "Corpus linguistics" in fake_llm["calls"][0]

    job = owner.post(f"/api/kb/documents/{items[0]['id']}/reimport").json()
    assert job["kind"] == "kb_import"
    assert owner.post(f"/api/kb/documents/{items[0]['id']}/reimport").status_code == 409
    drain()
    again = owner.get(f"/api/kb/documents/{items[0]['id']}").json()
    assert again["status"] == "ready" and again["chunk_count"] == 2
    assert (
        again["meta"]["summary"] == "这是一段模型摘要。"
        and again["meta"]["year"] == 2024
    )

    assert kb_dir(items[0]["id"]).exists()
    assert owner.delete(f"/api/kb/documents/{items[0]['id']}").status_code == 204
    assert owner.get(f"/api/kb/documents/{items[0]['id']}").status_code == 404
    assert not kb_dir(items[0]["id"]).exists()


def test_upload_validation_and_parse_failure(owner, project):
    pid = project["id"]
    r = owner.post(
        f"/api/projects/{pid}/kb/documents", files=files_payload("a.doc", content=b"x")
    )
    assert r.status_code == 422 and r.json()["error"]["code"] == "UNSUPPORTED_FORMAT"
    r = owner.post(
        f"/api/projects/{pid}/kb/documents",
        files=files_payload("bad.pdf", content=b"FAIL"),
    )
    doc = r.json()["items"][0]
    drain()
    failed = owner.get(f"/api/kb/documents/{doc['id']}").json()
    assert failed["status"] == "failed" and failed["error"]
    job = owner.get(f"/api/jobs/{doc['job_id']}").json()
    assert job["state"] == "failed" and job["error"]["code"] == "PARSE_ERROR"
    r = owner.post(f"/api/projects/{pid}/kb/documents", json={"url": "ftp://x"})
    assert r.json()["error"]["code"] == "INVALID_URL"
    r = owner.post(f"/api/projects/{pid}/kb/documents", json={"kind": "note"})
    assert r.status_code == 422


def test_url_import(owner, project, monkeypatch):
    from engine.kb import parse

    page = (
        "<html><head><title>Corpus page</title></head><body><article><h1>Parallel corpora</h1>"
        "<p>Parallel corpora align source texts with their translations at the sentence level.</p>"
        "<h2>翻译</h2><p>平行语料库在句子层面对齐原文与译文，用于翻译研究。</p></article></body></html>"
    )
    monkeypatch.setattr(parse, "fetch", lambda url: page.encode())
    r = owner.post(
        f"/api/projects/{project['id']}/kb/documents",
        json={"url": "https://example.org/pc"},
    )
    assert r.status_code == 200, r.text
    doc = r.json()
    assert doc["kind"] == "url" and doc["title"] == "https://example.org/pc"
    drain()
    got = owner.get(f"/api/kb/documents/{doc['id']}").json()
    assert got["status"] == "ready" and got["title"] == "Parallel corpora"
    assert got["source"] == "https://example.org/pc"
    chunks = owner.get(f"/api/kb/documents/{doc['id']}/chunks").json()["items"]
    assert chunks[-1]["locator"]["heading_path"][-1] == "翻译"


def test_url_import_rejects_internal_targets(owner, project, monkeypatch):
    from engine.kb import parse

    monkeypatch.setattr(parse, "fetch", lambda url: b"<html></html>")
    pid = project["id"]
    for url in (
        "http://127.0.0.1:8000/api/health",
        "http://localhost/x",
        "http://10.0.0.8/",
        "http://169.254.169.254/latest/meta-data",
        "http://100.64.0.1/",
        "http://[::1]/",
    ):
        r = owner.post(f"/api/projects/{pid}/kb/documents", json={"url": url})
        assert r.status_code == 422, url
        assert r.json()["error"]["code"] == "INVALID_URL"
    assert owner.get(f"/api/projects/{pid}/kb/documents").json()["total"] == 0


def test_url_import_deduplicates(owner, project, monkeypatch):
    from engine.kb import parse

    page = "<html><body><article><p>Parallel corpora align texts.</p></article></body></html>"
    monkeypatch.setattr(parse, "fetch", lambda url: page.encode())
    pid = project["id"]
    first = owner.post(
        f"/api/projects/{pid}/kb/documents", json={"url": "https://example.org/pc"}
    )
    assert first.status_code == 200, first.text
    for same in ("https://example.org/pc", "HTTPS://Example.org:443/pc/#top"):
        r = owner.post(f"/api/projects/{pid}/kb/documents", json={"url": same})
        assert r.status_code == 409 and r.json()["error"]["code"] == "DUPLICATE_URL"
    other = owner.post(
        f"/api/projects/{pid}/kb/documents",
        json={"url": "https://example.org/pc?page=2"},
    )
    assert other.status_code == 200
    again = owner.post(
        f"/api/projects/{pid}/kb/documents",
        json={"url": "https://example.org/pc", "force": True},
    )
    assert again.status_code == 200 and again.json()["id"] != first.json()["id"]
    elsewhere = owner.post("/api/projects", json={"name": "另一个"}).json()
    r = owner.post(
        f"/api/projects/{elsewhere['id']}/kb/documents",
        json={"url": "https://example.org/pc"},
    )
    assert r.status_code == 200  # per project


def test_note_body_change_reindexes(owner, project):
    note = create_note(owner, project, "# 想法\n\n语料库很重要。")
    assert note["body"] == "# 想法\n\n语料库很重要。" and note["job_id"]
    drain()
    got = owner.get(f"/api/kb/documents/{note['id']}").json()
    assert got["status"] == "ready" and got["chunk_count"] == 1 and got["refs"] == []
    r = owner.patch(f"/api/kb/documents/{note['id']}", json={"body": "香蕉 banana"})
    assert r.json()["status"] == "queued"
    owner.patch(f"/api/kb/documents/{note['id']}", json={"body": "香蕉 banana 2"})
    jobs = owner.get(f"/api/projects/{project['id']}/jobs").json()["items"]
    assert sum(j["kind"] == "kb_import" and j["state"] == "queued" for j in jobs) == 1
    drain()
    chunks = owner.get(f"/api/kb/documents/{note['id']}/chunks").json()["items"]
    assert [c["text"] for c in chunks] == ["香蕉 banana 2"]


def test_embedding_unavailable_keeps_keyword_search(owner, project, fake_embed):
    fake_embed["available"] = False
    note = create_note(owner, project, "Corpus methods for translation studies.")
    drain()
    got = owner.get(f"/api/kb/documents/{note['id']}").json()
    assert got["status"] == "ready" and got["error"].startswith("向量化未完成")
    res = search(owner, project, "corpus")
    assert res["warning"] == "EMBED_UNAVAILABLE" and res["mode"] == "keyword"
    assert [i["chunk"]["document_id"] for i in res["items"]] == [note["id"]]
    fake_embed["available"] = True
    res = search(owner, project, "corpus")
    assert (
        "warning" not in res and len(res["items"]) == 1
    )  # no vectors yet: keyword hit only


# ---- search ----


def test_hybrid_search_rrf(owner, project):
    a = create_note(
        owner, project, "Corpus corpus corpus banana.", "A"
    )  # vector 1st, keyword 2nd
    b = create_note(owner, project, "Banana bread.", "B")  # no keyword hit
    c = create_note(owner, project, "The corpus of translation corpus studies.", "C")
    g = create_note(
        owner, project, "语料库与翻译：平行语料库的检索。", "G", kind="guideline"
    )
    drain()
    res = search(owner, project, "corpus", mode="vector")
    assert [i["document"]["title"] for i in res["items"]][:2] == ["A", "C"]
    res = search(owner, project, "corpus", mode="keyword")
    assert {i["document"]["title"] for i in res["items"]} == {"A", "C"}
    res = search(owner, project, "corpus", top_k=3)
    titles = [i["document"]["title"] for i in res["items"]]
    assert titles[:2] == ["A", "C"] and len(titles) == 3
    first = res["items"][0]
    assert (
        first["score"] == pytest.approx(2 / 61)
        and first["chunk"]["score"] == first["score"]
    )
    assert first["highlight"].count("<mark>") == 3
    assert first["document"] == {
        "id": a["id"],
        "title": "A",
        "kind": "note",
        "source": "",
    }
    assert b["id"] in {
        i["document"]["id"] for i in search(owner, project, "banana")["items"]
    }

    zh = search(owner, project, "平行语料库检索")
    assert zh["items"][0]["document"]["id"] == g["id"]
    assert (
        "<mark>平行</mark>" in zh["items"][0]["highlight"]
        or "<mark>语料库</mark>" in zh["items"][0]["highlight"]
    )
    only = search(owner, project, "corpus", kinds=["guideline"])
    assert {i["document"]["id"] for i in only["items"]} == {g["id"]}
    only = search(owner, project, "corpus", document_ids=[c["id"]])
    assert {i["document"]["id"] for i in only["items"]} == {c["id"]}

    owner.post(
        f"/api/projects/{project['id']}/kb/terms",
        json={"term": "corpus", "status": "confirmed"},
    )
    owner.post(
        f"/api/projects/{project['id']}/kb/terms", json={"term": "corpus linguistics"}
    )
    owner.post(f"/api/projects/{project['id']}/kb/terms", json={"term": "平行语料库"})
    assert [t["term"] for t in search(owner, project, "corpus")["terms"]] == [
        "corpus",
        "corpus linguistics",
    ]
    assert [t["term"] for t in search(owner, project, "什么是平行语料库")["terms"]] == [
        "平行语料库"
    ]


# ---- terms ----


def test_terms_crud(owner, project, member):
    pid = project["id"]
    r = owner.post(
        f"/api/projects/{pid}/kb/terms",
        json={
            "term": "语料库",
            "translations": [{"language": "en", "text": "corpus"}],
            "definition": "按抽样标准收集的真实文本集合",
            "domain": "语料库语言学",
        },
    )
    assert r.status_code == 200, r.text
    t = r.json()
    assert (t["language"], t["status"], t["source"], t["confirmed_by"]) == (
        "zh",
        "draft",
        "manual",
        None,
    )
    assert (
        owner.post(f"/api/projects/{pid}/kb/terms", json={"term": "语料库"}).status_code
        == 409
    )
    en = owner.post(
        f"/api/projects/{pid}/kb/terms", json={"term": "corpus", "language": "en-US"}
    ).json()
    assert en["language"] == "en"

    assert owner.get(f"/api/kb/terms/{t['id']}").json() == t
    listed = owner.get(f"/api/projects/{pid}/kb/terms", params={"q": "corpus"}).json()
    assert {x["term"] for x in listed["items"]} == {
        "语料库",
        "corpus",
    }  # translation text matches too
    assert (
        owner.get(f"/api/projects/{pid}/kb/terms", params={"language": "zh"}).json()[
            "total"
        ]
        == 1
    )

    annotator = member("annotator")
    r = annotator.patch(
        f"/api/kb/terms/{t['id']}", json={"status": "confirmed", "definition": None}
    )
    assert r.status_code == 200, r.text
    assert (
        r.json()["confirmed_by"] == annotator.user_id and r.json()["definition"] is None
    )
    assert (
        owner.get(
            f"/api/projects/{pid}/kb/terms", params={"status": "confirmed"}
        ).json()["total"]
        == 1
    )
    assert (
        owner.patch(
            f"/api/kb/terms/{en['id']}", json={"term": "语料库", "language": "zh"}
        ).status_code
        == 409
    )

    r = annotator.post(
        f"/api/kb/terms/{t['id']}/examples",
        json={"text": "这是一个语料库。", "source": "作文 / a"},
    )
    assert r.json()["examples"] == [{"text": "这是一个语料库。", "source": "作文 / a"}]
    bad = {"text": "x", "document_id": "00000000-0000-0000-0000-000000000000"}
    assert (
        annotator.post(f"/api/kb/terms/{t['id']}/examples", json=bad).status_code == 404
    )

    viewer = member("viewer")
    assert viewer.get(f"/api/projects/{pid}/kb/terms").json()["total"] == 2
    assert (
        viewer.post(f"/api/projects/{pid}/kb/terms", json={"term": "x"}).status_code
        == 403
    )
    assert annotator.delete(f"/api/kb/terms/{t['id']}").status_code == 403
    own = annotator.post(f"/api/projects/{pid}/kb/terms", json={"term": "搭配"}).json()
    assert annotator.delete(f"/api/kb/terms/{own['id']}").status_code == 204
    assert owner.delete(f"/api/kb/terms/{t['id']}").status_code == 204


TMX_LINES = [
    "machine translation quality\t机器 翻译 质量",
    "machine translation\t机器 翻译",
    "human translation\t人工 翻译",
    "translation quality\t翻译 质量",
]


@pytest.fixture
def parallel(owner, project, monkeypatch):
    """Fake TMX corpus with POS set in tokens; CWB counts replaced by the same counts from PostgreSQL."""
    from sqlalchemy import select, update

    from engine.kb import terms
    from services.api.db import session, transaction
    from services.api.models import Document, Sentence, Token

    c = owner.post(
        f"/api/projects/{project['id']}/corpora",
        json={"name": "平行", "language": "en"},
    ).json()
    upload(owner, c["id"], {"t.tmx": "\n".join(TMX_LINES)})
    drain()
    with transaction() as db:
        db.execute(
            update(Token)
            .where(Token.form.op("~")("^[a-z]+$"))
            .values(pos="NOUN", lemma=Token.form)
        )
        db.execute(
            update(Token).where(Token.pos.is_(None)).values(pos="n", lemma=Token.form)
        )

    def scan_scope(scope):
        with session() as db:
            rows = db.execute(
                select(
                    Document.language, Sentence.id, Token.form, Token.pos, Token.lemma
                )
                .join(Sentence, Sentence.document_id == Document.id)
                .join(Token, Token.sentence_id == Sentence.id)
                .order_by(Sentence.id, Token.idx)
            ).all()
        sents = {}
        for lang, sid, f, p, lemma in rows:
            sents.setdefault(sid, (lang, []))[1].append((f, p, lemma))
        return terms.count(sents.values())

    monkeypatch.setattr(terms, "scan_scope", scan_scope)
    return c


def test_extract_pos_pattern_with_translations(owner, project, parallel):
    pid = project["id"]
    body = {
        "source": "corpus",
        "scope": {"corpus_id": parallel["id"]},
        "method": "pos_pattern",
        "top": 10,
    }
    job = owner.post(f"/api/projects/{pid}/kb/terms/extract", json=body).json()
    assert job["kind"] == "kb_extract"
    drain()
    job = owner.get(f"/api/jobs/{job['id']}").json()
    assert job["state"] == "succeeded", job["error"]
    assert job["result"] == {"created": 4, "skipped": 0, "candidates": 4}
    items = owner.get(f"/api/projects/{pid}/kb/terms").json()["items"]
    got = {(t["term"], t["language"]): t for t in items}
    assert set(got) == {
        ("machine translation", "en"),
        ("translation quality", "en"),
        ("机器翻译", "zh"),
        ("翻译质量", "zh"),
    }
    assert got[("机器翻译", "zh")]["translations"] == [
        {"language": "en", "text": "machine translation"}
    ]
    assert got[("translation quality", "en")]["translations"] == [
        {"language": "zh", "text": "翻译质量"}
    ]
    t = got[("机器翻译", "zh")]
    assert t["source"] == "corpus" and t["status"] == "draft"
    assert t["examples"][0]["text"] == "机器 翻译 质量" and t["examples"][0][
        "source"
    ].startswith("平行《")
    again = owner.post(
        f"/api/projects/{pid}/kb/terms/extract", json={**body, "language": "zh"}
    ).json()
    drain()
    assert owner.get(f"/api/jobs/{again['id']}").json()["result"] == {
        "created": 0,
        "skipped": 2,
        "candidates": 2,
    }


def test_extract_model_methods(owner, project, parallel, fake_llm):
    pid = project["id"]
    fake_llm["answers"].append(
        "```json\n"
        + json.dumps(
            [
                {
                    "term": "机器翻译",
                    "language": "zh",
                    "translations": [{"language": "en", "text": "machine translation"}],
                    "definition": "由计算机完成的翻译",
                    "domain": "翻译学",
                },
                {"term": "", "language": "zh"},
                "junk",
            ],
            ensure_ascii=False,
        )
        + "\n```"
    )
    job = owner.post(
        f"/api/projects/{pid}/kb/terms/extract",
        json={
            "source": "corpus",
            "scope": {"corpus_id": parallel["id"]},
            "method": "model",
        },
    ).json()
    drain()
    assert owner.get(f"/api/jobs/{job['id']}").json()["result"]["created"] == 1
    assert (
        "机器翻译（zh，n+n，频次 2，候选译名 machine translation）"
        in fake_llm["calls"][0]
    )
    t = owner.get(f"/api/projects/{pid}/kb/terms").json()["items"][0]
    assert (t["source"], t["definition"], t["domain"]) == (
        "model",
        "由计算机完成的翻译",
        "翻译学",
    )

    note = create_note(owner, project, "Term extraction finds candidate terms.")
    drain()
    fake_llm["answers"].append('[{"term": "term extraction", "language": "en"}]')
    r = owner.post(
        f"/api/projects/{pid}/kb/terms/extract",
        json={"source": "literature", "document_ids": [note["id"]], "method": "model"},
    )
    assert r.status_code == 200, r.text
    drain()
    assert owner.get(f"/api/jobs/{r.json()['id']}").json()["result"]["created"] == 1
    assert "Term extraction finds candidate terms." in fake_llm["calls"][1]
    bad = {
        "source": "literature",
        "document_ids": [note["id"]],
        "method": "pos_pattern",
    }
    assert (
        owner.post(f"/api/projects/{pid}/kb/terms/extract", json=bad).status_code == 422
    )


def test_term_exports(owner, project, member):
    pid = project["id"]
    owner.post(
        f"/api/projects/{pid}/kb/terms",
        json={
            "term": "语料库",
            "translations": [{"language": "en", "text": "corpus"}],
            "definition": "真实文本集合",
            "domain": "语言学",
            "examples": [{"text": "建设语料库。", "source": "笔记"}],
            "status": "confirmed",
        },
    )
    owner.post(f"/api/projects/{pid}/kb/terms", json={"term": "搭配 & <强度>"})
    viewer = member("viewer")
    out = {}
    for fmt in ("csv", "xlsx", "tbx"):
        job = viewer.post(
            f"/api/projects/{pid}/kb/terms/export", json={"format": fmt}
        ).json()
        drain()
        r = viewer.get(f"/api/jobs/{job['id']}/download")
        assert r.status_code == 200, r.text
        out[fmt] = r
    rows = list(csv.reader(io.StringIO(out["csv"].content.decode("utf-8-sig"))))
    assert rows[0] == ["术语", "语言", "译名", "定义", "领域", "例句", "来源", "状态"]
    assert [
        "语料库",
        "zh",
        "en: corpus",
        "真实文本集合",
        "语言学",
        "建设语料库。（笔记）",
        "manual",
        "已确认",
    ] in rows
    ws = load_workbook(io.BytesIO(out["xlsx"].content)).active
    assert ws["A1"].value == "术语" and ws["A1"].font.name == "宋体"
    assert ws["A1"].fill.fill_type is None
    root = etree.fromstring(out["tbx"].content)
    ns = {"t": "urn:iso:std:iso:30042:ed-2"}
    assert root.get("type") == "TBX-Basic"
    entries = root.findall(".//t:conceptEntry", ns)
    assert len(entries) == 2
    terms = [e.findtext(".//t:term", namespaces=ns) for e in entries]
    assert set(terms) == {"语料库", "搭配 & <强度>"}
    entry = entries[terms.index("语料库")]
    assert entry.findtext("t:descrip[@type='subjectField']", namespaces=ns) == "语言学"
    langs = [
        s.get("{http://www.w3.org/XML/1998/namespace}lang")
        for s in entry.findall("t:langSec", ns)
    ]
    assert langs == ["zh", "en"]
    job = viewer.post(
        f"/api/projects/{pid}/kb/terms/export",
        json={"format": "tbx", "status": "confirmed"},
    ).json()
    drain()
    root = etree.fromstring(viewer.get(f"/api/jobs/{job['id']}/download").content)
    assert len(root.findall(".//t:conceptEntry", ns)) == 1


# ---- note refs ----


def test_evidence_ref_appends_to_note_and_exports(owner, project, member):
    pid = project["id"]
    note = create_note(owner, project, "# 搭配研究\n\n初步想法。", "搭配笔记")
    ev = owner.post(
        f"/api/projects/{pid}/evidence",
        json={
            "kind": "text",
            "ref": {"search_query": '"language"'},
            "text": "Language is a system.",
            "source": "作文 / a",
        },
    ).json()
    r = owner.post(
        f"/api/kb/documents/{note['id']}/refs",
        json={"kind": "evidence", "ref": {"evidence_id": ev["id"]}},
    )
    assert r.status_code == 200, r.text
    ref = r.json()
    assert ref["kind"] == "evidence" and ref["ref"]["text"] == "Language is a system."
    body = owner.get(f"/api/kb/documents/{note['id']}").json()
    assert body["body"] == (
        '# 搭配研究\n\n初步想法。\n\n> Language is a system.\n>\n> —— 作文 / a；查询式：`"language"`\n'
    )
    assert [x["id"] for x in body["refs"]] == [ref["id"]]
    stat = owner.post(
        f"/api/kb/documents/{note['id']}/refs",
        json={
            "kind": "search",
            "ref": {"query": "make /n", "scope": {"corpus_id": "x"}},
        },
    )
    assert stat.status_code == 200
    missing = {
        "kind": "evidence",
        "ref": {"evidence_id": "00000000-0000-0000-0000-000000000000"},
    }
    assert (
        owner.post(f"/api/kb/documents/{note['id']}/refs", json=missing).status_code
        == 404
    )
    lit = create_note(owner, project, "x", kind="guideline")
    assert (
        owner.post(
            f"/api/kb/documents/{lit['id']}/refs", json={"kind": "search", "ref": {}}
        ).status_code
        == 422
    )
    drain()

    viewer = member("viewer")
    job = viewer.post(
        f"/api/kb/documents/{note['id']}/export", json={"format": "docx"}
    ).json()
    drain()
    r = viewer.get(f"/api/jobs/{job['id']}/download")
    assert r.status_code == 200, r.text
    doc = DocxDocument(io.BytesIO(r.content))
    text = [p.text for p in doc.paragraphs]
    assert text[:4] == ["搭配笔记", "搭配研究", "初步想法。", "Language is a system."]
    assert "引用" in text
    assert "1. [证据] Language is a system." in text
    assert "" not in text
    assert "出处：作文 / a" in text and '查询式："language"' in text
    assert "2. [检索] 查询式：make /n" in text
    assert doc.styles["Normal"].font.name == "宋体"
    job = owner.post(
        f"/api/kb/documents/{note['id']}/export", json={"format": "md"}
    ).json()
    drain()
    md = owner.get(f"/api/jobs/{job['id']}/download").content.decode()
    assert (
        md.startswith("# 搭配研究") and "## 引用" in md and "   - 出处：作文 / a" in md
    )


# ---- permissions and agent token ----


def test_roles(owner, project, member, make_user):
    pid = project["id"]
    note = create_note(owner, project, "Corpus note.")
    drain()
    viewer, annotator = member("viewer"), member("annotator")
    assert viewer.get(f"/api/projects/{pid}/kb/documents").json()["total"] == 1
    assert search(viewer, project, "corpus")["items"]
    assert (
        viewer.post(
            f"/api/projects/{pid}/kb/documents",
            json={"kind": "note", "title": "v", "body": ""},
        ).status_code
        == 403
    )
    assert (
        viewer.patch(f"/api/kb/documents/{note['id']}", json={"title": "v"}).status_code
        == 403
    )
    assert viewer.post(f"/api/kb/documents/{note['id']}/summarize").status_code == 403
    assert (
        viewer.post(
            f"/api/kb/documents/{note['id']}/export", json={"format": "md"}
        ).status_code
        == 200
    )
    assert (
        annotator.patch(
            f"/api/kb/documents/{note['id']}", json={"title": "改名"}
        ).status_code
        == 200
    )
    assert annotator.delete(f"/api/kb/documents/{note['id']}").status_code == 403
    own = create_note(annotator, project, "mine")
    assert annotator.delete(f"/api/kb/documents/{own['id']}").status_code == 204
    stranger = make_user("x@example.edu")
    assert stranger.get(f"/api/kb/documents/{note['id']}").status_code == 404
    assert (
        stranger.post(f"/api/projects/{pid}/kb/search", json={"q": "x"}).status_code
        == 404
    )


def test_bearer_token(owner, project, fake_llm):
    pid = project["id"]
    note = create_note(owner, project, "Corpus note.")
    drain()
    token = owner.post("/api/auth/agent-token", json={"project_id": pid}).json()[
        "token"
    ]
    agent = bearer_client(token)
    assert search(agent, project, "corpus")["items"]
    assert agent.get(f"/api/kb/documents/{note['id']}").status_code == 200
    mine = agent.post(
        f"/api/projects/{pid}/kb/documents",
        json={"kind": "note", "title": "助手回答", "body": "回答"},
    )
    assert mine.status_code == 200
    assert (
        agent.patch(
            f"/api/kb/documents/{note['id']}", json={"body": "追加"}
        ).status_code
        == 200
    )
    assert (
        agent.post(
            f"/api/kb/documents/{note['id']}/refs", json={"kind": "chunk", "ref": {}}
        ).status_code
        == 200
    )
    r = agent.post(f"/api/projects/{pid}/kb/terms", json={"term": "corpus"})
    assert r.status_code == 200 and r.json()["source"] == "model"
    term = r.json()
    assert (
        agent.post(
            f"/api/projects/{pid}/kb/terms", json={"term": "x", "status": "confirmed"}
        ).status_code
        == 403
    )
    assert (
        agent.patch(
            f"/api/kb/terms/{term['id']}", json={"status": "confirmed"}
        ).status_code
        == 403
    )
    assert agent.delete(f"/api/kb/terms/{term['id']}").status_code == 403
    assert agent.post(f"/api/kb/documents/{note['id']}/summarize").status_code == 200
    guideline = {"kind": "guideline", "title": "g", "body": ""}
    assert (
        agent.post(f"/api/projects/{pid}/kb/documents", json=guideline).status_code
        == 403
    )
    assert (
        agent.post(
            f"/api/projects/{pid}/kb/documents", json={"url": "https://example.org"}
        ).status_code
        == 403
    )
    files = files_payload("kb-sample.md")
    assert (
        agent.post(f"/api/projects/{pid}/kb/documents", files=files).status_code == 403
    )
    assert agent.post(f"/api/kb/documents/{note['id']}/reimport").status_code == 403
    assert agent.delete(f"/api/kb/documents/{note['id']}").status_code == 403
    other = owner.post("/api/projects", json={"name": "另一个"}).json()
    assert agent.get(f"/api/projects/{other['id']}/kb/documents").status_code == 403
