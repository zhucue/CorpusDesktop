"""Checking model answers for span / relation pre-annotation (contracts/p5.md §三).

Spans come back as [{id, text, start, end, label, attrs}] with offsets relative to the sentence (code points).
An item is kept when `text` occurs in the sentence: at start..end if that matches, else at the occurrence
nearest to `start` (models miscount); without `text`, start..end must be a valid range. Edges are trimmed of
whitespace. Labels may be given by id or by name. Relations: [{id, from, to, label}] with 1-based span numbers.
"""


def _int(x):
    return x if isinstance(x, int) and not isinstance(x, bool) else None


def _attrs(value) -> dict:
    if not isinstance(value, dict):
        return {}
    return {
        str(k)[:64]: str(v)[:200]
        for k, v in list(value.items())[:20]
        if isinstance(v, (str, int, float)) and not isinstance(v, bool) and str(k)
    }


def label_of(value, labels: dict) -> str | None:
    """Label id for an id or a name ({id: {"name"...}})."""
    if not isinstance(value, str):
        return None
    value = value.strip()
    if value in labels:
        return value
    return next((k for k, v in labels.items() if v.get("name") == value), None)


def locate(sentence: str, text, start, end) -> tuple[int, int] | None:
    start, end = _int(start), _int(end)
    if isinstance(text, str) and text.strip():
        text = text.strip()
        if start is not None and sentence[start : start + len(text)] == text:
            a, b = start, start + len(text)
        else:
            found, i = [], sentence.find(text)
            while i >= 0:
                found.append(i)
                i = sentence.find(text, i + 1)
            if not found:
                return None
            a = min(found, key=lambda x: abs(x - (start or 0)))
            b = a + len(text)
    elif start is not None and end is not None and 0 <= start < end <= len(sentence):
        a, b = start, end
    else:
        return None
    while a < b and sentence[a].isspace():
        a += 1
    while b > a and sentence[b - 1].isspace():
        b -= 1
    return (a, b) if a < b else None


def clean_spans(items, sentences: dict, labels: dict) -> tuple[dict, int]:
    """items from the model; sentences {id: text} → ({id: [(start, end, label, attrs)]}, dropped count)."""
    out, dropped, seen = {}, 0, set()
    for item in items if isinstance(items, list) else []:
        if not isinstance(item, dict):
            dropped += 1
            continue
        sid = _int(item.get("id"))
        label = label_of(item.get("label"), labels)
        if sid not in sentences or label is None:
            dropped += 1
            continue
        where = locate(
            sentences[sid],
            item.get("text"),
            item.get("start", item.get("start_cp")),
            item.get("end", item.get("end_cp")),
        )
        if where is None or (sid, *where, label) in seen:
            dropped += where is None
            continue
        seen.add((sid, *where, label))
        out.setdefault(sid, []).append((*where, label, _attrs(item.get("attrs"))))
    return out, dropped


def clean_relations(items, span_counts: dict, labels: dict) -> tuple[dict, int]:
    """items [{id, from, to, label}] with 1-based span numbers; span_counts {id: n} →
    ({id: [(from index 0-based, to index 0-based, label)]}, dropped count)."""
    out, dropped, seen = {}, 0, set()
    for item in items if isinstance(items, list) else []:
        if not isinstance(item, dict):
            dropped += 1
            continue
        sid = _int(item.get("id"))
        a, b = _int(item.get("from")), _int(item.get("to"))
        label = label_of(item.get("label"), labels)
        n = span_counts.get(sid, 0)
        if (
            label is None
            or a is None
            or b is None
            or not (1 <= a <= n and 1 <= b <= n)
            or a == b
        ):
            dropped += 1
            continue
        if (sid, a, b, label) in seen:
            continue
        seen.add((sid, a, b, label))
        out.setdefault(sid, []).append((a - 1, b - 1, label))
    return out, dropped
