"""File → Documents (+ sentence alignments for parallel formats).

Format by extension: .txt .docx .csv .tsv .conllu .tmx. Tatoeba: pass the directory holding the
official `*sentences*.tsv[.bz2]` and `*links*.tsv[.bz2]` files of one upload batch; a single
header-less `*sentences*.tsv` is also accepted (no alignments). Only CoNLL-U yields tokens.
CSV/TSV take an optional column `mapping` (see `table.py`); without it the defaults are detected.
Text files may be UTF-8 (with or without BOM), UTF-16 (with BOM, or detected) or GB18030/GBK.
"""

import codecs
from pathlib import Path

from engine.model import Alignment, Document


class ParseError(ValueError):
    pass


def parse(
    path: Path, *, language: str | None, metadata: dict, mapping: dict | None = None
) -> tuple[list[Document], list[Alignment]]:
    from engine.parsers import conllu, table, tatoeba, text, tmx

    path = Path(path)
    language = language or ""
    metadata = dict(metadata or {})
    if path.is_dir():
        return tatoeba.parse_dir(path, metadata)
    name = path.name.lower()
    if tatoeba.is_tatoeba_file(path):
        return tatoeba.parse_files([path], metadata)
    if name.endswith(".txt"):
        return [text.parse_txt(path, language, metadata)], []
    if name.endswith(".docx"):
        return [text.parse_docx(path, language, metadata)], []
    if name.endswith((".csv", ".tsv")):
        return table.parse(
            path, language, metadata, table.delimiter_for(name), mapping
        ), []
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
