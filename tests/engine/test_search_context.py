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
