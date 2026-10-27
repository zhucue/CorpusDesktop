"""Alignment layers: sentence pairs and word links (contracts/p5.md §三), agent suggestions and alignment stats.

Rows: a sentence pair has src_tokens = tgt_tokens = []; in word layers each link is one more row of the same
pair with 1-based token numbers. GET …/alignments pages source sentences (cursor "<src_document_id>:<index>") and
returns one SentencePair per target sentence (tgt null when the source sentence has no pair).
"""

from collections import defaultdict
from datetime import UTC, datetime
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Query
from pydantic import BaseModel, Field
from sqlalchemy import exists, func, select, tuple_

from engine import align
from services.api import effective
from services.api.annotations import ANNOTATE, load_layer, refresh_progress
from services.api.annotators import visible, writer
from services.api.auth import CurrentUser, Db
from services.api.errors import ApiError, not_found
from services.api.label_sets import human_only
from services.api.models import (
    AlignmentAnnotation,
    Document,
    Sentence,
    Token,
)
from services.api.spans import check_document, mark_reviewed, sentence_page

router = APIRouter(prefix="/api")
A = AlignmentAnnotation


def now():
    return datetime.now(UTC)


def alignment_view(a) -> dict:
    return {
        "id": a.id,
        "level": "word" if a.src_tokens else "sentence",
        "src_document_id": a.src_document_id,
        "src_sentence_index": a.src_sentence_index,
        "tgt_document_id": a.tgt_document_id,
        "tgt_sentence_index": a.tgt_sentence_index,
        "src_tokens": list(a.src_tokens or []),
        "tgt_tokens": list(a.tgt_tokens or []),
        "score": a.score,
        "source": a.source,
        "status": a.status,
        "revision": a.revision,
        "annotator_id": a.annotator_id,
        "updated_at": a.updated_at,
    }


def _alignment_layer(db, layer_id, user, roles=None, lock=False):
    layer = (
        load_layer(db, layer_id, user, roles, lock=lock)
        if roles
        else load_layer(db, layer_id, user)
    )
    if layer.kind != "alignment":
        raise ApiError(422, "INVALID_LAYER", "该接口只用于对齐层")
    return layer


def sentence_tokens(db, keys) -> dict:
    """{(document_id, idx): (text, [form…])} for sentence keys."""
    if not keys:
        return {}
    out = {
        (d, i): (t, [])
        for d, i, t in db.execute(
            select(Sentence.document_id, Sentence.idx, Sentence.text).where(
                tuple_(Sentence.document_id, Sentence.idx).in_(list(keys))
            )
        )
    }
    for d, i, form in db.execute(
        select(Sentence.document_id, Sentence.idx, Token.form)
        .join(Token, Token.sentence_id == Sentence.id)
        .where(tuple_(Sentence.document_id, Sentence.idx).in_(list(keys)))
        .order_by(Sentence.document_id, Sentence.idx, Token.idx)
    ):
        out[(d, i)][1].append(form)
    return out


def _side(key, info):
    text, forms = info.get(key, ("", []))
    return {
        "document_id": key[0],
        "sentence_index": key[1],
        "text": text,
        "tokens": [{"index": n, "form": f} for n, f in enumerate(forms, 1)],
    }


def sentence_pairs(db, layer, sources, annotators):
    """SentencePair items for source sentence keys [(document_id, idx)], in order."""
    if not sources:
        return []
    of = [] if annotators is None else [A.annotator_id.in_(list(annotators))]
    rows = db.scalars(
        select(A)
        .where(
            A.layer_id == layer.id,
            tuple_(A.src_document_id, A.src_sentence_index).in_(sources),
            *of,
        )
        .order_by(
            A.tgt_document_id,
            A.tgt_sentence_index,
            func.cardinality(A.src_tokens),
            A.id,
        )
    ).all()
    by_src = defaultdict(lambda: defaultdict(list))
    for r in rows:
        by_src[(r.src_document_id, r.src_sentence_index)][
            (r.tgt_document_id, r.tgt_sentence_index)
        ].append(r)
    keys = set(sources) | {t for per in by_src.values() for t in per}
    info = sentence_tokens(db, keys)
    out = []
    for src in sources:
        targets = by_src.get(src)
        if not targets:
            out.append({"src": _side(src, info), "tgt": None, "alignments": []})
            continue
        for tgt, items in targets.items():
            out.append(
                {
                    "src": _side(src, info),
                    "tgt": _side(tgt, info),
                    "alignments": [alignment_view(a) for a in items],
                }
            )
    return out


@router.get("/layers/{layer_id}/alignments")
def list_alignments(
    layer_id: UUID,
    user: CurrentUser,
    db: Db,
    src_document_id: UUID | None = None,
    cursor: Annotated[str | None, Query(max_length=100)] = None,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
    status: Literal["pending", "all"] = "all",
    annotator_id: UUID | None = None,
):
    layer = _alignment_layer(db, layer_id, user)
    annotators = visible(db, layer, user, annotator_id)
    pending = None
    if status == "pending":
        of = [] if annotators is None else [A.annotator_id.in_(annotators)]
        pending = exists(
            select(A.id).where(
                A.layer_id == layer.id,
                A.status == "suggested",
                A.src_document_id == Sentence.document_id,
                A.src_sentence_index == Sentence.idx,
                *of,
            )
        )
    rows, next_cursor = sentence_page(
        db, layer, src_document_id, cursor, page_size, pending
    )
    sources = [(d, i) for d, i, *_ in rows]
    return {
        "items": sentence_pairs(db, layer, sources, annotators),
        "next_cursor": next_cursor,
    }


def _sentence_length(db, document_id, idx):
    n = db.scalar(
        select(func.count(Token.id))
        .select_from(Sentence)
        .outerjoin(Token, Token.sentence_id == Sentence.id)
        .where(Sentence.document_id == document_id, Sentence.idx == idx)
        .group_by(Sentence.id)
    )
    if n is None:
        raise ApiError(422, "INVALID_SENTENCE", f"文档 {document_id} 没有第 {idx} 句")
    return n


def _check_target(db, layer, document_id):
    doc = db.get(Document, document_id)
    if not doc or doc.corpus_id != layer.tgt_corpus_id:
        raise ApiError(422, "INVALID_DOCUMENTS", "目标文档不在该层的目标语料库中")
    return doc


def _check_tokens(db, layer, src, tgt, src_tokens, tgt_tokens):
    """Validated (src tuple, tgt tuple): both empty (sentence pair) or, in word layers, both non-empty."""
    if not src_tokens and not tgt_tokens:
        return (), ()
    if layer.level != "word":
        raise ApiError(422, "VALIDATION_ERROR", "句级对齐层不接受 token 序号")
    links = align.clean_links(
        [{"src": src_tokens, "tgt": tgt_tokens}],
        _sentence_length(db, *src),
        _sentence_length(db, *tgt),
    )
    if not links:
        raise ApiError(
            422,
            "INVALID_TOKENS",
            "src_tokens 与 tgt_tokens 须为该句内的 1 起 token 序号",
        )
    return links[0]


class AlignmentInput(BaseModel):
    src_document_id: UUID
    src_sentence_index: int = Field(ge=0)
    tgt_document_id: UUID
    tgt_sentence_index: int = Field(ge=0)
    src_tokens: list[int] = Field(default=[], max_length=200)
    tgt_tokens: list[int] = Field(default=[], max_length=200)


class AlignmentAction(BaseModel):
    action: Literal["confirm", "modify", "reject"]
    src_tokens: list[int] | None = Field(default=None, max_length=200)
    tgt_tokens: list[int] | None = Field(default=None, max_length=200)
    tgt_sentence_index: int | None = Field(default=None, ge=0)


def _find(db, layer, me, src, tgt, s_tok, t_tok):
    return db.scalar(
        select(A).where(
            A.layer_id == layer.id,
            A.annotator_id == me,
            A.src_document_id == src[0],
            A.src_sentence_index == src[1],
            A.tgt_document_id == tgt[0],
            A.tgt_sentence_index == tgt[1],
            A.src_tokens == list(s_tok),
            A.tgt_tokens == list(t_tok),
        )
    )


def _new(db, layer, me, src, tgt, s_tok, t_tok, source, status, user, score=None):
    row = A(
        layer_id=layer.id,
        annotator_id=me,
        src_document_id=src[0],
        src_sentence_index=src[1],
        tgt_document_id=tgt[0],
        tgt_sentence_index=tgt[1],
        src_tokens=list(s_tok),
        tgt_tokens=list(t_tok),
        score=score,
        source=source,
        status=status,
        revision=1,
        updated_by=user.id,
        updated_at=now(),
    )
    db.add(row)
    return row


def _check_pair(db, layer, body):
    check_document(db, layer, body.src_document_id)
    _check_target(db, layer, body.tgt_document_id)
    src = (body.src_document_id, body.src_sentence_index)
    tgt = (body.tgt_document_id, body.tgt_sentence_index)
    _sentence_length(db, *src)
    _sentence_length(db, *tgt)
    return src, tgt


@router.post("/layers/{layer_id}/alignments")
def create_alignment(layer_id: UUID, body: AlignmentInput, user: CurrentUser, db: Db):
    """A confirmed sentence pair, or a word link (the pair row is added when missing)."""
    human_only(user)
    layer = _alignment_layer(db, layer_id, user, ANNOTATE, lock=True)
    me = writer(layer, user)
    src, tgt = _check_pair(db, layer, body)
    s_tok, t_tok = _check_tokens(db, layer, src, tgt, body.src_tokens, body.tgt_tokens)
    found = _find(db, layer, me, src, tgt, s_tok, t_tok)
    if found and found.status != "rejected":
        raise ApiError(409, "ALIGNMENT_EXISTS", "已有相同的对齐")
    source = f"human:{user.id}"
    if s_tok and not _find(db, layer, me, src, tgt, (), ()):
        _new(db, layer, me, src, tgt, (), (), source, "confirmed", user)
    if found:  # a rejected identical row comes back
        found.status, found.source, found.revision = (
            "confirmed",
            source,
            found.revision + 1,
        )
        found.updated_by, found.updated_at = user.id, now()
        row = found
    else:
        row = _new(db, layer, me, src, tgt, s_tok, t_tok, source, "confirmed", user)
    db.flush()
    refresh_progress(db, layer)
    db.commit()
    return alignment_view(row)


@router.patch("/layers/{layer_id}/alignments/{alignment_id}")
def act_alignment(
    layer_id: UUID, alignment_id: int, body: AlignmentAction, user: CurrentUser, db: Db
):
    human_only(user)
    layer = _alignment_layer(db, layer_id, user, ANNOTATE, lock=True)
    row = db.get(A, alignment_id, with_for_update=True)
    if not row or row.layer_id != layer.id or row.annotator_id != writer(layer, user):
        raise not_found("对齐")
    src = (row.src_document_id, row.src_sentence_index)
    if body.action == "reject":
        row.status = "rejected"
    elif body.action == "confirm":
        row.status = "modified" if row.status == "modified" else "confirmed"
    else:
        if body.tgt_sentence_index is not None:
            if row.src_tokens:
                raise ApiError(422, "VALIDATION_ERROR", "改目标句须在句对上操作")
            _sentence_length(db, row.tgt_document_id, body.tgt_sentence_index)
            old = (row.tgt_document_id, row.tgt_sentence_index)
            for link in db.scalars(
                select(A).where(
                    A.layer_id == layer.id,
                    A.annotator_id == row.annotator_id,
                    A.src_document_id == src[0],
                    A.src_sentence_index == src[1],
                    A.tgt_document_id == old[0],
                    A.tgt_sentence_index == old[1],
                    func.cardinality(A.src_tokens) > 0,
                )
            ):  # links of the old pair no longer apply
                if link.status == "suggested":
                    db.delete(link)
                else:
                    link.status, link.updated_at = "rejected", now()
            row.tgt_sentence_index = body.tgt_sentence_index
        if body.src_tokens is not None or body.tgt_tokens is not None:
            if not row.src_tokens:
                raise ApiError(422, "VALIDATION_ERROR", "句对行没有 token 序号")
            tgt = (row.tgt_document_id, row.tgt_sentence_index)
            s_tok, t_tok = _check_tokens(
                db,
                layer,
                src,
                tgt,
                body.src_tokens if body.src_tokens is not None else row.src_tokens,
                body.tgt_tokens if body.tgt_tokens is not None else row.tgt_tokens,
            )
            row.src_tokens, row.tgt_tokens = list(s_tok), list(t_tok)
        if (
            body.tgt_sentence_index is None
            and body.src_tokens is None
            and body.tgt_tokens is None
        ):
            raise ApiError(
                422, "VALIDATION_ERROR", "修改须提供 tgt_sentence_index 或 token 序号"
            )
        row.status = "modified"
    row.source, row.revision = f"human:{user.id}", row.revision + 1
    row.updated_by, row.updated_at = user.id, now()
    db.flush()
    refresh_progress(db, layer)
    db.commit()
    return alignment_view(row)


class Link(BaseModel):
    src: list[int] = Field(min_length=1, max_length=200)
    tgt: list[int] = Field(min_length=1, max_length=200)


class AlignmentSuggestInput(BaseModel):
    model: str = Field(
        default="agent", min_length=1, max_length=100, pattern=r"^[\w.:/@-]+$"
    )
    src_document_id: UUID
    src_sentence_index: int = Field(ge=0)
    tgt_document_id: UUID
    tgt_sentence_index: int = Field(ge=0)
    links: list[Link] = Field(min_length=1, max_length=500)


@router.post("/layers/{layer_id}/alignments/suggest")
def suggest_alignments(
    layer_id: UUID, body: AlignmentSuggestInput, user: CurrentUser, db: Db
):
    """Suggested word links of one sentence pair (word layers); the pair row is added (suggested) when
    missing. Identical existing links are reported in skipped; reviewed rows never change."""
    layer = _alignment_layer(db, layer_id, user, ANNOTATE, lock=True)
    if layer.level != "word":
        raise ApiError(422, "INVALID_LAYER", "词级对齐建议须写入词级对齐层")
    me = writer(layer, user)
    src, tgt = _check_pair(db, layer, body)
    n_src, n_tgt = _sentence_length(db, *src), _sentence_length(db, *tgt)
    links = align.clean_links([x.model_dump() for x in body.links], n_src, n_tgt)
    if len(links) != len(
        {(tuple(sorted(set(x.src))), tuple(sorted(set(x.tgt)))) for x in body.links}
    ):
        raise ApiError(
            422,
            "INVALID_TOKENS",
            f"token 序号须在 1–{n_src}（源）与 1–{n_tgt}（目标）之间",
        )
    source = f"model:{body.model}"
    if not _find(db, layer, me, src, tgt, (), ()):
        _new(db, layer, me, src, tgt, (), (), source, "suggested", user)
    items, skipped = [], []
    for s_tok, t_tok in links:
        found = _find(db, layer, me, src, tgt, s_tok, t_tok)
        if found:
            skipped.append(
                {"src": list(s_tok), "tgt": list(t_tok), "reason": found.status}
            )
            continue
        items.append(
            _new(db, layer, me, src, tgt, s_tok, t_tok, source, "suggested", user)
        )
    db.flush()
    refresh_progress(db, layer)
    db.commit()
    return {"items": [alignment_view(a) for a in items], "skipped": skipped}


def confirm_alignment_sentence(db, layer, user, document_id, sentence_index):
    """The user's suggested rows of a source sentence → confirmed; the sentence is marked reviewed."""
    me = writer(layer, user)
    check_document(db, layer, document_id)
    _sentence_length(db, document_id, sentence_index)
    for row in db.scalars(
        select(A).where(
            A.layer_id == layer.id,
            A.annotator_id == me,
            A.status == "suggested",
            A.src_document_id == document_id,
            A.src_sentence_index == sentence_index,
        )
    ):
        row.status, row.source = "confirmed", f"human:{user.id}"
        row.revision += 1
        row.updated_by, row.updated_at = user.id, now()
    mark_reviewed(db, layer, me, document_id, sentence_index)
    db.flush()
    refresh_progress(db, layer)
    db.commit()
    return {"items": sentence_pairs(db, layer, [(document_id, sentence_index)], [me])}


# ---- statistics ----


class AlignmentStatsInput(BaseModel):
    layer_id: UUID


def alignment_stats(db, layer) -> dict:
    """Effective pairs; one-to-one / one-to-many groups (connected source–target sentence groups with one
    sentence on each side, or more); unaligned source sentences of the layer's documents and target sentences
    of the target documents that have pairs; mean links and word pairs per sentence pair (word layers)."""
    pairs = effective.effective_alignments(db, effective.eff_layer(layer))
    parent = {}

    def find(x):
        while parent.setdefault(x, x) != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for p in pairs:
        a = ("s", p["src_document_id"], p["src_sentence_index"])
        b = ("t", p["tgt_document_id"], p["tgt_sentence_index"])
        parent[find(a)] = find(b)
    groups = defaultdict(lambda: [0, 0])
    for node in list(parent):
        groups[find(node)][0 if node[0] == "s" else 1] += 1
    one_to_one = sum(1 for s, t in groups.values() if s == 1 and t == 1)
    src_total = db.scalar(
        select(func.count())
        .select_from(Sentence)
        .join(Document, Document.id == Sentence.document_id)
        .where(
            Document.corpus_id == layer.corpus_id,
            *(
                [Document.id.in_([UUID(d) for d in layer.document_ids])]
                if layer.document_ids
                else []
            ),
        )
    )
    tgt_docs = {p["tgt_document_id"] for p in pairs}
    tgt_total = (
        db.scalar(select(func.count()).where(Sentence.document_id.in_(list(tgt_docs))))
        if tgt_docs
        else 0
    )
    aligned_src = {(p["src_document_id"], p["src_sentence_index"]) for p in pairs}
    aligned_tgt = {(p["tgt_document_id"], p["tgt_sentence_index"]) for p in pairs}
    word = layer.level == "word"
    return {
        "layer_id": layer.id,
        "level": layer.level,
        "pairs": len(pairs),
        "one_to_one": one_to_one,
        "one_to_many": len(groups) - one_to_one,
        "unaligned": {
            "src": src_total - len(aligned_src),
            "tgt": tgt_total - len(aligned_tgt),
        },
        "avg_links": (
            sum(len(p["links"]) for p in pairs) / len(pairs) if word and pairs else None
        ),
        "avg_word_pairs": (
            sum(len(align.word_pairs(p["links"])) for p in pairs) / len(pairs)
            if word and pairs
            else None
        ),
    }


@router.post("/stats/alignment")
def stats_alignment(body: AlignmentStatsInput, user: CurrentUser, db: Db):
    layer = _alignment_layer(db, body.layer_id, user)
    return alignment_stats(db, layer)
