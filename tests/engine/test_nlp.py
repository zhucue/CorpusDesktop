from pathlib import Path

import pytest

from engine import nlp
from engine.model import Document
from engine.parsers import parse
from engine.query import JIEBA_TAGS

FIX = Path(__file__).resolve().parents[1] / "fixtures"


def check(doc):
    """Stanza output: full dependency annotation."""
    for s in doc.sentences:
        assert s.tokens and s.start == s.tokens[0].start and s.end == s.tokens[-1].end
        assert "\n" not in doc.text[s.start : s.end]
        for t in s.tokens:
            assert (
                t.pos
                and t.deprel
                and t.head is not None
                and 0 <= t.head <= len(s.tokens)
            )
            assert (
                doc.text[t.start : t.end] == t.form or len(t.form) != t.end - t.start
            )  # multiword parts may differ


def check_zh(doc):
    """jieba output: exact spans, no whitespace in tokens, POS from the jieba tag set, no dependencies."""
    for s in doc.sentences:
        assert s.tokens and s.start == s.tokens[0].start and s.end == s.tokens[-1].end
        assert "\n" not in doc.text[s.start : s.end]
        prev = s.start
        for t in s.tokens:
            assert doc.text[t.start : t.end] == t.form and t.form.strip() == t.form
            assert prev <= t.start < t.end and not doc.text[prev : t.start].strip()
            assert t.pos in JIEBA_TAGS and t.lemma == t.form
            assert t.head is None and t.deprel is None
            prev = t.end


def sents(doc):
    return [doc.text[s.start : s.end] for s in doc.sentences]


def test_detect_language():
    assert nlp.detect_language("社会语言学研究语言。") == "zh"
    assert nlp.detect_language("Language and society, 语言") == "en"


def test_chinese_jieba_offsets_and_pos():
    text = "  他说：“语言是文化交流的桥梁。”你呢？！Hello world. 3.14 和 2020年……\n\n第二段；结束"
    doc = Document("t", "zh", text, {}, [])
    nlp.annotate(doc)
    check_zh(doc)
    assert sents(doc) == [
        "他说：“语言是文化交流的桥梁。”",
        "你呢？！",
        "Hello world.",
        "3.14 和 2020年……",
        "第二段；",
        "结束",
    ]
    toks = {t.form: t.pos for s in doc.sentences for t in s.tokens}
    assert toks["语言"] == "n" and toks["的"] == "uj" and toks["是"] == "v"
    assert toks["Hello"] == "eng" and toks["2020"] == "m"
    assert toks["“"] == toks["。"] == toks["…"] == "w"
    first = doc.sentences[0].tokens
    assert (first[0].start, first[0].form) == (2, "他")


def test_chinese_jieba_deterministic():
    text = "语言是人类最重要的交际工具。社会语言学研究语言与社会的关系。"
    a, b = Document("a", "zh", text, {}, []), Document("b", "zh-CN", text, {}, [])
    nlp.annotate(a)
    nlp.annotate(b)
    assert a.sentences == b.sentences and len(a.sentences) == 2
    assert nlp.jieba_fingerprint().startswith("jieba ")


def test_chinese_txt_detected():
    [doc], _ = parse(FIX / "sample.txt", language=None, metadata={})
    nlp.annotate(doc)
    assert doc.language == "zh"
    check_zh(doc)
    assert sents(doc)[:4] == [
        "语言是人类最重要的交际工具。",
        "社会语言学研究语言与社会的关系。",
        "第二段：语言文化与翻译。",
        "The last paragraph is English.",
    ]
    forms = [t.form for t in doc.sentences[3].tokens]
    assert forms == ["The", "last", "paragraph", "is", "English", "."]


def test_existing_sentences_tokenised_in_place():
    docs, _ = parse(FIX / "tatoeba", language=None, metadata={})
    zh = [d for d in docs if nlp._lang(d.language) == "zh"]
    assert zh
    for d in zh:
        before = [(s.start, s.end, s.external_id) for s in d.sentences]
        nlp.annotate(d)
        assert [(s.start, s.end, s.external_id) for s in d.sentences] == before
        for s in d.sentences:
            assert s.tokens and all(
                s.start <= t.start < t.end <= s.end
                and d.text[t.start : t.end] == t.form
                for t in s.tokens
            )


@pytest.mark.nlp
def test_english_paragraphs():
    doc = Document(
        "t",
        "en",
        "Language shapes thought. It isn't simple.\nSecond paragraph here",
        {},
        [],
    )
    nlp.annotate(doc)
    check(doc)
    assert len(doc.sentences) == 3
    forms = [t.form for s in doc.sentences for t in s.tokens]
    assert "shapes" in forms and "n't" in forms
    assert (
        doc.text[doc.sentences[2].start : doc.sentences[2].end]
        == "Second paragraph here"
    )


@pytest.mark.nlp
def test_english_tatoeba_tokenised_in_place():
    docs, _ = parse(FIX / "tatoeba", language=None, metadata={})
    en = [d for d in docs if nlp._lang(d.language) == "en"]
    for d in en:
        nlp.annotate(d)
        assert all(s.tokens for s in d.sentences)


@pytest.mark.nlp
def test_chinese_dependencies_on_stored_tokens():
    doc = Document("t", "zh", "语言是文化交流的桥梁。我们研究语言。", {}, [])
    nlp.annotate(doc)
    assert len(doc.sentences) == 2
    before = [
        [(t.start, t.end, t.form, t.pos) for t in s.tokens] for s in doc.sentences
    ]
    nlp.annotate_dependencies_zh(doc)
    assert [
        [(t.start, t.end, t.form, t.pos) for t in s.tokens] for s in doc.sentences
    ] == before
    for s in doc.sentences:
        assert all(t.deprel and 0 <= t.head <= len(s.tokens) for t in s.tokens)
        assert sum(t.head == 0 for t in s.tokens) == 1
    nlp.annotate_dependencies_zh(doc)  # cached pipeline, same result
    assert {t.deprel for s in doc.sentences for t in s.tokens} >= {"root", "nsubj"}


def test_conllu_tokens_untouched():
    [doc, _], _ = parse(FIX / "zh-sample.conllu", language="zh", metadata={})
    before = [list(s.tokens) for s in doc.sentences]
    nlp.annotate(doc)
    assert [s.tokens for s in doc.sentences] == before


@pytest.mark.cwb
def test_txt_to_search(tmp_path):
    from engine import cwb, query
    from engine.model import Context

    [doc], _ = parse(FIX / "sample.txt", language="zh", metadata={"year": 2020})
    nlp.annotate(doc)
    info = cwb.build(tmp_path, "txt", [doc], ["d1"])
    assert info.sentences == len(doc.sentences) and info.tokens > 10
    assert info.tagset == cwb.tagset(tmp_path, "txt") == "jieba"

    def run(q, tagset="jieba"):
        return cwb.search(
            tmp_path,
            "txt",
            query.compile(query.parse(q, tagset)),
            restrict=None,
            sort="position",
            seed=None,
            page=1,
            page_size=50,
            context=Context(),
        )

    r = run("语言")
    assert r.counts.hits == 4 and all(h.match == "语言" for h in r.items)
    assert all(doc.text[h.start_cp : h.end_cp] == "语言" for h in r.items)
    tagged = run("语言/n")  # 社会语言学 is one token, so the tagged word has fewer hits
    assert 0 < tagged.counts.hits < 4
    assert all(doc.text[h.start_cp : h.end_cp] == "语言" for h in tagged.items)
    assert run("的/u").counts.hits == run("的/uj").counts.hits > 0
    assert run("/w").counts.hits == sum(
        t.pos == "w" for s in doc.sentences for t in s.tokens
    )
    assert run("语言/NOUN").counts.hits == tagged.counts.hits
    assert run("语言/n", "upos").counts.hits == 0


def test_progress_offsets(monkeypatch):
    """annotate(doc, progress) reports increasing offsets inside one document (zh and Stanza paths)."""
    monkeypatch.setattr(nlp, "ZH_PROGRESS", 1)
    monkeypatch.setattr(nlp, "BATCH", 1)
    zh = Document("zh", "zh", "语言是工具。社会语言学研究语言。\n第三句。", {}, [])
    seen = []
    nlp.annotate(zh, seen.append)
    assert seen == [s.end for s in zh.sentences] and seen == sorted(seen)
    en = Document("en", "en", "One line.\nAnother line here.", {}, [])
    seen = []
    nlp.annotate(en, seen.append)
    assert seen == [9, len(en.text)]
