"""CoNLL-U: tokens keep FORM, LEMMA, UPOS (as pos), HEAD, DEPREL.

One Document per file, or per `# newdoc` when present. Sentence text comes from `# text`; sentences are
joined by "\n" at `# newpar`, otherwise by a space. Token offsets are located in the sentence text; when
`# text` is missing or does not contain the forms, the sentence text is rebuilt from forms (SpaceAfter=No).
Multiword-token parts get their own offsets if their forms occur in the surface form, else the whole surface.
Empty nodes (n.m) are skipped.
"""

from pathlib import Path

from engine.model import Document, Sentence, Token
from engine.parsers import ParseError, read_text


def _value(v: str) -> str | None:
    return None if v == "_" else v


def _split_surface(surface: str, forms: list[str], base: int) -> list[tuple[int, int]]:
    if len(forms) == 1:
        return [(base, base + len(surface))]
    spans, k = [], 0
    for f in forms:
        m = surface.find(f, k)
        if m < 0 or surface[k:m].strip():
            return [(base, base + len(surface))] * len(forms)
        spans.append((base + m, base + m + len(f)))
        k = m + len(f)
    return spans


def _sentence_spans(text: str | None, units) -> tuple[str, list[tuple[int, int]]]:
    """units: [surface, word forms, space_after] → (sentence text, per-word spans relative to it)."""
    if text is not None:
        spans, pos = [], 0
        for surface, forms, _ in units:
            i = text.find(surface, pos)
            if i < 0 or text[pos:i].strip():
                break
            spans.extend(_split_surface(surface, forms, i))
            pos = i + len(surface)
        else:
            return text, spans
    rebuilt, spans = "", []
    for surface, forms, space_after in units:
        spans.extend(_split_surface(surface, forms, len(rebuilt)))
        rebuilt += surface + (" " if space_after else "")
    return rebuilt.rstrip(" "), spans


def parse(path: Path, language: str, metadata: dict) -> list[Document]:
    docs: list[dict] = []
    comments: dict[str, str] = {}
    newpar = False
    rows: list[tuple[int, list[str]]] = []

    def flush():
        nonlocal comments, newpar, rows
        if rows:
            if not docs:
                docs.append({"id": None, "text": "", "sentences": []})
            _add_sentence(path, docs[-1], rows, comments, newpar)
        comments, newpar, rows = {}, False, []

    for lineno, line in enumerate(read_text(path).split("\n"), 1):
        if not line.strip():
            flush()
        elif line.startswith("#"):
            key, eq, value = line[1:].partition("=")
            key = key.strip()
            if key.startswith("newdoc"):
                flush()
                docs.append({"id": value.strip() or None, "text": "", "sentences": []})
            elif key.startswith("newpar"):
                newpar = True
            elif eq and key in ("text", "sent_id"):
                comments[key] = value.strip()
        else:
            f = line.split("\t")
            if len(f) != 10:
                raise ParseError(f"{path.name}:{lineno} 不是 10 列")
            if "." not in f[0]:
                rows.append((lineno, f))
    flush()
    docs = [d for d in docs if d["sentences"]]
    if not docs:
        raise ParseError(f"{path.name} 没有句子")
    return [
        Document(
            title=d["id"] or (path.stem if len(docs) == 1 else f"{path.stem} #{n}"),
            language=language,
            text=d["text"],
            metadata=dict(metadata),
            sentences=d["sentences"],
            external_id=d["id"],
        )
        for n, d in enumerate(docs, 1)
    ]


def _add_sentence(path: Path, doc: dict, rows, comments: dict, newpar: bool) -> None:
    units, words, mwt, mwt_end = [], [], None, 0
    for lineno, f in rows:
        if "-" in f[0]:
            mwt, mwt_end = (
                [f[1], [], "SpaceAfter=No" not in f[9]],
                int(f[0].split("-")[1]),
            )
            units.append(mwt)
            continue
        words.append((lineno, f))
        if mwt is not None and int(f[0]) <= mwt_end:
            mwt[1].append(f[1])
        else:
            mwt = None
            units.append([f[1], [f[1]], "SpaceAfter=No" not in f[9]])
    text, spans = _sentence_spans(comments.get("text"), units)
    if doc["sentences"]:
        doc["text"] += "\n" if newpar else " "
    base = len(doc["text"])
    doc["text"] += text
    tokens = []
    for (lineno, f), (s, e) in zip(words, spans):
        try:
            head = None if f[6] == "_" else int(f[6])
        except ValueError as err:
            raise ParseError(f"{path.name}:{lineno} HEAD 不是数字") from err
        tokens.append(
            Token(
                base + s, base + e, f[1], _value(f[3]), _value(f[2]), head, _value(f[7])
            )
        )
    doc["sentences"].append(
        Sentence(base, base + len(text), tokens, comments.get("sent_id"))
    )
