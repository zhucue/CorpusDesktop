"""P8 method appendix (contracts/p8.md §六): statistics result + sampling layer → appendix and DOCX."""

import io
import uuid
import zipfile
from pathlib import Path

import pytest
from docx import Document as DocxDocument
from docx.oxml.ns import qn
from fastapi.testclient import TestClient

from tests.api.conftest import drain, upload

TEXT = "Language is a system.\nThe language of science."
SAMPLE = {
    "query": '"language"',
    "n": 2,
    "seed": 7,
    "total_hits": 2,
    "created_at": "2026-11-05T10:00:00Z",
}
SUMMARY = {
    "total_hits": 2,
    "sampled": 2,
    "coded": 2,
    "rejected": 0,
    "labels": [
        {
            "label": "名词",
            "count": 2,
            "pct": 1.0,
            "ci_low": 0.342,
            "ci_high": 1.0,
            "estimate": 2,
        }
    ],
}


@pytest.fixture
def corpus(owner, project):
    from services.api.db import transaction
    from services.api.models import Corpus

    c = owner.post(
        f"/api/projects/{project['id']}/corpora",
        json={"name": "作文", "language": "en"},
    ).json()
    upload(owner, c["id"], {"a.txt": TEXT})
    drain()
    with transaction() as db:
        db.get(Corpus, uuid.UUID(c["id"])).meta = {
            "license": "CC BY 4.0",
            "attribution": "某课题组",
            "version": "1",
        }
    return c


def make_stat(project, corpus, owner):
    from services.api.db import transaction
    from services.api.models import StatResult

    with transaction() as db:
        stat = StatResult(
            project_id=uuid.UUID(project["id"]),
            method="frequency",
            params={
                "method": "frequency",
                "scope": {"corpus_id": corpus["id"]},
                "unit": "word",
                "parts": "document",
                "dispersion": True,
                "min_freq": 1,
                "top": 200,
                "exclude_punct": True,
            },
            scope={"corpus_id": corpus["id"], "subcorpus_id": None, "name": "作文"},
            index_version="v1",
            totals={"tokens": 8, "sentences": 2, "documents": 1, "parts": 1},
            columns=[
                {"key": k, "label": k, "type": "number"}
                for k in (
                    "item",
                    "freq",
                    "per_million",
                    "range",
                    "dp",
                    "dp_norm",
                    "juilland_d",
                )
            ],
            rows_path=str(Path("missing.json")),
            row_count=0,
            created_by=uuid.UUID(owner.user_id),
        )
        db.add(stat)
        db.flush()
        return str(stat.id)


@pytest.fixture
def sample_layer(owner, project, corpus, monkeypatch):
    from services.api import methods, spans
    from services.api.db import transaction
    from services.api.models import AnnotationLayer

    sets = owner.get("/api/label-sets").json()["items"]
    label_set = next(s for s in sets if s["kind"] == "span")
    r = owner.post(
        f"/api/projects/{project['id']}/layers",
        json={
            "corpus_id": corpus["id"],
            "kind": "span",
            "name": "抽样：language",
            "label_set_id": label_set["id"],
        },
    )
    assert r.status_code == 200, r.text
    drain()
    layer_id = r.json()["id"]
    sample = {**SAMPLE, "scope": {"corpus_id": corpus["id"]}}
    if hasattr(AnnotationLayer, "meta"):  # 0009_layer_meta (implementer Q)
        with transaction() as db:
            db.get(AnnotationLayer, uuid.UUID(layer_id)).meta = {"sample": sample}
    else:
        real = methods._sample

        def fake(db, layer, user, corpora):
            layer.meta = {"sample": sample}
            return real(db, layer, user, corpora)

        monkeypatch.setattr(methods, "_sample", fake)
    # the appendix writes Q's summary (spans.sample_summary) as given; its numbers are tested with samples
    monkeypatch.setattr(
        spans, "sample_summary", lambda layer_id, user, db: SUMMARY, raising=False
    )
    return {"id": layer_id, "label_set": label_set}


def test_appendix_stat_and_sample_layer(
    owner, project, corpus, sample_layer, member, make_user
):
    stat_id = make_stat(project, corpus, owner)
    url = f"/api/projects/{project['id']}/method-appendix"
    body = {"stat_ids": [stat_id], "layer_ids": [sample_layer["id"]], "style": "apa"}
    r = owner.post(url, json=body)
    assert r.status_code == 200, r.text
    out = r.json()
    md = out["markdown"]
    # corpus size, license, index version; tool and platform versions
    assert (
        "**作文**（语言 en）：1 篇文档，2 句" in md
        and "许可：CC BY 4.0" in md
        and "索引版本：v" in md
    )
    assert (
        "Stanza" in md
        and "CWB）3.5.0" in md
        and "平台：语料检索、分析与标注研究平台 dev" in md
    )
    # statistics parameters and formula references
    assert "### 3.1 频次" in md and "部分 每篇文档" in md and "部分数 1" in md
    assert (
        "DP = ½ Σ|vᵢ − sᵢ|" in md
        and "（Gries 2008）" in md
        and "（Juilland & Chang-Rodríguez 1964）" in md
    )
    # sampling layer: label set, method, coding summary
    assert f"标签集：{sample_layer['label_set']['name']}" in md
    assert "按随机种子 7 等概率无放回抽取 2 条" in md and "范围 作文" in md
    assert "已编码 2 / 抽样 2" in md and "（Wilson 1927）" in md
    cites = out["citations"]
    assert any(c.startswith("Gries, S. Th. (2008).") for c in cites)
    assert any(c.startswith("Wilson, E. B. (1927).") for c in cites)
    assert not any(
        c.startswith("作文") for c in cites
    )  # project corpora are not cited as data sets
    assert cites[-1].startswith("语料检索、分析与标注研究平台 (Version dev)")

    # DOCX: opens with python-docx, headings in 宋体, no shading
    r = owner.post(url, params={"format": "docx"}, json=body)
    assert r.status_code == 200, r.text
    assert r.headers["content-type"].startswith("application/vnd.openxmlformats")
    doc = DocxDocument(io.BytesIO(r.content))
    heads = [p for p in doc.paragraphs if p.style.name.startswith("Heading")]
    assert heads[0].text == "方法附录"
    for name in ("Heading 1", "Heading 2", "Heading 3", "Normal"):
        fonts = doc.styles[name].element.rPr.rFonts
        assert (
            fonts.get(qn("w:eastAsia")) == "宋体" and fonts.get(qn("w:ascii")) == "宋体"
        )
    with zipfile.ZipFile(io.BytesIO(r.content)) as z:
        assert "w:shd" not in z.read("word/document.xml").decode("utf-8")
    text = "\n".join(p.text for p in doc.paragraphs)
    assert "DP = ½ Σ|vᵢ − sᵢ|" in text and "Wilson, E. B. (1927)" in text
    assert doc.tables and doc.tables[0].cell(0, 0).text == "标签"

    # viewers read; non-members get 404; other projects' results are not found
    viewer = member("viewer")
    assert viewer.post(url, json=body).status_code == 200
    stranger = make_user("stranger@example.edu")
    assert stranger.post(url, json=body).status_code == 404
    other = owner.post("/api/projects", json={"name": "另一个"}).json()
    r = owner.post(f"/api/projects/{other['id']}/method-appendix", json=body)
    assert r.status_code == 404 and r.json()["error"]["code"] == "NOT_FOUND"


def test_appendix_searches_evidence_and_bearer(owner, project, corpus):
    from services.api.main import app

    stat_id = make_stat(project, corpus, owner)
    scope = {"corpus_id": corpus["id"]}
    for ev in (
        {
            "kind": "stat_row",
            "ref": {"stat_id": stat_id, "row_key": "language"},
            "text": "language · 2",
            "source": "频次 · 作文",
        },
        {
            "kind": "hit",
            "ref": {"search_query": '"language"', "scope": scope},
            "text": "The language of science.",
            "source": "作文",
        },
        {"kind": "text", "ref": {}, "text": "随手记", "source": "笔记"},
    ):
        r = owner.post(f"/api/projects/{project['id']}/evidence", json=ev)
        assert r.status_code == 200, r.text
    token = owner.post(
        "/api/auth/agent-token", json={"project_id": project["id"]}
    ).json()["token"]
    agent = TestClient(app, headers={"Authorization": f"Bearer {token}"})
    r = agent.post(
        f"/api/projects/{project['id']}/method-appendix", json={"evidence": True}
    )
    assert r.status_code == 200, r.text
    md = r.json()["markdown"]
    assert "### 4.1 频次" in md  # stat row → its statistics result
    assert (
        '1. 查询式 `"language"`；范围：作文；命中 2 次，2 句，1 篇文档' in md
    )  # hit → its query, counted now
    assert "随手记" not in md

    r = owner.post(
        f"/api/projects/{project['id']}/method-appendix",
        json={"searches": [{"query": "[", "scope": scope}], "style": "gbt7714"},
    )
    assert r.status_code == 200, r.text
    assert "计数失败" in r.json()["markdown"]
    assert r.json()["citations"][-1].startswith("语料检索、分析与标注研究平台[CP/OL]")


def test_appendix_only_describes_this_project(owner, project, corpus, make_user):
    """Another project's statistics, layers, subcorpora and private corpora are 404 and never named, even for a
    user who belongs to both projects; evidence pointing elsewhere is left out."""
    from services.api.db import transaction
    from services.api.models import (
        AnnotationLayer,
        Corpus,
        LabelSet,
        StatResult,
        Subcorpus,
    )

    other = owner.post("/api/projects", json={"name": "另一个"}).json()
    oid, uid = uuid.UUID(other["id"]), uuid.UUID(owner.user_id)
    with transaction() as db:
        secret = Corpus(
            project_id=oid,
            name="机密语料",
            language="en",
            status="ready",
            index_version="v9",
            stats={"documents": 1, "sentences": 1, "tokens": 1},
            meta={},
        )
        db.add(secret)
        db.flush()
        sub = Subcorpus(
            project_id=oid,
            corpus_id=secret.id,
            name="机密子库",
            filter={"genre": "x"},
            created_by=uid,
        )
        stat = StatResult(
            project_id=oid,
            method="frequency",
            params={},
            scope={
                "corpus_id": str(secret.id),
                "subcorpus_id": None,
                "name": "机密语料",
            },
            index_version="v9",
            totals={},
            columns=[],
            rows_path="missing.json",
            row_count=0,
            created_by=uid,
        )
        label_set = db.query(LabelSet).filter(LabelSet.kind == "span").first()
        layer = AnnotationLayer(
            project_id=oid,
            corpus_id=secret.id,
            kind="span",
            name="机密层",
            label_set_id=label_set.id,
            source_model="manual",
            progress={},
            annotators=[],
            created_by=uid,
        )
        db.add_all([sub, stat, layer])
        db.flush()
        ids = {
            "corpus": str(secret.id),
            "sub": str(sub.id),
            "stat": str(stat.id),
            "layer": str(layer.id),
        }

    url = f"/api/projects/{project['id']}/method-appendix"
    for body in (
        {"stat_ids": [ids["stat"]]},
        {"layer_ids": [ids["layer"]]},
        {"searches": [{"query": '"a"', "scope": {"subcorpus_id": ids["sub"]}}]},
        {"searches": [{"query": '"a"', "scope": {"corpus_id": ids["corpus"]}}]},
        {
            "searches": [
                {"query": '"a"', "scope": {"corpus_id": ids["corpus"], "filter": {}}}
            ]
        },
    ):
        r = owner.post(url, json=body)
        assert r.status_code == 404, (body, r.text)
        assert "机密" not in r.text
        r = owner.post(url, params={"format": "docx"}, json=body)
        assert r.status_code == 404

    for ref in (
        {"search_query": '"a"', "scope": {"subcorpus_id": ids["sub"]}},
        {"search_query": '"a"', "scope": {"corpus_id": ids["corpus"]}},
        {"stat_id": ids["stat"], "row_key": "a"},
    ):
        kind = "stat_row" if "stat_id" in ref else "hit"
        owner.post(
            f"/api/projects/{project['id']}/evidence",
            json={"kind": kind, "ref": ref, "text": "a", "source": "外部"},
        )
    r = owner.post(url, json={"evidence": True})
    assert r.status_code == 200, r.text
    assert "机密" not in r.json()["markdown"]
    md = r.json()["markdown"]
    # no corpus, search or statistics section
    assert "## 1 处理工具" in md and "## 2 参考文献" in md
