"""KWIC character context helpers (engine.cwb) and corpus-tagset POS resolution (engine.query)."""

import pytest

from engine import cwb, query


def test_word_cut_drops_half_words_at_outer_edges():
    # one extra character outside the window: a letter there means the edge word is cut
    assert cwb._word_cut_left("uality Lawrence said", True) == "Lawrence said"
    assert cwb._word_cut_left(" quality Lawrence", True) == "quality Lawrence"
    assert cwb._word_cut_right("the Domestic", True) == "the"
    assert cwb._word_cut_right("said the Domestic", True) == "said the"
    assert cwb._word_cut_right("said the house ", True) == "said the house"
    assert cwb._word_cut_right("said the house.", True) == "said the house"
    # without the extra character (window reaches the text edge) nothing is dropped
    assert cwb._word_cut_left("uality Lawrence", False) == "uality Lawrence"
    # one long word: keep it rather than return nothing
    assert cwb._word_cut_left("xinternationalization", True) == "internationalization"
    # Chinese is cut by characters
    assert cwb._word_cut_left("言学研究语言", True) == "学研究语言"
    assert cwb._word_cut_right("研究语言与社", True) == "研究语言与"


def test_pos_resolves_against_corpus_tagset():
    """词/标签 on a UD (UPOS) corpus and on a jieba corpus (QA Q21)."""
    upos = query.compile(query.parse("中國/PROPN", "upos"))
    assert upos.split("\n")[0] == '[word="中國" & pos="PROPN"]'
    assert query.compile(query.parse("中國/n", "upos")).split("\n")[0] == (
        '[word="中國" & pos="NOUN|PROPN"]'
    )
    jieba = query.compile(query.parse("中国/PROPN", "jieba")).split("\n")[0]
    assert jieba == '[word="中国" & pos="nr|nrfg|nrt|ns|nt|nz"]'
    mixed = query.compile(query.parse("中国/PROPN", "mixed")).split("\n")[0]
    assert mixed == '[word="中国" & pos="PROPN|nr|nrfg|nrt|ns|nt|nz"]'
    with pytest.raises(query.QueryError):
        query.parse(
            "中国/ns", "upos"
        )  # a jieba tag on a UPOS corpus is rejected, not a silent 0
    assert query.parse("中国/ns", "jieba")


@pytest.mark.cwb
def test_doc_text_context_matches_cwb_hits(tmp_path):
    """cwb.DocText (hits answered from PostgreSQL) gives the context cwb.hits gives, without whole documents;
    sentence_only keeps parallel corpora inside the hit's sentence; documents missing from the index come
    from the fallback."""
    from engine.model import Context, Document, Sentence, Token

    text = "First words here.\nSecond sentence with target word inside it."
    sents = []
    for a, b in ((0, 17), (18, len(text))):
        toks, pos = [], a
        for w in text[a:b].split(" "):
            toks.append(Token(pos, pos + len(w), w, "NOUN", w))
            pos += len(w) + 1
        sents.append(Sentence(a, b, toks))
    cwb.build(tmp_path, "dt", [Document("d", "en", text, {}, sents)], ["d0"])
    start = text.index("target")
    end = start + len("target")
    texts = cwb.DocText(tmp_path, "dt")
    for ctx in (
        Context(unit="char", size=12),
        Context(unit="char", size=40, sentence_only=True),
        Context(unit="sentence"),
        Context(unit="paragraph"),
    ):
        h = texts.hit("d0", 1, start, end, ctx)
        assert h.match == "target" and h.hit_id == f"d0:{start}-{end}"
        if ctx.unit == "sentence" or ctx.sentence_only:
            assert h.left == "Second sentence with " and h.right == " word inside it."
    wide = texts.hit("d0", 1, start, end, Context(unit="char", size=30))
    assert "here." in wide.left  # crosses into the previous sentence
    missing = cwb.DocText(
        tmp_path, "dt", lambda d: (text, {0: (0, 17), 1: (18, len(text))})
    )
    h = missing.hit("other", 1, start, end, Context(unit="sentence"))
    assert h.left == "Second sentence with "
    with pytest.raises(ValueError):
        cwb.DocText(tmp_path / "none", "dt").hit("d0", 1, start, end, Context())
