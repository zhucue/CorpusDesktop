"""TMX: one Document per language, one sentence per <tuv>; Alignment per <tu> from the source language
(header srclang, else the first tuv) to each other language. Language from xml:lang (TMX 1.4) or
lang (TMX 1.1); inline codes (bpt/ept/ph/it/ut) inside <seg> are dropped, other inline tags keep their text.
Sentence ids: "<file stem>:<tu number>:<lang>"."""

from pathlib import Path

from engine.model import Alignment, Document, Sentence
from engine.parsers import ParseError

XML_LANG = "{http://www.w3.org/XML/1998/namespace}lang"
_CODES = {"bpt", "ept", "ph", "it", "ut"}  # inline native codes, not text


def _lang(code: str) -> str:
    return code.strip().lower().replace("_", "-").split("-")[0]


def _seg_text(el) -> str:
    parts = [el.text or ""]
    for child in el:
        tag = child.tag.split("}")[-1] if isinstance(child.tag, str) else ""
        if tag not in _CODES and isinstance(child.tag, str):
            parts.append(_seg_text(child))
        parts.append(child.tail or "")
    return " ".join("".join(parts).split())


def parse(path: Path, metadata: dict) -> tuple[list[Document], list[Alignment]]:
    from lxml import etree

    try:
        root = etree.parse(
            str(path),
            etree.XMLParser(resolve_entities=False, no_network=True, huge_tree=True),
        ).getroot()
    except (etree.XMLSyntaxError, OSError) as e:
        raise ParseError(f"{path.name} 不是有效的 TMX：{e}") from e
    header = root.find("{*}header")
    src_lang = _lang(header.get("srclang", "")) if header is not None else ""
    docs: dict[str, dict] = {}
    alignments = []
    for n, tu in enumerate(root.iter("{*}tu"), 1):
        ids = {}
        for tuv in tu.findall("{*}tuv"):
            lang = _lang(tuv.get(XML_LANG) or tuv.get("lang") or "")
            seg = tuv.find("{*}seg")
            text = _seg_text(seg) if seg is not None else ""
            if not lang or not text or lang in ids:
                continue
            d = docs.setdefault(lang, {"text": [], "sentences": [], "len": 0})
            start = d["len"] + (1 if d["text"] else 0)
            sid = f"{path.stem}:{n}:{lang}"
            d["text"].append(text)
            d["len"] = start + len(text)
            d["sentences"].append(Sentence(start, start + len(text), [], sid))
            ids[lang] = sid
        src = src_lang if src_lang in ids else next(iter(ids), None)
        alignments += [
            Alignment(ids[src], sid) for lang, sid in ids.items() if lang != src
        ]
    if not docs:
        raise ParseError(f"{path.name} 没有可用的翻译单元")
    return [
        Document(
            title=f"{path.stem} ({lang})",
            language=lang,
            text="\n".join(d["text"]),
            metadata=dict(metadata),
            sentences=d["sentences"],
        )
        for lang, d in docs.items()
    ], alignments
