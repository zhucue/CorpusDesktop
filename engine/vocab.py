"""Vocabulary level lists and level profiles (contracts/p10.md §二). Pure computation.

List files (upload and the built-in engine/data/ngsl.csv): UTF-8 text, one `word,level` per line (a tab also
separates; further columns are ignored); blank lines and lines starting with `#` are skipped, and a first line
whose level column reads level / 等级 / grade is a header. A word listed twice keeps its first level. Levels are
ordered naturally (HSK 1 … HSK 9, 1–1000 before 1001–2000) when every level name has a number, otherwise by
first appearance. English and other alphabetic lists are matched by lower-cased lemma (the form when a token
has no lemma); Chinese (zh) lists by word form. Forms are NFC-normalized.

Profile over words (tokens with a letter or CJK character, engine.metrics.is_word):
  per level: tokens (词次), types (distinct matched keys), coverage = tokens / words × 100; plus 表外 (off list)
  by=corpus: one row per level and 表外; search_query = the alternation of the level's word forms seen in the
    scope (`"a"|"b"`), null when there are more than MAX_QUERY_FORMS forms or the query is longer than
    MAX_QUERY_LENGTH; totals.off_list = the most frequent off-list types with their own search_query
  by=document / <field>: one row per document / field value (documents without it: "（无）") with the coverage
    of each level and 表外 (columns level_1 … level_n, off_list) and the words.
"""

import re
import unicodedata
from collections import Counter
from pathlib import Path

from engine.metrics import is_word
from engine.stats import NO_VALUE, Table, _col, _row

BUILTIN_PATH = Path(__file__).resolve().parent / "data" / "ngsl.csv"
OFF_LIST = "表外"
MAX_ENTRIES = 100_000
MAX_QUERY_FORMS = 200
MAX_QUERY_LENGTH = 1000  # search queries are at most 1000 characters
OFF_LIST_TOP = 100
_HEADER = {"level", "等级", "grade", "levels"}
_DIGITS = re.compile(r"(\d+)")


class ListError(ValueError):
    pass


def by_form(language) -> bool:
    code = (language or "").lower().replace("_", "-").split("-")[0]
    return code in ("zh", "cmn", "zho", "chi", "ja")


def normalize(word, language) -> str:
    w = unicodedata.normalize("NFC", word.strip())
    return w if by_form(language) else w.lower()


def _natural(name):
    return [int(x) if x.isdigit() else x for x in _DIGITS.split(name)]


def parse(text: str, language: str) -> tuple[list[tuple[str, str]], list[str], int]:
    """(entries [(form, level)], levels in order, duplicate lines left out); raises ListError."""
    entries, seen, first, duplicates = [], set(), [], 0
    for n, line in enumerate(text.lstrip("﻿").splitlines(), 1):
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        cells = [c.strip() for c in re.split(r"[,\t]", line)]
        if len(cells) < 2 or not cells[0] or not cells[1]:
            raise ListError(f"第 {n} 行应为“词,等级”：{line[:50]}")
        if not entries and not duplicates and cells[1].lower() in _HEADER:
            continue
        form, level = normalize(cells[0], language), cells[1]
        if len(form) > 200 or len(level) > 100:
            raise ListError(f"第 {n} 行过长")
        if form in seen:
            duplicates += 1
            continue
        seen.add(form)
        entries.append((form, level))
        if level not in first:
            first.append(level)
        if len(entries) > MAX_ENTRIES:
            raise ListError(f"词表超过 {MAX_ENTRIES} 词")
    if not entries:
        raise ListError("词表为空")
    levels = (
        sorted(first, key=_natural) if all(_DIGITS.search(v) for v in first) else first
    )
    return entries, levels, duplicates


def builtin() -> tuple[list[tuple[str, str]], list[str]]:
    entries, levels, _ = parse(BUILTIN_PATH.read_text(encoding="utf-8"), "en")
    return entries, levels


def _key(token, form_match):
    form, _, lemma, *_ = token
    if form_match:
        return unicodedata.normalize("NFC", form)
    return (lemma or form).lower()


def _query(forms):
    forms = sorted(f for f in forms if '"' not in f)
    if not forms or len(forms) > MAX_QUERY_FORMS:
        return None
    q = "|".join(f'"{f}"' for f in forms)
    return q if len(q) <= MAX_QUERY_LENGTH else None


def profile(
    docs, entries: dict, levels: list, language: str, by="corpus", check=None
) -> Table:
    """docs: engine.metrics.Doc; entries {normalized form: level}; by: corpus | document | <metadata field>."""
    form_match = by_form(language)
    names = [*levels, OFF_LIST]
    tokens = {v: Counter() for v in names}  # level → key → tokens
    forms = {v: {} for v in names}  # level → key → {form}
    groups, group_words, titles = {}, Counter(), {}
    for doc in docs:
        if check:
            check()
        if by == "corpus":
            g = None
        elif by == "document":
            g = doc.id
            titles[g] = doc.title
        else:
            v = (doc.meta or {}).get(by)
            g = NO_VALUE if v in (None, "") else str(v)
        counts = groups.setdefault(g, Counter())
        for sent in doc.sentences:
            for tok in sent:
                if not is_word(tok[0]):
                    continue
                k = _key(tok, form_match)
                level = entries.get(k, OFF_LIST)
                tokens[level][k] += 1
                forms[level].setdefault(k, set()).add(tok[0])
                counts[level] += 1
                group_words[g] += 1
    words = sum(group_words.values())
    totals = {"words": words, "levels": names, "language": language}
    if by == "corpus":
        rows = []
        for v in names:
            f = sum(tokens[v].values())
            values = {
                "level": v,
                "tokens": f,
                "types": len(tokens[v]),
                "coverage": f / words * 100 if words else 0.0,
            }
            seen = set().union(*forms[v].values()) if forms[v] else set()
            rows.append(_row(v, values, _query(seen)))
        top = sorted(tokens[OFF_LIST].items(), key=lambda x: (-x[1], x[0]))[
            :OFF_LIST_TOP
        ]
        totals["off_list"] = [
            {"item": k, "freq": f, "search_query": _query(forms[OFF_LIST][k])}
            for k, f in top
        ]
        columns = [
            _col("level", "等级", "string"),
            _col("tokens", "词次"),
            _col("types", "词种"),
            _col("coverage", "词次覆盖率 %"),
        ]
        return Table(columns, rows, len(rows), totals)
    keys = [f"level_{i}" for i in range(1, len(levels) + 1)] + ["off_list"]
    rows = []
    order = list(groups)
    if by != "document":
        order.sort(key=lambda v: (v == NO_VALUE, _sort_key(v)))
    for g in order:
        n = group_words[g]
        values = {"item": titles[g] if by == "document" else g, "words": n}
        for k, v in zip(keys, names):
            values[k] = groups[g][v] / n * 100 if n else None
        rows.append(_row(g, values, None))
    columns = [
        _col("item", "文档" if by == "document" else by, "string"),
        _col("words", "词数"),
    ]
    columns += [_col(k, f"{v} %") for k, v in zip(keys, names)]
    return Table(columns, rows, len(rows), totals)


def _sort_key(v):
    try:
        return (0, float(v), "")
    except ValueError:
        return (1, 0.0, v)
