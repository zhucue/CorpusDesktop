"""Term candidates by POS patterns (contracts/p4.md §四 抽取方法).

Patterns over two adjacent tokens of one sentence: Chinese n+n, a+n, v+n; other languages ADJ+NOUN, NOUN+NOUN.
Classes: UPOS NOUN → n, ADJ → a, VERB → v; jieba n* (not person / place / organisation names nr*, ns, nt) and vn
→ n, a / an / ag → a, other v* → v. Both forms must contain a letter (Latin words at least 2 characters).
Term text: Chinese forms concatenated; otherwise "form₁ lemma₂" lower-cased (language models → language model).
Language: the document language (doc_lang), else the default.

Counts: freq = occurrences of the pair; logDice = 14 + log2(2·freq / (f(x) + f(y))), with f(x) the frequency
of the first form (lower-cased) and f(y) of the second lemma in the same language. Candidates with
freq ≥ min_freq sort by freq desc, logDice desc, term.

Translations (parallel corpora): over aligned sentence pairs in both directions, a candidate in language A is
paired with the units (pattern pairs and single nouns) of the aligned language-B sentence; the best unit has
the highest Dice 2·co / (f(term) + f(unit)) over sentence co-occurrence counts, then the highest co, then the
longer unit, with
co ≥ min(min_co, f(term)).
"""

import math
from collections import Counter
from dataclasses import dataclass, field
from itertools import pairwise

ZH_PATTERNS = {("n", "n"), ("a", "n"), ("v", "n")}
PATTERNS = {("a", "n"), ("n", "n")}
_UPOS = {"NOUN": "n", "ADJ": "a", "VERB": "v"}
_EXCLUDED = {"ns", "nt"}
# cwb-scan-corpus constraints that keep only possible pattern pairs
_FIRST = "?pos=/(NOUN|ADJ|VERB|n[a-z]*|a|an|ag|v[a-z]*)/"
_SECOND = "?pos+1=/(NOUN|n[a-z]*|vn)/"


@dataclass
class Candidate:
    term: str
    language: str
    pattern: str
    freq: int
    logdice: float
    translations: list = field(default_factory=list)  # [{language, text, co, dice}]
    example: object = None  # ref of the first aligned sentence holding the term


def lang_code(language) -> str:
    code = (language or "").strip().lower().replace("_", "-").split("-")[0]
    return {"cmn": "zh", "zho": "zh", "chi": "zh", "eng": "en"}.get(code, code)


def pos_class(tag) -> str | None:
    if not tag or tag == "_":
        return None
    if tag in _UPOS:
        return _UPOS[tag]
    if tag.isupper() or tag.startswith("nr") or tag in _EXCLUDED:
        return None
    if tag == "vn" or tag.startswith("n"):
        return "n"
    if tag in ("a", "an", "ag"):
        return "a"
    if tag.startswith("v"):
        return "v"
    return None


def _pattern(lang, p1, p2) -> str | None:
    pair = (pos_class(p1), pos_class(p2))
    return (
        f"{pair[0]}+{pair[1]}"
        if pair in (ZH_PATTERNS if lang == "zh" else PATTERNS)
        else None
    )


def _word(form, lang) -> bool:
    return any(c.isalpha() for c in form) and (lang == "zh" or len(form) > 1)


def _lemma(form, lemma):
    return form if lemma in (None, "", "_") else lemma


def _key(lang, f1, l1, f2, l2) -> tuple[str, str, str]:
    """(term, first-word key, second-word key)."""
    if lang == "zh":
        return f1 + f2, f1, f2
    x, y = f1.lower(), _lemma(f2, l2).lower()
    return f"{x} {y}", x, y


# ---------------------------------------------------------------- counting


def count(sentences) -> tuple[Counter, Counter]:
    """sentences: iterable of (language, [(form, pos, lemma)]) →
    (pairs {(lang, f1, p1, l1, f2, p2, l2): n}, unigrams {(lang, form, lemma): n}) as rank() takes them."""
    pairs, unigrams = Counter(), Counter()
    for language, toks in sentences:
        for f, _, l in toks:
            unigrams[(language, f, l)] += 1
        for (f1, p1, l1), (f2, p2, l2) in pairwise(toks):
            if pos_class(p2) == "n" and pos_class(p1):
                pairs[(language, f1, p1, l1, f2, p2, l2)] += 1
    return pairs, unigrams


def scan_scope(scope) -> tuple[Counter, Counter]:
    """The same counts from a CWB index scope (engine.stats.Scope) with cwb-scan-corpus, pairs within s."""
    from engine import stats

    c = stats._Corpus(scope)
    keys = ["doc_lang", "word", "pos", "lemma", "word+1", "pos+1", "lemma+1"]
    pairs = c.scan([*keys, _FIRST, _SECOND], within_s=True)
    unigrams = c.scan(["doc_lang", "word", "lemma"])
    return pairs, unigrams


def rank(
    pairs, unigrams, top=100, min_freq=2, languages=None, default_language=""
) -> list[Candidate]:
    default = lang_code(default_language)
    fx, fy = Counter(), Counter()
    for (language, form, lemma), n in unigrams.items():
        lang = lang_code(language) or default
        if lang == "zh":
            fx[(lang, form)] += n
            fy[(lang, form)] += n
        else:
            fx[(lang, form.lower())] += n
            fy[(lang, _lemma(form, lemma).lower())] += n
    found = {}
    for (language, f1, p1, l1, f2, p2, l2), n in pairs.items():
        lang = lang_code(language) or default
        pattern = _pattern(lang, p1, p2)
        if not pattern or not (_word(f1, lang) and _word(f2, lang)):
            continue
        term, x, y = _key(lang, f1, l1, f2, l2)
        entry = found.setdefault((term, lang), [0, x, y, pattern])
        entry[0] += n
    out = []
    for (term, lang), (freq, x, y, pattern) in found.items():
        if freq < min_freq or (languages and lang not in languages):
            continue
        logdice = 14 + math.log2(2 * freq / (fx[(lang, x)] + fy[(lang, y)]))
        out.append(Candidate(term, lang, pattern, freq, logdice))
    out.sort(key=lambda c: (-c.freq, -round(c.logdice, 10), c.term))
    return out[:top]


def from_sentences(sentences, top=100, min_freq=2, languages=None, default_language=""):
    return rank(*count(sentences), top, min_freq, languages, default_language)


# ---------------------------------------------------------------- translations


def units(language, toks) -> set[str]:
    """Pattern pairs and single nouns of a sentence, as term texts."""
    lang = lang_code(language)
    out = set()
    for f, p, l in toks:
        if pos_class(p) == "n" and _word(f, lang):
            out.add(f if lang == "zh" else _lemma(f, l).lower())
    for (f1, p1, l1), (f2, p2, l2) in pairwise(toks):
        if _pattern(lang, p1, p2) and _word(f1, lang) and _word(f2, lang):
            out.add(_key(lang, f1, l1, f2, l2)[0])
    return out


def translate(candidates: list[Candidate], aligned, min_co=2) -> list[Candidate]:
    """aligned: iterable of ((language, toks, ref), (language, toks, ref)) sentence pairs. Sets each
    candidate's best translation and the ref of its first aligned sentence; returns the candidates."""
    wanted = {(c.term, c.language) for c in candidates}
    co, f_src, f_tgt, first = Counter(), Counter(), Counter(), {}
    for a, b in aligned:
        for (la, ta, ra), (lb, tb, _) in ((a, b), (b, a)):
            la, lb = lang_code(la), lang_code(lb)
            if la == lb:
                continue
            tgt = units(lb, tb)
            for t in tgt:
                f_tgt[(lb, t)] += 1
            for s in units(la, ta):
                if (s, la) not in wanted:
                    continue
                f_src[(s, la)] += 1
                first.setdefault((s, la), ra)
                for t in tgt:
                    co[((s, la), lb, t)] += 1
    best = {}
    for (src, lb, t), n in co.items():
        if n < min(min_co, f_src[src]):
            continue
        dice = 2 * n / (f_src[src] + f_tgt[(lb, t)])
        key = (-round(dice, 10), -n, -len(t), t)  # ties: the longer unit
        if src not in best or key < best[src][0]:
            best[src] = (key, {"language": lb, "text": t, "co": n, "dice": dice})
    for c in candidates:
        found = best.get((c.term, c.language))
        c.translations = [found[1]] if found else []
        c.example = first.get((c.term, c.language))
    return candidates
