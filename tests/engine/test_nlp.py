from pathlib import Path

import pytest

from engine import nlp
from engine.model import Document
from engine.parsers import parse

pytestmark = pytest.mark.nlp
FIX = Path(__file__).resolve().parents[1] / "fixtures"


def check(doc):
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


def test_detect_language():
    assert nlp.detect_language("社会语言学研究语言。") == "zh"
    assert nlp.detect_language("Language and society, 语言") == "en"


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


def test_chinese_txt_detected():
    [doc], _ = parse(FIX / "sample.txt", language=None, metadata={})
    nlp.annotate(doc)
    assert doc.language == "zh"
    check(doc)
    assert len(doc.sentences) >= 4
    zh_tokens = [t for t in doc.sentences[0].tokens]
    assert all(doc.text[t.start : t.end] == t.form for t in zh_tokens)


def test_existing_sentences_tokenised_in_place():
    docs, _ = parse(FIX / "tatoeba", language=None, metadata={})
    for d in docs:
        before = [(s.start, s.end, s.external_id) for s in d.sentences]
        nlp.annotate(d)
        assert [(s.start, s.end, s.external_id) for s in d.sentences] == before
        for s in d.sentences:
            assert s.tokens and all(
                s.start <= t.start < t.end <= s.end for t in s.tokens
            )


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
    r = cwb.search(
        tmp_path,
        "txt",
        query.compile(query.parse("语言")),
        restrict=None,
        sort="position",
        seed=None,
        page=1,
        page_size=50,
        context=Context(),
    )
    assert r.counts.hits == 4 and all(h.match == "语言" for h in r.items)
