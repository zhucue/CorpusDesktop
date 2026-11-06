"""P10 statistics (contracts/p10.md §一、二、四、五) against the pure-Python reference (tests/golden/p10-stats.json),
from documents in memory and from a CWB index (engine.stats.documents / doc_hits)."""

import json
import random

import pytest
from engine_reference import load_docs
from stats_p10_reference import GOLDEN, with_meta

from engine import compare, cwb, metrics, query, sketch, stats, vocab
from engine.metrics import Doc

GOLD = json.loads(GOLDEN.read_text(encoding="utf-8"))
TOL = 1e-9


def close(a, b):
    if isinstance(a, float) or isinstance(b, float):
        return a is not None and b is not None and abs(a - b) <= TOL * max(1, abs(b))
    return a == b


def as_docs(docs):
    return [
        Doc(
            f"d{i}",
            d.title,
            d.language,
            d.metadata,
            [
                [(t.form, t.pos, t.lemma, t.head, t.deprel) for t in s.tokens]
                for s in d.sentences
            ],
        )
        for i, d in enumerate(docs)
    ]


@pytest.fixture(scope="module")
def mem():
    return as_docs(with_meta(load_docs()))


@pytest.fixture(scope="module")
def ud(tmp_path_factory):
    d = tmp_path_factory.mktemp("stats_p10")
    docs = with_meta(load_docs())
    cwb.build(d, "ud_en", docs, [f"d{i}" for i in range(len(docs))])
    return d, docs


def indexed(ud):
    """Documents as the worker builds them: tokens from the index, title / language / metadata alongside."""
    d, docs = ud
    by_id = {f"d{i}": doc for i, doc in enumerate(docs)}
    return [
        Doc(i, by_id[i].title, by_id[i].language, by_id[i].metadata, sents)
        for i, sents in stats.documents(stats.Scope(d, "ud_en"))
    ]


def test_golden_file_matches_reference():
    pytest.importorskip("scipy")
    from stats_p10_reference import golden

    assert json.loads(json.dumps(golden())) == GOLD


def check_metrics(docs):
    for case in GOLD["text_metrics"]:
        t = metrics.table(docs, group_by="part", window=case["window"])
        got = {r["key"]: r["values"] for r in t.rows}
        assert set(got) == set(case["documents"])
        for doc, want in case["documents"].items():
            for k, v in want.items():
                assert close(got[doc][k], v), (doc, k, got[doc][k], v)
        for k, groups in case["groups"].items():
            for g, w in zip(t.totals["groups"][k], groups):
                assert g["value"] == w["value"] and g["documents"] == w["documents"], k
                assert close(g["mean"], w["mean"]) and close(g["sd"], w["sd"]), (
                    k,
                    g,
                    w,
                )
        assert t.totals["documents"] == 16
        assert any("少于 100" in n for n in t.totals["notes"])


def check_vocab(docs):
    entries, levels = vocab.builtin()
    want = GOLD["vocab"]
    t = vocab.profile(docs, dict(entries), levels, "en")
    assert t.totals["words"] == want["words"]
    for r in t.rows:
        w = want["corpus"][r["key"]]
        for k in ("tokens", "types", "coverage"):
            assert close(r["values"][k], w[k]), (r["key"], k)
    by_doc = vocab.profile(docs, dict(entries), levels, "en", by="document")
    keys = [c["key"] for c in by_doc.columns][2:]
    for r in by_doc.rows:
        for k, level in zip(keys, [*levels, vocab.OFF_LIST]):
            assert close(r["values"][k], want["documents"][r["key"]][level]), (
                r["key"],
                level,
            )


def check_sketch(docs):
    for case in GOLD["sketch"]:
        t = sketch.sketch(docs, case["lemma"], min_freq=case["min_freq"], top=10_000)
        assert t.totals["node_freq"] == case["node_freq"]
        assert {r["key"]: r["freq"] for r in t.totals["relations"]} == case["relations"]
        got = {r["key"]: r["values"] for r in t.rows}
        assert set(got) == set(case["rows"]), case["lemma"]
        for key, w in case["rows"].items():
            for k, v in w.items():
                assert close(got[key][k], v), (key, k)


def test_metrics_vocab_sketch_in_memory(mem):
    check_metrics(mem)
    check_vocab(mem)
    check_sketch(mem)


@pytest.mark.cwb
def test_metrics_vocab_sketch_from_index(ud):
    docs = indexed(ud)
    assert [d.id for d in docs] == [f"d{i}" for i in range(16)]
    check_metrics(docs)
    check_vocab(docs)
    check_sketch(docs)


def compare_items(hits, sizes, meta):
    items = []
    for g in ("a", "b"):
        ds = [d for d in sizes if meta[d]["part"] == g]
        items.append(
            {
                "label": g,
                "scope_name": f"part {g}",
                "query": "the",
                "hits": {d: hits.get(d, 0) for d in ds},
                "sizes": {d: sizes[d] for d in ds},
                "meta": meta,
                "search_query": "the",
                "search_scope": {"corpus_id": "c", "filter": {"part": g}},
                "corpus_id": "c",
                "base_filter": {"part": g},
            }
        )
    return items


def check_compare(items):
    want = GOLD["compare"]
    t = compare.table(items, test="mann_whitney")
    for r, w in zip(t.rows, want["items"]):
        for k, v in w.items():
            assert close(r["values"][k], v), k
    assert close(t.totals["comparison"]["ll"], want["ll"])
    assert close(t.totals["comparison"]["log_ratio"], want["log_ratio"])
    mw = t.totals["test"]
    assert close(mw["u"], want["mann_whitney"]["u"]) and close(
        mw["p"], want["mann_whitney"]["p"]
    )
    sp = compare.table(items, by="n", numeric=True, test="spearman")
    for got, w in zip(sp.totals["test"]["items"], want["spearman"]):
        assert (
            got["n"] == w["n"]
            and close(got["rho"], w["rho"])
            and close(got["p"], w["p"])
        )
    assert [r["values"]["value"] for r in sp.rows] == list(range(16))
    row = sp.rows[3]
    assert row["values"]["per_million_2"] is None  # document 3 is in part a only
    assert row["searches"][0]["search_scope"] == {
        "corpus_id": "c",
        "filter": {"part": "a", "n": 3},
    }


def test_compare_in_memory(mem):
    want = GOLD["compare"]
    sizes = {d.id: sum(len(s) for s in d.sentences) for d in mem}
    check_compare(compare_items(want["doc_hits"], sizes, {d.id: d.meta for d in mem}))


@pytest.mark.cwb
def test_compare_from_index(ud):
    d, docs = ud
    hits, sizes, totals = stats.doc_hits(stats.Scope(d, "ud_en"), "the")
    assert dict(hits) == {k: v for k, v in GOLD["compare"]["doc_hits"].items() if v}
    assert totals["documents"] == 16
    check_compare(
        compare_items(
            hits, sizes, {f"d{i}": doc.metadata for i, doc in enumerate(docs)}
        )
    )


def test_compare_validation():
    item = compare_items({}, {"d0": 10}, {"d0": {"part": "a", "n": 0}})
    with pytest.raises(ValueError):
        compare.table(item[:1], test="mann_whitney")
    with pytest.raises(ValueError):
        compare.table(item, test="spearman")
    t = compare.table(item)
    assert "comparison" not in t.totals  # no hits in either item
    assert t.rows[0]["search_scope"] == {"corpus_id": "c", "filter": {"part": "a"}}


def test_tests_match_scipy():
    ss = pytest.importorskip("scipy.stats")
    rng = random.Random(7)
    for _ in range(200):
        x = [
            rng.choice([0, 0, 1.5, 2, rng.random() * 50])
            for _ in range(rng.randint(1, 30))
        ]
        y = [rng.choice([0, 3, rng.random() * 50]) for _ in range(rng.randint(1, 30))]
        got, want = (
            compare.mann_whitney(x, y),
            ss.mannwhitneyu(x, y, method="asymptotic"),
        )
        if got["p"] is not None:
            assert (
                abs(got["u"] - want.statistic) < 1e-9
                and abs(got["p"] - want.pvalue) < 1e-9
            )
        n = rng.randint(3, 50)
        a = [rng.choice([1, 2, rng.random()]) for _ in range(n)]
        b = [rng.choice([0, rng.random()]) for _ in range(n)]
        got, want = compare.spearman(a, b), ss.spearmanr(a, b)
        if got["rho"] is not None:
            assert (
                abs(got["rho"] - want.statistic) < 1e-9
                and abs(got["p"] - want.pvalue) < 1e-9
            )


def test_mann_whitney_and_spearman_edges():
    assert compare.mann_whitney([1, 1], [1, 1])["p"] is None
    assert compare.mann_whitney([], [1])["u"] is None
    assert compare.spearman([1, 2], [3, 4])["rho"] is None
    assert compare.spearman([1, 2, 3], [5, 5, 5])["rho"] is None
    perfect = compare.spearman([1, 2, 3, 4], [10, 20, 30, 40])
    assert perfect["rho"] == 1 and perfect["p"] == 0


def test_metric_definitions():
    words = ["a", "b", "a", "c"] * 30  # 120 words, 3 types
    doc = Doc("x", "t", "en", {}, [[(w, "NOUN", w, None, None) for w in words]])
    m = metrics.document_metrics(doc, window=50)
    assert m["ttr"] == pytest.approx(3 / 120)
    assert m["sttr"] == pytest.approx(3 / 50)  # two full windows of 50
    assert m["mean_dependency_distance"] is None
    assert m["lexical_density"] == 1
    assert metrics.syllables("readable") == 3 and metrics.syllables("make") == 1
    assert metrics.syllables("rhythm") == 1 and metrics.syllables("table") == 2
    zh = Doc(
        "z",
        "t",
        "zh",
        {},
        [
            [
                ("我", "r", "我", 2, "nsubj"),
                ("喜欢", "v", "喜欢", 0, "root"),
                ("读书", "vn", "读书", 2, "obj"),
                ("。", "x", "。", 2, "punct"),
            ]
        ],
    )
    m = metrics.document_metrics(zh)
    assert m["words"] == 3 and m["lexical_density"] == pytest.approx(2 / 3)
    assert m["flesch_reading_ease"] is None and m["sttr"] is None and m["mtld"] is None
    assert m["mean_dependency_distance"] == pytest.approx((1 + 1 + 2) / 3)
    t = metrics.table([zh], metrics=["ttr"], group_by="year")
    assert [c["key"] for c in t.columns] == ["title", "language", "group", "ttr"]
    assert t.totals["groups"]["ttr"] == [
        {"value": "（无）", "documents": 1, "mean": 1.0, "sd": None}
    ]
    with pytest.raises(ValueError):
        metrics.table([zh], metrics=["nope"])


def test_mtld_known_value():
    # forward: a b a b → TTR 1, 1, 2/3 (> .72? no: 0.667 ≤ .72) → factor after 3 words, then "b" (TTR 1)
    words = list("abab")
    assert metrics._mtld_pass(words, 0.72) == pytest.approx(4 / 1)


def test_vocab_list_parse_and_chinese_profile():
    text = "﻿词,等级\n学习,HSK 2\n# 注释\n\n朋友,HSK 1\n学习,HSK 3\n书\tHSK 1\n中华人民共和国,HSK 10\n"
    entries, levels, dup = vocab.parse(text, "zh")
    assert levels == ["HSK 1", "HSK 2", "HSK 10"] and dup == 1
    assert dict(entries)["学习"] == "HSK 2"
    named, order, _ = vocab.parse("cat,AWL\ndog,basic\nCat,basic\n", "en")
    assert order == ["AWL", "basic"] and dict(named) == {"cat": "AWL", "dog": "basic"}
    for bad in ("", "# only\n", "word\n"):
        with pytest.raises(vocab.ListError):
            vocab.parse(bad, "zh")
    doc = Doc(
        "z",
        "作文",
        "zh",
        {"grade": 3},
        [
            [
                ("我", "r", None, None, None),
                ("学习", "v", None, None, None),
                ("书", "n", None, None, None),
                ("。", "x", None, None, None),
            ]
        ],
    )
    t = vocab.profile([doc], dict(entries), levels, "zh")
    got = {r["key"]: r["values"] for r in t.rows}
    assert (
        got["HSK 1"]["tokens"] == 1
        and got["HSK 2"]["tokens"] == 1
        and got["表外"]["tokens"] == 1
    )
    assert got["HSK 2"]["coverage"] == pytest.approx(100 / 3)
    assert {r["key"]: r["search_query"] for r in t.rows}["表外"] == '"我"'
    assert t.totals["off_list"] == [{"item": "我", "freq": 1, "search_query": '"我"'}]
    by_field = vocab.profile([doc], dict(entries), levels, "zh", by="grade")
    assert by_field.rows[0]["key"] == "3" and by_field.rows[0]["values"][
        "level_1"
    ] == pytest.approx(100 / 3)
    for r in t.rows:
        if r["search_query"]:
            query.parse(r["search_query"])


def test_builtin_ngsl():
    entries, levels = vocab.builtin()
    assert len(entries) == 2809 and levels == [
        "频率排名 1–1000",
        "频率排名 1001–2000",
        "频率排名 2001–2809",
    ]
    table = dict(entries)
    assert (
        table["the"] == "频率排名 1–1000" and table["true"] == table["i"] == "频率排名 1–1000"
    )
    assert table["thirst"] == "频率排名 2001–2809"


def test_sketch_queries_and_diff(mem):
    t = sketch.sketch(mem, "make", min_freq=1)
    objs = {
        r["values"]["collocate"]: r
        for r in t.rows
        if r["values"]["relation"] == "object"
    }
    assert {"mistake", "statement"} <= set(objs)
    assert objs["mistake"]["search_query"] == '"mistakes"{dep=obj} +"made"'
    for r in t.rows:
        for k in ("search_query", "search_query_reverse"):
            if r.get(k):
                query.parse(r[k])
    labels = [r["label"] for r in t.totals["relations"]]
    assert labels[:2] == ["主语", "宾语"] and "at + N" in labels
    d = sketch.diff(mem, "make", "say", min_freq=1, top=5)
    assert d.totals["node_freq_a"] == t.totals["node_freq"]
    for rel in d.totals["relations"]:
        rows = [r["values"] for r in d.rows if r["values"]["relation"] == rel["key"]]
        groups = [r["group"] for r in rows]
        assert groups == sorted(groups, key=["a", "common", "b"].index)
        for r in rows:
            assert r["diff"] == pytest.approx(
                (r["logdice_a"] or 0) - (r["logdice_b"] or 0)
            )
            assert (r["group"] == "a") == (r["freq_b"] == 0 and r["freq_a"] >= 1)
    with pytest.raises(ValueError):
        sketch.diff(mem, "make", "Make")
    say = sketch.sketch(mem, "say", pos_tags={"NOUN"})
    assert say.totals["node_freq"] == 0 and say.rows == []


def test_method_appendix_cites_p10_metrics():
    from engine import methods

    stats_ = [
        {
            "method": "text_metrics",
            "params": {
                "metrics": None,
                "group_by": "year",
                "sttr_window": 1000,
                "top": 2000,
            },
            "scope": "作文",
            "totals": {
                "documents": 2,
                "words": 300,
                "notes": ["1 篇文档词数少于 100"],
                "groups": {"ttr": []},
            },
            "columns": [
                "title",
                "language",
                "ttr",
                "sttr",
                "mtld",
                "lexical_density",
                "mean_dependency_distance",
                "flesch_reading_ease",
                "flesch_kincaid_grade",
            ],
        },
        {
            "method": "vocab_profile",
            "params": {
                "list_id": "x",
                "by": "document",
                "vocab_list": {
                    "name": "NGSL 1.2",
                    "license": "CC BY-SA 4.0",
                    "builtin": True,
                },
            },
            "scope": "作文",
            "totals": {"words": 300, "off_list": [{"item": "x"}]},
            "columns": ["item", "words", "level_1", "off_list"],
        },
        {
            "method": "compare",
            "params": {
                "items": [{"label": "A", "query": "the"}, {"label": "B", "query": "a"}],
                "test": "mann_whitney",
                "query_layers": [None, None],
            },
            "scope": "作文",
            "totals": {"items": 2, "test": {"method": "mann_whitney", "u": 3.0}},
            "columns": ["label", "hits", "per_million"],
        },
        {
            "method": "sketch_diff",
            "params": {"lemma_a": "big", "lemma_b": "large"},
            "scope": "作文",
            "totals": {},
            "columns": [
                "relation_label",
                "collocate",
                "logdice_a",
                "logdice_b",
                "diff",
            ],
        },
    ]
    out = methods.build({"stats": stats_}, "apa")
    md, refs = out["markdown"], "\n".join(out["citations"])
    for name in (
        "McCarthy",
        "Liu, H.",
        "Flesch, R.",
        "Kincaid",
        "Ure",
        "Browne",
        "Mann, H. B.",
        "Kilgarriff, A., Rychlý",
        "Kilgarriff, A., Baisa",
        "Rychlý, P.",
    ):
        assert name in refs, name
    assert "Spearman" not in refs
    assert "按字段 year 分组汇总" in md and "词表 NGSL 1.2（CC BY-SA 4.0）" in md
    assert "对比项 A：`the`；B：`a`" in md and "检验 Mann-Whitney U 检验" in md
    assert "词元 A big" in md and "off_list" not in md and "groups" not in md
    assert "说明：1 篇文档词数少于 100" in md
