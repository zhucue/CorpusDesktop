from pathlib import Path

import pytest

from engine import cwb, query
from engine.model import Context, Document, Sentence, Token
from engine.parsers import parse

pytestmark = pytest.mark.cwb
FIX = Path(__file__).resolve().parents[1] / "fixtures"


def run(
    index,
    q,
    restrict=None,
    sort="position",
    seed=None,
    page=1,
    page_size=50,
    ctx=None,
    key="zh",
):
    return cwb.search(
        index,
        key,
        query.compile(query.parse(q)),
        restrict=restrict,
        sort=sort,
        seed=seed,
        page=page,
        page_size=page_size,
        context=ctx or Context(),
    )


@pytest.fixture(scope="module")
def zh(tmp_path_factory):
    d = tmp_path_factory.mktemp("zh")
    docs, _ = parse(FIX / "zh-sample.conllu", language="zh", metadata={})
    docs[0].metadata = {"year": 1990, "genre": "news", "年份": 1990}
    docs[1].metadata = {"year": 2005, "genre": "a.b"}
    info = cwb.build(d, "zh", docs, ["zh1", "zh2"])
    assert (info.documents, info.sentences, info.tokens) == (2, 4, 19)
    return d


def spans(r):
    return [
        (h.doc_id, h.sentence_index, h.start_cp, h.end_cp, h.match) for h in r.items
    ]


def test_chinese_string_crosses_words(zh):
    r = run(zh, "语言")
    assert (r.counts.hits, r.counts.sentences, r.counts.documents) == (5, 4, 2)
    assert spans(r) == [
        ("zh1", 0, 2, 4, "语言"),
        ("zh1", 0, 7, 9, "语言"),
        ("zh1", 1, 14, 16, "语言"),
        ("zh2", 0, 2, 4, "语言"),
        ("zh2", 1, 7, 9, "语言"),
    ]
    assert spans(run(zh, "言文")) == [
        ("zh1", 1, 15, 17, "言文"),
        ("zh2", 1, 8, 10, "言文"),
    ]
    assert spans(run(zh, "语言学")) == [("zh1", 0, 2, 5, "语言学")]
    assert spans(run(zh, "说?言")) == [("zh2", 0, 1, 4, "说语言")]


def test_word_level_and_sequences(zh):
    assert run(zh, "语言/n").counts.hits == 3
    assert run(zh, '"语言"').counts.hits == 3
    assert spans(run(zh, "语言 文化")) == [("zh1", 1, 14, 18, "语言文化")]
    assert spans(run(zh, "/v $1 社会")) == []
    assert spans(run(zh, "/v $2 社会")) == [("zh1", 0, 5, 12, "研究语言与社会")]
    assert spans(run(zh, "汉 语言 文字")) == [
        ("zh2", 1, 6, 11, "汉语言文字")
    ]  # trailing CJK narrowed


def test_conditions(zh):
    r = run(zh, "语言 +社会")
    assert (r.counts.hits, r.counts.sentences, r.counts.documents) == (2, 1, 1)
    r = run(zh, "语言 -社会")
    assert (r.counts.hits, r.counts.sentences, r.counts.documents) == (3, 3, 2)
    assert run(zh, "语言 +社会 +重要").counts.hits == 0
    assert run(zh, "语言 -社会 -重要").counts.hits == 2


def test_restrict(zh):
    fields = {"year": "number", "genre": "string", "年份": "number"}
    r = run(
        zh,
        "语言",
        restrict=query.compile_filter({"year": {"gte": 2000, "lte": 2010}}, fields),
    )
    assert (r.counts.hits, r.counts.documents) == (2, 1) and {
        h.doc_id for h in r.items
    } == {"zh2"}
    assert (
        run(
            zh, "语言", restrict=query.compile_filter({"genre": ["a.b"]}, fields)
        ).counts.hits
        == 2
    )
    assert (
        run(
            zh, "语言", restrict=query.compile_filter({"genre": "aXb"}, fields)
        ).counts.hits
        == 0
    )
    assert (
        run(
            zh, "语言", restrict=query.compile_filter({"年份": {"lte": 2000}}, fields)
        ).counts.hits
        == 3
    )


def test_context_units(zh):
    h = run(zh, "文字", ctx=Context("char", 2)).items[0]
    assert (h.left, h.match, h.right) == ("语言", "文字", "学")
    h = run(zh, "文字", ctx=Context("paragraph")).items[0]
    assert (h.left, h.right) == ("汉语言", "学")
    h = run(zh, "说", ctx=Context("sentence")).items[0]
    assert (h.left, h.match, h.right) == ("他", "说", "语言。")
    h = run(zh, "研究", ctx=Context("char", 100)).items[0]
    assert h.left == "社会语言学" and h.right == "语言与社会。 语言文化很重要。"
    assert cwb.context(zh, "zh", "zh2", 1, 1, 1) == ["他说语言。", "汉语言文字学"]
    assert cwb.context(zh, "zh", "zh1", 0, 0, 5) == [
        "社会语言学研究语言与社会。",
        "语言文化很重要。",
    ]


def test_sort_and_pages(zh):
    pos = [h.hit_id for h in run(zh, "语言").items]
    assert pos == ["zh1:2-4", "zh1:7-9", "zh1:14-16", "zh2:2-4", "zh2:7-9"]
    # by the word after / before the hit tokens: 。 < 与 < 文化 < 文字学 < 研究 ;  。 < 他 < 汉 < 研究 < 社会
    assert [h.hit_id for h in run(zh, "语言", sort="right").items] == [
        "zh2:2-4",
        "zh1:7-9",
        "zh1:14-16",
        "zh2:7-9",
        "zh1:2-4",
    ]
    assert [h.hit_id for h in run(zh, "语言", sort="left").items] == [
        "zh1:14-16",
        "zh2:2-4",
        "zh2:7-9",
        "zh1:7-9",
        "zh1:2-4",
    ]
    r1 = [h.hit_id for h in run(zh, "语言", sort="random", seed=7).items]
    assert r1 == [
        h.hit_id for h in run(zh, "语言", sort="random", seed=7).items
    ] and sorted(r1) == sorted(pos)
    paged = [
        h.hit_id
        for p in (1, 2, 3)
        for h in run(zh, "语言", sort="random", seed=7, page=p, page_size=2).items
    ]
    assert paged == r1


def test_timeout_returns_page_without_counts(zh):
    r = cwb.search(
        zh,
        "zh",
        query.compile(query.parse("语言")),
        restrict=None,
        sort="position",
        seed=None,
        page=1,
        page_size=2,
        context=Context(),
        count_timeout=0.0001,
    )
    assert not r.counts.complete and r.counts.hits is None and len(r.items) == 2


def test_version_and_special_tokens(tmp_path):
    text = "café café <b> & x"
    toks = [
        Token(0, 5, "café"),
        Token(6, 10, "café"),
        Token(11, 14, "<b>"),
        Token(15, 16, "&"),
        Token(17, 18, "x"),
    ]
    doc = Document("t", "en", text, {"n": 3}, [Sentence(0, len(text), toks)])
    info = cwb.build(tmp_path, "t", [doc], ["d1"])
    assert cwb.build(tmp_path, "t", [doc], ["d1"]).index_version == info.index_version
    r = run(tmp_path, "café", key="t")  # CWB stores NFC; spans come from offsets.bin
    assert [(h.start_cp, h.end_cp, h.match) for h in r.items] == [
        (0, 5, "café"),
        (6, 10, "café"),
    ]
    assert run(tmp_path, '"<b>" "&"', key="t").items[0].match == "<b> &"
    doc.text = text.replace("x", "y")
    doc.sentences[0].tokens[-1].form = "y"
    info2 = cwb.build(tmp_path, "t", [doc], ["d1"])
    assert info2.index_version != info.index_version
    assert run(tmp_path, "y", key="t").counts.hits == 1
    assert sorted(p.name for p in (tmp_path / "t").iterdir()) == [info2.index_version]


def test_empty_corpus(tmp_path):
    doc = Document("e", "en", "untokenised", {}, [Sentence(0, 11, [])])
    info = cwb.build(tmp_path, "e", [doc], ["d1"])
    assert (info.tokens, info.sentences, info.documents) == (0, 1, 1)
    assert run(tmp_path, "x", key="e").counts.hits == 0
    assert cwb.context(tmp_path, "e", "d1", 0, 1, 1) == ["untokenised"]
