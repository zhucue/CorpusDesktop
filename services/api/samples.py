"""Sampling search hits for manual coding (contracts/p8.md §五).

POST /projects/{id}/samples draws n hits (equal probability, without replacement, `seed`) from the complete
hits of a query and creates a single-mode span layer with one uncoded span per hit (label "", status
suggested), in sampling order (span ids ascend in that order). Coding is review: the coder sets a label
(modified / confirmed) or rejects the hit (not counted). Spans with label "" are left out of statistics,
agreement and exports. GET /layers/{id}/sample-summary gives the coded proportions with 95% Wilson intervals
and the estimated hit counts.
"""

import math
import random
import secrets
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

from fastapi import APIRouter
from pydantic import BaseModel, Field
from sqlalchemy import select, tuple_

from engine import cwb, query
from engine.model import Context
from services.api import effective
from services.api import search as search_api
from services.api.access import WRITE, load_subcorpus, require_project
from services.api.annotations import (
    empty_progress,
    layer_view,
    load_layer,
    refresh_progress,
)
from services.api.auth import CurrentUser, Db
from services.api.errors import ApiError, not_found
from services.api.label_sets import load_label_set
from services.api.metadata import field_types
from services.api.models import AnnotationLayer, Document, Sentence, SpanAnnotation
from services.api.search import (
    COUNT_TIMEOUT,
    AlignedInput,
    LayersInput,
    Scope,
    aligned_cache_key,
    aligned_keep,
    attr_filter_for,
    cache_key,
    check_layer_problem,
    corpus_tagset,
    plan_aligned,
    plan_query,
    pure_attr,
    resolve_scope,
    scope_filter,
    searches,
    too_many_text,
    with_span_layer,
)
from services.api.spans import label_ids, span_view
from services.api.storage import corpus_key, index_dir
from services.api.subcorpora import project_corpus

router = APIRouter(prefix="/api")

Z95 = 1.959963984540054


class SampleLayerInput(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    label_set_id: UUID


class SampleInput(BaseModel):
    scope: Scope
    query: str = Field(min_length=1, max_length=1000)
    aligned: AlignedInput | None = None
    layers: LayersInput | None = None
    n: int = Field(ge=1, le=500)
    seed: int | None = Field(default=None, ge=0, lt=2**31)
    layer: SampleLayerInput


def wilson(k: int, n: int, z: float = Z95) -> tuple[float, float] | tuple[None, None]:
    """95% Wilson score interval of k successes in n trials (Wilson 1927)."""
    if n <= 0:
        return None, None
    p = k / n
    d = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / d
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return max(0.0, centre - half), min(1.0, centre + half)


def _incomplete(message="检索计数未完成，请在计数完成后再抽样"):
    return ApiError(409, "SEARCH_INCOMPLETE", message)


def full_hits(db, user, body: SampleInput, corpus, restrict):
    """(rows, to_hits): every hit of the query in corpus order and a function turning chosen rows into
    (document id str, sentence index, start_cp, end_cp). CWB queries reuse a finished result set of the same
    search; otherwise they run with COUNT_TIMEOUT. 409 SEARCH_INCOMPLETE when that is not enough or there are
    too many hits."""
    ast, cqp = plan_query(body.query, corpus_tagset(corpus))
    layers = effective.check_layers(db, body.layers, corpus, user)
    with_span_layer(db, cqp, layers, corpus, user)
    check_layer_problem(db, corpus, user, ast, layers)
    plan = plan_aligned(db, corpus, user, body.aligned, layers, body.scope)
    try:
        keep = aligned_keep(db, corpus, plan, COUNT_TIMEOUT) if plan else None
        if (
            query.spans(cqp)
            and query.pure_span(ast)
            or query.attrs(cqp)
            and pure_attr(ast)
        ):
            filt = scope_filter(db, body.scope)
            fields = field_types(db, corpus.id) if filt else {}
            if query.spans(cqp):
                spans = effective.scope_spans(
                    db, corpus, filt, fields, layers["span"], query.spans(cqp)[0]
                )
                rows = effective.keep_rows(
                    [
                        (
                            s["document_id"],
                            s["sentence_index"],
                            s["start_cp"],
                            s["end_cp"],
                        )
                        for s in spans
                    ],
                    keep,
                )
            else:
                atom = ast.anchor.items[0][0]
                rows = effective.pg_rows(
                    db,
                    corpus,
                    filt,
                    fields,
                    atom,
                    query.attrs(cqp)[0],
                    layers,
                    keep=keep,
                )
            return rows, lambda chosen: [(str(r[0]), r[1], r[2], r[3]) for r in chosen]
        ix, key = index_dir(corpus.id), corpus_key(corpus.id)
        path = searches.done_rows(
            corpus, restrict, aligned_cache_key(cache_key(cqp, layers), plan)
        )
        rows = None
        if path is not None:
            try:
                total = (Path(path) / "rows.bin").stat().st_size // 16
                rows = cwb.read_rows(path, 0, total)
            except FileNotFoundError:
                rows = None
        if rows is None:
            kw = {"aligned": keep} if keep is not None else {}
            rows = list(
                cwb.query_rows(
                    ix,
                    key,
                    cqp,
                    restrict=restrict,
                    timeout=COUNT_TIMEOUT,
                    attr_filter=attr_filter_for(db, cqp, layers),
                    max_hits=search_api.MAX_HITS,
                    **kw,
                )
            )
    except subprocess.TimeoutExpired:
        raise _incomplete()
    except cwb.TooManyHits as e:
        raise _incomplete(too_many_text(e))

    def to_hits(chosen):
        hits = cwb.hits(ix, key, cqp, chosen, Context(unit="sentence", size=0))
        return [(h.doc_id, h.sentence_index, h.start_cp, h.end_cp) for h in hits]

    return rows, to_hits


def _check_scope(db, project_id, scope: Scope, user):
    if scope.subcorpus_id:
        sub = load_subcorpus(db, scope.subcorpus_id, user)
        if sub.project_id != project_id:
            raise not_found("子库")
    else:
        project_corpus(db, project_id, scope.corpus_id)


@router.post("/projects/{project_id}/samples")
def create_sample(project_id: UUID, body: SampleInput, user: CurrentUser, db: Db):
    require_project(db, project_id, user, WRITE)  # the rule for creating layers
    _check_scope(db, project_id, body.scope, user)
    corpus, restrict = resolve_scope(db, body.scope, user)
    label_set = load_label_set(db, body.layer.label_set_id, user)
    if label_set.project_id not in (None, project_id):
        raise not_found("标签集")
    if label_set.kind != "span":
        raise ApiError(422, "VALIDATION_ERROR", "抽样编码须使用片段标签集")
    rows, to_hits = full_hits(db, user, body, corpus, restrict)
    total = len(rows)
    if total == 0:
        raise ApiError(422, "NO_HITS", "没有命中，无法抽样")
    seed = body.seed if body.seed is not None else secrets.randbelow(2**31)
    picked = random.Random(seed).sample(range(total), min(body.n, total))
    hits = to_hits([rows[i] for i in picked])
    now = datetime.now(UTC)
    layer = AnnotationLayer(
        project_id=project_id,
        corpus_id=corpus.id,
        kind="span",
        name=body.layer.name.strip(),
        label_set_id=label_set.id,
        source_model="human",
        status="ready",
        progress=empty_progress(),
        document_ids=sorted({h[0] for h in hits}),
        created_by=user.id,
        mode="single",
        annotators=[user.id],
        meta={
            "sample": {
                "query": body.query,
                "scope": body.scope.model_dump(mode="json", exclude_none=True),
                "aligned": body.aligned.model_dump() if body.aligned else None,
                "n": body.n,
                "seed": seed,
                "total_hits": total,
                "created_at": now.isoformat(),
            }
        },
    )
    db.add(layer)
    db.flush()
    db.add_all(
        SpanAnnotation(
            layer_id=layer.id,
            annotator_id=user.id,
            document_id=UUID(doc),
            sentence_index=idx,
            start_cp=start,
            end_cp=end,
            label="",
            attrs={},
            model_label="",  # not hand-made: cannot be deleted, only rejected
            source=f"sample:{seed}",
            status="suggested",
            revision=1,
            updated_by=user.id,
            updated_at=now,
        )
        for doc, idx, start, end in hits
    )
    db.flush()
    refresh_progress(db, layer)
    db.commit()
    return {
        "layer_id": layer.id,
        "sampled": len(hits),
        "total": total,
        "seed": seed,
        "layer": layer_view(db, layer),
    }


def _sample_layer(db, layer_id, user):
    layer = load_layer(db, layer_id, user)
    sample = (layer.meta or {}).get("sample")
    if layer.kind != "span" or not sample:
        raise ApiError(422, "NOT_SAMPLE", "该层不是抽样层")
    return layer, sample


def _spans(db, layer):
    return db.scalars(
        select(SpanAnnotation)
        .where(SpanAnnotation.layer_id == layer.id)
        .order_by(SpanAnnotation.id)
    ).all()


def summary(db, layer, sample) -> dict:
    spans = _spans(db, layer)
    coded = [s for s in spans if s.status in effective.HUMAN and s.label != ""]
    rejected = sum(s.status == "rejected" for s in spans)
    labels = label_ids(db, layer)
    counts = {}
    for s in coded:
        counts[s.label] = counts.get(s.label, 0) + 1
    order = list(labels) + sorted(k for k in counts if k not in labels)
    n, total = len(coded), sample["total_hits"]
    out = []
    for k in order:
        c = counts.get(k, 0)
        lo, hi = wilson(c, n)
        pct = c / n if n else None
        out.append(
            {
                "label": k,
                "name": labels.get(k, {}).get("name", k),
                "count": c,
                "pct": pct,
                "ci_low": lo,
                "ci_high": hi,
                "estimate": round(pct * total) if pct is not None else None,
            }
        )
    return {
        "total_hits": total,
        "sampled": len(spans),
        "coded": n,
        "rejected": rejected,
        "seed": sample.get("seed"),
        "labels": out,
    }


@router.get("/layers/{layer_id}/sample-summary")
def sample_summary(layer_id: UUID, user: CurrentUser, db: Db):
    layer, sample = _sample_layer(db, layer_id, user)
    return summary(db, layer, sample)


@router.get("/layers/{layer_id}/sample-items")
def sample_items(layer_id: UUID, user: CurrentUser, db: Db):
    """The sampled spans in sampling order with the sentence holding each hit."""
    layer, _ = _sample_layer(db, layer_id, user)
    spans = _spans(db, layer)
    keys = {(s.document_id, s.sentence_index) for s in spans}
    sentences = {}
    if keys:
        for doc, idx, a, b, text in db.execute(
            select(
                Sentence.document_id,
                Sentence.idx,
                Sentence.start_cp,
                Sentence.end_cp,
                Sentence.text,
            ).where(tuple_(Sentence.document_id, Sentence.idx).in_(keys))
        ):
            sentences[(doc, idx)] = {"start_cp": a, "end_cp": b, "text": text}
    titles = dict(
        db.execute(
            select(Document.id, Document.title).where(
                Document.id.in_({s.document_id for s in spans})
            )
        ).all()
    )
    items = []
    for i, s in enumerate(spans):
        sent = sentences.get((s.document_id, s.sentence_index))
        view = span_view(s)
        if sent:
            a = sent["start_cp"]
            view["text"] = sent["text"][s.start_cp - a : s.end_cp - a]
        items.append(
            {
                "n": i + 1,
                "span": view,
                "document_title": titles.get(s.document_id, ""),
                "sentence": sent,
            }
        )
    return {"items": items}
