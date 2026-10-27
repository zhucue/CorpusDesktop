"""Query syntax (doc/platform-redesign.md §五) → AST → engine CQP.

Syntax: `语言` string; `语言/n`, `/v` word + POS; space = adjacent; `$N` (0..N words) and `$N-M` gaps;
`a|b` alternatives (one word slot); `"x"` exact form; `*` any word; `?` any one character;
`+cond` / `-cond` same-sentence conditions after the main query (a condition runs to the next `+`/`-`).
`{dep=...}` and `[标签]` are recognised but not supported in P1. Parentheses (nesting) are rejected.

Matching: a string with CJK characters matches characters and may cross word boundaries; other strings
match whole word forms, case-insensitively (`?` = one character, `*` inside a word = any characters).
Quoted forms match exactly, case-sensitively. One hit per start token, the shortest match from it
(CQP MatchingStrategy traditional), always within one sentence.

Chinese character matching: a CJK string of n characters compiles to a CQP alternation over every way
the string can be spread over k = 1..n consecutive tokens: one token containing it (`.*语言.*`), or a
first token ending with a prefix, middle tokens equal to the inner pieces and a last token starting with
the rest (`[word=".*语"] [word="言.*"]`). That is exact on the token stream, but the hit then covers whole
tokens; the code-point span is narrowed in cwb.search by matching the same string (as a Python regex)
over the concatenated forms of the hit tokens (`#span/#lead/#trail` lines below). Strings longer than
MAX_CJK characters are rejected because the alternation grows as 2^(n-1).

compile() output (opaque to callers, passed unchanged to cwb.search), one item per line:
    <anchor CQP sequence>          always first; search adds `:: restrict within s`
    +<CQP> / -<CQP>                same-sentence conditions; search filters anchor hits by sentence
    #span|#lead|#trail <regex>     code-point narrowing for CJK strings at the edges of the anchor
"""

import re
import unicodedata
from dataclasses import dataclass, field

MAX_CJK = 8

UPOS = (
    "ADJ",
    "ADP",
    "ADV",
    "AUX",
    "CCONJ",
    "DET",
    "INTJ",
    "NOUN",
    "NUM",
    "PART",
    "PRON",
    "PROPN",
    "PUNCT",
    "SCONJ",
    "SYM",
    "VERB",
    "X",
)
POS_ALIASES = {  # CCL / PKU style short tags → UPOS
    "n": ("NOUN", "PROPN"),
    "v": ("VERB",),
    "a": ("ADJ",),
    "d": ("ADV",),
    "r": ("PRON",),
    "p": ("ADP",),
    "c": ("CCONJ", "SCONJ"),
    "u": ("PART",),
    "m": ("NUM",),
    "e": ("INTJ",),
    "w": ("PUNCT",),
    "x": ("X", "SYM"),
}

_CJK = re.compile(r"[㐀-䶿一-鿿豈-﫿\U00020000-\U0003134f぀-ヿ가-힯]")
_TERM_STOP = set(' \t\r\n|"{}[]()')


class QueryError(ValueError):
    def __init__(self, position: int, message: str):
        super().__init__(f"{message}（位置 {position}）")
        self.position = position
        self.message = message


@dataclass
class QueryToken:
    kind: str  # word | exact | pos | any | or | gap | cond
    text: str
    position: int


@dataclass
class Atom:
    kind: str  # string | exact | any
    text: str = ""
    pos: tuple[str, ...] = ()  # resolved UPOS tags; empty = no POS constraint

    @property
    def cjk(self) -> bool:
        """Character mode: CJK string without POS and without `*`."""
        return (
            self.kind == "string"
            and not self.pos
            and "*" not in self.text
            and bool(_CJK.search(self.text))
        )


@dataclass
class Gap:
    min: int
    max: int


@dataclass
class Sequence:
    text: str
    items: list  # list[list[Atom] | Gap]; list[Atom] = alternatives for one slot


@dataclass
class Condition:
    op: str  # + | -
    query: Sequence


@dataclass
class QueryAST:
    anchor: Sequence
    conditions: list[Condition] = field(default_factory=list)
    tokens: list[QueryToken] = field(default_factory=list)


# ---------------------------------------------------------------- parse


def _resolve_pos(tag: str, position: int) -> tuple[str, ...]:
    if tag.upper() in UPOS:
        return (tag.upper(),)
    if tag in POS_ALIASES:
        return POS_ALIASES[tag]
    raise QueryError(
        position, f"未知词性 {tag}；可用 {'、'.join(POS_ALIASES)} 或 UPOS 标签"
    )


def _lex(text: str) -> list[tuple[QueryToken, Atom | Gap | str | None]]:
    out = []
    i, n = 0, len(text)
    chunk_start = True  # at start of a whitespace-separated chunk
    while i < n:
        c = text[i]
        if c.isspace():
            i += 1
            chunk_start = True
            continue
        start = i
        if c in "+-" and chunk_start:
            out.append((QueryToken("cond", c, i), c))
            i += 1
            chunk_start = False
            continue
        chunk_start = False
        if c == "|":
            out.append((QueryToken("or", c, i), "|"))
            i += 1
        elif c in "()":
            raise QueryError(i, "不支持括号嵌套；查括号本身请加引号")
        elif c == "{":
            j = text.find("}", i)
            if j < 0:
                raise QueryError(i, "缺少 }")
            raise QueryError(i, f"{text[i : j + 1]} 依存查询暂不支持")
        elif c == "[":
            j = text.find("]", i)
            if j < 0:
                raise QueryError(i, "缺少 ]")
            raise QueryError(i, f"{text[i : j + 1]} 标签查询暂不支持")
        elif c in "}]":
            raise QueryError(i, f"多余的 {c}")
        elif c == "$":
            m = re.compile(r"\$(\d+)(?:-(\d+))?").match(text, i)
            if not m:
                raise QueryError(i, "$ 后应为数字，如 $3 或 $2-5")
            lo, hi = (
                (int(m.group(1)), int(m.group(2)))
                if m.group(2)
                else (0, int(m.group(1)))
            )
            if lo > hi or hi > 50:
                raise QueryError(i, "间隔应为 $N 或 $N-M（N≤M≤50）")
            out.append((QueryToken("gap", m.group(0), i), Gap(lo, hi)))
            i = m.end()
        elif c == '"':
            j = text.find('"', i + 1)
            if j < 0:
                raise QueryError(i, "引号未闭合")
            if j == i + 1:
                raise QueryError(i, "引号内为空")
            word = text[i + 1 : j]
            i = j + 1
            pos = ()
            if i < n and text[i] == "/":
                i, pos = _lex_pos(text, i)
            out.append(
                (QueryToken("exact", text[start:i], start), Atom("exact", word, pos))
            )
        else:
            j = i
            while j < n and text[j] not in _TERM_STOP and text[j] != "/":
                j += 1
            word = text[i:j]
            i = j
            pos = ()
            if i < n and text[i] == "/":
                i, pos = _lex_pos(text, i)
            if word in ("", "*"):
                kind = "pos" if word == "" else "any"
                out.append(
                    (QueryToken(kind, text[start:i], start), Atom("any", "", pos))
                )
            else:
                out.append(
                    (
                        QueryToken("word", text[start:i], start),
                        Atom("string", word, pos),
                    )
                )
    return out


def _lex_pos(text: str, i: int) -> tuple[int, tuple[str, ...]]:
    j = i + 1
    while j < len(text) and text[j] not in _TERM_STOP:
        j += 1
    tag = text[i + 1 : j]
    if not tag:
        raise QueryError(i, "/ 后缺少词性")
    return j, _resolve_pos(tag, i + 1)


def _sequence(text: str, toks: list) -> Sequence:
    items: list = []
    pending_or = False
    for tok, val in toks:
        if isinstance(val, Gap):
            if pending_or or not items or isinstance(items[-1], Gap):
                raise QueryError(tok.position, "间隔须在两个词之间")
            items.append(val)
        elif val == "|":
            if pending_or or not items or isinstance(items[-1], Gap):
                raise QueryError(tok.position, "| 两侧须为词")
            pending_or = True
        else:
            if pending_or:
                items[-1].append(val)
                pending_or = False
            else:
                items.append([val])
    if pending_or:
        raise QueryError(toks[-1][0].position, "| 两侧须为词")
    if isinstance(items[-1], Gap):
        raise QueryError(toks[-1][0].position, "间隔须在两个词之间")
    return Sequence(text.strip(), items)


def parse(text: str) -> QueryAST:
    # CWB stores NFC; keep queries comparable
    text = unicodedata.normalize("NFC", text or "")
    lexed = _lex(text)
    if not lexed:
        raise QueryError(0, "查询为空")
    if lexed[0][0].kind == "cond":
        raise QueryError(0, "缺少主查询；条件写在主查询之后")
    groups: list[tuple[str | None, int, list]] = [(None, 0, [])]
    for tok, val in lexed:
        if tok.kind == "cond":
            groups.append((val, tok.position, []))
        else:
            groups[-1][2].append((tok, val))
    bounds = [g[1] for g in groups[1:]] + [len(text)]
    parts = []
    for (op, pos, toks), end in zip(groups, bounds):
        if not toks:
            raise QueryError(pos, f"{op} 后缺少条件")
        src = text[(pos + 1 if op else 0) : end]
        parts.append((op, _sequence(src, toks)))
    for _, seq in parts:
        for item in seq.items:
            for atom in item if isinstance(item, list) else []:
                if atom.cjk and len(atom.text) > MAX_CJK:
                    raise QueryError(
                        text.find(atom.text),
                        f"中文字串最长 {MAX_CJK} 字，可用空格分成相邻的词",
                    )
    return QueryAST(
        parts[0][1],
        [Condition(op, seq) for op, seq in parts[1:]],
        [t for t, _ in lexed],
    )


# ---------------------------------------------------------------- compile

_CQP_META = set('\\.^$|?*+()[]{}"')


def cqp_literal(s: str) -> str:
    """Regex-escaped body of a CQP double-quoted string."""
    return "".join("\\" + c if c in _CQP_META else c for c in s)


def _wild(s: str) -> str:
    return "".join(".*" if c == "*" else "." if c == "?" else cqp_literal(c) for c in s)


def _units(s: str) -> list[str]:
    return ["." if c == "?" else cqp_literal(c) for c in s]


def _token(word: str | None, pos: tuple[str, ...], flags: str = "") -> str:
    parts = []
    if word is not None:
        parts.append(f'word="{word}"{flags}')
    if pos:
        parts.append(f'pos="{"|".join(pos)}"')
    return "[" + " & ".join(parts) + "]"


def _compositions(n: int):
    """Split n units over k >= 2 tokens: yields cut points (c1 < c2 < ... ) in 1..n-1."""
    for mask in range(1, 1 << (n - 1)):
        yield [i + 1 for i in range(n - 1) if mask >> i & 1]


def _cjk_alternatives(text: str) -> list[str]:
    u = _units(text)
    alts = [f'[word=".*{"".join(u)}.*"]']
    for cuts in _compositions(len(u)):
        bounds = [0, *cuts, len(u)]
        toks = []
        for k in range(len(bounds) - 1):
            body = "".join(u[bounds[k] : bounds[k + 1]])
            if k == 0:
                body = ".*" + body
            if k == len(bounds) - 2:
                body += ".*"
            toks.append(f'[word="{body}"]')
        alts.append(" ".join(toks))
    return alts


def _atom(a: Atom) -> list[str]:
    if a.kind == "any":
        return [_token(None, a.pos)]
    if a.kind == "exact":
        return [_token(cqp_literal(a.text), a.pos)]
    if a.cjk:
        return _cjk_alternatives(a.text)
    if _CJK.search(a.text):  # CJK with POS or `*`: one token
        return [_token(_wild(a.text), a.pos)]
    return [_token(_wild(a.text), a.pos, " %c")]


def compile_sequence(seq: Sequence) -> str:
    out = []
    for item in seq.items:
        if isinstance(item, Gap):
            out.append(f"[]{{{item.min},{item.max}}}")
            continue
        alts = [alt for atom in item for alt in _atom(atom)]
        out.append(alts[0] if len(alts) == 1 else "(" + " | ".join(alts) + ")")
    return " ".join(out)


def char_regex(a: Atom) -> str:
    """Python regex for a character-mode atom (used for code-point narrowing)."""
    return "".join("." if c == "?" else re.escape(c) for c in a.text)


def _edge(item) -> str | None:
    if isinstance(item, Gap):
        return None
    rx = [char_regex(a) for a in item if a.cjk]
    return "|".join(rx) if rx else None


def compile(ast: QueryAST) -> str:
    lines = [compile_sequence(ast.anchor)]
    lines += [c.op + compile_sequence(c.query) for c in ast.conditions]
    items = ast.anchor.items
    if len(items) == 1:
        if (rx := _edge(items[0])) is not None:
            lines.append("#span " + rx)
    else:
        if (rx := _edge(items[0])) is not None:
            lines.append("#lead " + rx)
        if (rx := _edge(items[-1])) is not None:
            lines.append("#trail " + rx)
    return "\n".join(lines)


def compile_filter(filter: dict, fields: dict[str, str]) -> str:
    """Subcorpus filter → CQP global constraint on `match` ("" when empty).

    filter: {field: value | [values] | {"gte": v, "lte": v}}; fields: {field: "string" | "number"}.
    Number ranges use CQP int() on the zero-padded index value; docs without the field never match.
    """
    from engine.cwb import meta_attr, meta_value
    from engine.parsers.table import number_or_text

    parts = []
    for name, cond in (filter or {}).items():
        if name not in fields:
            raise ValueError(f"未知筛选字段：{name}")
        attr = "match.doc_" + meta_attr(name)
        number = fields[name] == "number"
        if isinstance(cond, dict):
            if not number:
                raise ValueError(f"{name} 不是数值字段，不能按范围筛选")
            if not set(cond) <= {"gte", "lte"} or not cond:
                raise ValueError(f"{name} 范围只接受 gte、lte")
            terms = [f'{attr} != ""']
            for op, sym in (("gte", ">="), ("lte", "<=")):
                if op in cond:
                    v = cond[op]
                    if isinstance(v, bool) or not isinstance(v, (int, float)):
                        raise ValueError(f"{name} 的 {op} 须为数字")
                    terms.append(f"int({attr}) {sym} {int(v)}")
            parts.append("(" + " & ".join(terms) + ")")
            continue
        values = cond if isinstance(cond, list) else [cond]
        if not values:
            raise ValueError(f"{name} 未选择取值")
        if number:
            values = [number_or_text(v) if isinstance(v, str) else v for v in values]
        parts.append(
            "("
            + " | ".join(f'{attr} = "{cqp_literal(meta_value(v))}"' for v in values)
            + ")"
        )
    return " & ".join(parts)
