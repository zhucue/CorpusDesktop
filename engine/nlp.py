"""Automatic annotation with exact code-point offsets. The language is per document (detected when empty).

Chinese (zh): jieba. Sentences end at 。！？；… / ! ? ; (and `.` before whitespace or the end), with closing
quotes and brackets kept in the sentence; sentences never cross a newline. Tokens come from jieba.posseg
with the bundled default dictionary and HMM off, so the same text always gives the same tokens. POS are
jieba (ICTCLAS-style) tags (n, nr, ns, v, vn, a, d, p, r, m, q, c, u, uj, x, eng …), except that tokens made
only of punctuation or symbols are tagged `w` and tokens made only of digits `m`. lemma = form; head and
deprel stay empty at import (annotate_dependencies_zh adds them later from the stored tokens).

English (en): Stanza tokenize, mwt, pos (UPOS), lemma, depparse; pipelines load lazily from
STANZA_RESOURCES_DIR.

Documents without sentences are split per paragraph ("\n"); existing sentences without tokens (Tatoeba,
TMX) are tokenised in place; sentences that already have tokens (CoNLL-U) are left untouched.
"""

import functools
import hashlib
import logging
import os
import re
import unicodedata

from engine.model import Document, Sentence, Token

STANZA_PROCESSORS = {"en": "tokenize,mwt,pos,lemma,depparse"}
LANGUAGES = ("en", "zh")
BATCH = 200  # paragraphs / sentences per Stanza call

_CJK = re.compile(r"[㐀-䶿一-鿿豈-﫿]")
_CLOSE = "”’」』）》〉】〕］｝\"')]}"
_SENT_END = re.compile(
    rf"(?:[。！？；!?;…]+|\.+(?=[{re.escape(_CLOSE)}]*(?:\s|$)))[{re.escape(_CLOSE)}]*"
)


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
    if code not in LANGUAGES:
        raise ValueError(f"暂不支持该语言的自动标注：{language}")
    return code


# ---------------------------------------------------------------- Chinese (jieba)


@functools.cache
def _jieba():
    import jieba
    import jieba.posseg

    jieba.setLogLevel(logging.WARNING)
    return jieba.posseg.POSTokenizer(
        jieba.Tokenizer()
    )  # bundled dict.txt, no user words


@functools.cache
def jieba_fingerprint() -> str:
    """jieba version and default-dictionary hash; part of the index version of jieba-tagged corpora."""
    import jieba

    tk = _jieba().tokenizer
    with tk.get_dict_file() as f:
        digest = hashlib.sha256(f.read()).hexdigest()[:16]
    return f"jieba {jieba.__version__} dict {digest} hmm=off"


def _zh_tag(word: str, flag: str) -> str:
    if all(unicodedata.category(c)[0] in "PS" for c in word):
        return "w"
    if word.isdigit():
        return "m"
    return flag


def zh_sentences(text: str, base: int = 0) -> list[tuple[int, int]]:
    """(start, end) of sentences in text (offsets + base), whitespace trimmed, never crossing a newline."""
    out = []
    pos = 0
    for line in text.split("\n"):
        cuts = [m.end() for m in _SENT_END.finditer(line)]
        a = 0
        for b in [*cuts, len(line)]:
            seg = line[a:b]
            if seg.strip():
                lead = len(seg) - len(seg.lstrip())
                out.append((base + pos + a + lead, base + pos + a + len(seg.rstrip())))
            a = b
        pos += len(line) + 1
    return out


def zh_tokens(text: str, start: int, end: int) -> list[Token]:
    """jieba tokens of text[start:end] with document offsets; whitespace is never part of a token."""
    out, i = [], start
    for word, flag in _jieba().cut(text[start:end], HMM=False):
        a, i = i, i + len(word)
        stripped = word.strip()
        if not stripped:
            continue
        a += len(word) - len(word.lstrip())
        b = a + len(stripped)
        if (
            text[a:b] != stripped
        ):  # jieba keeps the input intact; fail loudly if that ever changes
            raise ValueError(f"分词偏移不一致：{stripped!r} @ {a}")
        out.append(Token(a, b, stripped, _zh_tag(stripped, flag), stripped))
    return out


def _annotate_zh(doc: Document) -> None:
    if not doc.sentences:
        for a, b in zh_sentences(doc.text):
            toks = zh_tokens(doc.text, a, b)
            if toks:
                doc.sentences.append(Sentence(toks[0].start, toks[-1].end, toks))
        return
    for s in doc.sentences:
        if not s.tokens:
            s.tokens = zh_tokens(doc.text, s.start, s.end)


# Rough jieba → UPOS map, only to feed Stanza's dependency parser pretagged input.
_JIEBA_UPOS = {
    "n": "NOUN",
    "nr": "PROPN",
    "ns": "PROPN",
    "nt": "PROPN",
    "nz": "PROPN",
    "v": "VERB",
    "a": "ADJ",
    "b": "ADJ",
    "d": "ADV",
    "p": "ADP",
    "r": "PRON",
    "m": "NUM",
    "q": "NOUN",
    "c": "CCONJ",
    "u": "PART",
    "y": "PART",
    "e": "INTJ",
    "o": "INTJ",
    "w": "PUNCT",
    "f": "NOUN",
    "s": "NOUN",
    "t": "NOUN",
}


def _upos(tag: str | None) -> str:
    if not tag:
        return "X"
    for k in (tag[:2], tag[:1]):
        if k in _JIEBA_UPOS:
            return _JIEBA_UPOS[k]
    return "X"


@functools.cache
def _zh_depparse():
    import stanza
    from stanza.pipeline.core import DownloadMethod

    return stanza.Pipeline(
        "zh",
        processors="tokenize,depparse",
        tokenize_pretokenized=True,
        depparse_pretagged=True,
        dir=os.environ.get("STANZA_RESOURCES_DIR"),
        logging_level="WARN",
        download_method=DownloadMethod.REUSE_RESOURCES,
    )


def annotate_dependencies_zh(doc: Document) -> None:
    """P3 pre-annotation: Stanza zh dependency parse over the stored jieba tokens (tokens and POS unchanged;
    Stanza's own POS tagger is not run, jieba tags are mapped to UPOS only as parser input). Not used at import."""
    import stanza

    sents = [s for s in doc.sentences if s.tokens]
    if not sents:
        return
    words = [
        [
            {
                "id": i + 1,
                "text": t.form,
                "lemma": t.form,
                "upos": _upos(t.pos),
                "xpos": t.pos,
            }
            for i, t in enumerate(s.tokens)
        ]
        for s in sents
    ]
    parsed = _zh_depparse()(stanza.Document(words))
    for s, ps in zip(sents, parsed.sentences):
        for t, w in zip(s.tokens, ps.words):
            t.head, t.deprel = w.head, w.deprel


# ---------------------------------------------------------------- English (Stanza)


@functools.cache
def pipeline(lang: str):
    import stanza
    from stanza.pipeline.core import DownloadMethod

    return stanza.Pipeline(
        lang,
        processors=STANZA_PROCESSORS[lang],
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


def _annotate_stanza(doc: Document, lang: str) -> None:
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


def annotate(doc: Document) -> None:
    if not doc.language:
        doc.language = detect_language(doc.text)
    lang = _lang(doc.language)
    if lang == "zh":
        _annotate_zh(doc)
    else:
        _annotate_stanza(doc, lang)
