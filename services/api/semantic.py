"""Semantic sentence search (contracts/p10.md §六).

The worker (`embed_corpus`, services/worker/embed_tasks.py) embeds every sentence of a corpus with the knowledge
base model (engine.kb.embed) into `sentence_embeddings`; the query sentence is embedded here and the nearest
sentences in the scope come back as whole-sentence hits. `corpora.semantic` keeps the result of the last build:
{status: ready | stale | failed, sentences, model, built_at, seconds, error}; "building" and "none" are derived
(an active job / nothing built). A build may cover the documents of one language only (`language`, e.g. the Chinese
side of a parallel corpus). An index build after documents were added or deleted marks a ready index stale
(mark_stale, called by the worker's index task); a stale index still answers searches.
"""

import os
from datetime import datetime
from uuid import UUID

from fastapi import APIRouter
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, literal, select, text

from engine.kb import embed
from engine.model import Hit
from services.api.access import (
    WRITE,
    human_only,
    load_corpus,
    project_role,
    token_project,
)
from services.api.auth import CurrentUser, Db
from services.api.effective import scope_clauses
from services.api.errors import ApiError
from services.api.jobs import ACTIVE, enqueue, queue_ahead
from services.api.metadata import field_types
from services.api.models import Document, Job, Sentence, SentenceEmbedding
from services.api.search import Scope, enrich, resolve_scope, scope_filter
from services.api.views import job_view

router = APIRouter(prefix="/api")

KIND = "embed_corpus"
SEARCHABLE = ("ready", "stale")
# scopes with at most this many embedded sentences are searched exactly; larger ones through the HNSW index
EXACT_MAX = 50_000
# sentences per second until a build has been measured (MiniLM-L12 on 16 CPU cores: 250-280 for model calls alone)
DEFAULT_RATE = 200.0


def max_sentences() -> int:
    return int(os.environ.get("SEMANTIC_MAX_SENTENCES") or 300_000)


def documents_of(corpus_id, language=None):
    """Conditions on Document for the documents a semantic index covers."""
    where = [Document.corpus_id == corpus_id]
    if language:
        where.append(Document.language == language)
    return where


def sentence_count(db, corpus_id, language=None) -> int:
    return db.scalar(
        select(func.count())
        .select_from(Sentence)
        .join(Document, Document.id == Sentence.document_id)
        .where(*documents_of(corpus_id, language))
    )


def by_language(db, corpus_id) -> dict[str, int]:
    rows = db.execute(
        select(Document.language, func.sum(Document.sentence_count))
        .where(Document.corpus_id == corpus_id)
        .group_by(Document.language)
        .order_by(Document.language)
    )
    return {lang: int(n or 0) for lang, n in rows}


def mark_stale(db, corpus):
    """After an index build: a ready semantic index whose sentence count no longer matches (documents added or
    deleted) is stale. Metadata edits keep it ready (scope filters read document metadata live)."""
    sem = corpus.semantic or {}
    if sem.get("status") != "ready":
        return
    now = db.scalar(
        select(func.coalesce(func.sum(Document.sentence_count), 0)).where(
            *documents_of(corpus.id, sem.get("language"))
        )
    )
    if sem.get("sentences") != now:
        corpus.semantic = {**sem, "status": "stale"}


def latest_job(db, corpus_id):
    return db.scalar(
        select(Job)
        .where(Job.kind == KIND, Job.params["corpus_id"].astext == str(corpus_id))
        .order_by(Job.created_at.desc(), Job.id)
        .limit(1)
    )


def may_build(db, corpus, user) -> bool:
    """Owner / editor of the corpus's project; built-in corpora: platform admins. Browser sessions only."""
    if token_project(user) is not None:
        return False
    if corpus.project_id is None:
        return bool(user.is_admin)
    return project_role(db, corpus.project_id, user) in WRITE


def _when(value):
    return datetime.fromisoformat(value) if value else None


def status_of(db, corpus):
    """(status, error, job): building while a job is queued or running; failed when the last job failed after the
    last successful build (also a job failed by the worker reaper); otherwise the stored status, "none" if never
    built, and "stale" when the vectors came from another model."""
    sem = corpus.semantic or {}
    job = latest_job(db, corpus.id)
    status, error = sem.get("status") or "none", sem.get("error")
    if job is not None and job.state in ACTIVE:
        return "building", None, job
    built = _when(sem.get("built_at"))
    if status in SEARCHABLE and sem.get("model") != embed.model_name():
        return "stale", "向量模型已更换，请重建语义索引", job
    if (
        job is not None
        and job.state == "failed"
        and (built is None or job.finished_at > built)
    ):
        message = (job.error or {}).get("message") or error
        if status in SEARCHABLE:  # the previous index still answers
            return status, f"上次重建失败：{message}", job
        return "failed", message, job
    if status in SEARCHABLE:
        error = None  # the last build succeeded
    return status, error, job


def semantic_view(db, corpus, user):
    sem = corpus.semantic or {}
    status, error, job = status_of(db, corpus)
    languages = by_language(db, corpus.id)
    total = sum(languages.values())
    rate = DEFAULT_RATE
    if sem.get("seconds") and sem.get("sentences"):
        rate = max(sem["sentences"] / max(sem["seconds"], 0.001), 1.0)
    return {
        "corpus_id": corpus.id,
        "status": status,
        "error": error,
        "sentences": total,
        # sentences per document language (a build may cover one language)
        "languages": languages,
        "language": sem.get("language"),
        "rate": round(rate, 1),
        "indexed": sem.get("sentences") if status != "none" else None,
        # the stored vectors answer searches (also while a rebuild runs)
        "searchable": sem.get("status") in SEARCHABLE
        and sem.get("model") == embed.model_name(),
        "model": sem.get("model"),
        "built_at": sem.get("built_at"),
        "estimate_seconds": round(total / rate),
        "max_sentences": max_sentences(),
        "can_build": may_build(db, corpus, user),
        "job": job
        and {
            "id": job.id,
            "state": job.state,
            "progress": job.progress,
            "error": job.error,
            "queue_ahead": queue_ahead(db, job),
        },
    }


@router.get("/corpora/{corpus_id}/semantic-index")
def get_semantic_index(corpus_id: UUID, user: CurrentUser, db: Db):
    corpus = load_corpus(db, corpus_id, user)
    return semantic_view(db, corpus, user)


class BuildInput(BaseModel):
    """language: index only the documents of this language (e.g. one side of a parallel corpus); omitted = all."""

    language: str | None = Field(default=None, max_length=20)


@router.post("/corpora/{corpus_id}/semantic-index")
def build_semantic_index(
    corpus_id: UUID, user: CurrentUser, db: Db, body: BuildInput | None = None
):
    human_only(user)
    corpus = load_corpus(db, corpus_id, user, write=True)
    if corpus.status not in SEARCHABLE or not corpus.index_version:
        raise ApiError(409, "CORPUS_NOT_READY", "语料库尚未完成索引")
    language = ((body.language or "").strip() or None) if body else None
    if language and language not in by_language(db, corpus.id):
        raise ApiError(422, "VALIDATION_ERROR", f"语料中没有语言为 {language} 的文档")
    n = sentence_count(db, corpus.id, language)
    limit = max_sentences()
    if n > limit:
        raise ApiError(
            422,
            "TOO_LARGE",
            f"语料共 {n:,} 句，超过语义索引上限 {limit:,} 句，可只建一种语言或拆分语料",
        )
    if status_of(db, corpus)[0] == "building":
        raise ApiError(409, "JOB_IN_PROGRESS", "语义索引正在建立")
    job = enqueue(
        db,
        KIND,
        {"corpus_id": str(corpus.id), "sentences": n, "language": language},
        user.id,
        corpus.project_id,
    )
    db.commit()
    return job_view(job)


class SemanticInput(BaseModel):
    scope: Scope
    text: str = Field(min_length=1, max_length=500)
    top: int = Field(default=50, ge=1, le=200)

    @field_validator("text")
    @classmethod
    def not_blank(cls, v):
        if not v.strip():
            raise ValueError("请输入句子")
        return v.strip()


def nearest(db, corpus, where, vec, top):
    """[(sentence id, document id, sentence idx, start_cp, end_cp, text, distance)] closest first. Small scopes
    are ranked exactly; larger ones by the HNSW index with an iterative scan, so scope filters still fill `top`."""
    base = (
        select(func.count())
        .select_from(SentenceEmbedding)
        .join(Sentence, Sentence.id == SentenceEmbedding.sentence_id)
        .join(Document, Document.id == Sentence.document_id)
        .where(SentenceEmbedding.corpus_id == corpus.id, *where)
    )
    dist = SentenceEmbedding.embedding.cosine_distance(vec)
    if db.scalar(base) <= EXACT_MAX:
        order = dist + literal(
            0.0
        )  # not the indexed expression: exact ranking of the scope's rows
    else:
        db.execute(text("SET LOCAL hnsw.ef_search = 400"))
        db.execute(text("SET LOCAL hnsw.iterative_scan = strict_order"))
        db.execute(text("SET LOCAL hnsw.max_scan_tuples = 200000"))
        order = dist
    return db.execute(
        select(
            Sentence.id,
            Sentence.document_id,
            Sentence.idx,
            Sentence.start_cp,
            Sentence.end_cp,
            Sentence.text,
            dist,
        )
        .join(SentenceEmbedding, SentenceEmbedding.sentence_id == Sentence.id)
        .join(Document, Document.id == Sentence.document_id)
        .where(SentenceEmbedding.corpus_id == corpus.id, *where)
        .order_by(order, Sentence.id)
        .limit(top)
    ).all()


@router.post("/search/semantic")
def semantic_search(body: SemanticInput, user: CurrentUser, db: Db):
    corpus, _ = resolve_scope(db, body.scope, user)
    status = status_of(db, corpus)[0]
    sem = corpus.semantic or {}
    if sem.get("status") not in SEARCHABLE:
        raise ApiError(409, "SEMANTIC_NOT_READY", "该语料尚未建语义索引")
    if sem.get("model") != embed.model_name():
        raise ApiError(409, "SEMANTIC_MODEL_CHANGED", "向量模型已更换，请重建语义索引")
    try:
        vec = embed.embed([body.text], download=False)[0]
    except embed.EmbedUnavailable as e:
        raise ApiError(503, "EMBED_UNAVAILABLE", str(e)) from e
    where = scope_clauses(
        corpus, scope_filter(db, body.scope), field_types(db, corpus.id)
    )
    if sem.get("language"):
        where.append(Document.language == sem["language"])
    rows = nearest(db, corpus, where, vec, body.top)
    hits = [
        Hit(f"{doc}:{a}-{b}", str(doc), idx, a, b, "", sentence, "")
        for _sid, doc, idx, a, b, sentence, _d in rows
    ]
    items = enrich(db, hits)
    for item, row in zip(items, rows):
        item["score"] = round(1 - float(row[-1]), 4)
    return {
        "items": items,
        "status": status,
        "indexed": sem.get("sentences"),
        "model": sem.get("model"),
    }
