import hashlib
import json
import logging
import os
import re
import secrets
import shutil
import subprocess
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from threading import Event, Lock
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Query
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import select, tuple_

from engine import cwb, query
from engine.model import Context
from services.api import effective
from services.api.access import (
    READ,
    WRITE,
    Paging,
    human_only,
    load_corpus,
    load_subcorpus,
    require_project,
    token_project,
)
from services.api.auth import CurrentUser, Db
from services.api.db import data_dir, session
from services.api.errors import ApiError, not_found
from services.api.jobs import enqueue
from services.api.metadata import field_types, validate_filter
from services.api.models import (
    Corpus,
    Document,
    SavedQuery,
    Sentence,
    SentenceAlignment,
    Subcorpus,
    Token,
)
from services.api.storage import corpus_key, index_dir
from services.api.subcorpora import project_corpus
from services.api.views import document_view, job_view, saved_query_view

router = APIRouter(prefix="/api")

COUNT_TIMEOUT = float(os.environ.get("SEARCH_COUNT_TIMEOUT") or 20)  # seconds
# background full count after COUNT_TIMEOUT (contracts/p7.md §1)
FULL_TIMEOUT = float(os.environ.get("SEARCH_FULL_TIMEOUT") or 300)
# more anchor hits fail the count; total size of the stored result sets
MAX_HITS = int(os.environ.get("SEARCH_MAX_HITS") or 2_000_000)
CACHE_MAX_BYTES = int(os.environ.get("SEARCH_CACHE_MAX_BYTES") or 2 * 1024**3)

log = logging.getLogger(__name__)


class Scope(BaseModel):
    """{corpus_id} | {subcorpus_id} | {corpus_id, filter}: filter is a temporary subcorpus filter, not saved."""

    corpus_id: UUID | None = None
    subcorpus_id: UUID | None = None
    filter: dict | None = None

    @model_validator(mode="after")
    def one_target(self):
        if (self.corpus_id is None) == (self.subcorpus_id is None):
            raise ValueError("scope 须且只能包含 corpus_id 或 subcorpus_id")
        if self.filter is not None and self.corpus_id is None:
            raise ValueError("filter 只能与 corpus_id 一起使用")
        return self


class LayersInput(BaseModel):
    """Annotation layers whose effective values answer `{pos=}` / `{dep=}` (omitted = system values) and `[标签]`
    (span; omitted = the corpus's most recently updated span layer in the user's projects); relation: the
    relation layer of `unit=relation_label` statistics."""

    pos: UUID | None = None
    dep: UUID | None = None
    span: UUID | None = None
    relation: UUID | None = None


class ContextInput(BaseModel):
    unit: Literal["char", "sentence", "paragraph"] = "char"
    size: int = Field(default=40, ge=1, le=500)


class SearchInput(BaseModel):
    scope: Scope
    query: str = Field(min_length=1, max_length=1000)
    context: ContextInput = ContextInput()
    sort: Literal["position", "left", "right", "random"] = "position"
    seed: int | None = None
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=50, ge=1, le=200)
    search_id: str | None = Field(default=None, max_length=64)
    include_tokens: bool = (
        False  # add Hit.tokens (sentence tokens with POS) to each item
    )
    layers: LayersInput | None = None


class ExportInput(SearchInput):
    format: Literal["csv", "xlsx"]
    project_id: UUID | None = None


class ParseInput(BaseModel):
    """scope: resolve POS against that corpus's tagset and check the annotation layers the query needs."""

    query: str = Field(max_length=1000)
    scope: Scope | None = None


class SavedQueryInput(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    query: str = Field(min_length=1, max_length=1000)
    scope: Scope


# ---- shared search steps (API and export worker) ----


def parse_view(text, tagset="mixed"):
    try:
        ast = query.parse(text, tagset)
    except query.QueryError as e:
        return {
            "ok": False,
            "anchor": "",
            "conditions": [],
            "tokens": [],
            "error": {"position": e.position, "message": e.message},
        }
    return {
        "ok": True,
        "anchor": ast.anchor.text,
        "conditions": [{"op": c.op, "text": c.query.text} for c in ast.conditions],
        "tokens": [{"kind": t.kind, "text": t.text} for t in ast.tokens],
        "error": None,
    }


def corpus_tagset(corpus) -> str:
    """POS tag set of the corpus index (upos | jieba | mixed); queries and POS filters resolve against it."""
    return cwb.tagset(index_dir(corpus.id), corpus_key(corpus.id))


def plan_query(text, tagset="mixed"):
    """(ast, compiled engine string); 422 QUERY_INVALID on syntax errors."""
    try:
        ast = query.parse(text, tagset)
        return ast, query.compile(ast)
    except query.QueryError as e:
        raise ApiError(422, "QUERY_INVALID", f"第 {e.position + 1} 个字符：{e.message}")


def compile_query(text, tagset="mixed"):
    return plan_query(text, tagset)[1]


TAGSET_NAMES = {"upos": "UPOS", "jieba": "jieba（北大标注）", "mixed": "UPOS + jieba"}


def corpus_info(db, corpus, user, tagset):
    """What the parse line shows about the searched corpus: POS tagset and the tags in its index, script
    (Corpus.meta.script when import recorded it), and whether dependency / span layers exist."""
    key, ix = corpus_key(corpus.id), index_dir(corpus.id)
    dep = cwb.has_values(ix, key, "deprel") or bool(
        effective.default_layer(db, corpus, user, "dep")
    )
    return {
        "tagset": tagset,
        "tagset_name": TAGSET_NAMES.get(tagset, tagset),
        "pos_tags": sorted(cwb.lexicon(ix, key, "pos")),
        "script": (corpus.meta or {}).get("script"),
        "parallel": corpus.parallel,
        "layers": {
            "dep": dep,
            "span": effective.default_layer(db, corpus, user, "span") is not None,
        },
    }


_ATTR_KEY = re.compile(r"(?:^\{|,)\s*(\w+)\s*=")


def layer_problem(db, corpus, user, ast, layers=None):
    """(position, message) when the query needs an annotation the corpus lacks, else None: `{dep=}` without
    system dependencies or a dependency layer, `{lemma=}` without lemmas, `[标签]` without a span layer.
    layers None (parse line): any of the user's layers on the corpus counts; otherwise the chosen ones."""
    key, ix = corpus_key(corpus.id), index_dir(corpus.id)

    def has_layer(kind):
        if layers is not None:
            return layers.get(kind) is not None
        return effective.default_layer(db, corpus, user, kind) is not None

    for tok in ast.tokens:
        if tok.kind == "attr":
            keys = {k.lower() for k in _ATTR_KEY.findall(tok.text)}
            if (
                "dep" in keys
                and cwb.has_values(ix, key, "deprel") is False
                and not has_layer("dep")
            ):
                return tok.position, "该语料无依存层，{dep=} 无法检索"
            if "lemma" in keys and cwb.has_values(ix, key, "lemma") is False:
                return tok.position, "该语料无词元标注，{lemma=} 无法检索"
        elif tok.kind == "span" and not has_layer("span"):
            return tok.position, "该语料无片段标注层，[标签] 无法检索"
    return None


def check_layer_problem(db, corpus, user, ast, layers):
    if problem := layer_problem(db, corpus, user, ast, layers):
        raise ApiError(
            422, "INVALID_LAYER", f"第 {problem[0] + 1} 个字符：{problem[1]}"
        )


def pure_attr(ast) -> bool:
    """One `{…}` slot (optionally with `/pos`), no word and no +/- condition: answered from PostgreSQL."""
    items = ast.anchor.items
    return (
        not ast.conditions
        and len(items) == 1
        and len(items[0]) == 1
        and items[0][0].kind == "any"
        and bool(items[0][0].attrs)
    )


def cache_key(cqp, layers):
    """Search cache key text: attribute and span queries also depend on the layers they read."""
    if not (query.attrs(cqp) or query.spans(cqp)) or not any(layers.values()):
        return cqp
    return f"{cqp}\n#layers {layers['pos']} {layers['dep']} {layers.get('span')}"


def with_span_layer(db, cqp, layers, corpus, user):
    """Span queries need a span layer: the requested one or the default (422 INVALID_LAYER when none)."""
    if query.spans(cqp) and not layers.get("span"):
        layers["span"] = effective.default_layer(db, corpus, user, "span")
        if layers["span"] is None:
            raise ApiError(
                422, "INVALID_LAYER", "该语料库没有片段标注层，[标签] 查询需要片段层"
            )
    return layers


def scope_filter(db, scope: Scope):
    """The metadata filter a scope applies ({} for a whole corpus)."""
    if scope.subcorpus_id:
        return db.get(Subcorpus, scope.subcorpus_id).filter
    return scope.filter or {}


def resolve_scope(db, scope: Scope, user):
    """Return (corpus, restrict) after access checks; corpus must have an index."""
    restrict = None
    if scope.subcorpus_id:
        sub = load_subcorpus(db, scope.subcorpus_id, user)
        corpus = db.get(Corpus, sub.corpus_id)
        try:
            restrict = (
                query.compile_filter(sub.filter, field_types(db, corpus.id)) or None
            )
        except ValueError as e:
            raise ApiError(409, "INVALID_FILTER", f"子库筛选条件已失效：{e}")
    else:
        corpus = load_corpus(db, scope.corpus_id, user)
        if scope.filter is not None:
            fields = field_types(db, corpus.id)
            validate_filter(scope.filter, fields)
            restrict = query.compile_filter(scope.filter, fields) or None
    if corpus.status not in ("ready", "stale") or not corpus.index_version:
        raise ApiError(409, "CORPUS_NOT_READY", "语料库尚未完成索引")
    return corpus, restrict


def search_context(corpus, req: SearchInput) -> Context:
    # parallel corpora: neighbouring sentences are unrelated pairs, so context stays in the hit's sentence
    return Context(
        unit=req.context.unit, size=req.context.size, sentence_only=corpus.parallel
    )


def run_search(
    corpus,
    restrict,
    cqp,
    req: SearchInput,
    page,
    page_size,
    count_timeout,
    attr_filter=None,
):
    kw = {"attr_filter": attr_filter} if attr_filter else {}
    return cwb.search(
        index_dir(corpus.id),
        corpus_key(corpus.id),
        cqp,
        restrict=restrict,
        sort=req.sort,
        seed=req.seed,
        page=page,
        page_size=page_size,
        context=search_context(corpus, req),
        count_timeout=count_timeout,
        **kw,
    )


def pg_answered(ast, cqp) -> bool:
    """Pure span and pure attribute queries are answered from PostgreSQL (services.api.effective)."""
    return bool(query.spans(cqp) and query.pure_span(ast)) or bool(
        query.attrs(cqp) and pure_attr(ast)
    )


def attr_filter_for(db, cqp, layers):
    """attr_filter for cwb: keep hits whose attribute / span slot tokens satisfy the constraints; None
    without such slots."""
    constraints = query.attrs(cqp)
    span_constraints = query.spans(cqp)
    if not constraints and not span_constraints:
        return None

    def attr_filter(slot, keys):
        if slot in constraints:
            keys = effective.filter_tokens(db, layers, constraints[slot], keys)
        if slot in span_constraints:
            keys = effective.filter_span_tokens(
                db, layers["span"], span_constraints[slot], keys
            )
        return keys

    return attr_filter


def search_page(db, corpus, restrict, ast, cqp, layers, req, page, page_size, timeout):
    """One page of hits. Attribute constraints are resolved in PostgreSQL (services.api.effective):
    pure attribute queries entirely, anchored ones by filtering the CWB hits on the slot tokens. Span labels
    likewise: a pure span query lists the effective spans, anchored ones keep slot tokens inside them."""
    constraints = query.attrs(cqp)
    span_constraints = query.spans(cqp)
    if span_constraints and query.pure_span(ast):
        filt = scope_filter(db, req.scope)
        fields = field_types(db, corpus.id) if filt else {}
        return effective.span_search(
            db,
            corpus,
            filt,
            fields,
            layers["span"],
            span_constraints[0],
            req,
            page,
            page_size,
        )
    if constraints and pure_attr(ast):
        filt = scope_filter(db, req.scope)
        fields = field_types(db, corpus.id) if filt else {}
        atom = ast.anchor.items[0][0]
        return effective.pg_search(
            db, corpus, filt, fields, atom, constraints[0], layers, req, page, page_size
        )
    return run_search(
        corpus,
        restrict,
        cqp,
        req,
        page,
        page_size,
        timeout,
        attr_filter_for(db, cqp, layers),
    )


class SearchCache:
    """search_id → seed, counts and the result set, so paging and count re-checks reuse the first search.

    CWB searches (contracts/p7.md §1): the complete hit rows (filtered and sorted) are computed once and
    stored under DATA_DIR/search-cache/<search_id>; pages are slices of it. When the first run exceeds
    COUNT_TIMEOUT, one background full count per search_id runs (at most WORKERS at a time; one per user and
    sign-in kind — browser session or agent token — where a new one cancels the previous unfinished count).
    Until it finishes pages come from a corpus-order prefix (`partial`, the first `cut` rows). More than
    MAX_HITS anchor hits fail the count. Entry state: None (not run) | running | done | failed.

    Held in the single API process; after a restart an old search_id gets 409 and the page re-runs the
    search. Result sets are deleted with their entries (LRU by count, LIMIT, and by size, CACHE_MAX_BYTES);
    the API empties the directory at startup (clear_dir).
    """

    LIMIT = 2000
    WORKERS = 2

    def __init__(self):
        self.entries = OrderedDict()
        self.lock = Lock()
        self.pool = None
        self.running = {}  # (user id, sign-in kind) → entry whose background count has not finished
        self.bytes = 0  # size of the stored result sets

    @staticmethod
    def root():
        return data_dir() / "search-cache"

    def clear_dir(self):
        """Delete all stored result sets (API startup)."""
        shutil.rmtree(self.root(), ignore_errors=True)

    def clear(self):
        """Forget every entry and delete its files (tests)."""
        with self.lock:
            while self.entries:
                self._drop(self.entries.popitem(last=False)[1])
            self.bytes = 0

    def open(self, corpus, restrict, cqp, req: SearchInput):
        """Return (search_id, entry); entry = {"key", "seed", "counts", "state", ...}."""
        key = hashlib.sha256(
            json.dumps(
                [str(corpus.id), corpus.index_version, restrict, cqp, req.sort]
            ).encode()
        ).hexdigest()
        with self.lock:
            if req.search_id:
                entry = self.entries.get(req.search_id)
                if not entry or entry["key"] != key:
                    raise ApiError(409, "SEARCH_EXPIRED", "检索结果已失效，请重新检索")
                self.entries.move_to_end(req.search_id)
                return req.search_id, entry
            seed = req.seed
            if req.sort == "random" and seed is None:
                seed = secrets.randbelow(2**31)
            sid = secrets.token_hex(8)
            entry = {
                "sid": sid,
                "key": key,
                "seed": seed,
                "counts": None,
                "state": None,
                "dir": None,
                "bytes": 0,
                "partial": [],
                "cut": 0,
                "message": None,
                "cancel": Event(),
            }
            self.entries[sid] = entry
            while len(self.entries) > self.LIMIT:
                self._drop(self.entries.popitem(last=False)[1])
            return sid, entry

    def _drop(self, entry):
        """(under the lock) an entry left the cache: stop its count, delete its files."""
        entry["cancel"].set()
        if entry["dir"]:
            shutil.rmtree(entry["dir"], ignore_errors=True)
            self.bytes -= entry["bytes"]

    def finish(self, entry, rows):
        """Write the complete rows as the entry's result set and record the counts; then delete the least
        recently used result sets while the stored total exceeds CACHE_MAX_BYTES."""
        path = self.root() / entry["sid"]
        size = cwb.write_rows(path, rows)
        counts = counts_view(cwb.count_rows(rows))
        with self.lock:
            if self.entries.get(entry["sid"]) is not entry:  # evicted meanwhile
                shutil.rmtree(path, ignore_errors=True)
                return
            entry.update(
                state="done", dir=path, bytes=size, counts=counts, partial=None
            )
            self.bytes += size
            for sid in list(self.entries):
                if self.bytes <= CACHE_MAX_BYTES:
                    break
                old = self.entries[sid]
                if old is not entry and old["dir"]:
                    del self.entries[sid]
                    self._drop(old)

    def fail(self, entry, message):
        with self.lock:
            if entry["state"] != "done":
                entry.update(state="failed", message=message)

    def start(self, entry, owner, job):
        """Run job(cancel) → complete rows in the background; owner = (user id, sign-in kind)."""
        with self.lock:
            prev = self.running.get(owner)
            if prev is not None and prev is not entry:
                prev["cancel"].set()
            self.running[owner] = entry
            entry["state"] = "running"
            if self.pool is None:
                self.pool = ThreadPoolExecutor(
                    self.WORKERS, thread_name_prefix="search-count"
                )
            self.pool.submit(self._run, entry, owner, job)

    def _run(self, entry, owner, job):
        try:
            if entry["cancel"].is_set():
                raise cwb.Cancelled()
            rows = job(entry["cancel"])
            if entry["cancel"].is_set():
                raise cwb.Cancelled()
            self.finish(entry, rows)
        except subprocess.TimeoutExpired:
            self.fail(entry, timeout_message())
        except cwb.TooManyHits:
            self.fail(entry, too_many_message())
        except cwb.Cancelled:
            self.fail(entry, "计数已取消：已开始新的检索")
        except Exception:
            log.exception("background search count failed")
            self.fail(entry, "计数失败，请重试")
        finally:
            with self.lock:
                if self.running.get(owner) is entry:
                    del self.running[owner]

    def counts(self, entry):
        """Counts of an unfinished entry: unknown, or failed with the reason."""
        counts = {"hits": None, "sentences": None, "documents": None, "complete": False}
        with self.lock:
            if entry["state"] == "failed":
                counts.update(failed=True, message=entry["message"])
        return counts


searches = SearchCache()


def timeout_message():
    return f"计数超时（{FULL_TIMEOUT:g} 秒），请缩小范围或加条件"


def too_many_message():
    n = MAX_HITS
    shown = f"{n // 10000} 万" if n >= 10000 and n % 10000 == 0 else f"{n}"
    return f"命中超过 {shown}，请缩小范围或加条件"


def counts_view(c):
    return {
        "hits": c.hits,
        "sentences": c.sentences,
        "documents": c.documents,
        "complete": c.complete,
    }


def cwb_page(db, user, entry, corpus, restrict, cqp, layers, req: SearchInput):
    """(engine hits, counts, sort_applied) of one page of a CWB query, from the search_id's result set.

    First request: the full query with COUNT_TIMEOUT; on timeout a background count with FULL_TIMEOUT
    starts and pages come from a corpus-order prefix (sort not applied) until it is done. More than MAX_HITS
    anchor hits fail the count at once; pages still come from the prefix."""
    ix, key = index_dir(corpus.id), corpus_key(corpus.id)
    ctx = search_context(corpus, req)
    lo, hi = (req.page - 1) * req.page_size, req.page * req.page_size
    rows_kw = {"restrict": restrict, "attr_filter": attr_filter_for(db, cqp, layers)}
    if entry["state"] is None:  # only the request that created the search_id gets here
        try:
            rows = cwb.query_rows(
                ix,
                key,
                cqp,
                sort=req.sort,
                seed=req.seed,
                timeout=COUNT_TIMEOUT,
                max_hits=MAX_HITS,
                **rows_kw,
            )
        except subprocess.TimeoutExpired:
            owner = (user.id, "token" if token_project(user) else "session")
            job = full_count(corpus, restrict, cqp, layers, req)
            searches.start(entry, owner, job)
        except cwb.TooManyHits:
            searches.fail(entry, too_many_message())
        else:
            searches.finish(entry, rows)
            return cwb.hits(ix, key, cqp, rows[lo:hi], ctx), entry["counts"], True
    with searches.lock:
        state, path, counts = entry["state"], entry["dir"], entry["counts"]
        partial, cut = entry["partial"], entry["cut"]
    if state == "done":
        try:
            rows = cwb.read_rows(path, lo, hi)
        except FileNotFoundError:
            raise ApiError(409, "SEARCH_EXPIRED", "检索结果已失效，请重新检索")
        return cwb.hits(ix, key, cqp, rows, ctx), counts, True
    if cut < hi:  # a page past the prefix read so far
        partial = cwb.prefix_rows(
            ix,
            key,
            cqp,
            hi,
            timeout=max(COUNT_TIMEOUT, 60),
            max_hits=MAX_HITS,
            **rows_kw,
        )
        with searches.lock:
            if entry["state"] != "done" and entry["cut"] < hi:
                entry.update(partial=partial, cut=hi)
    hits = cwb.hits(ix, key, cqp, partial[lo:hi], ctx)
    return hits, searches.counts(entry), req.sort == "position"


def full_count(corpus, restrict, cqp, layers, req: SearchInput):
    """Background job: the complete rows with FULL_TIMEOUT and MAX_HITS, in its own database session."""
    ix, key = index_dir(corpus.id), corpus_key(corpus.id)

    def job(cancel):
        with session() as db:
            return cwb.query_rows(
                ix,
                key,
                cqp,
                restrict=restrict,
                sort=req.sort,
                seed=req.seed,
                timeout=FULL_TIMEOUT,
                attr_filter=attr_filter_for(db, cqp, layers),
                cancel=cancel,
                max_hits=MAX_HITS,
            )

    return job


def aligned_texts(db, sentence_ids):
    """{sentence id: [{"language", "text"}]}: sentences aligned to each id, in either direction."""
    aligned = {}
    if sentence_ids:
        ids = list(sentence_ids)
        for mine, other in (
            (SentenceAlignment.src_sentence_id, SentenceAlignment.tgt_sentence_id),
            (SentenceAlignment.tgt_sentence_id, SentenceAlignment.src_sentence_id),
        ):
            rows = db.execute(
                select(mine, Document.language, Sentence.text)
                .join(Sentence, Sentence.id == other)
                .join(Document, Document.id == Sentence.document_id)
                .where(mine.in_(ids))
                .order_by(Document.language, Sentence.document_id, Sentence.idx)
            )
            for sid, language, text in rows:
                aligned.setdefault(sid, []).append({"language": language, "text": text})
    return aligned


def enrich(db, hits):
    """Engine hits → HTTP hits with document title, metadata and aligned sentences."""
    doc_ids = {UUID(h.doc_id) for h in hits}
    docs = {
        d.id: d for d in db.scalars(select(Document).where(Document.id.in_(doc_ids)))
    }
    keys = {(UUID(h.doc_id), h.sentence_index) for h in hits}
    sentence_ids = {}
    if keys:
        rows = db.execute(
            select(Sentence.id, Sentence.document_id, Sentence.idx).where(
                tuple_(Sentence.document_id, Sentence.idx).in_(keys)
            )
        )
        sentence_ids = {(doc, idx): sid for sid, doc, idx in rows}
    aligned = aligned_texts(db, sentence_ids.values())
    items = []
    for h in hits:
        doc = docs.get(UUID(h.doc_id))
        sid = sentence_ids.get((UUID(h.doc_id), h.sentence_index))
        items.append(
            {
                "hit_id": h.hit_id,
                "document_id": h.doc_id,
                "document_title": doc.title if doc else "",
                "sentence_index": h.sentence_index,
                "left": h.left,
                "match": h.match,
                "right": h.right,
                "start_cp": h.start_cp,
                "end_cp": h.end_cp,
                "metadata": doc.meta if doc else {},
                "aligned": aligned.get(sid, []),
            }
        )
    return items


def attach_tokens(db, items):
    """Hit.tokens: the hit sentence's tokens in order, part left/match/right by document code points."""
    keys = {(UUID(i["document_id"]), i["sentence_index"]) for i in items}
    by_sentence = {}
    if keys:
        rows = db.execute(
            select(
                Sentence.document_id,
                Sentence.idx,
                Token.start_cp,
                Token.end_cp,
                Token.form,
                Token.pos,
            )
            .join(Token, Token.sentence_id == Sentence.id)
            .where(tuple_(Sentence.document_id, Sentence.idx).in_(keys))
            .order_by(Sentence.document_id, Sentence.idx, Token.idx)
        )
        for doc, idx, start, end, form, pos in rows:
            by_sentence.setdefault((doc, idx), []).append((start, end, form, pos))
    for item in items:
        a, b = item["start_cp"], item["end_cp"]
        toks = by_sentence.get((UUID(item["document_id"]), item["sentence_index"]), [])
        item["tokens"] = [
            {
                "part": "left" if end <= a else "right" if start >= b else "match",
                "form": form,
                "pos": pos,
            }
            for start, end, form, pos in toks
        ]
    return items


# ---- routes ----


@router.post("/search/parse")
def parse(body: ParseInput, user: CurrentUser, db: Db):
    if body.scope is None:
        return parse_view(body.query)
    corpus, _ = resolve_scope(db, body.scope, user)
    tagset = corpus_tagset(corpus)
    view = parse_view(body.query, tagset)
    view["corpus"] = corpus_info(db, corpus, user, tagset)
    if view["ok"]:
        problem = layer_problem(db, corpus, user, query.parse(body.query, tagset))
        if problem:
            view["ok"] = False
            view["error"] = {"position": problem[0], "message": problem[1]}
    return view


@router.post("/search")
def search(body: SearchInput, user: CurrentUser, db: Db):
    corpus, restrict = resolve_scope(db, body.scope, user)
    tagset = corpus_tagset(corpus)
    ast, cqp = plan_query(body.query, tagset)
    layers = effective.check_layers(db, body.layers, corpus, user)
    with_span_layer(db, cqp, layers, corpus, user)
    check_layer_problem(db, corpus, user, ast, layers)
    sid, entry = searches.open(corpus, restrict, cache_key(cqp, layers), body)
    req = body.model_copy(update={"seed": entry["seed"]})
    if pg_answered(ast, cqp):
        result = search_page(
            db,
            corpus,
            restrict,
            ast,
            cqp,
            layers,
            req,
            body.page,
            body.page_size,
            COUNT_TIMEOUT,
        )
        hits = result.items
        counts = entry["counts"] or counts_view(result.counts)
        if counts["complete"]:
            entry["counts"] = counts
        sort_applied = counts["complete"] or body.sort == "position"
    else:
        hits, counts, sort_applied = cwb_page(
            db, user, entry, corpus, restrict, cqp, layers, req
        )
    items = enrich(db, hits)
    if body.include_tokens:
        attach_tokens(db, items)
    return {
        "search_id": sid,
        "parse": parse_view(body.query, tagset),
        "counts": counts,
        "sort_applied": sort_applied,
        "items": items,
        "page": body.page,
        "page_size": body.page_size,
    }


@router.get("/search/context")
def context(
    user: CurrentUser,
    db: Db,
    document_id: UUID,
    sentence_index: Annotated[int, Query(ge=0)],
    before: Annotated[int, Query(ge=0, le=20)] = 1,
    after: Annotated[int, Query(ge=0, le=20)] = 1,
    start_cp: Annotated[int | None, Query(ge=0)] = None,
    end_cp: Annotated[int | None, Query(ge=0)] = None,
):
    doc = db.get(Document, document_id)
    if not doc:
        raise not_found("文档")
    load_corpus(db, doc.corpus_id, user)
    rows = db.scalars(
        select(Sentence)
        .where(
            Sentence.document_id == document_id,
            Sentence.idx.between(sentence_index - before, sentence_index + after),
        )
        .order_by(Sentence.idx)
    ).all()
    if not any(s.idx == sentence_index for s in rows):
        raise not_found("句子")
    sentences = []
    for s in rows:
        highlight = None
        if s.idx == sentence_index and start_cp is not None and end_cp is not None:
            # Hit code points are document-relative; highlight is relative to the sentence text.
            highlight = [start_cp - s.start_cp, end_cp - s.start_cp]
        sentences.append({"index": s.idx, "text": s.text, "highlight": highlight})
    return {"document": document_view(doc), "sentences": sentences}


@router.post("/search/export")
def export(body: ExportInput, user: CurrentUser, db: Db):
    corpus, restrict = resolve_scope(db, body.scope, user)
    ast, cqp = plan_query(body.query, corpus_tagset(corpus))
    layers = effective.check_layers(db, body.layers, corpus, user)
    with_span_layer(db, cqp, layers, corpus, user)
    check_layer_problem(db, corpus, user, ast, layers)
    if layers.get("span"):
        body = body.model_copy(
            update={
                "layers": (body.layers or LayersInput()).model_copy(
                    update={"span": layers["span"].id}
                )
            }
        )
    _, entry = searches.open(corpus, restrict, cache_key(cqp, layers), body)
    body = body.model_copy(update={"seed": entry["seed"], "search_id": None})
    if body.scope.subcorpus_id:
        project_id = db.get(Subcorpus, body.scope.subcorpus_id).project_id
    else:
        project_id = corpus.project_id or body.project_id or token_project(user)
        if body.project_id and corpus.project_id is None:
            require_project(db, body.project_id, user, READ)
    params = body.model_dump(mode="json", exclude={"project_id"})
    job = enqueue(db, "export", params, user.id, project_id)
    db.commit()
    return job_view(job)


@router.get("/projects/{project_id}/queries")
def list_queries(project_id: UUID, user: CurrentUser, db: Db, paging: Paging):
    require_project(db, project_id, user)
    stmt = (
        select(SavedQuery)
        .where(SavedQuery.project_id == project_id)
        .order_by(SavedQuery.created_at.desc(), SavedQuery.id)
    )
    return paging.run(db, stmt, saved_query_view)


@router.post("/projects/{project_id}/queries")
def create_query(project_id: UUID, body: SavedQueryInput, user: CurrentUser, db: Db):
    require_project(db, project_id, user, WRITE)
    if body.scope.subcorpus_id:
        sub = load_subcorpus(db, body.scope.subcorpus_id, user)
        if sub.project_id != project_id:
            raise not_found("子库")
    else:
        project_corpus(db, project_id, body.scope.corpus_id)
    saved = SavedQuery(
        project_id=project_id,
        name=body.name.strip(),
        query=body.query,
        scope=body.scope.model_dump(mode="json", exclude_none=True),
        created_by=user.id,
    )
    db.add(saved)
    db.commit()
    return saved_query_view(saved)


@router.delete("/queries/{query_id}", status_code=204)
def delete_query(query_id: UUID, user: CurrentUser, db: Db):
    human_only(user)
    saved = db.get(SavedQuery, query_id)
    if not saved:
        raise not_found("查询")
    require_project(db, saved.project_id, user, WRITE)
    db.delete(saved)
    db.commit()
