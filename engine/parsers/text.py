"""Plain text and Word: non-empty paragraphs joined by "\n", one Document per file, no sentences."""

from pathlib import Path

from engine.model import Document
from engine.parsers import ParseError, read_text


def _document(
    path: Path, title: str, paragraphs, language: str, metadata: dict
) -> Document:
    paragraphs = [p.strip() for p in paragraphs]
    text = "\n".join(p for p in paragraphs if p)
    if not text:
        raise ParseError(f"{path.name} 没有正文")
    return Document(
        title=title, language=language, text=text, metadata=metadata, sentences=[]
    )


def parse_txt(path: Path, language: str, metadata: dict) -> Document:
    return _document(path, path.stem, read_text(path).split("\n"), language, metadata)


def parse_docx(path: Path, language: str, metadata: dict) -> Document:
    import docx

    try:
        d = docx.Document(str(path))
    except Exception as e:  # python-docx raises several zip/xml errors
        raise ParseError(f"{path.name} 无法读取：{e}") from e
    title = (d.core_properties.title or "").strip() or path.stem
    return _document(path, title, (p.text for p in d.paragraphs), language, metadata)
