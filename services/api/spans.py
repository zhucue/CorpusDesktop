"""Span and relation layers: review (contracts/p5.md §三 校对), agent suggestions, per-layer documents and stats.

Span offsets are document code points ([start_cp, end_cp)); SentenceSpans lists every sentence of the layer's
documents in corpus order with the spans overlapping it (a span crossing sentences appears in each, its
sentence_index is null). A relation layer reads the spans of its base span layer and lists its own relations
under the sentence where the relation's first span starts.

Statuses as in P3: model suggestions are `suggested`; confirm → confirmed (modified stays modified), modify →
modified, reject → rejected; spans created by hand are confirmed with source human:<user>. Only hand-made spans
(model_label null) can be deleted. Agent tokens read and suggest (POST …/spans/suggest), never confirm.
"""

from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Query
from pydantic import BaseModel, Field
from sqlalchemy import and_, exists, func, literal, or_, select, tuple_, union

from services.api.annotations import (
    ANNOTATE,
    load_layer,
    parse_cursor,
    refresh_progress,
)
from services.api.annotators import visible, writer
from services.api.auth import CurrentUser, Db
from services.api.errors import ApiError, not_found
from services.api.label_sets import human_only
from services.api.models import (
    AnnotationLayer,
    Document,
    LabelSet,
    RelationAnnotation,
    Sentence,
    SentenceReview,
    SpanAnnotation,
)

router = APIRouter(prefix="/api")

HUMAN = ("confirmed", "modified")


def now():
    return datetime.now(UTC)


# ---- shared helpers (also used by services.api.alignments and services.api.agreement) ----


def layer_documents_stmt(layer, document_id=None):
    stmt = select(Document.id).where(Document.corpus_id == layer.corpus_id)
    if layer.document_ids:
        stmt = stmt.where(Document.id.in_([UUID(d) for d in layer.document_ids]))
    if document_id is not None:
        stmt = stmt.where(Document.id == document_id)
    return stmt


def check_document(db, layer, document_id) -> Document:
    doc = db.get(Document, document_id)
    if (
        not doc
        or doc.corpus_id != layer.corpus_id
        or (layer.document_ids and str(doc.id) not in layer.document_ids)
    ):
        raise ApiError(422, "INVALID_DOCUMENTS", "文档不在该层的范围内")
    return doc


def doc_texts(db, doc_ids) -> dict:
    return {
        d.id: Path(d.text_path).read_text(encoding="utf-8")
        for d in db.scalars(select(Document).where(Document.id.in_(list(doc_ids))))
    }


def sentence_page(db, layer, document_id, cursor, page_size, pending=None):
    """Sentences [(document_id, idx, start_cp, end_cp, text)] of the layer's documents in corpus order after
    cursor "<document_id>:<sentence_index>"; pending: an extra SQL condition on Sentence."""
    stmt = (
        select(
            Sentence.document_id,
            Sentence.idx,
            Sentence.start_cp,
            Sentence.end_cp,
            Sentence.text,
        )
        .join(Document, Document.id == Sentence.document_id)
        .where(Sentence.document_id.in_(layer_documents_stmt(layer, document_id)))
        .order_by(Document.created_at, Sentence.document_id, Sentence.idx)
        .limit(page_size + 1)
    )
    if pending is not None:
        stmt = stmt.where(pending)
    if cursor:
        created, doc, idx = parse_cursor(db, cursor)
        stmt = stmt.where(
            tuple_(Document.created_at, Sentence.document_id, Sentence.idx)
            > tuple_(literal(created), literal(doc), literal(idx))
        )
    rows = [tuple(r) for r in db.execute(stmt)]
    more = len(rows) > page_size
    rows = rows[:page_size]
    return rows, (f"{rows[-1][0]}:{rows[-1][1]}" if more else None)


def label_ids(db, layer) -> dict:
    s = db.get(LabelSet, layer.label_set_id) if layer.label_set_id else None
    return {x["id"]: x for x in (s.labels if s else [])}


def check_label(db, layer, label, labels=None) -> str:
    labels = labels if labels is not None else label_ids(db, layer)
    if label in labels:
        return label
    by_name = [k for k, v in labels.items() if v.get("name") == label]
    if by_name:
        return by_name[0]
    raise ApiError(422, "INVALID_LABEL", f"标签 {label} 不在该层的标签集中")


def clean_attrs(attrs) -> dict:
    if attrs is None:
        return {}
    if len(attrs) > 20:
        raise ApiError(422, "VALIDATION_ERROR", "attrs 最多 20 项")
    out = {}
    for k, v in attrs.items():
        if not isinstance(k, str) or not k or len(k) > 64:
            raise ApiError(422, "VALIDATION_ERROR", "attrs 的键须为 1–64 字符")
        if isinstance(v, bool) or not isinstance(v, (str, int, float)):
            raise ApiError(422, "VALIDATION_ERROR", "attrs 的值须为字符串或数字")
        out[k] = str(v)[:200]
    return out


def sentence_index_of(db, document_id, start, end):
    """Index of the sentence holding [start, end), or None when the span crosses sentences."""
    return db.scalar(
        select(Sentence.idx).where(
            Sentence.document_id == document_id,
            Sentence.start_cp <= start,
            Sentence.end_cp >= end,
        )
    )


def span_view(s, text=None) -> dict:
    return {
        "id": s.id,
        "document_id": s.document_id,
        "sentence_index": s.sentence_index,
        "start_cp": s.start_cp,
        "end_cp": s.end_cp,
        "text": text[s.start_cp : s.end_cp] if text is not None else None,
        "label": s.label,
        "attrs": s.attrs or {},
        "source": s.source,
        "status": s.status,
        "model_label": s.model_label,
        "model_attrs": s.model_attrs,
        "revision": s.revision,
        "annotator_id": s.annotator_id,
        "updated_at": s.updated_at,
    }


def relation_view(r) -> dict:
    return {
        "id": r.id,
        "from_span_id": r.from_span_id,
        "to_span_id": r.to_span_id,
        "label": r.label,
        "source": r.source,
        "status": r.status,
        "model_label": r.model_label,
        "revision": r.revision,
        "annotator_id": r.annotator_id,
        "updated_at": r.updated_at,
    }


def _of(model, annotators):
    return [] if annotators is None else [model.annotator_id.in_(list(annotators))]


def span_layer_of(db, layer) -> AnnotationLayer:
    if layer.kind == "span":
        return layer
    if layer.kind == "relation":
        base = db.get(AnnotationLayer, layer.base_layer_id)
        if base is None:
            raise not_found("片段层")
        return base
    raise ApiError(422, "INVALID_LAYER", "该接口只用于片段层与关系层")


def _overlapping(sentences):
    return or_(
        *(
            and_(
                SpanAnnotation.document_id == d,
                SpanAnnotation.start_cp < b,
                SpanAnnotation.end_cp > a,
            )
            for d, _, a, b, _ in sentences
        )
    )


def sentence_spans(db, layer, sentences, span_annotators, rel_annotators):
    """SentenceSpans for [(document_id, idx, start_cp, end_cp, text)]."""
    if not sentences:
        return []
    base = span_layer_of(db, layer)
    spans = db.scalars(
        select(SpanAnnotation)
        .where(
            SpanAnnotation.layer_id == base.id,
            _overlapping(sentences),
            *_of(SpanAnnotation, span_annotators),
        )
        .order_by(SpanAnnotation.start_cp, SpanAnnotation.end_cp, SpanAnnotation.id)
    ).all()
    relations = []
    if layer.kind == "relation":
        relations = db.execute(
            select(RelationAnnotation, SpanAnnotation)
            .join(SpanAnnotation, SpanAnnotation.id == RelationAnnotation.from_span_id)
            .where(
                RelationAnnotation.layer_id == layer.id,
                _overlapping(sentences),
                *_of(RelationAnnotation, rel_annotators),
            )
            .order_by(RelationAnnotation.id)
        ).all()
    texts = doc_texts(db, {s[0] for s in sentences})
    out = []
    for doc, idx, a, b, text in sentences:
        mine = [
            s for s in spans if s.document_id == doc and s.start_cp < b and s.end_cp > a
        ]
        rels = [r for r, f in relations if f.document_id == doc and a <= f.start_cp < b]
        out.append(
            {
                "document_id": doc,
                "sentence_index": idx,
                "text": text,
                "start_cp": a,
                "end_cp": b,
                "spans": [span_view(s, texts.get(doc)) for s in mine],
                "relations": [relation_view(r) for r in rels],
            }
        )
    return out


def _pending(layer, annotators):
    """SQL condition: the sentence has suggested rows of the visible annotators."""
    if layer.kind == "relation":
        return exists(
            select(RelationAnnotation.id)
            .join(SpanAnnotation, SpanAnnotation.id == RelationAnnotation.from_span_id)
            .where(
                RelationAnnotation.layer_id == layer.id,
                RelationAnnotation.status == "suggested",
                SpanAnnotation.document_id == Sentence.document_id,
                SpanAnnotation.start_cp >= Sentence.start_cp,
                SpanAnnotation.start_cp < Sentence.end_cp,
                *_of(RelationAnnotation, annotators),
            )
        )
    return exists(
        select(SpanAnnotation.id).where(
            SpanAnnotation.layer_id == layer.id,
            SpanAnnotation.status == "suggested",
            SpanAnnotation.document_id == Sentence.document_id,
            SpanAnnotation.start_cp < Sentence.end_cp,
            SpanAnnotation.end_cp > Sentence.start_cp,
            *_of(SpanAnnotation, annotators),
        )
    )


def _annotators(db, layer, user, annotator_id):
    """(visible span annotators, visible relation annotators) for a span or relation layer."""
    if layer.kind == "span":
        return visible(db, layer, user, annotator_id), None
    base = span_layer_of(db, layer)
    rel = visible(db, layer, user, annotator_id)
    if base.mode != "multi":
        return visible(db, base, user), rel
    return (rel if rel is not None else visible(db, base, user, annotator_id)), rel


def mark_reviewed(db, layer, annotator, document_id, sentence_index):
    from sqlalchemy.dialects.postgresql import insert

    db.execute(
        insert(SentenceReview)
        .values(
            layer_id=layer.id,
            annotator_id=annotator,
            document_id=document_id,
            sentence_index=sentence_index,
        )
        .on_conflict_do_nothing()
    )


# ---- routes ----


@router.get("/layers/{layer_id}/spans")
def list_spans(
    layer_id: UUID,
    user: CurrentUser,
    db: Db,
    document_id: UUID | None = None,
    cursor: Annotated[str | None, Query(max_length=100)] = None,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
    status: Literal["pending", "all"] = "all",
    annotator_id: UUID | None = None,
):
    layer = load_layer(db, layer_id, user)
    span_layer_of(db, layer)
    span_ann, rel_ann = _annotators(db, layer, user, annotator_id)
    pending = None
    if status == "pending":
        pending = _pending(layer, rel_ann if layer.kind == "relation" else span_ann)
    rows, next_cursor = sentence_page(
        db, layer, document_id, cursor, page_size, pending
    )
    return {
        "items": sentence_spans(db, layer, rows, span_ann, rel_ann),
        "next_cursor": next_cursor,
    }


class SpanInput(BaseModel):
    document_id: UUID
    start_cp: int = Field(ge=0)
    end_cp: int = Field(ge=1)
    label: str = Field(min_length=1, max_length=64)
    attrs: dict | None = None


class SpanAction(BaseModel):
    action: Literal["confirm", "modify", "reject"]
    label: str | None = Field(default=None, min_length=1, max_length=64)
    start_cp: int | None = Field(default=None, ge=0)
    end_cp: int | None = Field(default=None, ge=1)
    attrs: dict | None = None


def _check_range(doc, start, end):
    if not 0 <= start < end <= doc.char_count:
        raise ApiError(
            422, "INVALID_RANGE", f"片段须满足 0 ≤ start_cp < end_cp ≤ {doc.char_count}"
        )


def _span_layer(db, layer_id, user, lock=True):
    layer = load_layer(db, layer_id, user, ANNOTATE, lock=lock)
    if layer.kind != "span":
        raise ApiError(422, "INVALID_LAYER", "片段只能在片段层中创建")
    return layer


@router.post("/layers/{layer_id}/spans")
def create_span(layer_id: UUID, body: SpanInput, user: CurrentUser, db: Db):
    human_only(user)
    layer = _span_layer(db, layer_id, user)
    me = writer(layer, user)
    doc = check_document(db, layer, body.document_id)
    _check_range(doc, body.start_cp, body.end_cp)
    label = check_label(db, layer, body.label)
    if db.scalar(
        select(
            exists().where(
                SpanAnnotation.layer_id == layer.id,
                SpanAnnotation.annotator_id == me,
                SpanAnnotation.document_id == doc.id,
                SpanAnnotation.start_cp == body.start_cp,
                SpanAnnotation.end_cp == body.end_cp,
                SpanAnnotation.label == label,
                SpanAnnotation.status != "rejected",
            )
        )
    ):
        raise ApiError(409, "SPAN_EXISTS", "已有相同范围与标签的片段")
    span = SpanAnnotation(
        layer_id=layer.id,
        annotator_id=me,
        document_id=doc.id,
        sentence_index=sentence_index_of(db, doc.id, body.start_cp, body.end_cp),
        start_cp=body.start_cp,
        end_cp=body.end_cp,
        label=label,
        attrs=clean_attrs(body.attrs),
        source=f"human:{user.id}",
        status="confirmed",
        revision=1,
        updated_by=user.id,
        updated_at=now(),
    )
    db.add(span)
    db.flush()
    refresh_progress(db, layer)
    db.commit()
    return span_view(span, doc_texts(db, [doc.id])[doc.id])


def _own_span(db, layer, span_id, user) -> SpanAnnotation:
    span = db.get(SpanAnnotation, span_id, with_for_update=True)
    if (
        not span
        or span.layer_id != layer.id
        or span.annotator_id != writer(layer, user)
    ):
        raise not_found("片段")
    return span


@router.patch("/layers/{layer_id}/spans/{span_id}")
def act_span(layer_id: UUID, span_id: int, body: SpanAction, user: CurrentUser, db: Db):
    human_only(user)
    layer = _span_layer(db, layer_id, user)
    span = _own_span(db, layer, span_id, user)
    if body.action == "reject":
        span.status = "rejected"
    elif body.action == "confirm":
        span.status = "modified" if span.status == "modified" else "confirmed"
    else:
        changed = {
            k: v
            for k, v in body.model_dump(exclude={"action"}).items()
            if v is not None
        }
        if not changed:
            raise ApiError(422, "VALIDATION_ERROR", "修改须提供 label、范围或 attrs")
        if "label" in changed:
            span.label = check_label(db, layer, body.label)
        if body.start_cp is not None or body.end_cp is not None:
            start = body.start_cp if body.start_cp is not None else span.start_cp
            end = body.end_cp if body.end_cp is not None else span.end_cp
            _check_range(db.get(Document, span.document_id), start, end)
            span.start_cp, span.end_cp = start, end
            span.sentence_index = sentence_index_of(db, span.document_id, start, end)
        if body.attrs is not None:
            span.attrs = clean_attrs(body.attrs)
        span.status = "modified"
    span.source, span.revision = f"human:{user.id}", span.revision + 1
    span.updated_by, span.updated_at = user.id, now()
    db.flush()
    refresh_progress(db, layer)
    db.commit()
    return span_view(span, doc_texts(db, [span.document_id])[span.document_id])


@router.delete("/layers/{layer_id}/spans/{span_id}", status_code=204)
def delete_span(layer_id: UUID, span_id: int, user: CurrentUser, db: Db):
    human_only(user)
    layer = _span_layer(db, layer_id, user)
    span = _own_span(db, layer, span_id, user)
    if span.model_label is not None:
        raise ApiError(409, "NOT_DELETABLE", "模型建议的片段不能删除，请拒绝")
    db.delete(span)
    db.flush()
    refresh_progress(db, layer)
    db.commit()


class RelationInput(BaseModel):
    from_span_id: int
    to_span_id: int
    label: str = Field(min_length=1, max_length=64)


class RelationAction(BaseModel):
    action: Literal["confirm", "modify", "reject"]
    label: str | None = Field(default=None, min_length=1, max_length=64)


def _relation_layer(db, layer_id, user):
    layer = load_layer(db, layer_id, user, ANNOTATE, lock=True)
    if layer.kind != "relation":
        raise ApiError(422, "INVALID_LAYER", "关系只能在关系层中创建")
    return layer


def _endpoint(db, layer, span_id, user) -> SpanAnnotation:
    """A base-layer span the user may connect (in a multi base layer: the user's own)."""
    base = span_layer_of(db, layer)
    span = db.get(SpanAnnotation, span_id)
    allowed = visible(db, base, user)
    if base.mode == "multi":
        allowed = [user.id]
    if (
        not span
        or span.layer_id != base.id
        or (allowed is not None and span.annotator_id not in allowed)
    ):
        raise ApiError(422, "INVALID_SPAN", f"片段 {span_id} 不在该关系层的片段层中")
    return span


def _new_relation(db, layer, me, a, b, label, source, status, user, model_label=None):
    if a.id == b.id:
        raise ApiError(422, "INVALID_SPAN", "关系的两端不能是同一片段")
    rel = RelationAnnotation(
        layer_id=layer.id,
        annotator_id=me,
        from_span_id=a.id,
        to_span_id=b.id,
        label=label,
        model_label=model_label,
        source=source,
        status=status,
        revision=1,
        updated_by=user.id,
        updated_at=now(),
    )
    db.add(rel)
    return rel


@router.post("/layers/{layer_id}/relations")
def create_relation(layer_id: UUID, body: RelationInput, user: CurrentUser, db: Db):
    human_only(user)
    layer = _relation_layer(db, layer_id, user)
    me = writer(layer, user)
    a = _endpoint(db, layer, body.from_span_id, user)
    b = _endpoint(db, layer, body.to_span_id, user)
    label = check_label(db, layer, body.label)
    if db.scalar(
        select(
            exists().where(
                RelationAnnotation.layer_id == layer.id,
                RelationAnnotation.annotator_id == me,
                RelationAnnotation.from_span_id == a.id,
                RelationAnnotation.to_span_id == b.id,
                RelationAnnotation.label == label,
                RelationAnnotation.status != "rejected",
            )
        )
    ):
        raise ApiError(409, "RELATION_EXISTS", "已有相同的关系")
    rel = _new_relation(
        db, layer, me, a, b, label, f"human:{user.id}", "confirmed", user
    )
    db.flush()
    refresh_progress(db, layer)
    db.commit()
    return relation_view(rel)


def _own_relation(db, layer, rel_id, user) -> RelationAnnotation:
    rel = db.get(RelationAnnotation, rel_id, with_for_update=True)
    if not rel or rel.layer_id != layer.id or rel.annotator_id != writer(layer, user):
        raise not_found("关系")
    return rel


@router.patch("/layers/{layer_id}/relations/{rel_id}")
def act_relation(
    layer_id: UUID, rel_id: int, body: RelationAction, user: CurrentUser, db: Db
):
    human_only(user)
    layer = _relation_layer(db, layer_id, user)
    rel = _own_relation(db, layer, rel_id, user)
    if body.action == "reject":
        rel.status = "rejected"
    elif body.action == "confirm":
        rel.status = "modified" if rel.status == "modified" else "confirmed"
    else:
        if body.label is None:
            raise ApiError(422, "VALIDATION_ERROR", "修改须提供 label")
        rel.label = check_label(db, layer, body.label)
        rel.status = "modified"
    rel.source, rel.revision = f"human:{user.id}", rel.revision + 1
    rel.updated_by, rel.updated_at = user.id, now()
    db.flush()
    refresh_progress(db, layer)
    db.commit()
    return relation_view(rel)


@router.delete("/layers/{layer_id}/relations/{rel_id}", status_code=204)
def delete_relation(layer_id: UUID, rel_id: int, user: CurrentUser, db: Db):
    human_only(user)
    layer = _relation_layer(db, layer_id, user)
    rel = _own_relation(db, layer, rel_id, user)
    if rel.model_label is not None:
        raise ApiError(409, "NOT_DELETABLE", "模型建议的关系不能删除，请拒绝")
    db.delete(rel)
    db.flush()
    refresh_progress(db, layer)
    db.commit()


# ---- agent suggestions ----


class SuggestSpan(BaseModel):
    start_cp: int = Field(ge=0)
    end_cp: int = Field(ge=1)
    label: str = Field(min_length=1, max_length=64)
    attrs: dict | None = None


class SuggestRelation(BaseModel):
    from_: int | str = Field(alias="from")
    to: int | str
    label: str = Field(min_length=1, max_length=64)


class SpanSuggestInput(BaseModel):
    """spans: document code points inside the sentence; relations from / to: 0-based index into this call's
    spans (int) or an existing span id (string, or an int beyond the spans)."""

    model: str = Field(
        default="agent", min_length=1, max_length=100, pattern=r"^[\w.:/@-]+$"
    )
    document_id: UUID
    sentence_index: int = Field(ge=0)
    spans: list[SuggestSpan] = Field(default=[], max_length=100)
    relations: list[SuggestRelation] = Field(default=[], max_length=100)


@router.post("/layers/{layer_id}/spans/suggest")
def suggest_spans(layer_id: UUID, body: SpanSuggestInput, user: CurrentUser, db: Db):
    """Suggested spans and relations of one sentence. Spans go to the span layer (the layer itself, or the base
    of a relation layer); relations go to the relation layer (the layer itself, or the only relation layer on a
    span layer). Identical existing rows are returned and reported in skipped; reviewed rows never change."""
    layer = load_layer(db, layer_id, user, ANNOTATE, lock=True)
    span_layer = span_layer_of(db, layer)
    rel_layer = layer if layer.kind == "relation" else None
    if body.relations and rel_layer is None:
        found = db.scalars(
            select(AnnotationLayer).where(
                AnnotationLayer.base_layer_id == layer.id,
                AnnotationLayer.kind == "relation",
            )
        ).all()
        if len(found) != 1:
            raise ApiError(
                422, "INVALID_LAYER", "关系建议须写入关系层（该片段层没有唯一的关系层）"
            )
        rel_layer = found[0]
    sentence = db.scalar(
        select(Sentence).where(
            Sentence.document_id == body.document_id,
            Sentence.idx == body.sentence_index,
        )
    )
    check_document(db, span_layer, body.document_id)
    if sentence is None:
        raise not_found("句子")
    source = f"model:{body.model}"
    created, skipped = [], []
    if body.spans:
        me = writer(span_layer, user)
        labels = label_ids(db, span_layer)
        existing = {
            (s.start_cp, s.end_cp, s.label): s
            for s in db.scalars(
                select(SpanAnnotation).where(
                    SpanAnnotation.layer_id == span_layer.id,
                    SpanAnnotation.annotator_id == me,
                    SpanAnnotation.document_id == body.document_id,
                )
            )
        }
        for i, item in enumerate(body.spans):
            if not sentence.start_cp <= item.start_cp < item.end_cp <= sentence.end_cp:
                raise ApiError(
                    422,
                    "SPAN_OUT_OF_SENTENCE",
                    f"片段 {item.start_cp}-{item.end_cp} 不在该句 {sentence.start_cp}-{sentence.end_cp} 内",
                )
            label = check_label(db, span_layer, item.label, labels)
            key = (item.start_cp, item.end_cp, label)
            if key in existing:
                skipped.append({"index": i, "reason": existing[key].status})
                created.append(existing[key])
                continue
            span = SpanAnnotation(
                layer_id=span_layer.id,
                annotator_id=me,
                document_id=body.document_id,
                sentence_index=sentence.idx,
                start_cp=item.start_cp,
                end_cp=item.end_cp,
                label=label,
                attrs=clean_attrs(item.attrs),
                model_label=label,
                model_attrs=clean_attrs(item.attrs),
                source=source,
                status="suggested",
                revision=1,
                updated_by=user.id,
                updated_at=now(),
            )
            db.add(span)
            existing[key] = span
            created.append(span)
        db.flush()
        refresh_progress(db, span_layer)
    relations = []
    if body.relations:
        me = writer(rel_layer, user)
        labels = label_ids(db, rel_layer)

        def endpoint(ref):
            if isinstance(ref, int) and 0 <= ref < len(created):
                return created[ref]
            try:
                return _endpoint(db, rel_layer, int(ref), user)
            except ValueError:
                raise ApiError(422, "INVALID_SPAN", f"无效的片段引用 {ref}") from None

        for i, item in enumerate(body.relations):
            a, b = endpoint(item.from_), endpoint(item.to)
            label = check_label(db, rel_layer, item.label, labels)
            dup = db.scalar(
                select(RelationAnnotation).where(
                    RelationAnnotation.layer_id == rel_layer.id,
                    RelationAnnotation.annotator_id == me,
                    RelationAnnotation.from_span_id == a.id,
                    RelationAnnotation.to_span_id == b.id,
                    RelationAnnotation.label == label,
                )
            )
            if dup:
                skipped.append({"relation": i, "reason": dup.status})
                relations.append(dup)
                continue
            relations.append(
                _new_relation(
                    db, rel_layer, me, a, b, label, source, "suggested", user, label
                )
            )
        db.flush()
        refresh_progress(db, rel_layer)
    db.commit()
    texts = doc_texts(db, [body.document_id])
    return {
        "spans": [span_view(s, texts[body.document_id]) for s in created],
        "relations": [relation_view(r) for r in relations],
        "skipped": skipped,
    }


# ---- sentence confirm, documents, stats (dispatched from services.api.annotations) ----


def confirm_p5_sentence(db, layer, user, document_id, sentence_index):
    """The user's suggested rows of the sentence → confirmed; the sentence is marked reviewed."""
    from services.api.alignments import confirm_alignment_sentence

    if layer.kind == "alignment":
        return confirm_alignment_sentence(db, layer, user, document_id, sentence_index)
    me = writer(layer, user)
    sentence = db.scalar(
        select(Sentence).where(
            Sentence.document_id == document_id, Sentence.idx == sentence_index
        )
    )
    if sentence is None:
        raise not_found("句子")
    check_document(db, span_layer_of(db, layer), document_id)
    values = {
        "status": "confirmed",
        "source": f"human:{user.id}",
        "updated_by": user.id,
        "updated_at": now(),
    }
    if layer.kind == "span":
        rows = db.scalars(
            select(SpanAnnotation).where(
                SpanAnnotation.layer_id == layer.id,
                SpanAnnotation.annotator_id == me,
                SpanAnnotation.status == "suggested",
                SpanAnnotation.document_id == document_id,
                SpanAnnotation.start_cp >= sentence.start_cp,
                SpanAnnotation.start_cp < sentence.end_cp,
            )
        ).all()
    else:
        rows = db.scalars(
            select(RelationAnnotation)
            .join(SpanAnnotation, SpanAnnotation.id == RelationAnnotation.from_span_id)
            .where(
                RelationAnnotation.layer_id == layer.id,
                RelationAnnotation.annotator_id == me,
                RelationAnnotation.status == "suggested",
                SpanAnnotation.document_id == document_id,
                SpanAnnotation.start_cp >= sentence.start_cp,
                SpanAnnotation.start_cp < sentence.end_cp,
            )
        ).all()
    for r in rows:
        for k, v in values.items():
            setattr(r, k, v)
        r.revision += 1
    mark_reviewed(db, layer, me, document_id, sentence_index)
    db.flush()
    refresh_progress(db, layer)
    db.commit()
    row = (
        sentence.document_id,
        sentence.idx,
        sentence.start_cp,
        sentence.end_cp,
        sentence.text,
    )
    span_ann, rel_ann = _annotators(db, layer, user, None)
    return sentence_spans(db, layer, [row], span_ann, rel_ann)[0]


def p5_documents(db, layer, annotators):
    """Documents of a span / relation / alignment layer: sentences, done and pending (with suggestions).

    A sentence is done when it was confirmed (sentence_reviews) or has rows and none is suggested; a document is
    done (done = sentences) when it has rows and none is suggested."""
    from services.api.models import AlignmentAnnotation

    docs = db.execute(
        select(Document.id, Document.title, Document.sentence_count)
        .where(Document.id.in_(layer_documents_stmt(layer)))
        .order_by(Document.created_at, Document.id)
    ).all()
    if layer.kind == "alignment":
        m = AlignmentAnnotation
        doc_col, idx_col = m.src_document_id, m.src_sentence_index
        rows = select().select_from(m)
    elif layer.kind == "span":
        m = SpanAnnotation
        doc_col, idx_col = m.document_id, m.sentence_index
        rows = select().select_from(m)
    else:
        m = RelationAnnotation
        doc_col, idx_col = SpanAnnotation.document_id, SpanAnnotation.sentence_index
        rows = (  # columns come from the first span; rows from the relations
            select()
            .select_from(m)
            .join(SpanAnnotation, SpanAnnotation.id == m.from_span_id)
        )
    per_sentence = (
        rows.add_columns(
            doc_col.label("d"),
            idx_col.label("i"),
            func.bool_and(m.status != "suggested").label("ok"),
        )
        .where(m.layer_id == layer.id, *_of(m, annotators))
        .group_by(doc_col, idx_col)
        .subquery()
    )
    s = per_sentence.c
    per_doc = {
        d: (pending, all_ok)
        for d, pending, all_ok in db.execute(
            select(
                s.d,
                func.count().filter(~s.ok, s.i.is_not(None)),
                func.bool_and(s.ok),
            ).group_by(s.d)
        )
    }
    finished = union(
        select(s.d, s.i).where(s.ok, s.i.is_not(None)),
        select(SentenceReview.document_id, SentenceReview.sentence_index).where(
            SentenceReview.layer_id == layer.id, *_of(SentenceReview, annotators)
        ),
    ).subquery()
    done = dict(
        db.execute(select(finished.c[0], func.count()).group_by(finished.c[0])).all()
    )
    items = []
    for d, t, n in docs:
        pending, all_ok = per_doc.get(d, (0, False))
        items.append(
            {
                "document_id": d,
                "title": t,
                "sentences": n,
                "done": n if all_ok else min(done.get(d, 0), n),
                "pending": pending,
            }
        )
    return {"items": items, "total": len(items)}


def p5_stats(db, layer, annotators, progress):
    """labels: counts of the visible rows' current labels (non-rejected), of which confirmed / modified."""
    from services.api.models import AlignmentAnnotation

    n = func.count()
    if layer.kind == "alignment":
        m = AlignmentAnnotation
        level = func.cardinality(m.src_tokens) > 0
        rows = db.execute(
            select(
                level,
                n,
                n.filter(m.status == "confirmed"),
                n.filter(m.status == "modified"),
            )
            .where(m.layer_id == layer.id, m.status != "rejected", *_of(m, annotators))
            .group_by(level)
        ).all()
        labels = [
            {
                "label": "word" if w else "sentence",
                "count": c,
                "confirmed": cf,
                "modified": md,
            }
            for w, c, cf, md in rows
        ]
    else:
        m = SpanAnnotation if layer.kind == "span" else RelationAnnotation
        rows = db.execute(
            select(
                m.label,
                n,
                n.filter(m.status == "confirmed"),
                n.filter(m.status == "modified"),
            )
            .where(m.layer_id == layer.id, m.status != "rejected", *_of(m, annotators))
            .group_by(m.label)
            .order_by(n.desc(), m.label)
        ).all()
        labels = [
            {"label": label, "count": c, "confirmed": cf, "modified": md}
            for label, c, cf, md in rows
        ]
    return {
        "labels": labels,
        "progress": progress,
        "per_document": p5_documents(db, layer, annotators)["items"],
    }
