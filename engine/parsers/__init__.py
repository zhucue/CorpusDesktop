"""File → Documents (+ sentence alignments for parallel formats).

Format by extension: .txt .docx .csv .tsv .conllu .tmx. Tatoeba: pass the directory holding the
official `*sentences*.tsv[.bz2]` and `*links*.tsv[.bz2]` files of one upload batch; a single
header-less `*sentences*.tsv` is also accepted (no alignments). Only CoNLL-U yields tokens.
"""

from pathlib import Path

from engine.model import Alignment, Document


class ParseError(ValueError):
    pass


def parse(
    path: Path, *, language: str | None, metadata: dict
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
            path, language, metadata, "\t" if name.endswith(".tsv") else ","
        ), []
    if name.endswith(".conllu"):
        return conllu.parse(path, language, metadata), []
    if name.endswith(".tmx"):
        return tmx.parse(path, metadata)
    raise ParseError(f"不支持的文件格式：{path.name}")


def read_text(path: Path) -> str:
    try:
        return (
            path.read_bytes()
            .decode("utf-8-sig")
            .replace("\r\n", "\n")
            .replace("\r", "\n")
        )
    except UnicodeDecodeError as e:
        raise ParseError(f"{path.name} 不是 UTF-8 编码") from e
