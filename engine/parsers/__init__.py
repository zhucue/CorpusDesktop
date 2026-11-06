"""File → Documents (+ sentence alignments for parallel formats).

Format by extension: .txt .docx .pdf .csv .tsv .xlsx .jsonl .conllu .tmx. Tatoeba: pass the directory
holding the official `*sentences*.tsv[.bz2]` and `*links*.tsv[.bz2]` files of one upload batch; a single
header-less `*sentences*.tsv` is also accepted (no alignments). Only CoNLL-U yields tokens.
CSV/TSV/XLSX/JSONL take an optional field `mapping` (see `table.py`); without it the defaults are detected.
Text files may be UTF-8 (with or without BOM), UTF-16 (with BOM, or detected) or GB18030/GBK.

Every document gets a `source` attribute naming where it came from, for import messages (duplicates):
the file name, or "<file> #n" for row n of a table or JSONL file (see table.py). It is not stored.
"""

import codecs
import hashlib
import re
import unicodedata
from pathlib import Path

from engine.model import Alignment, Document


class ParseError(ValueError):
    pass


def content_hash(text: str) -> str:
    """Import dedup key (contracts/p10.md §七): the text stripped, whitespace runs collapsed to one space,
    NFKC-normalized, as sha256 hex. Migration 0011 inlines the same rule to backfill stored documents."""
    norm = unicodedata.normalize("NFKC", re.sub(r"\s+", " ", text.strip()))
    return hashlib.sha256(norm.encode("utf-8")).hexdigest()


def source_of(doc: Document) -> str:
    """Where a parsed document came from (file, or file and row); the title for documents made elsewhere."""
    return getattr(doc, "source", None) or doc.title


def parse(
    path: Path, *, language: str | None, metadata: dict, mapping: dict | None = None
) -> tuple[list[Document], list[Alignment]]:
    docs, links = _parse(Path(path), language or "", dict(metadata or {}), mapping)
    for d in docs:
        if not getattr(d, "source", None):
            d.source = d.title if Path(path).is_dir() else Path(path).name
    return docs, links


def _parse(path: Path, language: str, metadata: dict, mapping: dict | None):
    from engine.parsers import conllu, pdf, table, tatoeba, text, tmx

    if path.is_dir():
        return tatoeba.parse_dir(path, metadata)
    name = path.name.lower()
    if tatoeba.is_tatoeba_file(path):
        return tatoeba.parse_files([path], metadata)
    if name.endswith(".txt"):
        return [text.parse_txt(path, language, metadata)], []
    if name.endswith(".docx"):
        return [text.parse_docx(path, language, metadata)], []
    if name.endswith(".pdf"):
        return [pdf.parse(path, language, metadata)], []
    if name.endswith((".csv", ".tsv", ".xlsx", ".jsonl")):
        return table.parse(path, language, metadata, mapping=mapping), []
    if name.endswith(".conllu"):
        return conllu.parse(path, language, metadata), []
    if name.endswith(".tmx"):
        return tmx.parse(path, metadata)
    raise ParseError(f"不支持的文件格式：{path.name}")


def _looks_utf16(data: bytes) -> str | None:
    """BOM-less UTF-16: mostly-ASCII/Latin text has a NUL in every other byte."""
    sample = data[:4096]
    if len(sample) < 4:
        return None
    even, odd = sample[0::2].count(0), sample[1::2].count(0)
    half = len(sample) // 2
    if odd > half * 0.3 and even < half * 0.05:
        return "utf-16-le"
    if even > half * 0.3 and odd < half * 0.05:
        return "utf-16-be"
    return None


def detect_encoding(data: bytes, *, partial: bool = False) -> str:
    """UTF-8 (BOM optional) → UTF-16 (BOM or NUL pattern) → GB18030 (superset of GBK/GB2312).
    `partial`: data may be cut mid-character at the end (a preview slice)."""
    if data.startswith(codecs.BOM_UTF8):
        return "utf-8-sig"
    if data.startswith((codecs.BOM_UTF16_LE, codecs.BOM_UTF16_BE)):
        return "utf-16"
    utf16 = _looks_utf16(data)
    if utf16:
        return utf16
    for enc in ("utf-8", "gb18030"):
        try:
            codecs.getincrementaldecoder(enc)().decode(data, final=not partial)
            return enc
        except UnicodeDecodeError:
            continue
    raise ParseError("无法识别编码（支持 UTF-8、GB18030/GBK、UTF-16）")


def decode(data: bytes, name: str, *, partial: bool = False) -> str:
    """Bytes → str with "\n" line endings; ParseError names the file."""
    try:
        enc = detect_encoding(data, partial=partial)
        s = codecs.getincrementaldecoder(enc)(errors="strict").decode(
            data, final=not partial
        )
    except ParseError as e:
        raise ParseError(f"{name} {e}") from e
    except UnicodeDecodeError as e:
        raise ParseError(f"{name} 编码错误：{e}") from e
    s = s.removeprefix(chr(0xFEFF))
    return s.replace("\r\n", "\n").replace("\r", "\n")


def read_text(path: Path) -> str:
    path = Path(path)
    return decode(path.read_bytes(), path.name)
