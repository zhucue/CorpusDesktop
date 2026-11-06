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

import contextlib
import functools
import hashlib
import json
import os
import random
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import unicodedata
from array import array
from bisect import bisect_left, bisect_right
from collections.abc import Callable, Iterable
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


def _run(args: list[str], input: str | None = None, cancel=None) -> str:
    """Run a CWB tool and return its stdout. cancel (threading.Event): the tool is killed and Cancelled raised
    within about 0.2 s of it being set (long cwb-scan-corpus runs of statistics jobs)."""
    if cancel is None:
        r = subprocess.run(
            args,
            input=input,
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=False,
        )
        code, out, err = r.returncode, r.stdout, r.stderr
    else:
        if cancel.is_set():
            raise Cancelled("已取消")
        p = subprocess.Popen(
            args,
            stdin=subprocess.DEVNULL if input is None else subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
        )
        pending = input
        while True:
            try:
                out, err = p.communicate(pending, timeout=0.2)
                break
            except subprocess.TimeoutExpired:
                # the input was handed over; a retry must not send it again
                pending = None
                if cancel.is_set():
                    p.kill()
                    p.communicate()
                    raise Cancelled("已取消") from None
        code = p.returncode
    if code != 0:
        raise CQPError(f"{args[0]} 失败：{err.strip() or out.strip()}")
    return out


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
        self._s_starts = None

    def token_index(self, cpos: int) -> int:
        """Position of a token within its sentence (0-based), from the CWB `s` regions (s.rng)."""
        if self._s_starts is None:
            arr = array("i")
            arr.frombytes((self.home / "data" / "s.rng").read_bytes())
            if sys.byteorder == "little":
                arr.byteswap()  # CWB stores int32 big-endian
            self._s_starts = arr[0::2]
        return cpos - self._s_starts[bisect_right(self._s_starts, cpos) - 1]

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


class Cancelled(RuntimeError):
    """A CQP run stopped through its `cancel` event."""


class TooManyHits(RuntimeError):
    """More anchor hits than `max_hits`; CQP was stopped."""

    def __init__(self, limit: int):
        super().__init__(f"命中超过 {limit}")
        self.limit = limit


def _cqp_lines(
    index_dir: Path,
    key: str,
    commands: list[str],
    timeout: float,
    cancel: threading.Event | None = None,
):
    """Run CQP and yield its output as it arrives: a list of tab-separated fields per line, None at each
    `.EOL.` marker. subprocess.TimeoutExpired after `timeout` seconds and Cancelled once `cancel` is set (a
    watchdog kills the process); closing the generator early also kills it."""
    if cancel is not None and cancel.is_set():
        raise Cancelled("检索已取消")
    script = (
        "\n".join(
            [f"{key.upper()};", "set MatchingStrategy traditional;", *commands, "exit;"]
        )
        + "\n"
    )
    args = ["cqp", "-c", "-r", str(Path(index_dir) / "registry")]
    with tempfile.TemporaryFile() as err_f:
        p = subprocess.Popen(
            args,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=err_f,
            text=True,
            encoding="utf-8",
        )
        stopped, done = [], threading.Event()

        def watch():
            deadline = time.monotonic() + timeout
            while not done.wait(min(0.2, max(0.0, deadline - time.monotonic()))):
                if cancel is not None and cancel.is_set():
                    stopped.append("cancel")
                elif time.monotonic() >= deadline:
                    stopped.append("timeout")
                else:
                    continue
                p.kill()
                return

        threading.Thread(target=watch, daemon=True).start()
        errors = []
        try:
            try:
                p.stdin.write(script)
                p.stdin.close()
            except BrokenPipeError:  # CQP exited early; its error is on stderr
                pass
            first = True
            for line in p.stdout:
                line = line.rstrip("\n")
                if first and line.startswith("CQP version"):
                    first = False
                    continue
                first = False
                if line == EOL:
                    yield None
                elif "CQP Error" in line or "PARSE ERROR" in line:
                    errors.append(line)
                elif line:
                    yield line.split("\t")
            p.wait()
        finally:
            done.set()
            if p.poll() is None:
                p.kill()
            p.wait()
            p.stdout.close()
        if stopped == ["cancel"]:
            raise Cancelled("检索已取消")
        if stopped:
            raise subprocess.TimeoutExpired(args, timeout)
        err_f.seek(0)
        err = err_f.read().decode("utf-8", "replace") + "\n".join(errors)
    if p.returncode != 0 or "CQP Error" in err or "PARSE ERROR" in err:
        raise CQPError(err.strip())


def _cqp(
    index_dir: Path,
    key: str,
    commands: list[str],
    timeout: float,
    cancel: threading.Event | None = None,
) -> list[list[list[str]]]:
    """CQP output split into sections at the `.EOL.` markers (lines after the last marker are dropped)."""
    sections, cur = [], []
    for fields in _cqp_lines(index_dir, key, commands, timeout, cancel):
        if fields is None:
            sections.append(cur)
            cur = []
        else:
            cur.append(fields)
    return sections


def _split(cqp: str):
    lines = cqp.split("\n")
    conds = [(ln[0], ln[1:]) for ln in lines[1:] if ln[:1] in "+-"]
    edges = {
        key: re.compile(rest)
        for ln in lines[1:]
        if ln.startswith("#")
        for key, rest in [ln[1:].split(" ", 1)]
        if key in ("span", "lead", "trail")
    }
    return lines[0], conds, edges


def _targets(cqp: str) -> dict[int, str]:
    """`#target <slot> <CQP>` lines: anchor variants marking an attribute slot's token with `@`."""
    return {
        int(slot): q
        for ln in cqp.split("\n")
        if ln.startswith("#target ")
        for slot, q in [ln[8:].split(" ", 1)]
    }


AttrFilter = Callable[[int, set[tuple[str, int, int]]], set[tuple[str, int, int]]]


# match, matchend (corpus positions), doc_id, sentence index
Row = tuple[int, int, str, int]
SORTS = ("position", "left", "right", "random")


class RowSet:
    """Hit rows packed as int32 (match, matchend, doc number, sentence) with the doc ids by number; slicing
    and iteration give Row tuples."""

    def __init__(self, arr: array | None = None, docs: list[str] | None = None):
        self.arr = arr if arr is not None else array("i")
        self.docs = docs if docs is not None else []

    def __len__(self) -> int:
        return len(self.arr) // 4

    def __getitem__(self, s: slice) -> list[Row]:
        lo, hi, _ = s.indices(len(self))
        a, docs = self.arr, self.docs
        return [
            (a[i], a[i + 1], docs[a[i + 2]], a[i + 3]) for i in range(lo * 4, hi * 4, 4)
        ]

    def __iter__(self):
        return iter(self[:])

    def __eq__(self, other) -> bool:
        return list(self) == list(other)


def _query(
    index_dir: Path,
    corpus_key: str,
    cqp: str,
    *,
    restrict: str | None,
    sort: str,
    seed: int | None,
    timeout: float,
    attr_filter: AttrFilter | None,
    cut: int | None,
    cancel: threading.Event | None,
    max_hits: int | None,
    aligned: tuple[str, set] | None = None,
) -> tuple[RowSet, int]:
    """(filtered and sorted rows, number of anchor hits before filtering); see query_rows."""
    key = _key(corpus_key)
    if sort not in SORTS:
        raise ValueError(f"未知排序：{sort}")
    ix = _open(str(_home(index_dir, key)))
    if ix.empty:
        return RowSet(), 0
    anchor, conds, _ = _split(cqp)
    targets = _targets(cqp)
    if targets and attr_filter is None:
        raise ValueError("属性约束需要 attr_filter")
    fields = "match, matchend, match doc_id, match s_n"
    if sort == "left":
        fields += ", match[-1] word, match[-2] word, match[-3] word"
    elif sort == "right":
        fields += ", matchend[1] word, matchend[2] word, matchend[3] word"

    cmds = []
    for i, (_, q) in enumerate(conds):
        cmds += [
            f"C{i} = {q} within s;",
            f"S{i} = C{i} expand to s;",
            f"tabulate S{i} match doc_id, match s_n;",
            ".EOL.;",
        ]
    where = f" :: {restrict}" if restrict else ""
    tail = f"{where} within s{f' cut {cut}' if cut else ''};"
    for slot, q in sorted(targets.items()):
        cmds += [
            f"T{slot} = {q}{tail}",
            f"tabulate T{slot} match, matchend, target;",
            ".EOL.;",
        ]
    cmds += [
        f"A = {anchor}{tail}",
        f"tabulate A {fields};",
        ".EOL.;",
    ]

    # Streamed into compact structures: condition sentences, slot tokens by hit, packed anchor rows and
    # (left / right) one sort key string per row. "\0" joins the three words so that string order equals
    # the order of the word lists.
    slots = sorted(targets)
    found = [set() for _ in conds]
    marked = [{} for _ in slots]
    docs, num = [], {}
    arr, keys = array("i"), ([] if sort in ("left", "right") else None)
    last, sec, anchors = len(conds) + len(slots), 0, 0

    def doc(d: str) -> int:
        i = num.get(d)
        if i is None:
            i = num[d] = len(docs)
            docs.append(d)
        return i

    lines = _cqp_lines(index_dir, key, cmds, timeout, cancel)
    with contextlib.closing(lines):  # leaving early (TooManyHits) stops CQP
        for f in lines:
            if f is None:
                sec += 1
            elif sec == last:
                anchors += 1
                if max_hits is not None and anchors > max_hits:
                    raise TooManyHits(max_hits)
                arr.extend((int(f[0]), int(f[1]), doc(f[2]), int(f[3])))
                if keys is not None:
                    keys.append("\0".join(w.casefold() for w in f[4:7]))
            elif sec < len(conds):
                found[sec].add((doc(f[0]), int(f[1])))
            elif sec < last:
                at = marked[sec - len(conds)]
                at[(int(f[0]), int(f[1]))] = int(f[2])
                if max_hits is not None and len(at) > max_hits:
                    raise TooManyHits(max_hits)

    keep = None  # row numbers left after filtering, in order; None = all
    for (op, _), sents in zip(conds, found):
        rows = range(len(arr) // 4) if keep is None else keep
        keep = [
            i
            for i in rows
            if ((arr[4 * i + 2], arr[4 * i + 3]) in sents) == (op == "+")
        ]
    if aligned is not None:  # sentences given by the caller (translation condition)
        op, sents = aligned
        rows = range(len(arr) // 4) if keep is None else keep
        keep = [
            i
            for i in rows
            if ((docs[arr[4 * i + 2]], arr[4 * i + 3]) in sents) == (op == "+")
        ]
    for slot, at in zip(slots, marked):
        rows = range(len(arr) // 4) if keep is None else keep
        tokens = [
            (docs[arr[4 * i + 2]], arr[4 * i + 3], ix.token_index(t))
            if (t := at.get((arr[4 * i], arr[4 * i + 1]), -1)) >= 0
            else None
            for i in rows
        ]
        allowed = attr_filter(slot, {k for k in tokens if k})
        keep = [i for i, k in zip(rows, tokens) if k in allowed]
    if keys is not None:
        keep = list(range(len(arr) // 4)) if keep is None else keep
        keep.sort(key=keys.__getitem__)
    elif sort == "random":
        keep = list(range(len(arr) // 4)) if keep is None else keep
        random.Random(seed or 0).shuffle(keep)
    if keep is not None:
        out = array("i")
        for i in keep:
            out.extend(arr[4 * i : 4 * i + 4])
        arr = out
    return RowSet(arr, docs), anchors


def query_rows(
    index_dir: Path,
    corpus_key: str,
    cqp: str,
    *,
    restrict: str | None,
    sort: str = "position",
    seed: int | None = None,
    timeout: float = 20,
    attr_filter: AttrFilter | None = None,
    cut: int | None = None,
    cancel: threading.Event | None = None,
    max_hits: int | None = None,
    aligned: tuple[str, set] | None = None,
) -> RowSet:
    """Anchor hits within s, filtered by same-sentence conditions and attribute slots, ordered by `sort`.

    cut: only the first `cut` anchor hits in corpus order are taken (then filtered), so with sort "position"
    the rows are a prefix of the uncut rows. Raises subprocess.TimeoutExpired when CQP runs longer than
    `timeout` seconds, Cancelled when `cancel` is set meanwhile, TooManyHits as soon as there are more than
    `max_hits` anchor hits (CQP is stopped in all three cases).

    Attribute slots (`#attr` / `#target` lines, engine.query): for each slot the anchor is run again with
    the target marker on it, giving that slot's token per hit; attr_filter(slot, {(doc_id, sentence_index,
    token_index)}) returns the tokens that satisfy the slot's constraints and the other hits are dropped.

    aligned: (op, {(doc_id, sentence_index)}) keeps hits whose sentence is in the set (op "+") or not in it
    ("-"); the API passes the sentences aligned to the hits of a translation-side query.
    """
    return _query(
        index_dir,
        corpus_key,
        cqp,
        restrict=restrict,
        sort=sort,
        seed=seed,
        timeout=timeout,
        attr_filter=attr_filter,
        cut=cut,
        cancel=cancel,
        max_hits=max_hits,
        aligned=aligned,
    )[0]


def prefix_rows(
    index_dir: Path,
    corpus_key: str,
    cqp: str,
    need: int,
    *,
    restrict: str | None,
    timeout: float = 60,
    attr_filter: AttrFilter | None = None,
    max_hits: int | None = None,
    aligned: tuple[str, set] | None = None,
) -> list[Row]:
    """The first `need` rows in corpus order (fewer when the query has fewer). The anchor hits are cut at
    `need` and the cut is doubled while conditions or attribute slots leave too few rows, up to `max_hits`
    anchor hits and `timeout` seconds in all; a later run that times out returns the rows found so far."""
    deadline = time.monotonic() + timeout
    cut = max(1, min(need, max_hits or need))
    rows, anchors = _query(
        index_dir,
        corpus_key,
        cqp,
        restrict=restrict,
        sort="position",
        seed=None,
        timeout=timeout,
        attr_filter=attr_filter,
        cut=cut,
        cancel=None,
        max_hits=None,
        aligned=aligned,
    )
    while len(rows) < need and anchors >= cut and (max_hits is None or cut < max_hits):
        cut = cut * 2 if max_hits is None else min(cut * 2, max_hits)
        left = deadline - time.monotonic()
        if left <= 0:
            break
        try:
            rows, anchors = _query(
                index_dir,
                corpus_key,
                cqp,
                restrict=restrict,
                sort="position",
                seed=None,
                timeout=left,
                attr_filter=attr_filter,
                cut=cut,
                cancel=None,
                max_hits=None,
                aligned=aligned,
            )
        except subprocess.TimeoutExpired:
            break
    return rows[:need]


def count_rows(rows) -> Counts:
    """Exact hits / sentences / documents of complete rows."""
    if isinstance(rows, RowSet):
        a = rows.arr
        sents = {(a[i], a[i + 1]) for i in range(2, len(a), 4)}
        return Counts(len(rows), len(sents), len({d for d, _ in sents}), True)
    return Counts(
        len(rows), len({(r[2], r[3]) for r in rows}), len({r[2] for r in rows}), True
    )


def hits(
    index_dir: Path, corpus_key: str, cqp: str, rows: list[Row], context: Context
) -> list[Hit]:
    """Hits (code points, text and context) of rows from query_rows, on the current index."""
    if not rows:
        return []
    ix = _open(str(_home(index_dir, _key(corpus_key))))
    edges = _split(cqp)[2]
    return [_hit(ix, m, me, d, n, edges, context) for m, me, d, n in rows]


def write_rows(path: Path, rows) -> int:
    """Store rows (RowSet or Row list) in directory `path` (rows.bin: int32 match, matchend, doc number,
    sentence; docs.json: doc ids by number), so any slice can be read back with read_rows without holding
    the rows in memory. Returns the bytes written."""
    path = Path(path)
    path.mkdir(parents=True, exist_ok=True)
    if not isinstance(rows, RowSet):
        docs = list(dict.fromkeys(r[2] for r in rows))
        num = {d: i for i, d in enumerate(docs)}
        rows = RowSet(
            array("i", (x for m, me, d, n in rows for x in (m, me, num[d], n))), docs
        )
    meta = json.dumps(rows.docs, ensure_ascii=False).encode("utf-8")
    (path / "docs.json").write_bytes(meta)
    data = rows.arr.tobytes()
    (path / "rows.bin").write_bytes(data)
    return len(meta) + len(data)


def read_rows(path: Path, lo: int, hi: int | None = None) -> list[Row]:
    """Rows lo..hi-1 written by write_rows (fewer past the end; hi None: to the end); FileNotFoundError when
    the files are gone."""
    path = Path(path)
    lo = max(0, lo)
    arr = array("i")
    with open(path / "rows.bin", "rb") as f:
        if hi is None:
            hi = os.fstat(f.fileno()).st_size // 16
        f.seek(lo * 16)
        arr.frombytes(f.read(max(0, hi - lo) * 16))
    if not arr:
        return []
    docs = json.loads((path / "docs.json").read_text("utf-8"))
    return [
        (arr[i], arr[i + 1], docs[arr[i + 2]], arr[i + 3])
        for i in range(0, len(arr), 4)
    ]


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
    attr_filter: AttrFilter | None = None,
    aligned: tuple[str, set] | None = None,
) -> SearchResult:
    """One page of query_rows, with exact counts over all filtered hits.

    If CQP does not finish within count_timeout, the page is taken from the first page*page_size anchor hits
    in corpus order (sort not applied) and counts are None with complete=False.
    """
    page, page_size = max(1, page), max(1, page_size)
    kw = {"restrict": restrict, "attr_filter": attr_filter, "aligned": aligned}
    try:
        rows = query_rows(
            index_dir,
            corpus_key,
            cqp,
            sort=sort,
            seed=seed,
            timeout=count_timeout,
            **kw,
        )
        counts = count_rows(rows)
    except subprocess.TimeoutExpired:
        rows = prefix_rows(
            index_dir,
            corpus_key,
            cqp,
            page * page_size,
            timeout=max(count_timeout, 60),
            **kw,
        )
        counts = Counts(None, None, None, False)
    lo = (page - 1) * page_size
    items = hits(index_dir, corpus_key, cqp, rows[lo : lo + page_size], context)
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
    left, right = _around(
        lambda a, b: ix.text(d, a, b),
        d[2],
        lambda: ix.pairs("sents.bin", d[4] + n, 1)[0],
        start,
        end,
        ctx,
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


def _around(text, length, sentence, start, end, ctx: Context) -> tuple[str, str]:
    """(left, right) context of code points start..end of a document: text(a, b) reads its code points a..b-1
    (clamped), length = its code points, sentence() = (start, end) of the hit's sentence."""
    if ctx.unit == "sentence" or (ctx.sentence_only and ctx.unit == "paragraph"):
        ss, se = sentence()
        return text(ss, start), text(end, se)
    if ctx.unit == "paragraph":
        left = text(start - PARA_MAX, start).rsplit("\n", 1)[-1]
        return left, text(end, end + PARA_MAX).split("\n", 1)[0]
    floor, ceil = sentence() if ctx.sentence_only else (0, length)
    lo, hi = max(floor, start - ctx.size), min(ceil, end + ctx.size)
    # the window cuts the text: one extra character outside it tells whether a word is cut
    more_l, more_r = lo > floor, hi < ceil
    left = _word_cut_left(text(lo - more_l, start), more_l)
    return left, _word_cut_right(text(end, hi + more_r), more_r)


class DocText:
    """Code-point reads of the documents of a corpus, for hits given in document code points (answered from
    PostgreSQL): text.bin / sents.bin of the current index, so a page never reads whole documents. Documents
    the index lacks (no index yet, or added after it was built) come from fallback(doc_id) → (text, {sentence
    index: (start, end)})."""

    def __init__(self, index_dir: Path, corpus_key: str, fallback=None):
        try:
            self.ix = _open(str(_home(Path(index_dir), _key(corpus_key))))
        except ValueError:
            self.ix = None
        self.fallback = fallback
        self._loaded = {}

    def _doc(self, doc_id: str):
        if self.ix is not None:
            with contextlib.suppress(ValueError):
                return self.ix.doc(doc_id), None
        if doc_id not in self._loaded:
            if self.fallback is None:
                raise ValueError(f"索引中没有文档：{doc_id}")
            self._loaded[doc_id] = self.fallback(doc_id)
        return None, self._loaded[doc_id]

    def text(self, doc_id: str, a: int, b: int) -> str:
        d, mem = self._doc(doc_id)
        if d is not None:
            return self.ix.text(d, a, b)
        return mem[0][max(0, a) : max(0, b)]

    def hit(self, doc_id: str, n: int, start: int, end: int, ctx: Context) -> Hit:
        """The hit at code points start..end of sentence n, context as cwb hits."""
        d, mem = self._doc(doc_id)
        if d is not None:
            length = d[2]

            def sentence():
                return self.ix.pairs("sents.bin", d[4] + n, 1)[0]
        else:
            length = len(mem[0])

            def sentence():
                return mem[1].get(n, (start, end))

        left, right = _around(
            lambda a, b: self.text(doc_id, a, b), length, sentence, start, end, ctx
        )
        match = self.text(doc_id, start, end)
        return Hit(f"{doc_id}:{start}-{end}", doc_id, n, start, end, left, match, right)


def _wordy(c: str) -> bool:
    """Letter or digit of a space-separated script (Latin, Cyrillic …), not CJK."""
    return c.isalnum() and not query._CJK.match(c)


def _word_cut_left(s: str, more: bool) -> str:
    """Left character context; with `more` it starts with one extra character from outside the window, which
    tells whether the window cut a word in half: then that half word is dropped (English starts at a word)."""
    if not more or not s:
        return s
    extra, s = s[0], s[1:]
    if s and _wordy(extra) and _wordy(s[0]) and (m := re.search(r"\s", s)):
        return s[m.end() :]
    return s


def _word_cut_right(s: str, more: bool) -> str:
    """Right character context; with `more` it ends with one extra character (see _word_cut_left)."""
    if not more or not s:
        return s
    s, extra = s[:-1], s[-1]
    if s and _wordy(extra) and _wordy(s[-1]) and (m := re.search(r"\s\S*$", s)):
        return s[: m.start()]
    return s


def doc_starts(index_dir: Path, corpus_key: str) -> dict[str, int]:
    """{doc_id: corpus position of its first token} of the current index ({} when empty)."""
    key = _key(corpus_key)
    ix = _open(str(_home(Path(index_dir), key)))
    if ix.empty:
        return {}
    reg = str(Path(index_dir) / "registry")
    out = _run(["cwb-s-decode", "-r", reg, key.upper(), "-S", "doc_id"])
    starts = {}
    for line in out.split("\n"):
        if line:
            a, _, doc_id = line.split("\t", 2)
            starts[doc_id] = int(a)
    return starts


def lexicon(index_dir: Path, corpus_key: str, attr: str) -> list[str]:
    """Distinct values of a positional attribute (pos, deprel …) in the current index, "_" (empty) excluded;
    [] without an index. Meant for small lexicons: callers check `has_values` before reading lemma/word."""
    try:
        home = _home(Path(index_dir), _key(corpus_key))
    except ValueError:
        return []
    return list(_lexicon(str(home), attr))


@functools.lru_cache(maxsize=256)
def _lexicon(home: str, attr: str) -> tuple[str, ...]:
    try:
        raw = (Path(home) / "data" / f"{attr}.lexicon").read_bytes()
    except FileNotFoundError:
        return ()
    return tuple(v for v in raw.decode("utf-8").split("\0") if v and v != "_")


def has_values(index_dir: Path, corpus_key: str, attr: str) -> bool | None:
    """Whether any token has a value for the attribute (deprel: the corpus has system dependencies);
    None when unknown (no index on disk)."""
    try:
        home = _home(Path(index_dir), _key(corpus_key))
        size = (home / "data" / f"{attr}.lexicon").stat().st_size
    except (ValueError, FileNotFoundError):
        return None
    return size > 2 or bool(_lexicon(str(home), attr))


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
