"""P10 statistics through the api and worker with the real CWB engine (contracts/p10.md §一~§五): text metrics,
vocabulary lists and level profiles, tidy export, comparison and Word Sketch."""

import csv
import io
import json
import math
import shutil
import zipfile

import pytest
from openpyxl import load_workbook

from engine import cwb
from tests.api.conftest import drain, upload

pytestmark = pytest.mark.skipif(not shutil.which("cqp"), reason="CWB not installed")

NAMES = ("build", "search", "query_rows", "prefix_rows", "hits")
REAL = {n: getattr(cwb, n) for n in NAMES}
LEMMAS = {"makes": "make", "made": "make", "takes": "take", "decisions": "decision"}
EN_A = "I make decisions\nShe makes decisions\nThey make mistakes\nWe take decisions"
EN_B = "He takes notes\nYou make plans\nThey take decisions"
HSK = "词,等级\n我们,HSK 1\n研究,HSK 3\n语言,HSK 2\n文化,HSK 3\n"


def parse3(sentence):
    """Three-token sentences: subject ← verb (root) → object."""
    for i, t in enumerate(sentence.tokens):
        t.head, t.deprel = (
            [(2, "nsubj"), (0, "root"), (2, "obj")][i] if i < 3 else (2, "dep")
        )


@pytest.fixture
def real(monkeypatch, fake_engine):
    for name in NAMES:
        monkeypatch.setattr(cwb, name, REAL[name])
    from engine import nlp

    def annotate(doc, progress=None):
        fake_engine.annotate(doc)
        for s in doc.sentences:
            for t in s.tokens:
                t.pos, t.lemma = "NOUN", LEMMAS.get(t.form.lower(), t.form.lower())
            if doc.language == "en":
                parse3(s)

    monkeypatch.setattr(nlp, "annotate", annotate)
    monkeypatch.setattr(
        nlp, "annotate_many", lambda docs, progress=None: [annotate(d) for d in docs]
    )


def make_corpus(client, project, name, language, files):
    c = client.post(
        f"/api/projects/{project['id']}/corpora",
        json={"name": name, "language": language},
    ).json()
    for fname, (text, meta) in files.items():
        upload(client, c["id"], {fname: text}, metadata=json.dumps(meta))
    drain()
    assert client.get(f"/api/corpora/{c['id']}").json()["status"] == "ready"
    return c


@pytest.fixture
def en(real, owner, project):
    return make_corpus(
        owner,
        project,
        "英文",
        "en",
        {
            "a.txt": (EN_A, {"genre": "news", "year": 2001}),
            "b.txt": (EN_B, {"genre": "fiction", "year": 2010}),
        },
    )


@pytest.fixture
def zh(real, owner, project):
    return make_corpus(
        owner,
        project,
        "中文作文",
        "zh",
        {"z.txt": ("我们 研究 语言\n他们 研究 文化\n我们 喜欢 音乐", {"grade": 3})},
    )


def run_stat(client, method, body):
    r = client.post(f"/api/stats/{method}", json=body)
    assert r.status_code == 200, r.text
    drain()
    job = client.get(f"/api/jobs/{r.json()['id']}").json()
    assert job["state"] == "succeeded", job
    return client.get(f"/api/stats/{job['result']['stat_id']}").json()


def search(client, body):
    r = client.post("/api/search", json={"page_size": 1, **body})
    assert r.status_code == 200, r.text
    return r.json()["counts"]


def error(r, status, code):
    assert r.status_code == status and r.json()["error"]["code"] == code, r.text


def test_text_metrics(owner, en):
    scope = {"corpus_id": en["id"]}
    stat = run_stat(owner, "text_metrics", {"scope": scope, "group_by": "genre"})
    keys = [c["key"] for c in stat["columns"]]
    assert keys[:3] == ["title", "language", "group"] and "mtld" in keys
    rows = {r["values"]["title"]: r["values"] for r in stat["rows"]}
    a = rows["a"]
    assert a["words"] == 12 and a["sentences"] == 4 and a["group"] == "news"
    assert a["ttr"] == pytest.approx(9 / 12)
    assert a["sttr"] is None and a["mtld"] is None  # fewer than 100 words
    assert a["mean_dependency_distance"] == pytest.approx(1)
    assert a["flesch_reading_ease"] is not None
    groups = {g["value"]: g for g in stat["totals"]["groups"]["ttr"]}
    assert groups["news"]["documents"] == 1 and groups["news"]["sd"] is None
    assert stat["totals"]["notes"] and stat["totals"]["tokens"] == 21
    only = run_stat(owner, "text_metrics", {"scope": scope, "metrics": ["ttr"]})
    assert [c["key"] for c in only["columns"]] == ["title", "language", "ttr"]
    error(
        owner.post(
            "/api/stats/text_metrics", json={"scope": scope, "group_by": "nope"}
        ),
        422,
        "INVALID_FIELD",
    )
    error(
        owner.post("/api/stats/text_metrics", json={"scope": scope, "metrics": ["x"]}),
        422,
        "VALIDATION_ERROR",
    )
    r = owner.post(f"/api/stats/{stat['id']}/export", json={"format": "csv"})
    drain()
    text = owner.get(f"/api/jobs/{r.json()['id']}/download").content.decode("utf-8-sig")
    assert "文本指标" in text and "TTR" in text


def test_vocab_lists_and_profiles(owner, member, project, en, zh, make_user):
    base = f"/api/projects/{project['id']}/vocab-lists"
    items = owner.get(base).json()["items"]
    ngsl = items[0]
    assert ngsl["builtin"] and ngsl["name"] == "NGSL 1.2" and ngsl["entries"] == 2809
    assert ngsl["license"] == "CC BY-SA 4.0" and len(ngsl["levels"]) == 3

    files = {"file": ("hsk.csv", HSK.encode(), "text/csv")}
    form = {"name": "HSK 节选", "language": "zh"}
    viewer = member("viewer")
    error(viewer.post(base, files=files, data=form), 403, "FORBIDDEN")
    error(member("annotator").post(base, files=files, data=form), 403, "FORBIDDEN")
    r = owner.post(base, files=files, data=form)
    assert r.status_code == 201, r.text
    hsk = r.json()
    assert hsk["levels"] == ["HSK 1", "HSK 2", "HSK 3"] and hsk["entries"] == 4
    bad = owner.post(
        base, files={"file": ("x.csv", b"only-one-column\n", "text/csv")}, data=form
    )
    error(bad, 422, "INVALID_FILE")

    scope = {"corpus_id": zh["id"]}
    stat = run_stat(owner, "vocab_profile", {"scope": scope, "list_id": hsk["id"]})
    rows = {r["key"]: r for r in stat["rows"]}
    assert stat["totals"]["words"] == 9
    assert (
        rows["HSK 1"]["values"]["tokens"] == 2
        and rows["HSK 3"]["values"]["tokens"] == 3
    )
    assert rows["表外"]["values"]["types"] == 3  # 他们 喜欢 音乐
    assert rows["HSK 3"]["values"]["coverage"] == pytest.approx(100 / 3)
    for key, r in rows.items():
        got = search(owner, {"scope": r["search_scope"], "query": r["search_query"]})
        assert got["hits"] == r["values"]["tokens"], key
    assert stat["params"]["vocab_list"]["name"] == "HSK 节选"
    by_doc = run_stat(
        owner, "vocab_profile", {"scope": scope, "list_id": hsk["id"], "by": "document"}
    )
    assert by_doc["rows"][0]["values"]["level_1"] == pytest.approx(200 / 9)

    en_stat = run_stat(
        owner,
        "vocab_profile",
        {"scope": {"corpus_id": en["id"]}, "list_id": ngsl["id"]},
    )
    assert sum(r["values"]["tokens"] for r in en_stat["rows"]) == 21
    assert en_stat["params"]["vocab_list"]["builtin"]

    other = make_user("other@example.edu")
    theirs = other.post("/api/projects", json={"name": "别人"}).json()
    error(other.get(base), 404, "NOT_FOUND")
    their_list = other.post(
        f"/api/projects/{theirs['id']}/vocab-lists", files=files, data=form
    ).json()
    error(
        owner.post(
            "/api/stats/vocab_profile",
            json={"scope": scope, "list_id": their_list["id"]},
        ),
        404,
        "NOT_FOUND",
    )
    error(owner.delete(f"/api/vocab-lists/{ngsl['id']}"), 403, "FORBIDDEN")
    error(viewer.delete(f"/api/vocab-lists/{hsk['id']}"), 403, "FORBIDDEN")
    assert owner.delete(f"/api/vocab-lists/{hsk['id']}").status_code == 204
    assert [i["id"] for i in owner.get(base).json()["items"]] == [ngsl["id"]]


def tidy(client, body):
    from services.api.storage import export_path

    fmt = "xlsx" if body.get("format") == "xlsx" else "zip"

    r = client.post("/api/stats/tidy_export", json=body)
    assert r.status_code == 200, r.text
    drain()
    job = client.get(f"/api/jobs/{r.json()['id']}").json()
    assert job["state"] == "succeeded", job
    return job, export_path(job["id"], fmt)


def test_tidy_export(owner, en):
    scope = {"corpus_id": en["id"]}
    queries = ["decisions", "make|makes"]
    job, path = tidy(owner, {"scope": scope, "queries": queries, "metrics": True})
    assert job["result"]["filename"].endswith(".zip")
    with zipfile.ZipFile(path) as z:
        assert sorted(z.namelist()) == ["tidy_data.codebook.csv", "tidy_data.csv"]
        data = list(
            csv.DictReader(io.StringIO(z.read("tidy_data.csv").decode("utf-8")))
        )
        book = list(
            csv.DictReader(
                io.StringIO(z.read("tidy_data.codebook.csv").decode("utf-8"))
            )
        )
    header = list(data[0])
    assert header[:5] == ["document_id", "title", "language", "meta_genre", "meta_year"]
    assert header[5:11] == [
        "tokens",
        "sentences",
        "q1_hits",
        "q1_pm",
        "q2_hits",
        "q2_pm",
    ]
    assert "mtld" in header and [b["column"] for b in book] == header
    assert {b["column"]: b["query"] for b in book}["q2_pm"] == "make|makes"
    assert len(data) == 2
    for i, q in enumerate(queries, 1):
        assert (
            sum(int(r[f"q{i}_hits"]) for r in data)
            == search(owner, {"scope": scope, "query": q})["hits"]
        )
    a = next(r for r in data if r["title"] == "a")
    assert float(a["q1_pm"]) == pytest.approx(3 / 12 * 1e6)
    assert a["meta_genre"] == "news" and a["words"] == "12"

    _, xlsx = tidy(owner, {"scope": scope, "queries": ["decisions"], "format": "xlsx"})
    wb = load_workbook(xlsx)
    assert wb.sheetnames == ["data", "codebook"]
    assert [c.value for c in wb["data"][1]][-2:] == ["q1_hits", "q1_pm"]
    assert wb["data"][1][0].font.name == "宋体"
    for body in (
        {"queries": ["a $"]},
        {"queries": ["x"] * 11},
    ):
        r = owner.post("/api/stats/tidy_export", json={"scope": scope, **body})
        assert r.status_code == 422, r.text


def test_compare(owner, en, project):
    news = {"corpus_id": en["id"], "filter": {"genre": "news"}}
    fiction = {"corpus_id": en["id"], "filter": {"genre": "fiction"}}
    items = [
        {"label": "新闻", "scope": news, "query": "decisions"},
        {"label": "小说", "scope": fiction, "query": "decisions"},
    ]
    stat = run_stat(owner, "compare", {"items": items, "test": "mann_whitney"})
    a, b = (r["values"] for r in stat["rows"])
    assert (a["hits"], a["tokens"], b["hits"], b["tokens"]) == (3, 12, 1, 9)
    assert a["doc_freq_pct"] == 100 and a["documents"] == 1
    e1, e2 = 12 * 4 / 21, 9 * 4 / 21
    ll = 2 * (3 * math.log(3 / e1) + 1 * math.log(1 / e2))
    assert stat["totals"]["comparison"]["ll"] == pytest.approx(ll)
    assert stat["totals"]["comparison"]["log_ratio"] == pytest.approx(
        math.log2((3 / 12) / (1 / 9))
    )
    test = stat["totals"]["test"]
    assert test["method"] == "mann_whitney" and test["n1"] == test["n2"] == 1
    for r in stat["rows"]:
        got = search(owner, {"scope": r["search_scope"], "query": r["search_query"]})
        assert got["hits"] == r["values"]["hits"]
    whole = {"corpus_id": en["id"]}
    by_year = run_stat(
        owner,
        "compare",
        {
            "items": [
                {"label": "decisions", "scope": whole, "query": "decisions"},
                {"label": "take", "scope": whole, "query": "take|takes"},
            ],
            "by": "year",
            "test": "spearman",
        },
    )
    assert [r["values"]["value"] for r in by_year["rows"]] == [2001, 2010]
    row = by_year["rows"][0]
    assert row["values"]["hits_1"] == 3 and row["values"]["hits_2"] == 1
    s = row["searches"][1]
    assert s["search_scope"] == {"corpus_id": en["id"], "filter": {"year": 2001}}
    assert (
        search(owner, {"scope": s["search_scope"], "query": s["search_query"]})["hits"]
        == row["values"]["hits_2"]
    )
    assert [t["n"] for t in by_year["totals"]["test"]["items"]] == [2, 2]
    for body in (
        {"items": items[:1]},
        {"items": items * 2, "test": "mann_whitney"},
        {"items": items, "test": "spearman"},
        {"items": items, "by": "genre", "test": "spearman"},
        {"items": items, "by": "nope"},
    ):
        r = owner.post("/api/stats/compare", json=body)
        assert r.status_code == 422, (body, r.text)


def test_word_sketch_english_system_dependencies(owner, en):
    scope = {"corpus_id": en["id"]}
    stat = run_stat(
        owner, "word_sketch", {"scope": scope, "lemma": "make", "min_freq": 1, "top": 1}
    )
    rels = {r["key"]: r for r in stat["totals"]["relations"]}
    assert rels["object"]["freq"] == 4 and rels["subject"]["freq"] == 4
    objs = [r for r in stat["rows"] if r["values"]["relation"] == "object"]
    assert (
        len(objs) == 1 and objs[0]["values"]["collocate"] == "decision"
    )  # top 1 per relation
    assert len(stat["rows"]) == len(rels)  # GET keeps every relation's rows
    q = objs[0]["search_query"]
    assert q == '"decisions"{dep=obj} +"make"|"makes"'
    assert (
        search(owner, {"scope": scope, "query": q})["hits"] >= objs[0]["values"]["freq"]
    )
    diff = run_stat(
        owner,
        "sketch_diff",
        {"scope": scope, "lemma_a": "make", "lemma_b": "take", "min_freq": 1},
    )
    by = {
        (r["values"]["relation"], r["values"]["collocate"]): r["values"]
        for r in diff["rows"]
    }
    assert by[("object", "decision")]["group"] == "common"
    assert by[("object", "mistakes")]["group"] == "a"
    assert by[("object", "notes")]["group"] == "b"
    error(
        owner.post(
            "/api/stats/sketch_diff",
            json={"scope": scope, "lemma_a": "make", "lemma_b": "Make"},
        ),
        422,
        "VALIDATION_ERROR",
    )


def test_word_sketch_chinese_needs_a_dependency_layer(owner, project, zh, monkeypatch):
    from engine import nlp
    from tests.api.test_annotations import make_layer

    scope = {"corpus_id": zh["id"]}
    error(
        owner.post("/api/stats/word_sketch", json={"scope": scope, "lemma": "研究"}),
        422,
        "NO_DEPENDENCIES",
    )
    monkeypatch.setattr(
        nlp, "annotate_dependencies_zh", lambda doc: [parse3(s) for s in doc.sentences]
    )
    layer = make_layer(owner, project, zh, "dep")
    assert layer["status"] == "ready"
    stat = run_stat(
        owner, "word_sketch", {"scope": scope, "lemma": "研究", "min_freq": 1}
    )
    assert stat["params"]["layers"]["dep"] == layer["id"]
    got = {(r["values"]["relation"], r["values"]["collocate"]) for r in stat["rows"]}
    assert {
        ("subject", "我们"),
        ("subject", "他们"),
        ("object", "语言"),
        ("object", "文化"),
    } <= got
    assert all(r["search_layers"] == {"dep": layer["id"]} for r in stat["rows"])


def test_pure_attribute_queries_project_scope_and_formulas(
    owner, project, en, zh, make_user
):
    """Whole `{…}` queries are counted in PostgreSQL (compare, tidy export); scopes of one comparison stay in
    one project; a list must match the corpus language; spreadsheet formulas are written as text."""
    adj = make_corpus(
        owner,
        project,
        "形容词",
        "en",
        {
            "x.txt": (
                "a big house\nthe large dog\nso big a deal",
                {"note": "=HYPERLINK(1)"},
            ),
            "y.txt": ("big big words\nlarge rooms here", {"note": "-plain"}),
        },
    )
    scope = {"corpus_id": adj["id"]}
    items = [
        {"label": "big", "scope": scope, "query": "{lemma=big}"},
        {"label": "large", "scope": scope, "query": "{lemma=large}"},
    ]
    stat = run_stat(owner, "compare", {"items": items, "test": "mann_whitney"})
    got = [r["values"]["hits"] for r in stat["rows"]]
    assert got == [4, 2]
    for r in stat["rows"]:
        assert (
            search(owner, {"scope": r["search_scope"], "query": r["search_query"]})[
                "hits"
            ]
            == r["values"]["hits"]
        )
    assert stat["totals"]["test"]["n1"] == 2 and stat["totals"]["comparison"]["ll"] > 0

    _, path = tidy(owner, {"scope": scope, "queries": ["{lemma=big}"]})
    with zipfile.ZipFile(path) as z:
        data = list(
            csv.DictReader(io.StringIO(z.read("tidy_data.csv").decode("utf-8")))
        )
    assert [int(r["q1_hits"]) for r in data] == [2, 2]
    assert [r["meta_note"] for r in data] == ["'=HYPERLINK(1)", "'-plain"]
    _, xlsx = tidy(owner, {"scope": scope, "format": "xlsx"})
    notes = [row[3].value for row in load_workbook(xlsx)["data"].iter_rows(min_row=2)]
    assert notes == ["'=HYPERLINK(1)", "'-plain"]

    other = make_user("other@example.edu")
    theirs = other.post("/api/projects", json={"name": "别人"}).json()
    mine = other.post(
        f"/api/projects/{theirs['id']}/corpora", json={"name": "他的", "language": "en"}
    ).json()
    owner.put(
        f"/api/projects/{project['id']}/members/{other.user_id}",
        json={"role": "viewer"},
    )
    upload(other, mine["id"], {"m.txt": "big plans"})
    drain()
    cross = [
        items[0],
        {"label": "他", "scope": {"corpus_id": mine["id"]}, "query": "big"},
    ]
    error(
        other.post("/api/stats/compare", json={"items": cross}), 422, "VALIDATION_ERROR"
    )
    error(
        other.post(
            "/api/stats/keywords",
            json={"target": scope, "reference": {"corpus_id": mine["id"]}},
        ),
        422,
        "VALIDATION_ERROR",
    )
    ngsl = owner.get(f"/api/projects/{project['id']}/vocab-lists").json()["items"][0]
    r = owner.post(
        "/api/stats/vocab_profile",
        json={"scope": {"corpus_id": zh["id"]}, "list_id": ngsl["id"]},
    )
    error(r, 422, "VALIDATION_ERROR")
    assert r.json()["error"]["message"] == "词表语言与语料不一致"


def test_excel_safe():
    from services.worker.tasks import excel_safe

    for raw in ("=1+1", "+cmd", "-x", "@sum", "\tx", "\rx"):
        assert excel_safe(raw) == "'" + raw
    assert (
        excel_safe("a=b") == "a=b" and excel_safe(-3) == -3 and excel_safe(None) is None
    )
