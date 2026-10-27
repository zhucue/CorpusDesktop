"""CWB index build and CQP search.

Layout under index_dir:
    registry/<key>                    CWB registry entry (HOME points at the current version)
    <key>/<index_version>/data/       cwb-encode output
    <key>/<index_version>/docs.json   [doc_id, text byte offset, chars, chunk byte offsets, first sentence,
                                       sentences, text bytes] per document
    <key>/<index_version>/text.bin    document texts, UTF-8, concatenated
    <key>/<index_version>/offsets.bin int32 (start, end) code points per corpus position, document-relative
    <key>/<index_version>/sents.bin   int32 (start, end) per sentence (all sentences, incl. token-less ones)

CWB normalises token strings to NFC when encoding, so forms read back from CWB may differ from the text.
Spans are therefore never derived from CWB strings: every corpus position maps to its exact code-point
offsets through offsets.bin, and hit text always comes from text.bin. Queries are NFC-normalised by
engine.query.parse so they match the NFC lexicon.
"""

import functools
import hashlib
import json
import os
import random
import re
import shutil
import subprocess
import tempfile
import unicodedata
from array import array
from bisect import bisect_left, bisect_right
from collections.abc import Iterable
from itertools import accumulate
from pathlib import Path

from engine import query
from engine.model import Context, Counts, Document, Hit, IndexInfo, SearchResult

FORMAT = "engine-cwb/1"
CHUNK = 4096  # code points between byte-offset checkpoints in text.bin
PAD = 12  # zero-padded width of numeric metadata
PARA_MAX = 2000  # paragraph context cap per side
EOL = "-::-EOL-::-"
ENCODE = [
    "-c",
    "utf8",
    "-x",
    "-s",
    "-P",
    "pos",
    "-P",
    "lemma",
    "-P",
    "deprel",
    "-P",
    "head",
    "-S",
    "s:0+n",
]


class CQPError(RuntimeError):
    pass


def meta_attr(key: str) -> str:
    """Metadata key → s-attribute annotation name (doc_<name> in CQP). Injective: plain keys never start with '_'."""
    if re.fullmatch(r"[a-z0-9][a-z0-9_]{0,40}", key):
        return "meta_" + key
    return "meta__" + key.encode("utf-8").hex()


def meta_value(v) -> str:
    """Non-negative numbers are zero-padded to PAD integer digits so lexical order equals numeric order."""
    if isinstance(v, bool) or not isinstance(v, (int, float)) or v < 0:
        return _clean("" if v is None else str(v))
    whole, _, frac = (
        repr(v).partition(".") if isinstance(v, float) else (str(v), "", "")
    )
    return whole.zfill(PAD) + ("." + frac if frac and frac != "0" else "")


def _clean(s: str) -> str:
    return re.sub(r"[\t\r\n]", " ", s)


def _xml(s: str) -> str:
    return (
        _clean(s)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def _key(corpus_key: str) -> str:
    key = corpus_key.lower()
    if not re.fullmatch(r"[a-z][a-z0-9_]{0,60}", key):
        raise ValueError(f"无效的语料索引名：{corpus_key}")
    return key


def _run(args: list[str], **kw) -> str:
    r = subprocess.run(
        args, capture_output=True, text=True, encoding="utf-8", check=False, **kw
    )
    if r.returncode != 0:
        raise CQPError(f"{args[0]} 失败：{r.stderr.strip() or r.stdout.strip()}")
    return r.stdout


@functools.cache
def cwb_version() -> str:
    return _run(["cwb-config", "--version"]).strip()


# ---------------------------------------------------------------- build


def build(
    index_dir: Path,
    corpus_key: str,
    documents: Iterable[Document],
    doc_ids: Iterable[str],
) -> IndexInfo:
    key = _key(corpus_key)
    root = Path(index_dir) / key
    root.mkdir(parents=True, exist_ok=True)
    tmp = Path(tempfile.mkdtemp(prefix=".build-", dir=root))
    try:
        digest = hashlib.sha256(f"{FORMAT} cwb {cwb_version()}\n".encode())
        docs, metas, n_tokens, n_sents, tags = [], set(), 0, 0, set()
        with (
            open(tmp / "corpus.vrt", "w", encoding="utf-8", newline="\n") as vrt,
            open(tmp / "text.bin", "wb") as text_f,
            open(tmp / "offsets.bin", "wb") as off_f,
            open(tmp / "sents.bin", "wb") as sent_f,
        ):
            for doc, doc_id in zip(documents, doc_ids, strict=True):
                doc_id = str(doc_id)
                raw = doc.text.encode("utf-8")
                chunks, pos = [], 0
                for k in range(0, max(len(doc.text), 1), CHUNK):
                    chunks.append(pos)
                    pos += len(doc.text[k : k + CHUNK].encode("utf-8"))
                docs.append(
                    [
                        doc_id,
                        text_f.tell(),
                        len(doc.text),
                        chunks,
                        n_sents,
                        len(doc.sentences),
                        len(raw),
                    ]
                )
                text_f.write(raw)
                spans = array("i", [x for s in doc.sentences for x in (s.start, s.end)])
                sent_f.write(spans.tobytes())
                n_sents += len(doc.sentences)
                lines = []
                for n, s in enumerate(doc.sentences):
                    if not s.tokens:
                        continue
                    lines.append(f'<s n="{n}">')
                    offs = array("i")
                    for t in s.tokens:
                        offs.extend((t.start, t.end))
                        tags.add(t.pos)
                        lines.append(
                            "\t".join(
                                _xml(v) if v not in (None, "") and v.strip() else "_"
                                for v in (
                                    t.form,
                                    t.pos,
                                    t.lemma,
                                    t.deprel,
                                    None if t.head is None else str(t.head),
                                )
                            )
                        )
                    off_f.write(offs.tobytes())
                    n_tokens += len(s.tokens)
                    lines.append("</s>")
                if lines:
                    attrs = {
                        "id": doc_id,
                        "title": doc.title[:500],
                        "lang": doc.language or "",
                    }
                    for k, v in (doc.metadata or {}).items():
                        attrs[meta_attr(k)] = meta_value(v)
                        metas.add(meta_attr(k))
                    head = (
                        "<doc "
                        + " ".join(f'{k}="{_xml(v)}"' for k, v in attrs.items())
                        + ">"
                    )
                    block = head + "\n" + "\n".join(lines) + "\n</doc>\n"
                    vrt.write(block)
                    digest.update(block.encode("utf-8"))
                digest.update(raw)
                digest.update(spans.tobytes())
        (tmp / "docs.json").write_text(
            json.dumps(docs, ensure_ascii=False), encoding="utf-8"
        )
        tagset = query.infer_tagset(tags)
        if (
            tagset != "upos"
        ):  # jieba output depends on the jieba release and its dictionary
            from engine.nlp import jieba_fingerprint

            digest.update(f"\n{jieba_fingerprint()}\n".encode())
        info = IndexInfo(
            tokens=n_tokens,
            sentences=n_sents,
            documents=len(docs),
            index_version="",
            tagset=tagset,
        )
        info.index_version = digest.hexdigest()[:16]
        final = root / info.index_version
        if n_tokens:
            (tmp / "data").mkdir()
            (tmp / "reg").mkdir()
            s_doc = "doc:0+id+title+lang" + "".join("+" + m for m in sorted(metas))
            args = ["-f", str(tmp / "corpus.vrt"), "-d", str(tmp / "data")]
            args += ["-R", str(tmp / "reg" / key), *ENCODE, "-S", s_doc]
            _run(["cwb-encode", *args])
            _run(["cwb-makeall", "-r", str(tmp / "reg"), "-V", key.upper()])
        (tmp / "corpus.vrt").unlink()
        (tmp / "info.json").write_text(json.dumps(info.__dict__), encoding="utf-8")
        if final.exists():
            (final / "info.json").write_text(
                json.dumps(info.__dict__), encoding="utf-8"
            )
            shutil.rmtree(tmp)
        else:
            tmp.rename(final)
        _write_registry(Path(index_dir), key, final)
        for p in root.iterdir():
            if p != final and not p.name.startswith(".build-"):
                shutil.rmtree(p, ignore_errors=True)
        return info
    except BaseException:
        shutil.rmtree(tmp, ignore_errors=True)
        raise


def _write_registry(index_dir: Path, key: str, home: Path) -> None:
    reg = index_dir / "registry"
    reg.mkdir(exist_ok=True)
    src = home / "reg" / key
    if src.exists():
        text = src.read_text(encoding="utf-8")
        text = re.sub(r"(?m)^HOME .*$", lambda _: f'HOME "{home / "data"}"', text)
        text = re.sub(
            r"(?m)^INFO .*$", lambda _: f'INFO "{home / "data" / ".info"}"', text
        )
    else:  # empty corpus: no CWB data, search returns nothing
        text = f'# empty\nHOME "{home / "data"}"\n'
    tmp = reg / f".{key}.tmp"
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, reg / key)


def tagset(index_dir: Path, corpus_key: str) -> str:
    """POS tag set of the current index (engine.query.TAGSETS); "mixed" for indexes built before it was
    recorded or when there is no index."""
    try:
        home = _home(Path(index_dir), _key(corpus_key))
    except ValueError:
        return "mixed"
    return _tagset(str(home))


@functools.lru_cache(maxsize=64)
def _tagset(home: str) -> str:
    try:
        info = json.loads((Path(home) / "info.json").read_text(encoding="utf-8"))
    except FileNotFoundError:
        return "mixed"
    return info.get("tagset") or "mixed"


def _home(index_dir: Path, key: str) -> Path:
    try:
        text = (Path(index_dir) / "registry" / key).read_text(encoding="utf-8")
    except FileNotFoundError:
        raise ValueError(f"索引不存在：{key}") from None
    return Path(re.search(r'(?m)^HOME "?(.*?)"?$', text).group(1)).parent


class _Index:
    def __init__(self, home: Path):
        self.home = home
        self.docs = json.loads((home / "docs.json").read_text(encoding="utf-8"))
        self.by_id = {unicodedata.normalize("NFC", d[0]): d for d in self.docs}
        self.empty = not (home / "data").exists()

    def doc(self, doc_id: str) -> list:
        try:
            return self.by_id[unicodedata.normalize("NFC", doc_id)]
        except KeyError:
            raise ValueError(f"索引中没有文档：{doc_id}") from None

    def text(self, d: list, a: int, b: int) -> str:
        a, b = max(0, a), min(d[2], b)
        if a >= b:
            return ""
        chunks = d[3]
        k0, k1 = a // CHUNK, (b - 1) // CHUNK + 1
        start = d[1] + chunks[k0]
        end = d[1] + (chunks[k1] if k1 < len(chunks) else d[6])
        with open(self.home / "text.bin", "rb") as f:
            f.seek(start)
            s = f.read(end - start).decode("utf-8")
        return s[a - k0 * CHUNK : b - k0 * CHUNK]

    def pairs(self, name: str, first: int, count: int) -> list[tuple[int, int]]:
        arr = array("i")
        with open(self.home / name, "rb") as f:
            f.seek(first * 8)
            arr.frombytes(f.read(count * 8))
        return list(zip(arr[0::2], arr[1::2]))


@functools.lru_cache(maxsize=16)
def _open(home: str) -> _Index:
    return _Index(Path(home))  # version directories are immutable


# ---------------------------------------------------------------- search


def _cqp(
    index_dir: Path, key: str, commands: list[str], timeout: float
) -> list[list[str]]:
    script = (
        "\n".join(
            [f"{key.upper()};", "set MatchingStrategy traditional;", *commands, "exit;"]
        )
        + "\n"
    )
    r = subprocess.run(
        ["cqp", "-c", "-r", str(Path(index_dir) / "registry")],
        input=script,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=timeout,
        check=False,
    )
    err = r.stderr + r.stdout
    if r.returncode != 0 or "CQP Error" in err or "PARSE ERROR" in err:
        raise CQPError(err.strip())
    out = r.stdout.split("\n")
    if out and out[0].startswith("CQP version"):
        out = out[1:]
    sections, cur = [], []
    for line in out:
        if line == EOL:
            sections.append(cur)
            cur = []
        elif line:
            cur.append(line.split("\t"))
    return sections


def _split(cqp: str):
    lines = cqp.split("\n")
    conds = [(ln[0], ln[1:]) for ln in lines[1:] if ln[:1] in "+-"]
    edges = {
        ln[1:].split(" ", 1)[0]: re.compile(ln.split(" ", 1)[1])
        for ln in lines[1:]
        if ln.startswith("#")
    }
    return lines[0], conds, edges


def search(
    index_dir: Path,
    corpus_key: str,
    cqp: str,
    *,
    restrict: str | None,
    sort: str,
    seed: int | None,
    page: int,
    page_size: int,
    context: Context,
    count_timeout: float = 20,
) -> SearchResult:
    """Anchor hits within s, filtered by same-sentence conditions; counts over the filtered hits.

    All anchor hits are tabulated and counted in Python (exact hits / sentences / documents). If CQP does
    not finish within count_timeout, the first page is taken from the first page*page_size anchor hits
    in corpus order and counts are None with complete=False.
    """
    key = _key(corpus_key)
    if sort not in ("position", "left", "right", "random"):
        raise ValueError(f"未知排序：{sort}")
    page, page_size = max(1, page), max(1, page_size)
    ix = _open(str(_home(index_dir, key)))
    if ix.empty:
        return SearchResult(Counts(0, 0, 0, True), [], page, page_size)
    anchor, conds, edges = _split(cqp)
    fields = "match, matchend, match doc_id, match s_n"
    if sort == "left":
        fields += ", match[-1] word, match[-2] word, match[-3] word"
    elif sort == "right":
        fields += ", matchend[1] word, matchend[2] word, matchend[3] word"

    def commands(cut: int | None) -> list[str]:
        cmds = []
        for i, (_, q) in enumerate(conds):
            cmds += [
                f"C{i} = {q} within s;",
                f"S{i} = C{i} expand to s;",
                f"tabulate S{i} match doc_id, match s_n;",
                ".EOL.;",
            ]
        where = f" :: {restrict}" if restrict else ""
        cmds += [
            f"A = {anchor}{where} within s{f' cut {cut}' if cut else ''};",
            f"tabulate A {fields};",
            ".EOL.;",
        ]
        return cmds

    complete = True
    try:
        sections = _cqp(index_dir, key, commands(None), count_timeout)
    except subprocess.TimeoutExpired:
        complete = False
        sections = _cqp(
            index_dir, key, commands(page * page_size), max(count_timeout, 60)
        )
    rows = sections[-1]
    for (op, _), sents in zip(conds, sections):
        found = {(r[0], r[1]) for r in sents}
        rows = [r for r in rows if ((r[2], r[3]) in found) == (op == "+")]
    if sort in ("left", "right"):
        rows.sort(key=lambda r: [w.casefold() for w in r[4:7]])
    elif sort == "random":
        random.Random(seed or 0).shuffle(rows)
    counts = (
        Counts(
            len(rows),
            len({(r[2], r[3]) for r in rows}),
            len({r[2] for r in rows}),
            True,
        )
        if complete
        else Counts(None, None, None, False)
    )
    lo = (page - 1) * page_size
    items = [
        _hit(ix, int(r[0]), int(r[1]), r[2], int(r[3]), edges, context)
        for r in rows[lo : lo + page_size]
    ]
    return SearchResult(counts, items, page, page_size)


def _narrow(forms: list[str], edges: dict) -> tuple[int, int]:
    """Character offsets (into ''.join(forms)) of the hit, narrowed for CJK edge strings."""
    s = "".join(forms)
    first, last_start = len(forms[0]), len(s) - len(forms[-1])
    start, end = 0, len(s)
    if rx := edges.get("span"):
        for i in range(first):
            m = rx.match(s, i)
            if m and (m.end() > last_start or len(forms) == 1):
                return i, m.end()
        return start, end
    if rx := edges.get("lead"):
        for i in range(first):
            if rx.match(s, i):
                start = i
                break
    if rx := edges.get("trail"):
        ends = [
            m.end()
            for i in range(start, len(s))
            if (m := rx.match(s, i)) and m.end() > last_start
        ]
        if ends:
            end = min(ends)
    return start, end


def _hit(
    ix: _Index, m: int, me: int, doc_id: str, n: int, edges: dict, ctx: Context
) -> Hit:
    d = ix.doc(doc_id)
    toks = ix.pairs("offsets.bin", m, me - m + 1)
    t0, t1 = toks[0][0], toks[-1][1]
    if edges:
        body = ix.text(d, t0, t1)
        forms = [body[s - t0 : e - t0] for s, e in toks]
        a, b = _narrow(forms, edges)
        cum = list(accumulate((len(f) for f in forms), initial=0))
        i = bisect_right(cum, a) - 1  # token holding character a
        j = bisect_left(cum, b) - 1  # token holding character b-1
        start = toks[min(i, len(toks) - 1)][0] + a - cum[i]
        end = toks[max(j, 0)][0] + b - cum[max(j, 0)]
    else:
        start, end = t0, t1
    if ctx.unit == "sentence":
        ss, se = ix.pairs("sents.bin", d[4] + n, 1)[0]
        left, right = ix.text(d, ss, start), ix.text(d, end, se)
    elif ctx.unit == "paragraph":
        left = ix.text(d, start - PARA_MAX, start).rsplit("\n", 1)[-1]
        right = ix.text(d, end, end + PARA_MAX).split("\n", 1)[0]
    else:
        left, right = (
            ix.text(d, start - ctx.size, start),
            ix.text(d, end, end + ctx.size),
        )
    return Hit(
        f"{d[0]}:{start}-{end}",
        d[0],
        n,
        start,
        end,
        left,
        ix.text(d, start, end),
        right,
    )


def context(
    index_dir: Path,
    corpus_key: str,
    doc_id: str,
    sentence_index: int,
    before: int,
    after: int,
) -> list[str]:
    ix = _open(str(_home(index_dir, _key(corpus_key))))
    d = ix.doc(doc_id)
    if not 0 <= sentence_index < d[5]:
        raise ValueError(f"句子序号超出范围：{sentence_index}")
    lo, hi = max(0, sentence_index - before), min(d[5] - 1, sentence_index + after)
    return [ix.text(d, s, e) for s, e in ix.pairs("sents.bin", d[4] + lo, hi - lo + 1)]
