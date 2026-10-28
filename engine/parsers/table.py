"""CSV / TSV: one Document per row.

Column mapping (per upload batch, stored in the import job's params):
  {"text": [col] or [col, col], "title": col|None, "language": col|None, "metadata": [col…]|None}
Two text columns are joined by a blank line ("headline\n\nabstract"). `metadata` None = every column
not used as text/title/language; values that look like plain numbers become numbers. Without a
mapping `detect()` supplies the defaults: text = first column named text/content/body/sentence/
abstract/正文/内容/句子 (case-insensitive), else the column with the longest average value in the
first rows; title = title/headline/标题; language = language/lang/语言. Rows with empty text are skipped.
"""

import csv
import io
import re
import sys
from pathlib import Path

from engine.model import Document
from engine.parsers import ParseError, decode, read_text

_NUMBER = re.compile(r"(0|[1-9]\d*)(\.\d+)?")
TEXT_NAMES = ("text", "content", "body", "sentence", "abstract", "正文", "内容", "句子")
TITLE_NAMES = ("title", "headline", "标题")
LANGUAGE_NAMES = ("language", "lang", "语言")
SAMPLE_ROWS = 200
PREVIEW_ROWS = 5

csv.field_size_limit(min(sys.maxsize, 2**31 - 1))


def delimiter_for(name: str) -> str:
    return "\t" if name.lower().endswith(".tsv") else ","


def number_or_text(value: str):
    """'1990' → 1990, '2.5' → 2.5; '007', '1,000' and other text stay strings."""
    value = value.strip()
    m = _NUMBER.fullmatch(value)
    if not m:
        return value
    return float(value) if m.group(2) else int(value)


def _header(raw: list[str]) -> list[str]:
    """Strip names; blank → 列N; duplicates → name_2."""
    out = []
    for i, c in enumerate(raw, 1):
        name = c.strip() or f"列{i}"
        base, k = name, 2
        while name in out:
            name, k = f"{base}_{k}", k + 1
        out.append(name)
    return out


def _rows(text: str, delimiter: str, name: str):
    """(columns, iterator of (row number, {column: value}))."""
    reader = csv.reader(io.StringIO(text), delimiter=delimiter)
    try:
        raw = next(reader, None)
    except csv.Error as e:
        raise ParseError(f"{name} 表头无法解析：{e}") from e
    if not raw or not any(c.strip() for c in raw):
        raise ParseError(f"{name} 没有表头")
    columns = _header(raw)

    def rows():
        n = 0
        while True:
            try:
                values = next(reader)
            except StopIteration:
                return
            except csv.Error as e:
                raise ParseError(f"{name} 第 {reader.line_num} 行无法解析：{e}") from e
            if not any(v.strip() for v in values):
                continue
            n += 1
            yield n, dict(zip(columns, values))

    return columns, rows()


def _pick(columns: list[str], names) -> str | None:
    lower = {c.lower(): c for c in reversed(columns)}
    return next((lower[n] for n in names if n in lower), None)


def detect(columns: list[str], sample: list[dict]) -> dict:
    title = _pick(columns, TITLE_NAMES)
    language = _pick(columns, LANGUAGE_NAMES)
    text = _pick(columns, TEXT_NAMES)
    if text is None:
        rest = [c for c in columns if c not in (title, language)] or columns

        def avg(c):
            return sum(len((r.get(c) or "").strip()) for r in sample) / max(
                len(sample), 1
            )

        text = max(rest, key=avg)
    return {"text": [text], "title": title, "language": language, "metadata": None}


def check_mapping(columns: list[str], mapping: dict, name: str) -> dict:
    text = [c for c in mapping.get("text") or [] if c]
    if not 1 <= len(text) <= 2:
        raise ParseError(f"{name} 须选择 1–2 个正文列")
    title, language = mapping.get("title") or None, mapping.get("language") or None
    meta = mapping.get("metadata")
    used = [*text, title, language, *(meta or [])]
    missing = [c for c in used if c and c not in columns]
    if missing:
        raise ParseError(f"{name} 缺少列：{'、'.join(missing)}")
    return {"text": text, "title": title, "language": language, "metadata": meta}


def preview(data: bytes, name: str, *, partial: bool = True) -> dict:
    """Header, first rows and detected defaults of a (possibly truncated) table file."""
    text = decode(data, name, partial=partial)
    if partial and "\n" in text:
        text = text[: text.rindex("\n") + 1]  # drop the cut-off last line
    columns, rows = _rows(text, delimiter_for(name), name)
    sample = []
    for _, row in rows:
        sample.append(row)
        if len(sample) >= SAMPLE_ROWS:
            break
    return {
        "columns": columns,
        "rows": [[r.get(c, "") for c in columns] for r in sample[:PREVIEW_ROWS]],
        "defaults": detect(columns, sample),
    }


def parse(
    path: Path,
    language: str,
    metadata: dict,
    delimiter: str,
    mapping: dict | None = None,
) -> list[Document]:
    columns, rows = _rows(read_text(path), delimiter, path.name)
    if mapping:
        m = check_mapping(columns, mapping, path.name)
    else:
        sample, buffered = [], []
        for item in rows:
            buffered.append(item)
            sample.append(item[1])
            if len(sample) >= SAMPLE_ROWS:
                break
        m = detect(columns, sample)
        rows = _chain(buffered, rows)
    special = {*m["text"], m["title"], m["language"]}
    meta_cols = (
        [c for c in columns if c not in special]
        if m["metadata"] is None
        else [c for c in m["metadata"] if c not in special]
    )
    docs = []
    for n, row in rows:
        text = "\n\n".join(
            v for v in ((row.get(c) or "").strip() for c in m["text"]) if v
        )
        if not text:
            continue
        extra = {
            c: number_or_text(row[c]) for c in meta_cols if (row.get(c) or "").strip()
        }
        title = (row.get(m["title"]) or "").strip() if m["title"] else ""
        lang = (row.get(m["language"]) or "").strip() if m["language"] else ""
        docs.append(
            Document(
                title=title[:500] or f"{path.stem} #{n}",
                language=lang or language,
                text=text,
                metadata={**metadata, **extra},
                sentences=[],
            )
        )
    if not docs:
        raise ParseError(f"{path.name} 正文列（{'、'.join(m['text'])}）没有内容")
    return docs


def _chain(first, rest):
    yield from first
    yield from rest
