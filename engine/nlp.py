"""Automatic annotation with exact code-point offsets. The language is per document (detected when empty).

Chinese (zh): jieba. Sentences end at 。！？；… / ! ? ; (and `.` before whitespace or the end), with closing
quotes and brackets kept in the sentence; sentences never cross a newline. Tokens come from jieba.posseg
with the bundled default dictionary and HMM off, so the same text always gives the same tokens. POS are
jieba (ICTCLAS-style) tags (n, nr, ns, v, vn, a, d, p, r, m, q, c, u, uj, x, eng …), except that tokens made
only of punctuation or symbols are tagged `w` and tokens made only of digits `m`. lemma = form; head and
deprel stay empty at import; annotate_dependencies_zh (P3 pre-annotation) parses the stored tokens with Stanza.

English (en): Stanza tokenize, mwt, pos (UPOS), lemma, depparse; pipelines load lazily from
STANZA_RESOURCES_DIR. Peak memory grows with the text per pipeline call, so each call takes at most BATCH
items and BATCH_WORDS whitespace-separated words (an item longer than that is a call of its own), and pos /
depparse run in batches of STANZA_BATCH: a 4,000-token Word file peaks at about 1.3 GB instead of 5 GB.

Documents without sentences are split per paragraph ("\n"); existing sentences without tokens (Tatoeba,
TMX) are tokenised in place; sentences that already have tokens (CoNLL-U) are left untouched.

annotate(doc, progress) calls progress(offset) with the code-point offset reached in doc.text after every
BATCH Stanza items and every ZH_PROGRESS Chinese sentences, so callers can report progress inside large documents.
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
BATCH = 200  # max paragraphs / sentences per Stanza call; also the progress cadence
BATCH_WORDS = 500  # max words per Stanza call
STANZA_BATCH = 1000  # pos_batch_size / depparse_batch_size (Stanza default 5000)
ZH_PROGRESS = 2000  # Chinese sentences between progress callbacks

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


# Language check at import (contracts/p9.md §九): only Chinese and English are annotated.
SUPPORTED = ("zh", "en")
OTHER_SCRIPT_MAX = 0.3  # share of letters neither Han nor Latin
EN_FUNCTION_MIN = 0.03  # share of English function words among Latin words
EN_MIN_WORDS = 200  # fewer Latin words: the function-word test is skipped
ACCENTED_MIN = (
    0.01  # share of accented Latin letters (é, ü, ñ, ß…) for the function-word test
)
MIXED_HAN_MIN = (
    0.1  # share of Han letters from which a text counts as Chinese-English mixed
)
CHECK_CHARS = 50_000  # characters of a document sampled
NOT_ZH_EN = "未识别为中文或英文，请确认语言；暂只支持中英"
NOT_EN = "可能不是英文，请确认语言；暂只支持中英，可指定 zh 或 en 后重试"


def _class(*ranges):
    return "[" + "".join(f"{chr(a)}-{chr(b)}" for a, b in ranges) + "]"


_HAN = re.compile(
    _class((0x3400, 0x4DBF), (0x4E00, 0x9FFF), (0xF900, 0xFAFF), (0x20000, 0x3134F))
)
# Latin with IPA, spacing modifier letters, phonetic extensions and full-width letters
_LATIN = re.compile(
    _class(
        (0x41, 0x5A),
        (0x61, 0x7A),
        (0xC0, 0x24F),
        (0x250, 0x2FF),
        (0x1D00, 0x1DBF),
        (0x1E00, 0x1EFF),
        (0xFF21, 0xFF3A),
        (0xFF41, 0xFF5A),
    )
)
# accented letters of Latin-1 Supplement / Extended-A / B; letters also used in IPA (æ ð þ ø ŋ ħ, clicks) are left out
_ACCENTED = re.compile(_class((0xC0, 0xD6), (0xD8, 0xF6), (0xF8, 0x24F)))
_NOT_ACCENTED = set("æÆðÐþÞøØŋŊħĦǀǁǂǃ")
_LATIN_WORD = re.compile(_class((0x41, 0x5A), (0x61, 0x7A), (0xC0, 0x24F)) + "+")
# the 50 most frequent English words (function words), as in common frequency lists
_EN_TOP50 = (
    "the of and to a in is that for it as was with be by on not he i this are or his from at which but have"
    " an had they you were their one all we can her has there been if more when will would who so no"
)
EN_FUNCTION_WORDS = frozenset(_EN_TOP50.split())


def language_problem(text: str, check_english: bool = True) -> str | None:
    """Why a text is not taken as Chinese or English, None when it is. Over the first CHECK_CHARS characters:
    letters (punctuation, digits, symbols and spaces left out) that are neither Han nor Latin (Latin includes
    IPA; Cyrillic, kana, Hangul, Arabic… are other) above OTHER_SCRIPT_MAX → NOT_ZH_EN. With check_english, a
    Latin text (Han below MIXED_HAN_MIN of the letters) with accented letters above ACCENTED_MIN and at least
    EN_MIN_WORDS words of which fewer than EN_FUNCTION_MIN are EN_FUNCTION_WORDS → NOT_EN. English glossaries,
    reference lists and title lists have few function words but hardly any accented letters, so they pass."""
    sample = text[:CHECK_CHARS]
    letters = other = han = accented = 0
    for c in sample:
        if c.isalpha():
            letters += 1
            if _HAN.match(c):
                han += 1
            elif not _LATIN.match(c):
                other += 1
            elif _ACCENTED.match(c) and c not in _NOT_ACCENTED:
                accented += 1
    if not letters:
        return None
    if other / letters > OTHER_SCRIPT_MAX:
        return NOT_ZH_EN
    if (
        check_english
        and han / letters < MIXED_HAN_MIN
        and accented / letters > ACCENTED_MIN
    ):
        words = [w.lower() for w in _LATIN_WORD.findall(sample)]
        if len(words) >= EN_MIN_WORDS:
            hits = sum(w in EN_FUNCTION_WORDS for w in words)
            if hits / len(words) < EN_FUNCTION_MIN:
                return NOT_EN
    return None


def lang_code(language: str | None) -> str:
    """Primary language code: zh-Hans / cmn / zho → zh, eng → en; other codes lower-cased as given."""
    code = (language or "").lower().replace("_", "-").split("-")[0]
    return {"cmn": "zh", "eng": "en", "zho": "zh", "chi": "zh"}.get(code, code)


# Frequent characters written differently in simplified and traditional Chinese, pairwise.
_HANS = "为与并后时说个们这国会来对过还发经学问门见让间长开关东车马鱼书图画点电话听写读语认记级华业体区实现动种应无进头产从将两当机气万处义乐历网员"
_HANT = "為與並後時說個們這國會來對過還發經學問門見讓間長開關東車馬魚書圖畫點電話聽寫讀語認記級華業體區實現動種應無進頭產從將兩當機氣萬處義樂歷網員"
SCRIPT_MIN_HITS = 5


def detect_script(text: str) -> str | None:
    """Chinese script of a text sample: "simplified", "traditional" or "mixed" (from the share of
    traditional forms among SCRIPT_MIN_HITS+ telling characters); None when the sample has too few."""
    hans = sum(text.count(c) for c in _HANS)
    hant = sum(text.count(c) for c in _HANT)
    if hans + hant < SCRIPT_MIN_HITS:
        return None
    share = hant / (hans + hant)
    if share >= 0.85:
        return "traditional"
    if share <= 0.15:
        return "simplified"
    return "mixed"


def _lang(language: str) -> str:
    code = lang_code(language)
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


def _annotate_zh(doc: Document, progress) -> None:
    if not doc.sentences:
        for i, (a, b) in enumerate(zh_sentences(doc.text), 1):
            toks = zh_tokens(doc.text, a, b)
            if toks:
                doc.sentences.append(Sentence(toks[0].start, toks[-1].end, toks))
            if i % ZH_PROGRESS == 0:
                progress(b)
        return
    for i, s in enumerate(doc.sentences, 1):
        if not s.tokens:
            s.tokens = zh_tokens(doc.text, s.start, s.end)
        if i % ZH_PROGRESS == 0:
            progress(s.end)


# Rough jieba → UPOS map, for the UPOS column of CoNLL-U exports of jieba-tagged text.
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


def jieba_upos(tag: str | None) -> str:
    if not tag or tag == "eng":
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
        "zh-hans",
        processors="tokenize,pos,lemma,depparse",
        tokenize_pretokenized=True,
        pos_batch_size=STANZA_BATCH,
        depparse_batch_size=STANZA_BATCH,
        dir=os.environ.get("STANZA_RESOURCES_DIR"),
        logging_level="WARN",
        download_method=DownloadMethod.REUSE_RESOURCES,
    )


def annotate_dependencies_zh(doc: Document) -> None:
    """P3 pre-annotation: Stanza zh (simplified) dependency parse over the stored jieba tokens.

    The tokens are passed pretokenized, one list per sentence, so token boundaries never change; Stanza's
    own POS and lemma are computed only as parser input and discarded. Sets head (1-based, 0 = root) and
    deprel on every token of every sentence with tokens; pos, lemma and offsets stay as they are. The
    pipeline loads once per process from STANZA_RESOURCES_DIR."""
    sents = [s for s in doc.sentences if s.tokens]
    for i in range(0, len(sents), BATCH):
        part = sents[i : i + BATCH]
        parsed = _zh_depparse()([[t.form for t in s.tokens] for s in part])
        for s, ps in zip(part, parsed.sentences, strict=True):
            words = ps.words
            if len(words) != len(s.tokens):
                raise ValueError(
                    f"依存分析 token 数不一致：{len(words)} ≠ {len(s.tokens)}"
                )
            for t, w in zip(s.tokens, words):
                t.head, t.deprel = w.head, w.deprel


# ---------------------------------------------------------------- English (Stanza)


@functools.cache
def pipeline(lang: str):
    import stanza
    from stanza.pipeline.core import DownloadMethod

    return stanza.Pipeline(
        lang,
        processors=STANZA_PROCESSORS[lang],
        pos_batch_size=STANZA_BATCH,
        depparse_batch_size=STANZA_BATCH,
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


def _chunks(texts: list[str]):
    """Consecutive slices of texts, one per Stanza call: at most BATCH items and BATCH_WORDS words;
    an item longer than BATCH_WORDS goes alone."""
    i = 0
    while i < len(texts):
        j, words = i, 0
        while j < len(texts) and j - i < BATCH:
            n = len(texts[j].split())
            if j > i and words + n > BATCH_WORDS:
                break
            words += n
            j += 1
        yield texts[i:j]
        i = j


def _process(lang: str, texts: list[str]):
    """One Stanza document per text, in order."""
    import stanza

    nlp = pipeline(lang)
    for part in _chunks(texts):
        yield from nlp.bulk_process([stanza.Document([], text=t) for t in part])


def _annotate_stanza(doc: Document, lang: str, progress) -> None:
    if not doc.sentences:
        paras, pos = [], 0
        for line in doc.text.split("\n"):
            if line.strip():
                paras.append((pos, line))
            pos += len(line) + 1
        for i, ((base, line), sd) in enumerate(
            zip(paras, _process(lang, [p for _, p in paras])), 1
        ):
            for sent in sd.sentences:
                toks = _tokens(sent, base)
                if toks:
                    doc.sentences.append(Sentence(toks[0].start, toks[-1].end, toks))
            if i % BATCH == 0:
                progress(base + len(line))
        return
    todo = [
        s for s in doc.sentences if not s.tokens and doc.text[s.start : s.end].strip()
    ]
    for i, (s, sd) in enumerate(
        zip(todo, _process(lang, [doc.text[s.start : s.end] for s in todo])), 1
    ):
        s.tokens = [t for sent in sd.sentences for t in _tokens(sent, s.start)]
        if i % BATCH == 0:
            progress(s.end)


def _ignore(_offset: int) -> None:
    pass


def annotate_many(docs: list[Document], progress=None) -> None:
    """Annotate documents in order. Paragraphs of unsentenced Stanza-language documents are batched
    across documents: a 12,000-row CSV otherwise pays one pipeline call per row (about 50 words/s
    instead of several hundred). progress(offset): characters into the concatenated texts, may step
    back when Chinese and Stanza documents are mixed."""
    progress = progress or _ignore
    pending: dict[str, list] = {}
    base = 0
    for doc in docs:
        if not doc.language:
            doc.language = detect_language(doc.text)
        lang = _lang(doc.language)
        if lang == "zh" or doc.sentences:
            annotate(doc, lambda off, b=base: progress(b + off))
        else:
            pos = 0
            for line in doc.text.split("\n"):
                if line.strip():
                    pending.setdefault(lang, []).append((doc, base, pos, line))
                pos += len(line) + 1
        base += len(doc.text)
    for lang, items in pending.items():
        texts = [line for *_, line in items]
        for i, ((doc, doc_base, para, line), sd) in enumerate(
            zip(items, _process(lang, texts)), 1
        ):
            for sent in sd.sentences:
                toks = _tokens(sent, para)
                if toks:
                    doc.sentences.append(Sentence(toks[0].start, toks[-1].end, toks))
            if i % BATCH == 0:
                progress(doc_base + para + len(line))


def annotate(doc: Document, progress=None) -> None:
    if not doc.language:
        doc.language = detect_language(doc.text)
    lang = _lang(doc.language)
    if lang == "zh":
        _annotate_zh(doc, progress or _ignore)
    else:
        _annotate_stanza(doc, lang, progress or _ignore)
