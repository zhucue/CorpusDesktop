"""Plain text and Word: non-empty paragraphs joined by "\n", one Document per file, no sentences.

TXT: encoding detected by `read_text`; CRLF/CR become "\n". Word: body paragraphs (headings included)
and table cells in document order, one line per cell paragraph (merged cells once); text boxes,
footnotes, headers/footers and images are not read.
"""

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


def _docx_lines(container):
    from docx.table import Table

    for item in container.iter_inner_content():
        if isinstance(item, Table):
            seen = set()
            for row in item.rows:
                for cell in row.cells:
                    if (
                        cell._tc in seen
                    ):  # merged cells repeat; the set keeps elements alive
                        continue
                    seen.add(cell._tc)
                    yield from _docx_lines(cell)
        else:
            yield item.text


def parse_docx(path: Path, language: str, metadata: dict) -> Document:
    import docx

    try:
        d = docx.Document(str(path))
        title = (d.core_properties.title or "").strip() or path.stem
        lines = list(_docx_lines(d))
    except Exception as e:  # python-docx raises several zip/xml errors
        raise ParseError(f"{path.name} 无法读取：{e}") from e
    return _document(path, title, lines, language, metadata)
