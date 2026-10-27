from pathlib import Path

import pytest

from engine import nlp
from engine.conllu import write_conllu
from engine.model import Document
from engine.parsers import parse

conllu = pytest.importorskip("conllu")
FIX = Path(__file__).resolve().parents[1] / "fixtures"


def surface(sent):
    """Sentence text rebuilt from FORM and SpaceAfter=No."""
    out = ""
    for tok in sent:
        out += tok["form"]
        if (tok["misc"] or {}).get("SpaceAfter") != "No":
            out += " "
    return out.rstrip(" ")


def test_ud_round_trip():
    source = FIX / "ud-en-ewt-sample.conllu"
    original = conllu.parse(source.read_text(encoding="utf-8"))
    docs, _ = parse(source, language="en", metadata={})
    written = conllu.parse(write_conllu(docs))
    assert len(written) == len(original) == 221
    for old, new in zip(original, written):
        words = [t for t in old if isinstance(t["id"], int)]
        assert new.metadata["text"] == old.metadata["text"]
        assert [t["id"] for t in new] == list(range(1, len(words) + 1))
        for key in ("form", "lemma", "upos", "head", "deprel"):
            assert [t[key] for t in new] == [t[key] for t in words], key
        assert all(t["xpos"] is None and t["feats"] is None for t in new)
        if len(words) == len(old):  # no multiword tokens: spacing is reproduced exactly
            assert surface(new) == old.metadata["text"]
    ids = [s.metadata["sent_id"] for s in written]
    assert len(set(ids)) == len(ids)
    assert [s.metadata["newdoc id"] for s in written if "newdoc id" in s.metadata] == [
        d.external_id for d in docs
    ]


def test_jieba_tags_and_effective_values():
    doc = Document("样本", "zh", "语言是工具。我们研究语言！", {}, [])
    nlp.annotate(doc)
    tok = doc.sentences[0].tokens[0]
    tok.head, tok.deprel = 2, "nsubj"
    [first, second] = conllu.parse(write_conllu([doc]))
    assert first.metadata == {
        "newdoc id": "样本",
        "sent_id": "样本-1",
        "text": "语言是工具。",
    }
    assert [(t["form"], t["upos"], t["xpos"]) for t in first] == [
        ("语言", "NOUN", "n"),
        ("是", "VERB", "v"),
        ("工具", "NOUN", "n"),
        ("。", "PUNCT", "w"),
    ]
    assert (first[0]["head"], first[0]["deprel"]) == (2, "nsubj")
    assert first[1]["head"] is None and first[1]["deprel"] == "_"
    assert surface(first) == "语言是工具。" and surface(second) == "我们研究语言！"
