"""Stanza annotation (zh, en): sentences, tokens, UPOS, lemma, head, deprel with exact code-point offsets.

Pipelines are loaded lazily, once per language, from STANZA_RESOURCES_DIR (Stanza downloads missing
models there). Documents without sentences are split per paragraph ("\n"), so sentences never cross a
paragraph; existing sentences without tokens (Tatoeba, TMX) are tokenised in place; sentences that
already have tokens (CoNLL-U) are left untouched.
"""

import functools
import os
import re

from engine.model import Document, Sentence, Token

PROCESSORS = {
    "en": "tokenize,mwt,pos,lemma,depparse",
    "zh": "tokenize,pos,lemma,depparse",
}
BATCH = 200  # paragraphs / sentences per Stanza call

_CJK = re.compile(r"[㐀-䶿一-鿿豈-﫿]")


def detect_language(text: str) -> str:
    sample = [c for c in text[:5000] if not c.isspace()]
    return (
        "zh"
        if sample and sum(bool(_CJK.match(c)) for c in sample) / len(sample) > 0.3
        else "en"
    )


def _lang(language: str) -> str:
    code = (language or "").lower().replace("_", "-").split("-")[0]
    code = {"cmn": "zh", "eng": "en", "zho": "zh", "chi": "zh"}.get(code, code)
    if code not in PROCESSORS:
        raise ValueError(f"暂不支持该语言的自动标注：{language}")
    return code


@functools.cache
def pipeline(lang: str):
    import stanza
    from stanza.pipeline.core import DownloadMethod

    return stanza.Pipeline(
        lang,
        processors=PROCESSORS[lang],
        dir=os.environ.get("STANZA_RESOURCES_DIR"),
        logging_level="WARN",
        download_method=DownloadMethod.REUSE_RESOURCES,
    )


def _tokens(sent, base: int) -> list[Token]:
    """Stanza sentence → Tokens; base = offset of the processed text within Document.text."""
    out = []
    for tok in sent.tokens:
        s, e = tok.start_char, tok.end_char
        words = tok.words
        spans = [(s, e)] * len(words)
        if len(words) > 1:  # multiword token: locate parts in the surface when possible
            k, parts = 0, []
            for w in words:
                m = tok.text.find(w.text, k)
                if m < 0:
                    break
                parts.append((s + m, s + m + len(w.text)))
                k = m + len(w.text)
            else:
                spans = parts
        for w, (a, b) in zip(words, spans):
            out.append(
                Token(base + a, base + b, w.text, w.upos, w.lemma, w.head, w.deprel)
            )
    return out


def _process(lang: str, texts: list[str]):
    import stanza

    nlp = pipeline(lang)
    for i in range(0, len(texts), BATCH):
        yield from nlp.bulk_process(
            [stanza.Document([], text=t) for t in texts[i : i + BATCH]]
        )


def annotate(doc: Document) -> None:
    if not doc.language:
        doc.language = detect_language(doc.text)
    lang = _lang(doc.language)
    if not doc.sentences:
        paras, pos = [], 0
        for line in doc.text.split("\n"):
            if line.strip():
                paras.append((pos, line))
            pos += len(line) + 1
        for (base, line), sd in zip(paras, _process(lang, [p for _, p in paras])):
            for sent in sd.sentences:
                toks = _tokens(sent, base)
                if toks:
                    doc.sentences.append(Sentence(toks[0].start, toks[-1].end, toks))
        return
    todo = [
        s for s in doc.sentences if not s.tokens and doc.text[s.start : s.end].strip()
    ]
    for s, sd in zip(todo, _process(lang, [doc.text[s.start : s.end] for s in todo])):
        s.tokens = [t for sent in sd.sentences for t in _tokens(sent, s.start)]
