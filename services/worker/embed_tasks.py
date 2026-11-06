"""embed_corpus (contracts/p10.md §六): embed every sentence of a corpus into sentence_embeddings.

Vectors are upserted in blocks of BLOCK sentences: during a rebuild with the same model every sentence keeps a
valid vector (old or new), so the previous index stays complete and searchable; vectors of sentences the build no
longer covers are removed only at the end. A cancelled build leaves corpora.semantic as it was. A failed build
records the error (error, last_error_at) and keeps a searchable index of the same model as it was; without one the
status is failed. Documents added or deleted while the build runs: the index ends stale when the sentences it
holds no longer match the covered documents.
"""

import time
import uuid
from datetime import UTC, datetime

from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from engine.kb import embed
from services.api.db import session, transaction
from services.api.errors import ApiError
from services.api.models import Corpus, Document, Sentence, SentenceEmbedding
from services.api.semantic import SEARCHABLE, documents_of, max_sentences
from services.worker.main import Cancelled, JobFailed, log

BLOCK = 512  # sentences per model call and per INSERT


def _failed(corpus_id, message):
    """A failed build: a searchable index of the current model keeps its status and vectors."""
    with transaction() as db:
        corpus = db.get(Corpus, corpus_id)
        if corpus is None:
            return
        sem = corpus.semantic or {}
        keep = (
            sem.get("status") in SEARCHABLE and sem.get("model") == embed.model_name()
        )
        corpus.semantic = {
            **sem,
            "status": sem["status"] if keep else "failed",
            "error": message,
            "last_error_at": datetime.now(UTC).isoformat(),
        }


def _embed_all(run, corpus_id, language):
    with session() as db:
        if db.get(Corpus, corpus_id) is None:
            raise JobFailed("NOT_FOUND", "语料库已删除")
        ids = db.scalars(
            select(Sentence.id)
            .join(Document, Document.id == Sentence.document_id)
            .where(*documents_of(corpus_id, language))
            .order_by(Sentence.id)
        ).all()
    total, limit = len(ids), max_sentences()
    if total > limit:
        raise JobFailed(
            "TOO_LARGE", f"语料共 {total:,} 句，超过语义索引上限 {limit:,} 句"
        )
    model = embed.model_name()
    run.progress(0, total, "加载向量模型", "句")
    try:
        embed.load(download=True)
    except embed.EmbedUnavailable as e:
        raise JobFailed("EMBED_UNAVAILABLE", str(e)) from e
    started = time.monotonic()
    for i in range(0, total, BLOCK):
        run.check()
        run.progress(i, total, "向量化", "句")
        with session() as db:
            rows = db.execute(
                select(Sentence.id, Sentence.text).where(
                    Sentence.id.in_(ids[i : i + BLOCK])
                )
            ).all()  # sentences deleted meanwhile are left out
        if not rows:
            continue
        try:
            vectors = embed.embed([t for _, t in rows], download=False)
        except embed.EmbedUnavailable as e:
            raise JobFailed("EMBED_UNAVAILABLE", str(e)) from e
        stmt = pg_insert(SentenceEmbedding).values(
            [
                {"sentence_id": sid, "corpus_id": corpus_id, "embedding": v}
                for (sid, _), v in zip(rows, vectors)
            ]
        )
        with transaction() as db:
            db.execute(
                stmt.on_conflict_do_update(
                    index_elements=["sentence_id"],
                    set_={"embedding": stmt.excluded.embedding},
                )
            )
    seconds = round(time.monotonic() - started, 1)
    with transaction() as db:
        run.lock(db)
        corpus = db.get(Corpus, corpus_id)
        if corpus is None:
            raise JobFailed("NOT_FOUND", "语料库已删除")
        # vectors of sentences the build does not cover (another language than this build's) go
        db.execute(
            delete(SentenceEmbedding).where(
                SentenceEmbedding.corpus_id == corpus_id,
                SentenceEmbedding.sentence_id.not_in(
                    select(Sentence.id)
                    .join(Document, Document.id == Sentence.document_id)
                    .where(*documents_of(corpus_id, language))
                ),
            )
        )
        n = db.scalar(
            select(func.count())
            .select_from(SentenceEmbedding)
            .where(SentenceEmbedding.corpus_id == corpus_id)
        )
        # documents imported or deleted meanwhile: the covered documents no longer match the vectors
        covered = db.scalar(
            select(func.coalesce(func.sum(Document.sentence_count), 0)).where(
                *documents_of(corpus_id, language)
            )
        )
        corpus.semantic = {
            "status": "ready" if n == covered else "stale",
            "sentences": n,
            "model": model,
            "language": language,
            "built_at": datetime.now(UTC).isoformat(),
            "seconds": seconds,
            "error": None,
        }
        run.succeed(db, {"sentences": n, "seconds": seconds})
    log.info("embed_corpus %s: %d sentences in %.1f s", corpus_id, n, seconds)


def run_embed_corpus(run):
    corpus_id = uuid.UUID(run.params["corpus_id"])
    try:
        _embed_all(run, corpus_id, run.params.get("language"))
    except Cancelled:
        raise
    except (JobFailed, ApiError) as e:
        _failed(corpus_id, e.message)
        raise
    except Exception as e:
        _failed(corpus_id, str(e)[:500])
        raise


HANDLERS = {"embed_corpus": run_embed_corpus}
