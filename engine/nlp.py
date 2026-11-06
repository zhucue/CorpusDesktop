"""Automatic annotation with exact code-point offsets. The language is per document (detected when empty).

Languages (SUPPORTED): zh, en, ja, fr, de, es, ru.

Chinese (zh): jieba. Sentences end at 。！？；… / ! ? ; (and `.` before whitespace or the end), with closing
quotes and brackets kept in the sentence; sentences never cross a newline. Tokens come from jieba.posseg
with the bundled default dictionary and HMM off, so the same text always gives the same tokens. POS are
jieba (ICTCLAS-style) tags (n, nr, ns, v, vn, a, d, p, r, m, q, c, u, uj, x, eng …), except that tokens made
only of punctuation or symbols are tagged `w` and tokens made only of digits `m`. lemma = form; head and
deprel stay empty at import; annotate_dependencies_zh (P3 pre-annotation) parses the stored tokens with Stanza.

Other languages: Stanza (STANZA_PROCESSORS: tokenize, mwt for en / fr / de / es, pos (UPOS), lemma,
depparse). Models live in STANZA_RESOURCES_DIR and are downloaded on first use (`notify("下载 fr 模型")` is
called first; a failed download or load raises ModelError). At most STANZA_MAX_PIPELINES (default 2)
pipelines stay loaded per process; the least recently used one is dropped first (zh dependency parsing
counts as one). Peak memory grows with the text per pipeline call, so each call takes at most BATCH items
and BATCH_WORDS words (whitespace-separated; Japanese: characters / 2; an item longer than that is a call of
its own), and pos / depparse run in batches of STANZA_BATCH: a 4,000-token Word file peaks at about 1.3 GB
instead of 5 GB.

Documents without sentences are split per paragraph ("\n"); existing sentences without tokens (Tatoeba,
TMX) are tokenised in place; sentences that already have tokens (CoNLL-U) are left untouched.

annotate(doc, progress) calls progress(offset) with the code-point offset reached in doc.text after every
BATCH Stanza items and every ZH_PROGRESS Chinese sentences, so callers can report progress inside large documents.
"""

import collections
import contextlib
import ctypes
import functools
import gc
import hashlib
import json
import logging
import os
import re
import unicodedata
import uuid
from pathlib import Path

from engine.model import Document, Sentence, Token

SUPPORTED = ("zh", "en", "ja", "fr", "de", "es", "ru")
LANGUAGES = SUPPORTED
_FULL = "tokenize,mwt,pos,lemma,depparse"
_NO_MWT = "tokenize,pos,lemma,depparse"
STANZA_PROCESSORS = {
    "en": _FULL,
    "fr": _FULL,
    "de": _FULL,
    "es": _FULL,
    "ja": _NO_MWT,
    "ru": _NO_MWT,
}
BATCH = 200  # max paragraphs / sentences per Stanza call; also the progress cadence
BATCH_WORDS = 500  # max words per Stanza call
STANZA_BATCH = 1000  # pos_batch_size / depparse_batch_size (Stanza default 5000)
ZH_PROGRESS = 2000  # Chinese sentences between progress callbacks

_CJK = re.compile(r"[㐀-䶿一-鿿豈-﫿]")
_CLOSE = "”’」』）》〉】〕］｝\"')]}"
_SENT_END = re.compile(
    rf"(?:[。！？；!?;…]+|\.+(?=[{re.escape(_CLOSE)}]*(?:\s|$)))[{re.escape(_CLOSE)}]*"
)


# ---------------------------------------------------------------- language detection
# contracts/p10.md §八, keeping the P9 fixes (contracts/p9.md §十三 语言规则).

CHECK_CHARS = 50_000  # characters of a document sampled
KANA_MIN = 0.05  # share of kana among letters above which a text is Japanese
CYRILLIC_MAJOR = 0.5  # share of Cyrillic letters above which a text is Russian
# share of letters in other scripts (Hangul, Arabic, Greek…) above which a text fails
OTHER_SCRIPT_MAX = 0.3
# share of Han letters above which a text is Chinese (with Latin terms)
MIXED_HAN_MIN = 0.1
FUNCTION_MIN = 0.03  # share of a language's function words among Latin words
MIN_WORDS = 200  # fewer Latin words: never rejected, taken as the best guess
ACCENTED_MIN = 0.01  # share of accented Latin letters (é, ü, ñ, ß…) up to which a Latin text is English
NOT_DETECTED = "未识别语言，请指定（支持 zh、en、ja、fr、de、es、ru）"
OTHER_SCRIPT = "文本的文字不属于支持的语言（zh、en、ja、fr、de、es、ru），请确认语言"


def _class(*ranges):
    return "[" + "".join(f"{chr(a)}-{chr(b)}" for a, b in ranges) + "]"


_HAN = re.compile(
    _class((0x3400, 0x4DBF), (0x4E00, 0x9FFF), (0xF900, 0xFAFF), (0x20000, 0x3134F))
)
_KANA = re.compile(_class((0x3040, 0x30FF), (0x31F0, 0x31FF), (0xFF66, 0xFF9F)))
_CYRILLIC = re.compile(_class((0x0400, 0x052F)))
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
# 30 frequent function words per Latin-script language
_FUNCTION_WORDS = {
    "en": "the of and to a in is that for it as was with be by on not he this are or his from at which"
    " but have an had they",
    "fr": "le la les de des du et est un une que qui dans pour pas sur au aux avec il elle ce cette ne se"
    " son sa ses nous vous",
    "de": "der die das und ist nicht ein eine zu den dem mit von sich des auf für im auch es sie er wir"
    " ich dass wird sind aus bei nach",
    "es": "el la los las de del y que en un una es por con no se lo para su sus al como más pero este"
    " esta son fue ha muy",
    # not supported: recognized only so that they fail instead of being annotated as English
    "it": "il lo la i gli le di del della dei che e è un una per con non si da al alla sono ma come più"
    " anche questo questa nel",
    "pt": "o os a as de do da dos das e que em um uma não com para por no na se ao mais como mas foi ele"
    " ela são também",
    "nl": "de het een en van in is dat op te zijn met voor niet aan er die ook als bij door maar om of uit"
    " naar dan wat nog worden",
}
FUNCTION_WORDS = {k: frozenset(v.split()) for k, v in _FUNCTION_WORDS.items()}


def _detect(text: str) -> tuple[str, str | None]:
    """(language code, problem) over the first CHECK_CHARS characters; problem is NOT_DETECTED or
    OTHER_SCRIPT when the text cannot be taken as a supported language (the code is then a guess).

    Letters only (punctuation, digits, symbols, spaces left out): kana above KANA_MIN → ja; Cyrillic above
    CYRILLIC_MAJOR → ru; other scripts (not Han, kana, Cyrillic or Latin incl. IPA) above OTHER_SCRIPT_MAX →
    OTHER_SCRIPT; Han above MIXED_HAN_MIN → zh (Chinese with English terms stays zh). A Latin text takes
    the language whose FUNCTION_WORDS have the largest share of its words (ties: en); when that is it, pt or
    nl (listed but not supported) the problem is unsupported_message. Below FUNCTION_MIN with
    at least MIN_WORDS words it is NOT_DETECTED, unless accented letters are at most ACCENTED_MIN of the
    letters: English glossaries, reference and title lists, code and IPA have few function words and hardly
    any accents, and are taken as en.
    """
    sample = text[:CHECK_CHARS]
    letters = han = kana = cyr = other = accented = 0
    for c in sample:
        if not c.isalpha():
            continue
        letters += 1
        if _HAN.match(c):
            han += 1
        elif _KANA.match(c):
            kana += 1
        elif _CYRILLIC.match(c):
            cyr += 1
        elif not _LATIN.match(c):
            other += 1
        elif _ACCENTED.match(c) and c not in _NOT_ACCENTED:
            accented += 1
    if not letters:
        return "en", None
    if kana / letters > KANA_MIN:
        return "ja", None
    if cyr / letters > CYRILLIC_MAJOR:
        return "ru", None
    if other / letters > OTHER_SCRIPT_MAX:
        return "en", OTHER_SCRIPT
    if han / letters > MIXED_HAN_MIN:
        return "zh", None
    words = [w.lower() for w in _LATIN_WORD.findall(sample)]
    if not words:
        return "en", None
    shares = {
        lang: sum(w in fw for w in words) / len(words)
        for lang, fw in FUNCTION_WORDS.items()
    }
    best = max(shares, key=lambda k: (shares[k], k == "en"))
    if shares[best] >= FUNCTION_MIN:
        if best not in SUPPORTED:  # Italian, Portuguese, Dutch
            return "en", unsupported_message([best])
        return best, None
    guess = best if shares[best] and best in SUPPORTED else "en"
    if len(words) >= MIN_WORDS and accented / letters > ACCENTED_MIN:
        return guess, NOT_DETECTED
    return guess, None


def detect_language(text: str) -> str:
    """Best-guess language code of a text (see _detect); never fails."""
    return _detect(text)[0]


def language_problem(text: str, language: str | None = None) -> str | None:
    """Why a text cannot be imported, None when it can. Without a language (auto): the detection problem
    (NOT_DETECTED, OTHER_SCRIPT, unsupported_message for it / pt / nl). A given language is trusted, except for a text mostly in other scripts
    (Hangul, Arabic…), which fails with OTHER_SCRIPT."""
    problem = _detect(text)[1]
    if language is None:
        return problem
    return OTHER_SCRIPT if problem == OTHER_SCRIPT else None


def unsupported_message(codes) -> str:
    """Error message for language codes outside SUPPORTED (upload check in the api and the worker)."""
    return f"暂不支持该语言：{'、'.join(codes)}（支持 {'、'.join(SUPPORTED)}）"


_ALIASES = {
    "cmn": "zh",
    "zho": "zh",
    "chi": "zh",
    "eng": "en",
    "jpn": "ja",
    "fra": "fr",
    "fre": "fr",
    "deu": "de",
    "ger": "de",
    "spa": "es",
    "rus": "ru",
}


def lang_code(language: str | None) -> str:
    """Primary language code: zh-Hans / cmn / zho → zh, eng → en, jpn → ja, fra → fr, deu → de, spa → es,
    rus → ru; other codes lower-cased as given."""
    code = (language or "").lower().replace("_", "-").split("-")[0]
    return _ALIASES.get(code, code)


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


def _zh_depparse():
    return _pipeline(
        "zh-dep",
        "zh-hans",
        "zh",
        "tokenize,pos,lemma,depparse",
        tokenize_pretokenized=True,
    )


def annotate_dependencies_zh(doc: Document) -> None:
    """P3 pre-annotation: Stanza zh (simplified) dependency parse over the stored jieba tokens.

    The tokens are passed pretokenized, one list per sentence, so token boundaries never change; Stanza's
    own POS and lemma are computed only as parser input and discarded. Sets head (1-based, 0 = root) and
    deprel on every token of every sentence with tokens; pos, lemma and offsets stay as they are. The
    pipeline is cached with the Stanza pipelines (see _pipeline)."""
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


# ---------------------------------------------------------------- Stanza pipelines


class ModelError(RuntimeError):
    """A Stanza model could not be downloaded or loaded; the message names the language."""


# key → loaded pipeline, least recently used first
_PIPELINES: collections.OrderedDict = collections.OrderedDict()
_notify = None  # callable(message) told before a model download; set with notifying()


@contextlib.contextmanager
def notifying(fn):
    """Within the block, fn(message) is called before a model download ("下载 fr 模型")."""
    global _notify
    previous, _notify = _notify, fn
    try:
        yield
    finally:
        _notify = previous


def max_pipelines() -> int:
    return max(1, int(os.environ.get("STANZA_MAX_PIPELINES") or 2))


def resources_dir() -> str:
    from stanza.resources.common import DEFAULT_MODEL_DIR

    return os.environ.get("STANZA_RESOURCES_DIR") or DEFAULT_MODEL_DIR


def has_models(stanza_lang: str, processors: str) -> bool:
    """The processors' models (and word vectors) are in resources_dir(); otherwise loading downloads them."""
    d = Path(resources_dir()) / stanza_lang
    return all(any((d / p).glob("*.pt")) for p in [*processors.split(","), "pretrain"])


def _release() -> None:
    """Free a dropped pipeline: collect its reference cycles and hand freed heap pages back (glibc)."""
    gc.collect()
    try:
        ctypes.CDLL("libc.so.6").malloc_trim(0)
    except (OSError, AttributeError):
        pass


def _refresh_resources(stanza_lang: str) -> None:
    """Before a language is downloaded, take its entries (model files and md5) from the current upstream
    resources.json of this Stanza release: Stanza replaces models within a release, and the copy kept
    since an earlier download would reject the new files. Other languages keep their entries, so models
    already on disk are not fetched again. Without a resources.json Stanza downloads the whole file."""
    from stanza.resources.common import download_resources_json

    folder = Path(resources_dir())
    path = folder / "resources.json"
    if not path.exists():
        return
    # a unique name: the containers sharing the volume all run as pid 1
    fresh = folder / f".resources-{uuid.uuid4().hex}.json"
    try:
        download_resources_json(str(folder), resources_filepath=str(fresh))
        entry = json.loads(fresh.read_text(encoding="utf-8"))[stanza_lang]
        # read-modify-write: other languages may be downloaded at the same time
        with _file_lock(".resources.lock"):
            resources = json.loads(path.read_text(encoding="utf-8"))
            resources[stanza_lang] = entry
            fresh.write_text(json.dumps(resources, indent=2), encoding="utf-8")
            os.replace(fresh, path)  # atomic: readers see either version whole
    finally:
        fresh.unlink(missing_ok=True)


@contextlib.contextmanager
def _file_lock(name: str):
    """Exclusive lock on resources_dir()/name across processes and containers sharing the stanza volume
    (flock; no lock where fcntl is missing, i.e. outside Linux)."""
    try:
        import fcntl
    except ImportError:
        yield
        return
    folder = Path(resources_dir())
    folder.mkdir(parents=True, exist_ok=True)
    with open(folder / name, "a") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(f, fcntl.LOCK_UN)


def _pipeline(key: str, stanza_lang: str, code: str, processors: str, **options):
    """The cached pipeline for key, loaded (and its models downloaded) when missing. Before loading, the
    least recently used pipelines are dropped so that at most max_pipelines() stay in memory."""
    if key in _PIPELINES:
        _PIPELINES.move_to_end(key)
        return _PIPELINES[key]
    while len(_PIPELINES) >= max_pipelines():
        _PIPELINES.popitem(last=False)
        _release()
    import stanza
    from stanza.pipeline.core import DownloadMethod

    download = not has_models(stanza_lang, processors)
    if download and _notify is not None:
        _notify(f"下载 {code} 模型")
    try:
        # one process at a time loads (and if need be downloads) a language: another one waits here and
        # then finds the files in place
        with _file_lock(f".download-{stanza_lang}.lock"):
            download = not has_models(stanza_lang, processors)
            if download:
                _refresh_resources(stanza_lang)
            nlp = stanza.Pipeline(
                stanza_lang,
                processors=processors,
                pos_batch_size=STANZA_BATCH,
                depparse_batch_size=STANZA_BATCH,
                dir=resources_dir(),
                logging_level="WARN",
                download_method=DownloadMethod.REUSE_RESOURCES,
                **options,
            )
    except Exception as e:  # network, disk and model-file errors from Stanza
        verb = "下载" if download else "加载"
        raise ModelError(f"{verb} {code} 模型失败：{e}"[:500]) from e
    _PIPELINES[key] = nlp
    return nlp


def pipeline(lang: str):
    """Stanza pipeline of a language in STANZA_PROCESSORS (en, ja, fr, de, es, ru)."""
    return _pipeline(lang, lang, lang, STANZA_PROCESSORS[lang])


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


def _words(lang: str, text: str) -> int:
    """Rough word count for batching: whitespace-separated words; Japanese (no spaces) characters / 2."""
    return len(text) // 2 if lang == "ja" else len(text.split())


def _chunks(texts: list[str], lang: str = "en"):
    """Consecutive slices of texts, one per Stanza call: at most BATCH items and BATCH_WORDS words;
    an item longer than BATCH_WORDS goes alone."""
    i = 0
    while i < len(texts):
        j, words = i, 0
        while j < len(texts) and j - i < BATCH:
            n = _words(lang, texts[j])
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
    for part in _chunks(texts, lang):
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
