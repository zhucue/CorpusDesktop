import hashlib
import json
import secrets
from collections import OrderedDict
from threading import Lock
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Query
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import select, tuple_

from engine import cwb, query
from engine.model import Context
from services.api.access import (
    READ,
    WRITE,
    Paging,
    load_corpus,
    load_subcorpus,
    require_project,
    token_project,
)
from services.api.auth import CurrentUser, Db
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

COUNT_TIMEOUT = 20


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


class ExportInput(SearchInput):
    format: Literal["csv", "xlsx"]
    project_id: UUID | None = None


class ParseInput(BaseModel):
    query: str = Field(max_length=1000)


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


def compile_query(text, tagset="mixed"):
    try:
        return query.compile(query.parse(text, tagset))
    except query.QueryError as e:
        raise ApiError(422, "QUERY_INVALID", f"第 {e.position + 1} 个字符：{e.message}")


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


def run_search(corpus, restrict, cqp, req: SearchInput, page, page_size, count_timeout):
    return cwb.search(
        index_dir(corpus.id),
        corpus_key(corpus.id),
        cqp,
        restrict=restrict,
        sort=req.sort,
        seed=req.seed,
        page=page,
        page_size=page_size,
        context=Context(unit=req.context.unit, size=req.context.size),
        count_timeout=count_timeout,
    )


class SearchCache:
    """search_id → seed and final counts, so paging and count re-checks reuse the first search.

    Held in the single API process; after a restart an old search_id gets 409 and the page
    re-runs the search.
    """

    LIMIT = 2000

    def __init__(self):
        self.entries = OrderedDict()
        self.lock = Lock()

    def open(self, corpus, restrict, cqp, req: SearchInput):
        """Return (search_id, entry); entry = {"key", "seed", "counts"}."""
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
            entry = {"key": key, "seed": seed, "counts": None}
            self.entries[sid] = entry
            while len(self.entries) > self.LIMIT:
                self.entries.popitem(last=False)
            return sid, entry


searches = SearchCache()


def counts_view(c):
    return {
        "hits": c.hits,
        "sentences": c.sentences,
        "documents": c.documents,
        "complete": c.complete,
    }


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
    aligned = {}
    if sentence_ids:
        ids = list(sentence_ids.values())
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
def parse(body: ParseInput, user: CurrentUser):
    return parse_view(body.query)


@router.post("/search")
def search(body: SearchInput, user: CurrentUser, db: Db):
    corpus, restrict = resolve_scope(db, body.scope, user)
    tagset = corpus_tagset(corpus)
    cqp = compile_query(body.query, tagset)
    sid, entry = searches.open(corpus, restrict, cqp, body)
    req = body.model_copy(update={"seed": entry["seed"]})
    result = run_search(
        corpus, restrict, cqp, req, body.page, body.page_size, COUNT_TIMEOUT
    )
    counts = entry["counts"] or counts_view(result.counts)
    if counts["complete"]:
        entry["counts"] = counts
    items = enrich(db, result.items)
    if body.include_tokens:
        attach_tokens(db, items)
    return {
        "search_id": sid,
        "parse": parse_view(body.query, tagset),
        "counts": counts,
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
    cqp = compile_query(body.query, corpus_tagset(corpus))
    _, entry = searches.open(corpus, restrict, cqp, body)
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
    saved = db.get(SavedQuery, query_id)
    if not saved:
        raise not_found("查询")
    require_project(db, saved.project_id, user, WRITE)
    db.delete(saved)
    db.commit()
