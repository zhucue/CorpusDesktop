"""Per-document text metrics (contracts/p10.md §一). Pure computation over documents the worker reads from the
CWB index (engine.stats.documents) or from PostgreSQL; no database access here.

A document is Doc(id, title, language, meta, sentences); a sentence is a list of tokens (form, pos, lemma, head,
deprel), head = 1-based token number in the sentence (0 = root, None = no dependency).

Words: tokens whose form has a letter or CJK character (engine.stats.is_punct is false), so punctuation,
symbols and bare numbers are not words. Types: lower-cased word forms.
  words, sentences (sentences with at least one token)
  ttr = types / words
  sttr = mean TTR of consecutive windows of `window` words; the last, shorter window is left out
  mtld = (forward + backward) / 2 (McCarthy & Jarvis 2010): a pass reads words, keeping the running TTR of the
    current factor; when it falls to ≤ 0.72 a factor is complete and the count restarts; the remainder adds
    (1 − TTR) / (1 − 0.72) of a factor; pass value = words / factors (null when factors = 0)
  sttr and mtld are null for documents of fewer than MIN_WORDS words; sttr also when words < window
  lexical_density = content words / words; content = UPOS NOUN, PROPN, VERB, ADJ, ADV or a jieba tag starting
    with n, v, a, d
  mean_sentence_length = words / sentences
  mean_dependency_distance = Σ|head − i| / number of dependencies, over every token with a head ≠ 0 (root left
    out; punctuation included) in sentences that have dependencies (Liu 2008); null without any
  English documents (language code en): syllables = vowel groups [aeiouy]+ of the lower-cased word, minus one
    for a final silent "e" (not "le", word of more than one group), at least 1;
    flesch_reading_ease = 206.835 − 1.015 × words / sentences − 84.6 × syllables / words      (Flesch 1948)
    flesch_kincaid_grade = 0.39 × words / sentences + 11.8 × syllables / words − 15.59 (Kincaid et al. 1975)
Group summary (group_by): per metric, documents with a value, mean and sample SD (n − 1; null below 2).
"""

import math
import re
from dataclasses import dataclass, field

from engine.stats import NO_VALUE, Table, _col, _row, is_punct

MTLD_THRESHOLD = 0.72
MIN_WORDS = 100
CONTENT_UPOS = {"NOUN", "PROPN", "VERB", "ADJ", "ADV"}
CONTENT_JIEBA = ("n", "v", "a", "d")
METRICS = (
    "words",
    "sentences",
    "ttr",
    "sttr",
    "mtld",
    "lexical_density",
    "mean_sentence_length",
    "mean_dependency_distance",
    "flesch_reading_ease",
    "flesch_kincaid_grade",
)
LABELS = {
    "words": "词数（不含标点）",
    "sentences": "句数",
    "ttr": "TTR",
    "sttr": "STTR",
    "mtld": "MTLD",
    "lexical_density": "词汇密度",
    "mean_sentence_length": "平均句长",
    "mean_dependency_distance": "平均依存距离",
    "flesch_reading_ease": "Flesch 易读度",
    "flesch_kincaid_grade": "Flesch-Kincaid 年级",
}
_VOWELS = re.compile(r"[aeiouy]+")


@dataclass
class Doc:
    id: str
    title: str = ""
    language: str = ""
    meta: dict = field(default_factory=dict)
    sentences: list = field(
        default_factory=list
    )  # [[(form, pos, lemma, head, deprel)]]


def lang_code(language) -> str:
    code = (language or "").lower().replace("_", "-").split("-")[0]
    return {"cmn": "zh", "eng": "en", "zho": "zh", "chi": "zh"}.get(code, code)


def is_word(form) -> bool:
    return bool(form) and not is_punct(form)


def ttr(words) -> float | None:
    return len(set(words)) / len(words) if words else None


def sttr(words, window=1000) -> float | None:
    n = len(words) // window
    if not n:
        return None
    return (
        sum(len(set(words[i * window : (i + 1) * window])) / window for i in range(n))
        / n
    )


def _mtld_pass(words, threshold):
    factors, types, count, current = 0.0, set(), 0, 1.0
    for w in words:
        count += 1
        types.add(w)
        current = len(types) / count
        if current <= threshold:
            factors += 1
            types, count, current = set(), 0, 1.0
    factors += (1 - current) / (1 - threshold)
    return len(words) / factors if factors else None


def mtld(words, threshold=MTLD_THRESHOLD) -> float | None:
    fwd, bwd = _mtld_pass(words, threshold), _mtld_pass(words[::-1], threshold)
    if fwd is None or bwd is None:
        return None
    return (fwd + bwd) / 2


def is_content(pos) -> bool:
    if not pos:
        return False
    return pos in CONTENT_UPOS or pos[0] in CONTENT_JIEBA


def syllables(word) -> int:
    w = word.lower()
    n = len(_VOWELS.findall(w))
    if n > 1 and w.endswith("e") and not w.endswith("le"):
        n -= 1
    return max(n, 1)


def dependency_distance(sentences) -> float | None:
    total = count = 0
    for sent in sentences:
        for i, (_, _, _, head, _) in enumerate(sent, 1):
            if head:  # None = no dependency, 0 = root
                total += abs(head - i)
                count += 1
    return total / count if count else None


def document_metrics(doc: Doc, window=1000) -> dict:
    words, content, n_sent = [], 0, 0
    for sent in doc.sentences:
        if sent:
            n_sent += 1
        for form, pos, *_ in sent:
            if is_word(form):
                words.append(form.lower())
                content += is_content(pos)
    n = len(words)
    long = n >= MIN_WORDS
    out = {
        "words": n,
        "sentences": n_sent,
        "ttr": ttr(words),
        "sttr": sttr(words, window) if long else None,
        "mtld": mtld(words) if long else None,
        "lexical_density": content / n if n else None,
        "mean_sentence_length": n / n_sent if n_sent else None,
        "mean_dependency_distance": dependency_distance(doc.sentences),
        "flesch_reading_ease": None,
        "flesch_kincaid_grade": None,
    }
    if lang_code(doc.language) == "en" and n and n_sent:
        wps, spw = n / n_sent, sum(map(syllables, words)) / n
        out["flesch_reading_ease"] = 206.835 - 1.015 * wps - 84.6 * spw
        out["flesch_kincaid_grade"] = 0.39 * wps + 11.8 * spw - 15.59
    return out


def mean_sd(values) -> tuple[float | None, float | None]:
    values = [v for v in values if v is not None]
    if not values:
        return None, None
    mean = sum(values) / len(values)
    if len(values) < 2:
        return mean, None
    return mean, math.sqrt(sum((v - mean) ** 2 for v in values) / (len(values) - 1))


def group_value(meta, field_name):
    v = (meta or {}).get(field_name)
    return NO_VALUE if v in (None, "") else str(v)


def check_metrics(metrics):
    unknown = set(metrics or ()) - set(METRICS)
    if unknown:
        raise ValueError(f"未知文本指标：{'、'.join(sorted(unknown))}")


def table(docs, metrics=None, group_by=None, window=1000, check=None) -> Table:
    """One row per document (key = document id) with title, language, the metrics (all when None) and the
    group_by field value; totals: documents, words, sentences, notes, groups {metric: [{value, documents,
    mean, sd}]} with group_by. check() is called once per document (cancellation)."""
    check_metrics(metrics)
    if window < 1:
        raise ValueError("STTR 窗口须为正整数")
    shown = [m for m in METRICS if not metrics or m in metrics]
    rows, short, below_window, by_group = [], 0, 0, {}
    total_words = total_sents = 0
    for doc in docs:
        if check:
            check()
        m = document_metrics(doc, window)
        total_words += m["words"]
        total_sents += m["sentences"]
        if m["words"] < MIN_WORDS:
            short += 1
        elif m["words"] < window:
            below_window += 1
        values = {"title": doc.title, "language": doc.language}
        if group_by:
            values["group"] = group_value(doc.meta, group_by)
            by_group.setdefault(values["group"], []).append(m)
        values.update({k: m[k] for k in shown})
        rows.append(_row(doc.id, values, None))
    columns = [_col("title", "文档", "string"), _col("language", "语言", "string")]
    if group_by:
        columns.append(_col("group", group_by, "string"))
    columns += [_col(k, LABELS[k]) for k in shown]
    notes = []
    if short:
        notes.append(f"{short} 篇文档词数少于 {MIN_WORDS}，不计 STTR 与 MTLD")
    if below_window and ("sttr" in shown):
        notes.append(f"{below_window} 篇文档词数少于 STTR 窗口 {window}，不计 STTR")
    totals = {
        "documents": len(rows),
        "words": total_words,
        "sentences": total_sents,
        "notes": notes,
    }
    if group_by:
        groups = {}
        order = sorted(by_group, key=lambda v: (v == NO_VALUE, _sort_key(v)))
        for k in shown:
            groups[k] = []
            for v in order:
                vals = [m[k] for m in by_group[v] if m[k] is not None]
                mean, sd = mean_sd(vals)
                groups[k].append(
                    {"value": v, "documents": len(vals), "mean": mean, "sd": sd}
                )
        totals["groups"] = groups
        totals["group_by"] = group_by
    return Table(columns, rows, len(rows), totals)


def _sort_key(v):
    try:
        return (0, float(v), "")
    except ValueError:
        return (1, 0.0, v)
