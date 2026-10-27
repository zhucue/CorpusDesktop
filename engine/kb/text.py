"""Keyword text for PostgreSQL full text search (`to_tsvector('simple', …)`).

CJK runs are segmented by jieba (search mode for stored text, so 语料库 also yields 语料; precise mode for
queries) and joined by spaces; other text is kept and left to the PostgreSQL parser. Queries become an OR of
their words without common function words, ranked by ts_rank.
"""

import re
from html import escape

from engine.nlp import _jieba

_CJK_RUN = re.compile(r"[㐀-䶿一-鿿豈-﫿]+")
_WORD = re.compile(
    r"[㐀-䶿一-鿿豈-﫿]+|[^\W_㐀-䶿一-鿿豈-﫿]+(?:['’][^\W_㐀-䶿一-鿿豈-﫿]+)*"
)
STOPWORDS = frozenset(
    "的 了 是 在 和 与 及 或 也 都 就 而 之 其 这 那 什么 怎么 如何 哪些 为什么 吗 呢 吧 啊 有 对 把 被 从 "  # noqa: SIM905
    "a an the of to in on at for by with and or is are was were be been being it its this that these those what which who how why do does did as from not no".split()
)


def _segment(run: str, search: bool) -> list[str]:
    tokenizer = _jieba().tokenizer
    words = (
        tokenizer.cut_for_search(run, HMM=False)
        if search
        else tokenizer.cut(run, HMM=False)
    )
    return [w for w in words if w.strip()]


def tsv_text(text: str) -> str:
    """Stored text: CJK runs replaced by their jieba words (search mode) separated by spaces."""
    return _CJK_RUN.sub(lambda m: " " + " ".join(_segment(m.group(), True)) + " ", text)


def query_words(q: str) -> list[str]:
    """Lower-cased query words (jieba precise mode for CJK), function words dropped, order kept, unique."""
    out = []
    for m in _WORD.finditer(q):
        word = m.group()
        parts = _segment(word, False) if _CJK_RUN.fullmatch(word) else [word.lower()]
        for w in parts:
            if w not in STOPWORDS and w not in out:
                out.append(w)
    return out


def highlight(text: str, words: list[str], width=160) -> str | None:
    """Snippet (≤ width characters) around the first query word, HTML-escaped, words wrapped in <mark>."""
    low, spans = text.lower(), []
    for w in words:
        i = low.find(w)
        while i >= 0:
            spans.append((i, i + len(w)))
            i = low.find(w, i + len(w))
    if not spans:
        return None
    spans.sort()
    a = max(0, spans[0][0] - width // 3)
    b = min(len(text), a + width)
    out, pos = [], a
    for s, e in spans:
        if s >= pos and e <= b:
            out += [escape(text[pos:s]), "<mark>", escape(text[s:e]), "</mark>"]
            pos = e
    out.append(escape(text[pos:b]))
    return ("…" if a else "") + "".join(out) + ("…" if b < len(text) else "")


def tsquery(words: list[str]) -> str | None:
    """`to_tsquery('simple', …)` text: an OR of quoted words (each a phrase when PostgreSQL splits it)."""
    if not words:
        return None
    return " | ".join(
        "'" + w.replace("'", "''").replace("\\", "\\\\") + "'" for w in words
    )
