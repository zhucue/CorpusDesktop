"""P8 statistics through the api and worker with the real CWB engine (contracts/p8.md §一~§四): breakdown,
dispersion, keyword effect sizes, translations, validation and exports."""

import csv
import io
import json
import shutil
import threading
import time

import pytest
from docx import Document as DocxDocument

from engine import cwb
from tests.api.conftest import drain, upload

pytestmark = pytest.mark.skipif(not shutil.which("cqp"), reason="CWB not installed")

NAMES = ("build", "search", "query_rows", "prefix_rows", "hits")
REAL = {n: getattr(cwb, n) for n in NAMES}
REAL_CQP = cwb._cqp_lines
TEXT_A = "The language of science is the language.\nA language of the people.\nScience rules."
TEXT_B = (
    "Grammar rules apply here.\nThe grammar of a language.\nLanguage again and again."
)
TMX = [
    "I translate books\t我 翻译 书",
    "She translated the book\t她 翻译 了 书",
    "The book is red\t书 是 红 的",
    "I like the translation\t我 喜欢 这个 翻译",
    "He reads books\t他 读 书",
    "translate this\t翻译 这个",
]


@pytest.fixture
def real(monkeypatch, fake_engine):
    for name in NAMES:
        monkeypatch.setattr(cwb, name, REAL[name])
    from engine import nlp

    def annotate(doc, progress=None):
        fake_engine.annotate(doc)
        for s in doc.sentences:
            for t in s.tokens:
                t.pos, t.lemma = "NOUN", t.form.lower()

    monkeypatch.setattr(nlp, "annotate", annotate)
    monkeypatch.setattr(
        nlp, "annotate_many", lambda docs, progress=None: [annotate(d) for d in docs]
    )


@pytest.fixture
def corpus(real, owner, project):
    c = owner.post(
        f"/api/projects/{project['id']}/corpora",
        json={"name": "作文", "language": "en"},
    ).json()
    upload(
        owner,
        c["id"],
        {"a.txt": TEXT_A},
        metadata=json.dumps({"genre": "news", "year": 2001}),
    )
    upload(
        owner,
        c["id"],
        {"b.txt": TEXT_B},
        metadata=json.dumps({"genre": "fiction", "year": 2010}),
    )
    drain()
    assert owner.get(f"/api/corpora/{c['id']}").json()["status"] == "ready"
    return c


@pytest.fixture
def parallel(real, owner, project):
    c = owner.post(
        f"/api/projects/{project['id']}/corpora",
        json={"name": "平行", "language": "zh"},
    ).json()
    upload(owner, c["id"], {"t.tmx": "\n".join(TMX)})
    drain()
    got = owner.get(f"/api/corpora/{c['id']}").json()
    assert got["status"] == "ready" and got["parallel"]
    return c


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


def test_breakdown(owner, corpus):
    scope = {"corpus_id": corpus["id"]}
    hits = search(owner, {"scope": scope, "query": "language"})["hits"]
    words = run_stat(
        owner, "breakdown", {"scope": scope, "query": "language", "by": "word"}
    )
    assert words["totals"]["hits"] == hits
    assert sum(r["values"]["hits"] for r in words["rows"]) == hits
    assert [c["key"] for c in words["columns"]] == [
        "item",
        "hits",
        "pct",
        "per_million",
    ]
    for by in ("left1", "right1"):
        stat = run_stat(
            owner, "breakdown", {"scope": scope, "query": "language", "by": by}
        )
        for r in stat["rows"]:
            if r["search_query"]:
                got = search(
                    owner, {"scope": r["search_scope"], "query": r["search_query"]}
                )
                assert got["hits"] == r["values"]["hits"], r
    meta = run_stat(
        owner, "breakdown", {"scope": scope, "query": "language", "by": "meta:year"}
    )
    for r in meta["rows"]:
        assert r["search_scope"] == {
            "corpus_id": corpus["id"],
            "filter": {"year": int(r["key"])},
        }
        got = search(owner, {"scope": r["search_scope"], "query": r["search_query"]})
        assert got["hits"] == r["values"]["hits"]
    bad = [
        ({"query": "language", "by": "left2"}, "VALIDATION_ERROR"),
        ({"query": "language", "by": "meta:nope"}, "INVALID_FIELD"),
        ({"query": "{lemma=language}", "by": "word"}, "QUERY_INVALID"),
        ({"query": "a $", "by": "word"}, "QUERY_INVALID"),
    ]
    for body, code in bad:
        r = owner.post("/api/stats/breakdown", json={"scope": scope, **body})
        assert r.status_code == 422 and r.json()["error"]["code"] == code, r.text


def test_dispersion_keywords_collocations_and_exports(owner, corpus, project):
    scope = {"corpus_id": corpus["id"]}
    freq = run_stat(owner, "frequency", {"scope": scope})
    keys = [c["key"] for c in freq["columns"]]
    assert keys[-5:] == ["range", "range_pct", "dp", "dp_norm", "juilland_d"]
    assert freq["totals"]["parts"] == 2
    row = next(r for r in freq["rows"] if r["key"] == "of")
    assert row["values"]["range"] == 2 == row["values"]["doc_freq"]
    seg = run_stat(owner, "frequency", {"scope": scope, "parts": "segments"})
    assert seg["totals"]["parts"] == 10
    by_genre = run_stat(owner, "frequency", {"scope": scope, "parts": "field:genre"})
    assert by_genre["totals"]["parts"] == 2
    off = run_stat(owner, "frequency", {"scope": scope, "dispersion": False})
    assert "dp" not in [c["key"] for c in off["columns"]]
    for body, code in (
        ({"parts": "field:nope"}, "INVALID_FIELD"),
        ({"parts": "chapters"}, "VALIDATION_ERROR"),
    ):
        r = owner.post("/api/stats/frequency", json={"scope": scope, **body})
        assert r.status_code == 422 and r.json()["error"]["code"] == code, r.text

    sub = owner.post(
        f"/api/projects/{project['id']}/subcorpora",
        json={"name": "新闻", "corpus_id": corpus["id"], "filter": {"genre": "news"}},
    ).json()
    other = owner.post(
        f"/api/projects/{project['id']}/subcorpora",
        json={
            "name": "小说",
            "corpus_id": corpus["id"],
            "filter": {"genre": "fiction"},
        },
    ).json()
    pair = {
        "target": {"subcorpus_id": sub["id"]},
        "reference": {"subcorpus_id": other["id"]},
    }
    neg = run_stat(
        owner,
        "keywords",
        {**pair, "direction": "negative", "min_freq": 1, "measure": "pct_diff"},
    )
    assert neg["rows"] and all(
        r["values"]["ref_pm"] > r["values"]["target_pm"] for r in neg["rows"]
    )
    assert {"pct_diff", "odds_ratio", "log_ratio_ci_low", "bonferroni"} <= {
        c["key"] for c in neg["columns"]
    }
    items = run_stat(
        owner, "keywords", {**pair, "items": ["science", "absent"], "min_freq": 50}
    )
    assert [r["key"] for r in items["rows"]] == ["science", "absent"]
    r = owner.post(
        "/api/stats/keywords", json={**pair, "items": [f"w{i}" for i in range(51)]}
    )
    assert r.status_code == 422

    coll = run_stat(
        owner,
        "collocations",
        {
            "scope": scope,
            "node": "language",
            "measures": ["delta_p", "mi3", "z"],
            "min_freq": 1,
        },
    )
    assert [c["key"] for c in coll["columns"]][3:] == [
        "mi3",
        "delta_p_node",
        "delta_p_coll",
        "z",
    ]

    job = owner.post(f"/api/stats/{freq['id']}/export", json={"format": "docx"}).json()
    drain()
    r = owner.get(f"/api/jobs/{job['id']}/download")
    assert r.status_code == 200
    text = "\n".join(p.text for p in DocxDocument(io.BytesIO(r.content)).paragraphs)
    assert "离散度部分 文档" in text and "DPnorm：" in text
    job = owner.post(f"/api/stats/{neg['id']}/export", json={"format": "csv"}).json()
    drain()
    rows = list(
        csv.reader(
            io.StringIO(
                owner.get(f"/api/jobs/{job['id']}/download").content.decode("utf-8-sig")
            )
        )
    )
    assert "方向 参照多于目标" in rows[0][0]
    assert {"%DIFF", "odds ratio", "Bonferroni 显著性"} <= set(
        next(r for r in rows if r and r[0] == "词")
    )


def test_translations(owner, parallel, corpus):
    scope = {"corpus_id": parallel["id"]}
    stat = run_stat(
        owner, "translations", {"scope": scope, "query": "翻译", "min_freq": 1}
    )
    totals = stat["totals"]
    assert (
        totals["target_language"] == "en" and stat["params"]["target_language"] == "en"
    )
    assert (
        totals["hit_sentences"],
        totals["aligned_sentences"],
        totals["unaligned"],
    ) == (4, 4, 0)
    rows = {r["key"]: r for r in stat["rows"]}
    assert "translate" in rows and "translation" in rows
    t = rows["translate"]
    assert t["values"]["cooc"] == 2 and t["values"]["target_freq"] == 2
    assert t["values"]["dice"] == pytest.approx(2 * 2 / (4 + 2))
    assert t["search_query"] == "翻译" and t["search_aligned"] == {
        "op": "+",
        "query": '"translate"',
    }
    got = search(
        owner, {"scope": scope, "query": "翻译", "aligned": t["search_aligned"]}
    )
    assert got["sentences"] == t["values"]["cooc"]

    job = owner.post(f"/api/stats/{stat['id']}/export", json={"format": "csv"}).json()
    drain()
    lines = list(
        csv.reader(
            io.StringIO(
                owner.get(f"/api/jobs/{job['id']}/download").content.decode("utf-8-sig")
            )
        )
    )
    head = next(i for i, r in enumerate(lines) if r and r[0] == "译文词")
    assert lines[head][-2:] == ["查询式", "译文条件"]
    assert any(r[-1] == '\'+"translate"' for r in lines[head + 1 :])

    lemma = run_stat(
        owner,
        "translations",
        {
            "scope": scope,
            "query": "翻译",
            "unit": "lemma",
            "measure": "ll",
            "min_freq": 1,
        },
    )
    assert any(
        r["search_aligned"]["query"] == "{lemma=translate}" for r in lemma["rows"]
    )
    bad = [
        ({"scope": {"corpus_id": corpus["id"]}, "query": "language"}, "NOT_PARALLEL"),
        (
            {"scope": scope, "query": "翻译", "target_language": "fr"},
            "VALIDATION_ERROR",
        ),
        ({"scope": scope, "query": "翻译", "measure": "mi"}, "VALIDATION_ERROR"),
    ]
    for body, code in bad:
        r = owner.post("/api/stats/translations", json=body)
        assert r.status_code == 422 and r.json()["error"]["code"] == code, r.text


def test_translations_merge_case(owner, parallel):
    """P11: The / the merge by default; the condition lists both spellings and reopens the counted sentences;
    case_sensitive keeps them apart; the export says which (contracts/p11.md §一)."""
    scope = {"corpus_id": parallel["id"]}
    body = {"scope": scope, "query": "红|了", "min_freq": 1}
    stat = run_stat(owner, "translations", body)
    rows = {r["key"]: r for r in stat["rows"]}
    assert "The" not in rows
    the = rows["the"]
    assert the["values"]["cooc"] == 2
    assert set(the["search_aligned"]["query"].split("|")) == {'"the"', '"The"'}
    got = search(
        owner, {"scope": scope, "query": "红|了", "aligned": the["search_aligned"]}
    )
    assert got["sentences"] == 2
    exact = run_stat(owner, "translations", {**body, "case_sensitive": True})
    rows = {r["key"]: r["values"]["cooc"] for r in exact["rows"]}
    assert rows.get("the") == 1 and rows.get("The") == 1

    job = owner.post(f"/api/stats/{stat['id']}/export", json={"format": "csv"}).json()
    drain()
    text = owner.get(f"/api/jobs/{job['id']}/download").content.decode("utf-8-sig")
    assert "区分大小写：否" in text.splitlines()[0]


def test_distribution_position_rows_search_their_part(owner, corpus):
    """B06: 回到例句 of a 文档位置 row searches that part only; its hits equal the row's."""
    for scope in (
        {"corpus_id": corpus["id"]},
        {"corpus_id": corpus["id"], "filter": {"year": 2001}},
    ):
        stat = run_stat(
            owner,
            "distribution",
            {"scope": scope, "query": "language", "field": "position", "bins": 4},
        )
        total = search(owner, {"scope": scope, "query": "language"})["hits"]
        assert stat["totals"]["hits"] == total
        assert len({r["values"]["hits"] for r in stat["rows"]}) > 1  # the parts differ
        for k, r in enumerate(stat["rows"]):
            assert r["search_scope"] == {
                "corpus_id": corpus["id"],
                "filter": scope.get("filter", {}),
                "position": {"bin": k, "bins": 4},
            }
            got = search(
                owner, {"scope": r["search_scope"], "query": r["search_query"]}
            )
            assert got["hits"] == r["values"]["hits"], r
    # the part applies to search and export only; statistics refuse it rather than count everything
    r = owner.post(
        "/api/stats/frequency",
        json={"scope": stat["rows"][0]["search_scope"], "unit": "word"},
    )
    assert r.status_code == 422 and r.json()["error"]["code"] == "VALIDATION_ERROR"


def test_position_cache_key():
    """B06: the cached result set of a search is per document-position part."""
    from services.api.search import Scope, search_key

    cid = "00000000-0000-0000-0000-000000000001"
    plain = search_key("[word='a']", {}, None, Scope(corpus_id=cid))
    parts = {
        search_key(
            "[word='a']",
            {},
            None,
            Scope(corpus_id=cid, position={"bin": k, "bins": n}),
        )
        for k, n in ((0, 4), (1, 4), (1, 5))
    }
    assert plain not in parts and len(parts) == 3
    assert all(k.startswith(plain) and "#position" in k for k in parts)


def position_stat(owner, corpus):
    return run_stat(
        owner,
        "distribution",
        {
            "scope": {"corpus_id": corpus["id"]},
            "query": "language",
            "field": "position",
            "bins": 4,
        },
    )


def test_position_search_waits_for_the_count(owner, corpus, monkeypatch):
    """B06: past COUNT_TIMEOUT a search with a position part shows no corpus-order prefix (it would be
    unfiltered or short); once the background count is done the page holds that part's hits."""
    from services.api import search as search_api

    stat = position_stat(owner, corpus)
    row = max(stat["rows"], key=lambda r: r["values"]["hits"])
    hold = threading.Event()

    def held(index_dir, key, commands, timeout, cancel=None):
        if timeout == search_api.FULL_TIMEOUT:
            assert hold.wait(30)
        return REAL_CQP(index_dir, key, commands, timeout, cancel)

    monkeypatch.setattr(cwb, "_cqp_lines", held)
    monkeypatch.setattr(search_api, "COUNT_TIMEOUT", 0.0001)
    req = {"scope": row["search_scope"], "query": row["search_query"]}
    first = owner.post("/api/search", json=req).json()
    assert first["counts"]["complete"] is False and first["items"] == []
    hold.set()
    polled = {**req, "search_id": first["search_id"]}
    deadline = time.monotonic() + 30
    while not (done := owner.post("/api/search", json=polled).json())["counts"][
        "complete"
    ]:
        assert time.monotonic() < deadline, done["counts"]
        time.sleep(0.05)
    assert done["counts"]["hits"] == row["values"]["hits"] > 0
    assert len(done["items"]) == row["values"]["hits"]


def test_position_export(owner, corpus):
    """B06: a search export with a position part has that part's hits and says so in its head line."""
    stat = position_stat(owner, corpus)
    for k, row in enumerate(stat["rows"]):
        job = owner.post(
            "/api/search/export",
            json={
                "scope": row["search_scope"],
                "query": row["search_query"],
                "format": "csv",
            },
        ).json()
        drain()
        done = owner.get(f"/api/jobs/{job['id']}").json()
        assert done["state"] == "succeeded", done
        assert done["result"]["rows"] == row["values"]["hits"]
        lines = list(
            csv.reader(
                io.StringIO(
                    owner.get(f"/api/jobs/{job['id']}/download").content.decode(
                        "utf-8-sig"
                    )
                )
            )
        )
        assert f"（文档位置 {k * 25}–{(k + 1) * 25}%）" in lines[0][0], lines[0]
        assert len(lines) - 3 == row["values"]["hits"]
