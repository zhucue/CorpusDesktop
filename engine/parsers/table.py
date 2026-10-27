"""CSV / TSV: one Document per row. Column `text` required; `title`, `language` optional; other columns → metadata."""

import csv
import io
import re
from pathlib import Path

from engine.model import Document
from engine.parsers import ParseError, read_text

_NUMBER = re.compile(r"(0|[1-9]\d*)(\.\d+)?")


def number_or_text(value: str):
    """'1990' → 1990, '2.5' → 2.5; '007', '1,000' and other text stay strings."""
    value = value.strip()
    m = _NUMBER.fullmatch(value)
    if not m:
        return value
    return float(value) if m.group(2) else int(value)


def parse(path: Path, language: str, metadata: dict, delimiter: str) -> list[Document]:
    reader = csv.DictReader(io.StringIO(read_text(path)), delimiter=delimiter)
    columns = [c.strip() for c in reader.fieldnames or []]
    if "text" not in columns:
        raise ParseError(f"{path.name} 缺少 text 列")
    reader.fieldnames = columns
    docs = []
    for n, row in enumerate(reader, 1):
        text = (row.get("text") or "").strip()
        if not text:
            continue
        extra = {
            k: number_or_text(v)
            for k, v in row.items()
            if k and k not in ("text", "title", "language") and v not in (None, "")
        }
        docs.append(
            Document(
                title=(row.get("title") or "").strip() or f"{path.stem} #{n}",
                language=(row.get("language") or "").strip() or language,
                text=text,
                metadata={**metadata, **extra},
                sentences=[],
            )
        )
    if not docs:
        raise ParseError(f"{path.name} 没有正文行")
    return docs
