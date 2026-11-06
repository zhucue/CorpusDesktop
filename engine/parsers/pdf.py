"""PDF: one Document per file from the text layer, read as in the knowledge base (engine.kb.parse: pypdf,
line breaks inside a paragraph joined). Pages are joined by "\n"; metadata gets `pages` (and `author` when
the file names one). Title: the PDF title, else a title-like first line of page 1, else the file name.
A PDF without a text layer (a scan) fails: there is no OCR."""

from pathlib import Path

from engine.model import Document
from engine.parsers import ParseError

NO_TEXT_LAYER = "PDF 没有文字层（扫描件），暂不支持 OCR"


def parse(path: Path, language: str, metadata: dict) -> Document:
    from engine.kb import parse as kbparse

    path = Path(path)
    try:
        blocks, meta = kbparse.parse(path, "pdf")
    except kbparse.ParseError as e:
        if "没有可提取的文字" in str(e):
            raise ParseError(f"{path.name}：{NO_TEXT_LAYER}") from e
        raise ParseError(str(e)) from e
    text = "\n".join(b["text"].strip() for b in blocks if b["text"].strip())
    if not text:
        raise ParseError(f"{path.name}：{NO_TEXT_LAYER}")
    extra = {"pages": meta["pages"]}
    if meta.get("author"):
        extra["author"] = meta["author"]
    return Document(
        title=(meta.get("title") or path.stem)[:500],
        language=language,
        text=text,
        metadata={**metadata, **extra},
        sentences=[],
    )
