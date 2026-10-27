"""P5 engine pieces: span label queries, agreement coefficients, alignment candidates, model answer checks."""

import math

import pytest

from engine import agreement, align, annotate
from engine.query import compile, parse, pure_span, spans

# ---- span label queries ----


def test_span_queries_parse_and_compile():
    c = compile(parse("[时态]"))
    assert c.split("\n")[0] == "[]"
    assert spans(c) == {0: {"path": ("时态",), "attrs": {}}}
    assert "#target 0 @[]" in c
    assert pure_span(parse("[偏误:时态]"))
    assert spans(compile(parse("[偏误:时态]")))[0]["path"] == ("偏误", "时态")
    attrs = spans(compile(parse("[时态:tense=past|present,kind=a]")))[0]["attrs"]
    assert attrs == {"tense": ("past", "present"), "kind": ("a",)}

    anchored = parse("went[时态]")
    assert not pure_span(anchored)
    c = compile(anchored)
    assert c.split("\n")[0] == '[word="went" %c]'
    assert '#target 0 @[word="went" %c]' in c
    both = compile(parse('"went"{pos=VERB}[时态]'))
    assert "#attr 0 pos=VERB" in both and spans(both)[0]["path"] == ("时态",)
    assert both.count("#target") == 1

    second = compile(parse("language [x] of"))
    assert spans(second) == {1: {"path": ("x",), "attrs": {}}}
    assert '#target 1 [word="language" %c] @[] [word="of" %c]' in second
    assert not pure_span(parse("[x] +y"))
    # a CJK word with a span label matches one whole token, like `/pos`
    assert compile(parse("去[偏误:体]")).split("\n")[0] == '[word="去"]'
    tokens = [t.kind for t in parse("学生[x] [y]").tokens]
    assert tokens == ["word", "span", "span"]


# ---- agreement ----


def test_cohen_kappa_textbook():
    # 50 items: yes/yes 20, yes/no 5, no/yes 10, no/no 15 → p_o 0.7, p_e 0.5, κ 0.4
    a = ["y"] * 25 + ["n"] * 25
    b = ["y"] * 20 + ["n"] * 5 + ["y"] * 10 + ["n"] * 15
    assert agreement.cohen_kappa(a, b) == pytest.approx(0.4)
    assert agreement.cohen_kappa(["x", "y"], ["x", "y"]) == pytest.approx(1.0)
    assert agreement.cohen_kappa(["x", "x"], ["x", "x"]) is None
    assert agreement.cohen_kappa([], []) is None


def test_krippendorff_alpha_reference_example():
    # Krippendorff (2011) "Computing Krippendorff's Alpha-Reliability", nominal data, 4 observers,
    # 12 units with missing values: α = 0.743
    n = None
    a = [1, 2, 3, 3, 2, 1, 4, 1, 2, n, n, n]
    b = [1, 2, 3, 3, 2, 2, 4, 1, 2, 5, n, 3]
    c = [n, 3, 3, 3, 2, 3, 4, 2, 2, 5, 1, n]
    d = [1, 2, 3, 3, 2, 4, 4, 1, 2, 5, 1, n]
    alpha = agreement.krippendorff_alpha([list(u) for u in zip(a, b, c, d)])
    assert round(alpha, 3) == 0.743


def test_alpha_two_coders_by_hand():
    # units: (a,a) (a,b) (b,b) (b,b): o_aa=2, o_ab=o_ba=1, o_bb=4; n_a=3, n_b=5, n=8
    # α = 1 − (n−1)·(o_ab+o_ba) / (n_a·n_b + n_b·n_a) = 1 − 7·2/30
    alpha = agreement.krippendorff_alpha(
        [["a", "a"], ["a", "b"], ["b", "b"], ["b", "b"]]
    )
    assert alpha == pytest.approx(1 - 14 / 30)
    assert agreement.krippendorff_alpha([["a", "a"], ["a", "a"]]) is None


def test_summary_and_per_label():
    s = agreement.summary({"p": ["x", "y", "x", "x"], "q": ["x", "y", "y", "x"]})
    assert s["n"] == 4 and len(s["pairwise"]) == 1
    # p_o 0.75; p: x 3/4 y 1/4, q: x 1/2 y 1/2 → p_e 0.5 → κ 0.5
    assert s["pairwise"][0]["kappa"] == pytest.approx(0.5)
    per = {x["label"]: x["kappa"] for x in s["per_label"]}
    assert per["x"] == pytest.approx(0.5) and per["y"] == pytest.approx(0.5)


# ---- alignment ----


def _unit(*xs):
    n = math.sqrt(sum(x * x for x in xs))
    return [x / n for x in xs]


def test_sentence_matching_greedy_one_to_one():
    src = ["The cat sleeps.", "It rains today.", "Good night."]
    tgt = ["今天下雨。", "猫在睡觉。", "晚安。"]
    sv = [_unit(1, 0, 0), _unit(0, 1, 0), _unit(0, 0, 1)]
    tv = [_unit(0.1, 1, 0), _unit(1, 0.2, 0), _unit(0.3, 0, 0.2)]
    out = align.match_sentences(src, tgt, sv, tv)
    assert [(i, j) for i, j, _ in out] == [(0, 1), (1, 0), (2, 2)]
    assert all(0.5 <= s <= 1 for _, _, s in out)
    # below the cosine threshold nothing is proposed
    assert align.match_sentences(["a"], ["b"], [_unit(1, 0)], [_unit(0, 1)]) == []


def test_sentence_matching_prefers_higher_score_when_competing():
    src = ["aaaa", "bbbb"]
    tgt = ["xxxx"]
    sv = [_unit(1, 0.2), _unit(1, 0)]
    tv = [_unit(1, 0)]
    out = align.match_sentences(src, tgt, sv, tv)
    assert [(i, j) for i, j, _ in out] == [(1, 0)]


def test_clean_links_and_word_pairs():
    links = align.clean_links(
        [
            {"src": [2, 1], "tgt": [3]},
            {"src": [1, 2], "tgt": 3},  # duplicate after normalising
            {"src": [9], "tgt": [1]},  # out of range
            {"src": [], "tgt": [1]},
            {"src": [True], "tgt": [1]},
            "x",
        ],
        3,
        3,
    )
    assert links == [((1, 2), (3,))]
    assert align.word_pairs(links) == {(1, 3), (2, 3)}


# ---- model answers ----


def test_clean_spans_repairs_offsets():
    sentences = {1: "Yesterday I go to school.", 2: "He have two book."}
    labels = {
        "时态": {"name": "时态"},
        "主谓一致": {"name": "主谓一致"},
        "x": {"name": "名词单复数"},
    }
    items = [
        {
            "id": 1,
            "text": "go",
            "start": 12,
            "end": 14,
            "label": "时态",
        },  # correct offsets
        {
            "id": 2,
            "text": "have",
            "start": 0,
            "end": 4,
            "label": "主谓一致",
        },  # wrong offsets
        {
            "id": 2,
            "text": "book",
            "start": 12,
            "end": 16,
            "label": "名词单复数",
        },  # label by name
        {
            "id": 2,
            "text": "cars",
            "start": 0,
            "end": 4,
            "label": "时态",
        },  # not in sentence
        {"id": 3, "text": "x", "label": "时态"},  # unknown sentence
        {"id": 1, "text": "go", "start": 12, "label": "未知"},  # unknown label
        {"id": 1, "start": 0, "end": 10, "label": "时态"},  # no text: range trimmed
    ]
    found, dropped = annotate.clean_spans(items, sentences, labels)
    s1, s2 = sentences[1], sentences[2]
    assert [(s1[a:b], lab) for a, b, lab, _ in found[1]] == [
        ("go", "时态"),
        ("Yesterday", "时态"),
    ]
    assert [(s2[a:b], lab) for a, b, lab, _ in found[2]] == [
        ("have", "主谓一致"),
        ("book", "x"),
    ]
    assert dropped == 3


def test_clean_relations():
    labels = {"correction": {"name": "correction"}}
    found, dropped = annotate.clean_relations(
        [
            {"id": 1, "from": 1, "to": 2, "label": "correction"},
            {"id": 1, "from": 1, "to": 1, "label": "correction"},
            {"id": 1, "from": 1, "to": 3, "label": "correction"},
            {"id": 2, "from": 1, "to": 2, "label": "cause"},
        ],
        {1: 2, 2: 2},
        labels,
    )
    assert found == {1: [(0, 1, "correction")]} and dropped == 3
