"""Tatoeba official exports: `*sentences*.tsv` (id, lang, text[, owner, added, modified]) and `*links*.tsv`
(id, id), optionally .bz2. One Document per language, one sentence per Tatoeba sentence (text joined by
"\n"), Sentence.external_id = Tatoeba id. Links between two loaded sentences of different languages
become one Alignment per pair (reciprocal rows collapse), source = the language that sorts first."""

import bz2
import re
from pathlib import Path

from engine.model import Alignment, Document, Sentence
from engine.parsers import ParseError

LANGS = {
    "cmn": "zh",
    "eng": "en",
    "jpn": "ja",
    "kor": "ko",
    "fra": "fr",
    "deu": "de",
    "spa": "es",
    "rus": "ru",
    "ita": "it",
    "por": "pt",
    "ara": "ar",
    "yue": "yue",
}
_NAME = re.compile(r".*(sentences|links).*\.tsv(\.bz2)?$")


def is_tatoeba_file(path: Path) -> bool:
    if not _NAME.match(path.name.lower()):
        return False
    with _open(path) as f:
        first = f.readline()
    # a header with a `text` column means a plain TSV
    return "text" not in first.rstrip("\n").split("\t")


def _open(path: Path):
    if path.name.lower().endswith(".bz2"):
        return bz2.open(path, "rt", encoding="utf-8", newline="\n")
    return open(path, encoding="utf-8-sig", newline="\n")


def parse_dir(path: Path, metadata: dict) -> tuple[list[Document], list[Alignment]]:
    files = sorted(
        p for p in path.iterdir() if p.is_file() and _NAME.match(p.name.lower())
    )
    if not files:
        raise ParseError(f"{path.name} 中没有 Tatoeba sentences / links 文件")
    return parse_files(files, metadata)


def parse_files(
    files: list[Path], metadata: dict
) -> tuple[list[Document], list[Alignment]]:
    docs: dict[str, dict] = {}
    where: dict[str, str] = {}  # sentence id → tatoeba language
    for p in files:
        if "sentences" not in p.name.lower():
            continue
        with _open(p) as f:
            for lineno, line in enumerate(f, 1):
                fields = line.rstrip("\r\n").split("\t")
                if len(fields) < 3 or not fields[0].isdigit() or not fields[2].strip():
                    raise ParseError(f"{p.name}:{lineno} 不是 Tatoeba 句子行")
                sid, code, text = fields[0], fields[1], fields[2].strip()
                if sid in where:
                    continue
                d = docs.setdefault(code, {"text": [], "sentences": [], "len": 0})
                start = d["len"] + (1 if d["text"] else 0)
                d["text"].append(text)
                d["len"] = start + len(text)
                d["sentences"].append(Sentence(start, start + len(text), [], sid))
                where[sid] = code
    if not docs:
        raise ParseError("缺少 Tatoeba sentences 文件")
    pairs = set()
    for p in files:
        if "links" not in p.name.lower():
            continue
        with _open(p) as f:
            for lineno, line in enumerate(f, 1):
                fields = line.split()
                if len(fields) != 2:
                    raise ParseError(f"{p.name}:{lineno} 不是 Tatoeba 链接行")
                a, b = fields
                if a in where and b in where and where[a] != where[b]:
                    pairs.add((a, b) if where[a] < where[b] else (b, a))
    out = [
        Document(
            title=f"Tatoeba {code}",
            language=LANGS.get(code, code),
            text="\n".join(d["text"]),
            metadata={**metadata, "tatoeba_lang": code},
            sentences=d["sentences"],
        )
        for code, d in docs.items()
    ]
    return out, [
        Alignment(a, b) for a, b in sorted(pairs, key=lambda x: (int(x[0]), int(x[1])))
    ]
