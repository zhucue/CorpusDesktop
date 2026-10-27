"""Query syntax (doc/platform-redesign.md §五) → AST → engine CQP.

Syntax: `语言` string; `语言/n`, `/v` word + POS; space = adjacent; `$N` (0..N words) and `$N-M` gaps;
`a|b` alternatives (one word slot); `"x"` exact form; `*` any word; `?` any one character;
`+cond` / `-cond` same-sentence conditions after the main query (a condition runs to the next `+`/`-`).
`{k=v,...}` token attributes (contracts/p3.md §三), alone (`{dep=nsubj}`) or attached to a word, quoted form or
`/pos` (`学生{dep=nsubj}`, `"run"{pos=v}`, `/DET{dep=det}`); keys pos, dep, lemma; values may use `|`. They are
resolved by the api against annotation layers, not by CQP, and are allowed only in the main query and not in a
`|` alternation. `[标签]` is recognised but not supported. Parentheses (nesting) are rejected.

POS depends on the corpus tagset (parse(tagset=...), from cwb.tagset): "upos" (Stanza / CoNLL-U): UPOS names
or CCL short tags (n → NOUN|PROPN …); "jieba" (Chinese via engine.nlp): a one-letter tag matches every jieba
tag starting with it (n → n|ng|nr|ns|nt|nz…), longer jieba tags match exactly (nr), UPOS names map to jieba
groups (NOUN, VERB …); "mixed" (both in one corpus): the union of both readings.

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
    #attr <slot> <k>=<v>[|<v>...]  attribute constraint on anchor slot <slot> (0-based, gaps not counted);
                                   pos values are already resolved against the tagset; read by attrs()
    #target <slot> <CQP>           the anchor with the CQP target marker `@` on that slot, so cwb.search can
                                   find the slot's token in each hit and pass it to the api's attribute filter
A bare `{…}` slot compiles to `[]` (any token); a string with attributes matches one whole token (like `/pos`).
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

# jieba / ICTCLAS tags produced by engine.nlp for Chinese: the default dictionary's tags, `eng` (Latin words),
# `x` (other non-dictionary strings) and `w` (punctuation and symbols, assigned by engine.nlp).
JIEBA_TAGS = (
    "a",
    "ad",
    "ag",
    "an",
    "b",
    "c",
    "d",
    "df",
    "dg",
    "e",
    "eng",
    "f",
    "g",
    "h",
    "i",
    "j",
    "k",
    "l",
    "m",
    "mg",
    "mq",
    "n",
    "ng",
    "nr",
    "nrfg",
    "nrt",
    "ns",
    "nt",
    "nz",
    "o",
    "p",
    "q",
    "r",
    "rg",
    "rr",
    "rz",
    "s",
    "t",
    "tg",
    "u",
    "ud",
    "ug",
    "uj",
    "ul",
    "uv",
    "uz",
    "v",
    "vd",
    "vg",
    "vi",
    "vn",
    "vq",
    "w",
    "x",
    "y",
    "z",
    "zg",
)
# A one-letter tag matches every jieba tag starting with it (`n` → n, nr, ns, nt, nz, ng …), `eng` excepted.
JIEBA_ALIASES = {
    k: tuple(t for t in JIEBA_TAGS if t.startswith(k) and t != "eng")
    for k in "abcdefghijklmnopqrstuvwxyz"
    if k in JIEBA_TAGS
}
_PROPER = ("nr", "nrfg", "nrt", "ns", "nt", "nz")
UPOS_JIEBA = {  # UPOS names on a jieba-tagged corpus
    "NOUN": tuple(t for t in JIEBA_ALIASES["n"] if t not in _PROPER),
    "PROPN": _PROPER,
    "VERB": JIEBA_ALIASES["v"],
    "ADJ": JIEBA_ALIASES["a"],
    "ADV": JIEBA_ALIASES["d"],
    "PRON": JIEBA_ALIASES["r"],
    "ADP": JIEBA_ALIASES["p"],
    "CCONJ": JIEBA_ALIASES["c"],
    "SCONJ": JIEBA_ALIASES["c"],
    "PART": JIEBA_ALIASES["u"],
    "NUM": JIEBA_ALIASES["m"],
    "INTJ": JIEBA_ALIASES["e"],
    "PUNCT": ("w",),
    "SYM": ("w",),
    "X": ("x", "eng"),
}
TAGSETS = (
    "upos",
    "jieba",
    "mixed",
)  # mixed: both in one corpus (e.g. a zh–en TMX); tags of either apply

_CJK = re.compile(r"[㐀-䶿一-鿿豈-﫿\U00020000-\U0003134f぀-ヿ가-힯]")
_TERM_STOP = set(' \t\r\n|"{}[]()')
ATTR_KEYS = ("pos", "dep", "lemma")


class QueryError(ValueError):
    def __init__(self, position: int, message: str):
        super().__init__(f"{message}（位置 {position}）")
        self.position = position
        self.message = message


@dataclass
class QueryToken:
    kind: str  # word | exact | pos | any | or | gap | cond | attr
    text: str
    position: int


@dataclass
class Atom:
    kind: str  # string | exact | any
    text: str = ""
    pos: tuple[str, ...] = ()  # resolved UPOS tags; empty = no POS constraint
    attrs: dict[str, tuple[str, ...]] = field(default_factory=dict)  # pos / dep / lemma

    @property
    def cjk(self) -> bool:
        """Character mode: CJK string without POS, attributes and `*`."""
        return (
            self.kind == "string"
            and not self.pos
            and not self.attrs
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


def _resolve_upos(tag: str) -> tuple[str, ...] | None:
    if tag.upper() in UPOS:
        return (tag.upper(),)
    return POS_ALIASES.get(tag)


def _resolve_jieba(tag: str) -> tuple[str, ...] | None:
    if tag in JIEBA_ALIASES:
        return JIEBA_ALIASES[tag]
    if tag in JIEBA_TAGS:
        return (tag,)
    return UPOS_JIEBA.get(tag.upper())


def _resolve_pos(tag: str, position: int, tagset: str = "upos") -> tuple[str, ...]:
    if tagset not in TAGSETS:
        raise ValueError(f"未知词性体系：{tagset}")
    found = []
    if tagset in ("upos", "mixed"):
        found += _resolve_upos(tag) or ()
    if tagset in ("jieba", "mixed"):
        found += [t for t in _resolve_jieba(tag) or () if t not in found]
    if found:
        return tuple(found)
    hint = {
        "upos": f"{'、'.join(POS_ALIASES)} 或 UPOS 标签",
        "jieba": f"{'、'.join(JIEBA_ALIASES)}、jieba 标签（如 nr、vn）或 UPOS 标签",
        "mixed": f"{'、'.join(POS_ALIASES)}、UPOS 或 jieba 标签",
    }[tagset]
    raise QueryError(position, f"未知词性 {tag}；可用 {hint}")


def resolve_pos(tag: str, tagset: str = "upos") -> tuple[str, ...]:
    """Query-style POS (`n`, `NOUN`, `nr`) → index tags for a tagset; raises QueryError at position 0."""
    return _resolve_pos(tag, 0, tagset)


def infer_tagset(tags) -> str:
    """Tagset of an index from its POS values (None / "" ignored); "mixed" when unclear."""
    seen = {t for t in tags if t}
    if seen and seen <= set(UPOS):
        return "upos"
    if seen and seen <= set(JIEBA_TAGS):
        return "jieba"
    return "mixed"


def _lex(text: str, tagset: str) -> list[tuple[QueryToken, Atom | Gap | str | None]]:
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
            i, attrs = _lex_attrs(text, i, tagset)
            out.append(
                (QueryToken("attr", text[start:i], start), Atom("any", attrs=attrs))
            )
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
                i, pos = _lex_pos(text, i, tagset)
            atom = Atom("exact", word, pos)
            out.append((QueryToken("exact", text[start:i], start), atom))
            i = _attach_attrs(text, i, tagset, atom, out)
        else:
            j = i
            while j < n and text[j] not in _TERM_STOP and text[j] != "/":
                j += 1
            word = text[i:j]
            i = j
            pos = ()
            if i < n and text[i] == "/":
                i, pos = _lex_pos(text, i, tagset)
            if word in ("", "*"):
                kind, atom = "pos" if word == "" else "any", Atom("any", "", pos)
            else:
                kind, atom = "word", Atom("string", word, pos)
            out.append((QueryToken(kind, text[start:i], start), atom))
            i = _attach_attrs(text, i, tagset, atom, out)
    return out


def _attach_attrs(text: str, i: int, tagset: str, atom: Atom, out: list) -> int:
    """`{…}` right after a term: its attributes go on that atom; the lexed token carries no value."""
    if i < len(text) and text[i] == "{":
        start = i
        i, atom.attrs = _lex_attrs(text, i, tagset)
        out.append((QueryToken("attr", text[start:i], start), None))
    return i


def _lex_attrs(text: str, i: int, tagset: str) -> tuple[int, dict]:
    j = text.find("}", i)
    if j < 0:
        raise QueryError(i, "缺少 }")
    attrs, pos = {}, i + 1
    for part in text[i + 1 : j].split(","):
        key, eq, raw = part.partition("=")
        key = key.strip().lower()
        at = pos + len(part) - len(part.lstrip())
        pos += len(part) + 1
        if not eq or key not in ATTR_KEYS:
            raise QueryError(at, f"属性写作 {{k=v}}，k 为 {'、'.join(ATTR_KEYS)}")
        if key in attrs:
            raise QueryError(at, f"属性 {key} 重复")
        values = [v.strip() for v in raw.split("|")]
        if not all(values) or any(re.search(r"\s", v) for v in values):
            raise QueryError(at, f"{key} 的取值为空或含空白")
        if (
            key == "pos"
        ):  # query-style tags (n, VERB, nr) expand as in `/pos`; other labels stay literal
            found = []
            for v in values:
                try:
                    tags = _resolve_pos(v, at, tagset)
                except QueryError:
                    tags = (v,)
                found += [t for t in tags if t not in found]
            values = found
        attrs[key] = tuple(dict.fromkeys(values))
    return j + 1, attrs


def _lex_pos(text: str, i: int, tagset: str) -> tuple[int, tuple[str, ...]]:
    j = i + 1
    while j < len(text) and text[j] not in _TERM_STOP:
        j += 1
    tag = text[i + 1 : j]
    if not tag:
        raise QueryError(i, "/ 后缺少词性")
    return j, _resolve_pos(tag, i + 1, tagset)


ALT_ATTRS = "属性约束不能用于 | 并列的词；取值可写成 {pos=a|b}"


def _sequence(text: str, toks: list) -> Sequence:
    items: list = []
    pending_or = False
    for tok, val in toks:
        if val is None:  # `{…}` attached to the previous term
            if len(items[-1]) > 1:
                raise QueryError(tok.position, ALT_ATTRS)
            continue
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
                if val.attrs or items[-1][-1].attrs:
                    raise QueryError(tok.position, ALT_ATTRS)
                items[-1].append(val)
                pending_or = False
            else:
                items.append([val])
    if pending_or:
        raise QueryError(toks[-1][0].position, "| 两侧须为词")
    if isinstance(items[-1], Gap):
        raise QueryError(toks[-1][0].position, "间隔须在两个词之间")
    return Sequence(text.strip(), items)


def parse(text: str, tagset: str = "upos") -> QueryAST:
    """tagset: POS tags of the corpus searched ("upos" | "jieba" | "mixed"); `/tag` resolves against it."""
    # CWB stores NFC; keep queries comparable
    text = unicodedata.normalize("NFC", text or "")
    lexed = _lex(text, tagset)
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
        if op and any(t.kind == "attr" for t, _ in toks):
            at = next(t.position for t, _ in toks if t.kind == "attr")
            raise QueryError(at, "属性约束只能用于主查询，不能用于 +/- 条件")
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


def compile_sequence(seq: Sequence, target: int | None = None) -> str:
    """CQP for a sequence; `target` puts the CQP target marker `@` on the first token of that slot."""
    out, slot = [], -1
    for item in seq.items:
        if isinstance(item, Gap):
            out.append(f"[]{{{item.min},{item.max}}}")
            continue
        slot += 1
        alts = [alt for atom in item for alt in _atom(atom)]
        if slot == target:
            alts = ["@" + alt for alt in alts]
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
    slots = [item for item in items if not isinstance(item, Gap)]
    for p, item in enumerate(slots):
        if item[0].attrs:
            lines += [f"#attr {p} {k}={'|'.join(v)}" for k, v in item[0].attrs.items()]
            lines.append(f"#target {p} {compile_sequence(ast.anchor, p)}")
    return "\n".join(lines)


def attrs(compiled: str) -> dict[int, dict[str, tuple[str, ...]]]:
    """`#attr` lines of a compile() result: {anchor slot: {key: values}}."""
    out = {}
    for line in compiled.split("\n"):
        if line.startswith("#attr "):
            slot, kv = line[6:].split(" ", 1)
            key, values = kv.split("=", 1)
            out.setdefault(int(slot), {})[key] = tuple(values.split("|"))
    return out


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
