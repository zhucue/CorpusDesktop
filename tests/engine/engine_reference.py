"""Pure-Python reference matcher for golden counts (independent of CQP and of engine.query.compile).

Semantics (doc/platform-redesign.md §五 as implemented by the engine): within one sentence, one hit per
start token, ending at the shortest possible end; conditions keep anchor hits whose sentence does (+) or
does not (-) contain a condition match.

Regenerate tests/golden/p1-queries.json:  PYTHONPATH=. uv run --no-project --with lxml python tests/engine/engine_reference.py
"""

import json
import re
from pathlib import Path

from engine.parsers import parse as parse_file
from engine.query import Atom, Gap, parse

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / "tests/fixtures/ud-en-ewt-sample.conllu"
GOLDEN = ROOT / "tests/golden/p1-queries.json"
_CJK = re.compile(r"[㐀-䶿一-鿿]")

QUERIES = [
    "the",
    '"The"',
    "Google",
    "/v",
    "/PROPN",
    "have/v",
    "the /n",
    "in the",
    "the $2 of",
    "a $1-3 /n",
    "the|a /adj",
    "is|was|are /adv|/adj",
    "* of the",
    "Google +search",
    "the -of",
    "I +/v -not",
    "th??",
    "go*",
    '"\'s"',
    "/det /adj /noun -/propn",
]


def _wild(text: str) -> str:
    return "".join(
        ".*" if c == "*" else "." if c == "?" else re.escape(c) for c in text
    )


def token_ok(a: Atom, tok) -> bool:
    if a.pos and tok.pos not in a.pos:
        return False
    if a.kind == "any":
        return True
    if a.kind == "exact":
        return tok.form == a.text
    flags = 0 if _CJK.search(a.text) else re.IGNORECASE
    return re.fullmatch(_wild(a.text), tok.form, flags) is not None


def atom_ends(a: Atom, forms, toks, i: int) -> set[int]:
    if not a.cjk:
        return {i + 1} if token_ok(a, toks[i]) else set()
    rx = re.compile("".join("." if c == "?" else re.escape(c) for c in a.text))
    ends = set()
    for k in range(1, len(a.text) + 1):
        if i + k > len(forms):
            break
        s = "".join(forms[i : i + k])
        last = len(s) - len(forms[i + k - 1])
        if any(
            (m := rx.match(s, p)) and (k == 1 or m.end() > last)
            for p in range(len(forms[i]))
        ):
            ends.add(i + k)
    return ends


def seq_ends(items, toks, i: int) -> set[int]:
    forms = [t.form for t in toks]
    cur = {i}
    for item in items:
        nxt = set()
        for p in cur:
            if isinstance(item, Gap):
                nxt |= {
                    p + g for g in range(item.min, item.max + 1) if p + g <= len(toks)
                }
            elif p < len(toks):
                for a in item:
                    nxt |= atom_ends(a, forms, toks, p)
        cur = nxt
    return cur


def matches(items, toks) -> list[tuple[int, int]]:
    out = []
    for i in range(len(toks)):
        ends = seq_ends(items, toks, i)
        if ends:
            out.append((i, min(ends)))
    return out


def counts(query: str, docs) -> dict:
    ast = parse(query)
    hits = sents = 0
    doc_hits = set()
    for d, doc in enumerate(docs):
        for s in doc.sentences:
            n = len(matches(ast.anchor.items, s.tokens))
            if n and all(
                bool(matches(c.query.items, s.tokens)) == (c.op == "+")
                for c in ast.conditions
            ):
                hits += n
                sents += 1
                doc_hits.add(d)
    return {"hits": hits, "sentences": sents, "documents": len(doc_hits)}


def load_docs():
    return parse_file(FIXTURE, language="en", metadata={})[0]


if __name__ == "__main__":
    docs = load_docs()
    golden = {
        "fixture": "tests/fixtures/ud-en-ewt-sample.conllu",
        "source": "UD_English-EWT en_ewt-ud-test.conllu, first 16 documents "
        "(https://github.com/UniversalDependencies/UD_English-EWT, CC BY-SA 4.0)",
        "queries": [{"query": q, **counts(q, docs)} for q in QUERIES],
    }
    GOLDEN.write_text(
        json.dumps(golden, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    for q in golden["queries"]:
        print(q)
