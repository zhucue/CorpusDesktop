"""CSV / TSV / XLSX / JSONL: one Document per row (JSONL: per line).

Field mapping (per upload batch, stored in the import job's params):
  {"text": [col] or [col, col], "title": col|None, "language": col|None, "metadata": [col…]|None,
   "sheet": name|None}
Columns are the header row of CSV / TSV / XLSX and the keys of the JSONL objects (in order of first
appearance; nested objects give dotted keys such as meta.year, arrays become JSON text). XLSX reads `sheet`, else the first sheet;
cells are read as values (formulas as their cached result), whole numbers as integers, dates as ISO text.
Two text columns are joined by a blank line ("headline\n\nabstract"). `metadata` None = every column
not used as text/title/language; text values that look like plain numbers become numbers (JSON / XLSX
numbers stay numbers). Without a mapping `detect()` supplies the defaults: text = first column named
text/content/body/sentence/abstract/正文/内容/句子 (case-insensitive), else the column with the longest
average value in the first rows; title = title/headline/标题; language = language/lang/语言. Rows with
empty text are skipped. Row n (1-based, header and blank rows not counted) is titled "<file stem> #n"
when there is no title, and its `source` is "<file> #n".
"""

import csv
import io
import json
import re
import sys
from datetime import date, datetime, time
from pathlib import Path

from engine.model import Document
from engine.parsers import ParseError, decode, read_text

_NUMBER = re.compile(r"(0|[1-9]\d*)(\.\d+)?")
TEXT_NAMES = ("text", "content", "body", "sentence", "abstract", "正文", "内容", "句子")
TITLE_NAMES = ("title", "headline", "标题")
LANGUAGE_NAMES = ("language", "lang", "语言")
SAMPLE_ROWS = 200
PREVIEW_ROWS = 5
KINDS = {".csv": "csv", ".tsv": "tsv", ".xlsx": "xlsx", ".jsonl": "jsonl"}

csv.field_size_limit(min(sys.maxsize, 2**31 - 1))


def kind_of(name: str) -> str | None:
    return KINDS.get(Path(name.lower()).suffix)


def delimiter_for(name: str) -> str:
    return "\t" if name.lower().endswith(".tsv") else ","


def number_or_text(value: str):
    """'1990' → 1990, '2.5' → 2.5; '007', '1,000' and other text stay strings."""
    value = value.strip()
    m = _NUMBER.fullmatch(value)
    if not m:
        return value
    return float(value) if m.group(2) else int(value)


def _text(value) -> str:
    """A cell as stripped text ("" for empty)."""
    if value is None:
        return ""
    return (value if isinstance(value, str) else str(value)).strip()


def _meta(value):
    """A metadata cell: text that looks like a number becomes one; numbers and booleans stay as they are."""
    return number_or_text(value) if isinstance(value, str) else value


def _header(raw) -> list[str]:
    """Strip names; blank → 列N; duplicates → name_2."""
    out = []
    for i, c in enumerate(raw, 1):
        name = _text(c) or f"列{i}"
        base, k = name, 2
        while name in out:
            name, k = f"{base}_{k}", k + 1
        out.append(name)
    return out


# ---------------------------------------------------------------- readers: (columns, iterator of (n, row))


def _csv_rows(text: str, delimiter: str, name: str):
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


def _cell(value):
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, datetime):
        return (
            value.date().isoformat()
            if value.time() == time()
            else value.isoformat(sep=" ")
        )
    if isinstance(value, (date, time)):
        return value.isoformat()
    return value


def _workbook(source, name: str):
    from openpyxl import load_workbook

    try:
        return load_workbook(source, read_only=True, data_only=True)
    except Exception as e:  # zip, XML and openpyxl errors
        raise ParseError(f"{name} 不是有效的 XLSX 文件") from e


def _xlsx_rows(wb, name: str, sheet: str | None):
    """(columns, rows, sheet names, sheet read) of a workbook; the header is the first non-empty row."""
    sheets = wb.sheetnames
    if sheet and sheet not in sheets:
        raise ParseError(f"{name} 没有工作表：{sheet}")
    ws = wb[sheet or sheets[0]]
    it = ws.iter_rows(values_only=True)
    raw = next((r for r in it if any(_text(v) for v in r)), None)
    if raw is None:
        raise ParseError(f"{name} 工作表 {ws.title} 没有数据")
    columns = _header(raw)

    def rows():
        n = 0
        for values in it:
            if not any(_text(v) for v in values):
                continue
            n += 1
            yield n, dict(zip(columns, map(_cell, values)))

    return columns, rows(), sheets, ws.title


def _flatten(obj: dict, prefix: str = ""):
    """(key, value) pairs of a JSON object; nested objects become dotted keys (meta.year), arrays JSON text."""
    for k, v in obj.items():
        key = prefix + (str(k).strip() or "列")
        if isinstance(v, dict) and v:
            yield from _flatten(v, key + ".")
        elif isinstance(v, (dict, list)):
            yield key, json.dumps(v, ensure_ascii=False)
        else:
            yield key, v


def _jsonl_rows(text: str, name: str, *, partial: bool = False):
    """All objects of a JSONL text; columns are their keys in order of first appearance. `partial`: the
    text may end in a cut-off line, which is dropped."""
    lines = text.split("\n")
    if partial and len(lines) > 1:
        lines = lines[:-1]
    columns, rows, n = {}, [], 0
    for line_no, line in enumerate(lines, 1):
        if not line.strip():
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError as e:
            raise ParseError(f"{name} 第 {line_no} 行不是有效的 JSON：{e.msg}") from e
        if not isinstance(obj, dict):
            raise ParseError(f"{name} 第 {line_no} 行不是 JSON 对象")
        n += 1
        row = dict(_flatten(obj))
        for key in row:
            columns.setdefault(key, None)
        rows.append((n, row))
    if not rows:
        raise ParseError(f"{name} 没有 JSON 对象")
    return list(columns), iter(rows)


def _read(path: Path, sheet: str | None):
    kind = kind_of(path.name)
    if kind == "xlsx":
        wb = _workbook(path, path.name)
        columns, rows, _, _ = _xlsx_rows(wb, path.name, sheet)
        return columns, rows
    if kind == "jsonl":
        return _jsonl_rows(read_text(path), path.name)
    return _csv_rows(read_text(path), delimiter_for(path.name), path.name)


# ---------------------------------------------------------------- mapping


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
            return sum(len(_text(r.get(c))) for r in sample) / max(len(sample), 1)

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


def preview(
    data: bytes, name: str, *, partial: bool = True, sheet: str | None = None
) -> dict:
    """Header, first rows and detected defaults of a table or JSONL file (CSV / TSV / JSONL possibly
    truncated; XLSX whole). XLSX adds `sheets` (all sheet names) and the sheet read as defaults.sheet."""
    kind = kind_of(name)
    extra = {}
    if kind == "xlsx":
        wb = _workbook(io.BytesIO(data), name)
        columns, rows, sheets, read = _xlsx_rows(wb, name, sheet)
        extra = {"sheets": sheets}
    else:
        text = decode(data, name, partial=partial)
        if kind == "jsonl":
            columns, rows = _jsonl_rows(text, name, partial=partial)
        else:
            if partial and "\n" in text:
                text = text[: text.rindex("\n") + 1]  # drop the cut-off last line
            columns, rows = _csv_rows(text, delimiter_for(name), name)
    sample = []
    for _, row in rows:
        sample.append(row)
        if len(sample) >= SAMPLE_ROWS:
            break
    defaults = detect(columns, sample)
    if kind == "xlsx":
        defaults["sheet"] = read
    return {
        "columns": columns,
        "rows": [[_text(r.get(c)) for c in columns] for r in sample[:PREVIEW_ROWS]],
        "defaults": defaults,
        **extra,
    }


def parse(
    path: Path,
    language: str,
    metadata: dict,
    delimiter: str | None = None,
    mapping: dict | None = None,
) -> list[Document]:
    path = Path(path)
    if delimiter is not None and kind_of(path.name) not in ("xlsx", "jsonl"):
        columns, rows = _csv_rows(read_text(path), delimiter, path.name)
    else:
        columns, rows = _read(path, (mapping or {}).get("sheet"))
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
        text = "\n\n".join(v for v in (_text(row.get(c)) for c in m["text"]) if v)
        if not text:
            continue
        extra = {c: _meta(row[c]) for c in meta_cols if _text(row.get(c))}
        title = _text(row.get(m["title"])) if m["title"] else ""
        lang = _text(row.get(m["language"])) if m["language"] else ""
        doc = Document(
            title=title[:500] or f"{path.stem} #{n}",
            language=lang or language,
            text=text,
            metadata={**metadata, **extra},
            sentences=[],
        )
        doc.source = f"{path.name} #{n}"
        docs.append(doc)
    if not docs:
        raise ParseError(f"{path.name} 正文列（{'、'.join(m['text'])}）没有内容")
    return docs


def _chain(first, rest):
    yield from first
    yield from rest
