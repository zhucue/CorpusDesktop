"""Blocks → chunks of about SIZE characters with OVERLAP characters of overlap.

Consecutive blocks of one section (same page, same heading path) are joined by "\n" and cut; a chunk never
crosses a section. Cuts prefer, within the second half of the window, a line break, then a sentence end, then a
comma, then a space. An overlap never starts inside a Latin word. A chunk's locator is that of the block where
it starts (so md / txt chunks keep their first line number).
"""

from bisect import bisect_right
from itertools import groupby

SIZE, OVERLAP = 500, 80
_BREAKS = (
    ("\n",),
    ("。", "！", "？", "；", ". ", "! ", "? ", "; "),
    ("，", "、", ", "),
    (" ",),
)


def _section(locator):
    return locator.get("page"), tuple(locator.get("heading_path") or ())


def _cut(text, a, b):
    lo = a + (b - a) // 2
    for seps in _BREAKS:
        hits = [i + len(s) for s in seps if (i := text.rfind(s, lo, b)) >= 0]
        if hits:
            return max(hits)
    return b


def _word_start(text, p, limit):
    while (
        p < limit
        and text[p - 1].isascii()
        and text[p - 1].isalnum()
        and text[p].isalnum()
    ):
        p += 1
    return p


def chunk(blocks: list[dict], size=SIZE, overlap=OVERLAP) -> list[dict]:
    out = []
    for _, group in groupby(blocks, key=lambda b: _section(b["locator"])):
        group = list(group)
        text, starts = "", []
        for b in group:
            text += "\n" if text else ""
            starts.append(len(text))
            text += b["text"]
        pos = 0
        while pos < len(text):
            end = len(text) if len(text) - pos <= size else _cut(text, pos, pos + size)
            piece = text[pos:end]
            lead = len(piece) - len(piece.lstrip())
            if piece.strip():
                block = group[bisect_right(starts, pos + lead) - 1]
                out.append({"text": piece.strip(), "locator": dict(block["locator"])})
            if end >= len(text):
                break
            pos = _word_start(text, max(end - overlap, pos + 1), end)
    return out
