"""Annotation layers, pre-annotation, review, diff, statistics, export and agent suggestions
(contracts/p3.md §二–§三, §五 annot.suggest).

Token positions at this API are 1-based within the sentence (CoNLL-U): SentenceAnnot.tokens[].index,
Annotation.token_index and head (0 = root) all equal tokens.idx + 1; sentence_index is 0-based as in search.

Roles: owner / editor manage layers; owner / editor / annotator annotate; viewers read. Agent (Bearer) tokens
read, create layers and exports, and write suggestions only (POST /layers/{id}/suggest: status stays
suggested, never touches confirmed / modified / rejected tokens).

Layer.progress is recomputed with SQL aggregates after every change, inside a transaction that holds the
layer row lock, so concurrent reviewers never drift the counters.
"""

from datetime import UTC, datetime
from importlib.metadata import PackageNotFoundError, version
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Query
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import case, exists, func, literal, select, tuple_, update

from services.api.access import READ, WRITE, Paging, require_project
from services.api.auth import CurrentUser, Db
from services.api.errors import ApiError, not_found
from services.api.jobs import ACTIVE, enqueue
from services.api.label_sets import human_only, load_label_set
from services.api.models import (
    Annotation,
    AnnotationLayer,
    Corpus,
    Document,
    Job,
    LabelSet,
    Sentence,
    Token,
)
from services.api.search import corpus_tagset
from services.api.subcorpora import project_corpus
from services.api.views import job_view

router = APIRouter(prefix="/api")

ANNOTATE = ("owner", "editor", "annotator")
STATUSES = ("suggested", "confirmed", "modified", "rejected")
PROGRESS_KEYS = ("total", *STATUSES)
CHANGED = ("modified", "rejected")


def now():
    return datetime.now(UTC)


def is_zh(language):
    return (language or "").lower().split("-")[0] in ("zh", "cmn", "zho", "chi")


def _version(package):
    try:
        return version(package)
    except PackageNotFoundError:
        return "?"


def source_model(db, corpus, kind):
    """pos: jieba for jieba-tagged corpora, else the stored system tags; dep: Stanza zh when a Chinese corpus
    has tokens without dependencies, else the stored system values."""
    if kind == "pos":
        return (
            f"jieba {_version('jieba')}"
            if corpus_tagset(corpus) == "jieba"
            else "system"
        )
    if is_zh(corpus.language) and db.scalar(
        select(
            exists()
            .where(Token.deprel.is_(None))
            .where(Token.sentence_id == Sentence.id)
            .where(Sentence.document_id == Document.id)
            .where(Document.corpus_id == corpus.id)
        )
    ):
        return f"stanza {_version('stanza')} zh"
    return "system"


def system_source(layer):
    """annotations.source of pre-annotated values (used again by sentence reset)."""
    return "model:stanza-zh" if layer.source_model.startswith("stanza") else "system"


def refresh_progress(db, layer):
    counts = dict(
        db.execute(
            select(Annotation.status, func.count())
            .where(Annotation.layer_id == layer.id)
            .group_by(Annotation.status)
        ).all()
    )
    done = db.scalar(
        select(func.count()).select_from(
            select(Annotation.document_id)
            .where(Annotation.layer_id == layer.id)
            .group_by(Annotation.document_id)
            .having(func.bool_and(Annotation.status != "suggested"))
            .subquery()
        )
    )
    progress = {
        "total": sum(counts.values()),
        **{s: counts.get(s, 0) for s in STATUSES},
    }
    layer.progress = {**progress, "documents_done": done}
    layer.updated_at = now()


def empty_progress():
    return {k: 0 for k in PROGRESS_KEYS} | {"documents_done": 0}


def layer_view(db, layer):
    corpus_name = db.scalar(select(Corpus.name).where(Corpus.id == layer.corpus_id))
    if layer.document_ids:
        doc_total = len(layer.document_ids)
    else:
        doc_total = db.scalar(
            select(func.count()).where(Document.corpus_id == layer.corpus_id)
        )
    return {
        "id": layer.id,
        "project_id": layer.project_id,
        "corpus_id": layer.corpus_id,
        "corpus_name": corpus_name,
        "kind": layer.kind,
        "name": layer.name,
        "label_set_id": layer.label_set_id,
        "source_model": layer.source_model,
        "status": layer.status,
        "job_id": layer.job_id,
        "progress": {k: layer.progress.get(k, 0) for k in PROGRESS_KEYS},
        "documents": {
            "total": doc_total,
            "done": layer.progress.get("documents_done", 0),
        },
        "error": layer.error,
        "created_by": layer.created_by,
        "created_at": layer.created_at,
        "updated_at": layer.updated_at,
    }


def annotation_view(a):
    return {
        "id": a.id,
        "document_id": a.document_id,
        "sentence_index": a.sentence_index,
        "token_index": a.token_index,
        "label": a.label,
        "head": a.head,
        "model_label": a.model_label,
        "model_head": a.model_head,
        "source": a.source,
        "status": a.status,
        "revision": a.revision,
        "updated_by": a.updated_by,
        "updated_at": a.updated_at,
    }


def load_layer(db, layer_id, user, roles=READ, lock=False) -> AnnotationLayer:
    layer = db.get(AnnotationLayer, layer_id, with_for_update=lock)
    if not layer:
        raise not_found("标注层")
    require_project(db, layer.project_id, user, roles)
    return layer


def _check_documents(db, corpus_id, document_ids):
    if not document_ids:
        return None
    ids = list(dict.fromkeys(document_ids))
    found = db.scalar(
        select(func.count()).where(
            Document.id.in_(ids), Document.corpus_id == corpus_id
        )
    )
    if found != len(ids):
        raise ApiError(422, "INVALID_DOCUMENTS", "document_ids 含不属于该语料库的文档")
    return [str(i) for i in ids]


def _active_job(db, layer_id):
    return db.scalar(
        select(Job.id).where(
            Job.kind == "preannotate",
            Job.state.in_(ACTIVE),
            Job.params["layer_id"].astext == str(layer_id),
        )
    )


def _enqueue_preannotate(db, layer, user, document_ids):
    params = {
        "layer_id": str(layer.id),
        "corpus_id": str(layer.corpus_id),
        "document_ids": document_ids,
    }
    job = enqueue(db, "preannotate", params, user.id, layer.project_id)
    layer.job_id, layer.error = job.id, None
    return job


# ---- sentences ----


def sentence_views(db, layer, keys):
    """SentenceAnnot for (document_id, sentence_index) keys, in the given order."""
    if not keys:
        return []
    sents = {
        (s.document_id, s.idx): s
        for s in db.scalars(
            select(Sentence).where(tuple_(Sentence.document_id, Sentence.idx).in_(keys))
        )
    }
    toks = {}
    for t in db.scalars(
        select(Token)
        .where(Token.sentence_id.in_([s.id for s in sents.values()]))
        .order_by(Token.sentence_id, Token.idx)
    ):
        toks.setdefault(t.sentence_id, []).append(t)
    anns = {}
    for a in db.scalars(
        select(Annotation)
        .where(
            Annotation.layer_id == layer.id,
            tuple_(Annotation.document_id, Annotation.sentence_index).in_(keys),
        )
        .order_by(Annotation.token_index)
    ):
        anns.setdefault((a.document_id, a.sentence_index), []).append(a)
    out = []
    for key in keys:
        s = sents.get(key)
        if s is None:
            continue
        items = anns.get(key, [])
        out.append(
            {
                "document_id": s.document_id,
                "sentence_index": s.idx,
                "text": s.text,
                "tokens": [
                    {
                        "index": t.idx + 1,
                        "form": t.form,
                        "start_cp": t.start_cp,
                        "end_cp": t.end_cp,
                        "system": {"pos": t.pos, "head": t.head, "deprel": t.deprel},
                    }
                    for t in toks.get(s.id, [])
                ],
                "annotations": [annotation_view(a) for a in items],
                "status": "pending"
                if any(a.status == "suggested" for a in items)
                else "done",
            }
        )
    return out


def _sentence(db, layer, document_id, sentence_index):
    views = sentence_views(db, layer, [(document_id, sentence_index)])
    if not views:
        raise not_found("句子")
    return views[0]


def _sentence_page(db, layer, document_id, cursor, page_size, having=None):
    """Sentence keys of the layer in corpus order after `cursor` ("<document_id>:<sentence_index>")."""
    stmt = (
        select(Annotation.document_id, Annotation.sentence_index)
        .join(Document, Document.id == Annotation.document_id)
        .where(Annotation.layer_id == layer.id)
        .group_by(
            Annotation.document_id, Annotation.sentence_index, Document.created_at
        )
        .order_by(
            Document.created_at, Annotation.document_id, Annotation.sentence_index
        )
        .limit(page_size + 1)
    )
    if having is not None:
        stmt = stmt.having(having)
    if document_id:
        stmt = stmt.where(Annotation.document_id == document_id)
    if cursor:
        try:
            doc, _, idx = cursor.partition(":")
            doc, idx = UUID(doc), int(idx)
        except ValueError:
            raise ApiError(422, "INVALID_CURSOR", "cursor 无效") from None
        created = db.scalar(select(Document.created_at).where(Document.id == doc))
        if created is None:
            raise ApiError(422, "INVALID_CURSOR", "cursor 无效")
        stmt = stmt.where(
            tuple_(
                Document.created_at, Annotation.document_id, Annotation.sentence_index
            )
            > tuple_(literal(created), literal(doc), literal(idx))
        )
    keys = [tuple(r) for r in db.execute(stmt)]
    more = len(keys) > page_size
    keys = keys[:page_size]
    next_cursor = f"{keys[-1][0]}:{keys[-1][1]}" if more else None
    return keys, next_cursor


def _status_counts(db, layer, document_id=None):
    stmt = select(Annotation.status, func.count()).where(
        Annotation.layer_id == layer.id
    )
    if document_id:
        stmt = stmt.where(Annotation.document_id == document_id)
    return dict(db.execute(stmt.group_by(Annotation.status)).all())


# ---- request bodies ----


class LayerInput(BaseModel):
    corpus_id: UUID
    kind: Literal["pos", "dep"]
    name: str = Field(min_length=1, max_length=200)
    label_set_id: UUID
    document_ids: list[UUID] | None = Field(default=None, max_length=10000)


class PreannotateInput(BaseModel):
    document_ids: list[UUID] | None = Field(default=None, max_length=10000)


class TokenRef(BaseModel):
    document_id: UUID
    sentence_index: int = Field(ge=0)
    token_index: int = Field(ge=1)


class ActionInput(TokenRef):
    action: Literal["confirm", "modify", "reject"]
    label: str | None = Field(default=None, max_length=64)
    head: int | None = Field(default=None, ge=0)


class SuggestItem(TokenRef):
    label: str | None = Field(default=None, max_length=64)
    head: int | None = Field(default=None, ge=0)


class SuggestInput(BaseModel):
    """{model?, items: [...]} → {items: [Annotation], skipped: [...]}; or one item inline
    {model?, document_id, sentence_index, token_index, label?, head?} → Annotation (409 when already reviewed)."""

    model: str = Field(
        default="agent", min_length=1, max_length=100, pattern=r"^[\w.:/@-]+$"
    )
    items: list[SuggestItem] | None = Field(default=None, max_length=1000)
    document_id: UUID | None = None
    sentence_index: int | None = Field(default=None, ge=0)
    token_index: int | None = Field(default=None, ge=1)
    label: str | None = Field(default=None, max_length=64)
    head: int | None = Field(default=None, ge=0)

    @property
    def single(self):
        return self.document_id is not None

    @model_validator(mode="after")
    def collect(self):
        if self.items is None:
            if None in (self.document_id, self.sentence_index, self.token_index):
                raise ValueError(
                    "须提供 items 或 document_id、sentence_index、token_index"
                )
            self.items = [
                SuggestItem(**self.model_dump(include=set(SuggestItem.model_fields)))
            ]
        return self


class ExportInput(BaseModel):
    format: Literal["conllu"]
    document_ids: list[UUID] | None = Field(default=None, max_length=10000)


# ---- validation of labels and heads ----


def _label_ids(db, layer):
    return {label["id"] for label in db.get(LabelSet, layer.label_set_id).labels}


def _sentence_length(db, document_id, sentence_index):
    return db.scalar(
        select(func.count())
        .select_from(Token)
        .join(Sentence, Sentence.id == Token.sentence_id)
        .where(Sentence.document_id == document_id, Sentence.idx == sentence_index)
    )


def _check_values(db, layer, ref, label, head, labels=None):
    if label is not None and label not in (labels or _label_ids(db, layer)):
        raise ApiError(422, "INVALID_LABEL", f"标签 {label} 不在该层的标签集中")
    if head is not None:
        if layer.kind != "dep":
            raise ApiError(422, "VALIDATION_ERROR", "只有依存层有 head")
        n = _sentence_length(db, ref.document_id, ref.sentence_index)
        if head > n or head == ref.token_index:
            raise ApiError(422, "INVALID_HEAD", f"head 须为 0 至 {n} 且不等于自身")


def _final_status(a):
    same = a.label == a.model_label and a.head == a.model_head
    return "confirmed" if same else "modified"


# ---- layers ----


@router.get("/projects/{project_id}/layers")
def list_layers(
    project_id: UUID,
    user: CurrentUser,
    db: Db,
    paging: Paging,
    corpus_id: UUID | None = None,
):
    require_project(db, project_id, user)
    stmt = select(AnnotationLayer).where(AnnotationLayer.project_id == project_id)
    if corpus_id:
        stmt = stmt.where(AnnotationLayer.corpus_id == corpus_id)
    stmt = stmt.order_by(AnnotationLayer.created_at.desc(), AnnotationLayer.id)
    return paging.run(db, stmt, lambda layer: layer_view(db, layer))


@router.post("/projects/{project_id}/layers")
def create_layer(project_id: UUID, body: LayerInput, user: CurrentUser, db: Db):
    require_project(db, project_id, user, WRITE)
    corpus = project_corpus(db, project_id, body.corpus_id)
    if corpus.status not in ("ready", "stale") or not corpus.index_version:
        raise ApiError(409, "CORPUS_NOT_READY", "语料库尚未完成索引")
    label_set = load_label_set(db, body.label_set_id, user)
    if label_set.project_id not in (None, project_id):
        raise not_found("标签集")
    if label_set.kind != body.kind:
        raise ApiError(422, "VALIDATION_ERROR", "标签集类型与标注层类型不一致")
    layer = AnnotationLayer(
        project_id=project_id,
        corpus_id=corpus.id,
        kind=body.kind,
        name=body.name.strip(),
        label_set_id=label_set.id,
        source_model=source_model(db, corpus, body.kind),
        status="created",
        progress=empty_progress(),
        document_ids=_check_documents(db, corpus.id, body.document_ids),
        created_by=user.id,
    )
    db.add(layer)
    db.flush()
    _enqueue_preannotate(db, layer, user, None)
    db.commit()
    return layer_view(db, layer)


@router.get("/layers/{layer_id}")
def get_layer(layer_id: UUID, user: CurrentUser, db: Db):
    return layer_view(db, load_layer(db, layer_id, user))


@router.delete("/layers/{layer_id}", status_code=204)
def delete_layer(layer_id: UUID, user: CurrentUser, db: Db):
    human_only(user)
    layer = load_layer(db, layer_id, user, WRITE)
    db.execute(
        update(Job)
        .where(
            Job.kind == "preannotate",
            Job.state.in_(ACTIVE),
            Job.params["layer_id"].astext == str(layer.id),
        )
        .values(state="cancelled", finished_at=now())
    )
    db.delete(layer)
    db.commit()


@router.post("/layers/{layer_id}/preannotate")
def preannotate(layer_id: UUID, body: PreannotateInput, user: CurrentUser, db: Db):
    layer = load_layer(db, layer_id, user, WRITE, lock=True)
    if _active_job(db, layer.id):
        raise ApiError(409, "JOB_IN_PROGRESS", "该层正在预标")
    ids = _check_documents(db, layer.corpus_id, body.document_ids)
    if ids and layer.document_ids and not set(ids) <= set(layer.document_ids):
        raise ApiError(422, "INVALID_DOCUMENTS", "document_ids 不在该层的文档范围内")
    job = _enqueue_preannotate(db, layer, user, ids)
    db.commit()
    return job_view(job)


# ---- review ----


@router.get("/layers/{layer_id}/documents")
def layer_documents(layer_id: UUID, user: CurrentUser, db: Db):
    layer = load_layer(db, layer_id, user)
    pending = func.count(Annotation.sentence_index.distinct()).filter(
        Annotation.status == "suggested"
    )
    rows = db.execute(
        select(
            Annotation.document_id,
            Document.title,
            func.count(Annotation.sentence_index.distinct()),
            pending,
        )
        .join(Document, Document.id == Annotation.document_id)
        .where(Annotation.layer_id == layer.id)
        .group_by(Annotation.document_id, Document.title, Document.created_at)
        .order_by(Document.created_at, Annotation.document_id)
    ).all()
    items = [
        {"document_id": d, "title": t, "sentences": n, "done": n - p, "pending": p}
        for d, t, n, p in rows
    ]
    return {"items": items, "total": len(items)}


@router.get("/layers/{layer_id}/sentences")
def list_sentences(
    layer_id: UUID,
    user: CurrentUser,
    db: Db,
    document_id: UUID | None = None,
    cursor: Annotated[str | None, Query(max_length=100)] = None,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
    status: Literal["pending", "all"] = "all",
):
    layer = load_layer(db, layer_id, user)
    having = (
        func.bool_or(Annotation.status == "suggested") if status == "pending" else None
    )
    keys, next_cursor = _sentence_page(
        db, layer, document_id, cursor, page_size, having
    )
    return {"items": sentence_views(db, layer, keys), "next_cursor": next_cursor}


@router.get("/layers/{layer_id}/sentences/{document_id}/{sentence_index}")
def get_sentence(
    layer_id: UUID, document_id: UUID, sentence_index: int, user: CurrentUser, db: Db
):
    layer = load_layer(db, layer_id, user)
    return _sentence(db, layer, document_id, sentence_index)


@router.post("/layers/{layer_id}/annotations")
def annotate(layer_id: UUID, body: ActionInput, user: CurrentUser, db: Db):
    human_only(user)
    layer = load_layer(db, layer_id, user, ANNOTATE, lock=True)
    a = db.scalar(
        select(Annotation)
        .where(
            Annotation.layer_id == layer.id,
            Annotation.document_id == body.document_id,
            Annotation.sentence_index == body.sentence_index,
            Annotation.token_index == body.token_index,
        )
        .with_for_update()
    )
    if a is None:
        raise not_found("标注")
    if body.action == "reject":
        if layer.kind == "dep":
            raise ApiError(422, "REJECT_NOT_ALLOWED", "依存层不能拒绝，只能修改")
        a.status = "rejected"
    elif body.action == "modify":
        if body.label is None and body.head is None:
            raise ApiError(422, "VALIDATION_ERROR", "修改须提供 label 或 head")
        if layer.kind == "pos" and body.label is None:
            raise ApiError(422, "VALIDATION_ERROR", "修改须提供 label")
        _check_values(db, layer, body, body.label, body.head)
        if body.label is not None:
            a.label = body.label
        if body.head is not None:
            a.head = body.head
        a.status = _final_status(a)
    else:
        a.status = _final_status(a)
    a.source, a.revision = f"human:{user.id}", a.revision + 1
    a.updated_by, a.updated_at = user.id, now()
    db.flush()
    refresh_progress(db, layer)
    db.commit()
    return annotation_view(a)


def _sentence_update(db, layer, user, document_id, sentence_index, values, where=()):
    db.execute(
        update(Annotation)
        .where(
            Annotation.layer_id == layer.id,
            Annotation.document_id == document_id,
            Annotation.sentence_index == sentence_index,
            *where,
        )
        .values(
            revision=Annotation.revision + 1,
            updated_by=user.id,
            updated_at=now(),
            **values,
        )
    )
    refresh_progress(db, layer)
    db.commit()
    return _sentence(db, layer, document_id, sentence_index)


@router.post("/layers/{layer_id}/sentences/{document_id}/{sentence_index}/confirm")
def confirm_sentence(
    layer_id: UUID, document_id: UUID, sentence_index: int, user: CurrentUser, db: Db
):
    human_only(user)
    layer = load_layer(db, layer_id, user, ANNOTATE, lock=True)
    same = Annotation.label.is_not_distinct_from(Annotation.model_label) & (
        Annotation.head.is_not_distinct_from(Annotation.model_head)
    )
    values = {
        "status": case((same, "confirmed"), else_="modified"),
        "source": f"human:{user.id}",
    }
    return _sentence_update(
        db,
        layer,
        user,
        document_id,
        sentence_index,
        values,
        [Annotation.status == "suggested"],
    )


@router.post("/layers/{layer_id}/sentences/{document_id}/{sentence_index}/reset")
def reset_sentence(
    layer_id: UUID, document_id: UUID, sentence_index: int, user: CurrentUser, db: Db
):
    human_only(user)
    layer = load_layer(db, layer_id, user, ANNOTATE, lock=True)
    values = {
        "status": "suggested",
        "label": Annotation.model_label,
        "head": Annotation.model_head,
        "source": system_source(layer),
    }
    return _sentence_update(db, layer, user, document_id, sentence_index, values)


@router.get("/layers/{layer_id}/diff")
def diff(
    layer_id: UUID,
    user: CurrentUser,
    db: Db,
    document_id: UUID | None = None,
    only_changed: bool = True,
    cursor: Annotated[str | None, Query(max_length=100)] = None,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
):
    """Sentences with human changes (modified / rejected tokens); counts are token counts:
    changed = modified, confirmed, rejected, pending = suggested."""
    layer = load_layer(db, layer_id, user)
    having = func.bool_or(Annotation.status.in_(CHANGED)) if only_changed else None
    keys, next_cursor = _sentence_page(
        db, layer, document_id, cursor, page_size, having
    )
    c = _status_counts(db, layer, document_id)
    return {
        "items": sentence_views(db, layer, keys),
        "next_cursor": next_cursor,
        "counts": {
            "changed": c.get("modified", 0),
            "confirmed": c.get("confirmed", 0),
            "rejected": c.get("rejected", 0),
            "pending": c.get("suggested", 0),
        },
    }


@router.get("/layers/{layer_id}/stats")
def layer_stats(layer_id: UUID, user: CurrentUser, db: Db):
    """labels: current labels of non-rejected tokens (count, of which confirmed / modified)."""
    layer = load_layer(db, layer_id, user)
    n = func.count()
    rows = db.execute(
        select(
            Annotation.label,
            n,
            n.filter(Annotation.status == "confirmed"),
            n.filter(Annotation.status == "modified"),
        )
        .where(
            Annotation.layer_id == layer.id,
            Annotation.status != "rejected",
            Annotation.label.is_not(None),
        )
        .group_by(Annotation.label)
        .order_by(n.desc(), Annotation.label)
    ).all()
    per_doc = db.execute(
        select(
            Annotation.document_id,
            Document.title,
            n,
            *(n.filter(Annotation.status == s) for s in STATUSES),
        )
        .join(Document, Document.id == Annotation.document_id)
        .where(Annotation.layer_id == layer.id)
        .group_by(Annotation.document_id, Document.title, Document.created_at)
        .order_by(Document.created_at, Annotation.document_id)
    ).all()
    return {
        "labels": [
            {"label": label, "count": c, "confirmed": cf, "modified": m}
            for label, c, cf, m in rows
        ],
        "progress": layer_view(db, layer)["progress"],
        "per_document": [
            {
                "document_id": d,
                "title": t,
                "total": total,
                **dict(zip(STATUSES, counts)),
            }
            for d, t, total, *counts in per_doc
        ],
    }


@router.post("/layers/{layer_id}/export")
def export_layer(layer_id: UUID, body: ExportInput, user: CurrentUser, db: Db):
    layer = load_layer(db, layer_id, user)
    params = {
        "source": "layer",
        "layer_id": str(layer.id),
        "format": body.format,
        "document_ids": _check_documents(db, layer.corpus_id, body.document_ids),
    }
    job = enqueue(db, "export", params, user.id, layer.project_id)
    db.commit()
    return job_view(job)


@router.post("/layers/{layer_id}/suggest")
def suggest(layer_id: UUID, body: SuggestInput, user: CurrentUser, db: Db):
    """Agent / model suggestions: only tokens still `suggested` change (label / head, source model:<model>);
    confirmed, modified and rejected tokens are reported in `skipped`."""
    layer = load_layer(db, layer_id, user, ANNOTATE, lock=True)
    labels = _label_ids(db, layer)
    items, skipped = [], []
    for item in body.items:
        if item.label is None and item.head is None:
            raise ApiError(422, "VALIDATION_ERROR", "建议须提供 label 或 head")
        _check_values(db, layer, item, item.label, item.head, labels)
        a = db.scalar(
            select(Annotation)
            .where(
                Annotation.layer_id == layer.id,
                Annotation.document_id == item.document_id,
                Annotation.sentence_index == item.sentence_index,
                Annotation.token_index == item.token_index,
            )
            .with_for_update()
        )
        ref = item.model_dump(
            mode="json", include={"document_id", "sentence_index", "token_index"}
        )
        if a is None:
            skipped.append({**ref, "reason": "not_found"})
            continue
        if a.status != "suggested":
            skipped.append({**ref, "reason": a.status})
            continue
        if item.label is not None:
            a.label = item.label
        if item.head is not None:
            a.head = item.head
        a.source, a.revision = f"model:{body.model}", a.revision + 1
        a.updated_by, a.updated_at = user.id, now()
        items.append(a)
    if body.single and skipped:
        reason = skipped[0]["reason"]
        if reason == "not_found":
            raise not_found("标注")
        raise ApiError(
            409, "ANNOTATION_REVIEWED", f"该 token 已人工处理（{reason}），建议未写入"
        )
    db.flush()
    refresh_progress(db, layer)
    db.commit()
    if body.single:
        return annotation_view(items[0])
    return {"items": [annotation_view(a) for a in items], "skipped": skipped}
