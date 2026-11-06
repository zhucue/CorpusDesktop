"""P10 import (contracts/p10.md §七, §八) through the api and worker: PDF / XLSX / JSONL uploads with the real
parsers, duplicate skipping, the seven languages, model errors and the term-extraction language check.
NLP and CWB stay faked (tests/api/conftest.py)."""

import json
from pathlib import Path

import pytest
from sqlalchemy import func, select

from engine.parsers import parse as real_parse
from tests.api.conftest import drain, upload

IMP = Path(__file__).parents[1] / "fixtures" / "import"


@pytest.fixture
def real_parsers(monkeypatch):
    from engine import parsers

    monkeypatch.setattr(parsers, "parse", real_parse)


def _corpus(client, project, language="auto"):
    return client.post(
        f"/api/projects/{project['id']}/corpora",
        json={"name": "导入", "language": language},
    ).json()


def _send(client, corpus, files, **form):
    """files: {name: bytes}; runs the queue; returns the import job."""
    r = client.post(
        f"/api/corpora/{corpus['id']}/documents",
        files=[
            ("files", (name, body, "application/octet-stream"))
            for name, body in files.items()
        ],
        data=form,
    )
    assert r.status_code == 200, r.text
    drain()
    return client.get(f"/api/jobs/{r.json()['id']}").json()


def _docs(client, corpus):
    return client.get(f"/api/corpora/{corpus['id']}/documents").json()["items"]


def _index_jobs(corpus_id):
    from services.api.db import session
    from services.api.models import Job

    with session() as db:
        return db.scalar(
            select(func.count()).where(
                Job.kind == "index", Job.params["corpus_id"].astext == corpus_id
            )
        )


def test_pdf_upload(owner, project, real_parsers):
    c = _corpus(owner, project, "en")
    job = _send(owner, c, {"text-layer.pdf": (IMP / "text-layer.pdf").read_bytes()})
    assert job["state"] == "succeeded", job
    [doc] = _docs(owner, c)
    assert doc["title"] == "Reading Habits of Graduate Students"
    assert doc["metadata"]["pages"] == 2
    job = _send(owner, c, {"scanned.pdf": (IMP / "scanned.pdf").read_bytes()})
    assert job["state"] == "failed"
    assert job["error"] == {
        "code": "PARSE_ERROR",
        "message": "scanned.pdf：PDF 没有文字层（扫描件），暂不支持 OCR",
    }


def test_xlsx_duplicates_skipped_and_second_import_all_skipped(
    owner, project, real_parsers
):
    c = _corpus(owner, project)
    data = (IMP / "abstracts.xlsx").read_bytes()
    first = _send(owner, c, {"abstracts.xlsx": data})
    assert first["state"] == "succeeded", first
    # the fourth row repeats the first
    assert first["result"]["documents"] == 3
    assert first["result"]["skipped_duplicates"] == 1
    assert first["result"]["duplicates"] == ["abstracts.xlsx #4"]
    assert len(_docs(owner, c)) == 3
    indexed = _index_jobs(c["id"])
    assert owner.get(f"/api/corpora/{c['id']}").json()["status"] == "ready"

    again = _send(owner, c, {"abstracts.xlsx": data})
    assert again["state"] == "succeeded", again
    assert again["result"]["documents"] == 0
    assert again["result"]["skipped_duplicates"] == 4
    assert again["result"]["duplicates"][0] == "abstracts.xlsx #1"
    assert len(_docs(owner, c)) == 3
    assert _index_jobs(c["id"]) == indexed  # nothing new: the index is not rebuilt
    assert owner.get(f"/api/corpora/{c['id']}").json()["status"] == "ready"

    # whitespace and full-width differences still count as the same text
    from services.api.db import session
    from services.api.models import Document

    with session() as db:
        hashes = db.scalars(
            select(Document.content_hash).where(Document.corpus_id == c["id"])
        ).all()
    assert len(hashes) == 3 and all(hashes)
    copy = "  本文介绍在翻译课堂中使用平行语料库的做法。学生先检索原文中的难点词语，再比较多个译本的处理方式，最后写出自己的译文。\n"
    job = _send(owner, c, {"copy.txt": copy.encode()})
    assert job["result"]["skipped_duplicates"] == 1
    assert job["result"]["duplicates"] == ["copy.txt"]


def test_xlsx_sheet_and_jsonl_mapping(owner, project, real_parsers):
    c = _corpus(owner, project)
    mapping = {
        "text": ["摘要"],
        "title": "标题",
        "language": "语言",
        "metadata": ["年份"],
        "sheet": "2025",
    }
    job = _send(
        owner,
        c,
        {"abstracts.xlsx": (IMP / "abstracts.xlsx").read_bytes()},
        mapping=json.dumps(mapping, ensure_ascii=False),
    )
    assert job["state"] == "succeeded", job
    docs = sorted(_docs(owner, c), key=lambda d: d["title"])
    assert [(d["title"], d["language"], d["metadata"]) for d in docs] == [
        ("Hedging in student theses", "en", {"年份": 2025}),
        ("新闻标题的修辞", "zh", {"年份": 2025}),
    ]
    j = _corpus(owner, project)
    job = _send(owner, j, {"abstracts.jsonl": (IMP / "abstracts.jsonl").read_bytes()})
    assert job["state"] == "succeeded", job
    assert job["result"]["documents"] == 5 and job["result"]["skipped_duplicates"] == 1
    assert job["result"]["duplicates"] == ["abstracts.jsonl #4"]
    d = next(x for x in _docs(owner, j) if x["title"] == "Hedging in student theses")
    assert d["metadata"] == {"id": 5, "meta.year": 2025, "meta.genre": "thesis"}


def test_preview_xlsx_sheets_and_jsonl(owner):
    data = (IMP / "abstracts.xlsx").read_bytes()
    r = owner.post(
        "/api/imports/preview",
        files={"file": ("abstracts.xlsx", data)},
        data={"sheet": "2025"},
    )
    assert r.status_code == 200, r.text
    pv = r.json()
    assert pv["sheets"] == ["摘要", "2025"] and pv["defaults"]["sheet"] == "2025"
    assert len(pv["rows"]) == 2
    r = owner.post(
        "/api/imports/preview",
        files={"file": ("abstracts.jsonl", (IMP / "abstracts.jsonl").read_bytes())},
    )
    assert r.json()["defaults"]["text"] == ["body"]
    r = owner.post("/api/imports/preview", files={"file": ("a.pdf", b"%PDF")})
    assert r.status_code == 422 and r.json()["error"]["code"] == "UNSUPPORTED_FORMAT"


@pytest.mark.parametrize(
    ("name", "lang"),
    [
        ("lang-fr.txt", "fr"),
        ("lang-de.txt", "de"),
        ("lang-es.txt", "es"),
        ("lang-ru.txt", "ru"),
        ("lang-ja.txt", "ja"),
    ],
)
def test_five_languages_detected_at_import(owner, project, real_parsers, name, lang):
    c = _corpus(owner, project)
    job = _send(owner, c, {name: (IMP / name).read_bytes()}, language="auto")
    assert job["state"] == "succeeded", job
    assert [d["language"] for d in _docs(owner, c)] == [lang]
    corpus = owner.get(f"/api/corpora/{c['id']}").json()
    assert corpus["language"] == lang and corpus["meta"]["languages"] == [lang]


def test_upload_language_list(owner, project):
    c = _corpus(owner, project, "en")
    for lang in ("ja", "fr", "de", "es", "ru", "rus"):
        assert upload(owner, c["id"], {"a.txt": "x"}, language=lang).status_code == 200
    r = upload(owner, c["id"], {"a.txt": "x"}, language="ko")
    assert r.status_code == 422
    assert r.json()["error"] == {
        "code": "LANGUAGE_UNSUPPORTED",
        "message": "暂不支持该语言：ko（支持 zh、en、ja、fr、de、es、ru）",
    }
    r = upload(owner, c["id"], {"a.xlsx": "x", "b.jsonl": "x", "c.pdf": "x"})
    assert r.status_code == 200


def test_unrecognized_text_fails_with_hint(owner, project, real_parsers):
    c = _corpus(owner, project)
    text = (
        "Tänään sää oli kaunis ja lapset leikkivät pihalla. Äiti keittää kahvia keittiössä. "
        * 20
    )
    job = _send(owner, c, {"fi.txt": text.encode()})
    assert job["state"] == "failed"
    assert job["error"] == {
        "code": "LANGUAGE_UNSUPPORTED",
        "message": "fi：未识别语言，请指定（支持 zh、en、ja、fr、de、es、ru）",
    }


def test_model_download_failure(owner, project, monkeypatch):
    from engine import nlp

    def offline(docs, progress=None):
        raise nlp.ModelError("下载 fr 模型失败：network unreachable")

    monkeypatch.setattr(nlp, "annotate_many", offline)
    c = _corpus(owner, project, "fr")
    job = _send(owner, c, {"a.txt": b"Bonjour."})
    assert job["state"] == "failed"
    assert job["error"] == {
        "code": "MODEL_UNAVAILABLE",
        "message": "下载 fr 模型失败：network unreachable",
    }


def test_term_extraction_only_for_chinese_and_english(owner, project):
    pid = project["id"]
    fr = _corpus(owner, project, "fr")
    upload(owner, fr["id"], {"a.txt": "La traduction littéraire."})
    drain()
    body = {
        "source": "corpus",
        "scope": {"corpus_id": fr["id"]},
        "method": "pos_pattern",
    }
    r = owner.post(f"/api/projects/{pid}/kb/terms/extract", json=body)
    assert r.status_code == 422
    assert r.json()["error"] == {
        "code": "LANGUAGE_UNSUPPORTED",
        "message": "术语抽取的词性模式只支持中文与英文，暂不支持：fr",
    }
    en = _corpus(owner, project, "en")
    upload(owner, en["id"], {"a.txt": "Corpus linguistics."})
    drain()
    r = owner.post(
        f"/api/projects/{pid}/kb/terms/extract",
        json={**body, "scope": {"corpus_id": en["id"]}},
    )
    assert r.status_code == 200, r.text
    r = owner.post(
        f"/api/projects/{pid}/kb/terms/extract",
        json={**body, "scope": {"corpus_id": en["id"]}, "language": "de"},
    )
    assert r.status_code == 422


def test_concurrent_imports_of_the_same_text_keep_one(owner, project, monkeypatch):
    """Two workers importing the same text into one corpus at once: both pass the early duplicate check,
    the second one to write sees the first one's document under the corpus lock and skips its own."""
    import threading

    from engine import nlp
    from services.worker.main import run_once

    c = _corpus(owner, project, "en")
    for name in ("a.txt", "b.txt"):
        assert (
            upload(owner, c["id"], {name: "Same text in both files."}).status_code
            == 200
        )
    both_annotating = threading.Barrier(2, timeout=20)
    annotate = nlp.annotate_many

    def annotate_together(docs, progress=None):
        both_annotating.wait()  # both imports are past the check outside the lock
        return annotate(docs, progress)

    monkeypatch.setattr(nlp, "annotate_many", annotate_together)
    threads = [threading.Thread(target=run_once) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(60)
    monkeypatch.setattr(nlp, "annotate_many", annotate)
    drain()
    assert len(_docs(owner, c)) == 1
    jobs = [
        j
        for j in owner.get(f"/api/projects/{project['id']}/jobs").json()["items"]
        if j["kind"] == "import"
    ]
    assert sorted(j["state"] for j in jobs) == ["succeeded", "succeeded"]
    assert sorted(j["result"]["skipped_duplicates"] for j in jobs) == [0, 1]


def test_parallel_sides_skipped_only_together(owner, project, real_parsers):
    """A TMX whose English side is already in the corpus but whose French side is new is imported whole,
    so its alignments stay; the same TMX again is skipped whole."""
    c = _corpus(owner, project)
    tmx = (IMP / "en-fr.tmx").read_bytes()
    first = _send(owner, c, {"a.tmx": tmx})
    assert first["state"] == "succeeded", first
    assert first["result"]["documents"] == 3 and first["result"]["alignments"] > 0
    changed = tmx.replace(
        b"La traduction relie les cultures.",
        b"La traduction rapproche les cultures.",
    )
    second = _send(owner, c, {"b.tmx": changed})
    assert second["result"]["skipped_duplicates"] == 0
    assert second["result"]["documents"] == 3
    assert second["result"]["alignments"] == first["result"]["alignments"]
    again = _send(owner, c, {"c.tmx": changed})
    assert again["result"]["documents"] == 0
    assert again["result"]["skipped_duplicates"] == 3
    assert len(_docs(owner, c)) == 6
