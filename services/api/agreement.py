"""Multi-annotator agreement, disagreements and adjudication (contracts/p5.md §三).

Only targets every annotator of the layer has finished count:
- token layers: a token is finished when the annotator's row is not suggested; value = label (rejected = ∅);
- span / relation layers: a sentence is finished when the annotator confirmed it (sentence confirm) or has rows
  in it and none suggested; units are the span extents (start_cp, end_cp) found by anyone in finished
  sentences, value = the annotator's label there or ∅ (exact). The lenient variant groups spans that overlap
  across annotators and compares their labels. Relations: units are (from extent, to extent);
- alignment layers: a source sentence is finished as for spans; sentence level compares the set of target
  sentences, word level each word pair (i, j) linked by anyone (linked / not linked).
κ: Cohen per annotator pair; α: nominal Krippendorff over all annotators; per_label: one-vs-rest κ.

Adjudication (owner / editor) stores `final` for a target; it becomes the effective annotation
(services.api.effective). final: token {label|null, head?}; span {label|null, attrs?}; relation {label|null};
alignment source sentence "<doc>:<idx>" {tgt: [[document_id, sentence_index]…]}, sentence pair
"<doc>:<idx>><doc>:<idx>" {links: [{src: [i…], tgt: [j…]}]}.
"""

from collections import defaultdict
from datetime import UTC, datetime
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from engine import agreement as ag
from engine import align
from services.api import effective as eff
from services.api.alignments import _sentence_length
from services.api.annotations import load_layer
from services.api.annotators import can_adjudicate, layer_annotators
from services.api.auth import CurrentUser, Db
from services.api.errors import ApiError, forbidden
from services.api.label_sets import human_only
from services.api.models import (
    Adjudication,
    AlignmentAnnotation,
    Annotation,
    Document,
    RelationAnnotation,
    Sentence,
    SentenceReview,
    SpanAnnotation,
    User,
)
from services.api.spans import check_label

router = APIRouter(prefix="/api")
NONE = "∅"
HUMAN = ("confirmed", "modified")
KIND_OF_LAYER = {
    "pos": "token",
    "dep": "token",
    "span": "span",
    "relation": "relation",
    "alignment": "alignment",
}


# ---- finished sentences ----


def _finished_sentences(db, layer, rows_by_annotator) -> dict:
    """{annotator: set((document_id, sentence_index))} finished by each annotator.
    rows_by_annotator: {annotator: [(document_id, sentence_index, status)]}."""
    out = defaultdict(set)
    for a, d, s in db.execute(
        select(
            SentenceReview.annotator_id,
            SentenceReview.document_id,
            SentenceReview.sentence_index,
        ).where(SentenceReview.layer_id == layer.id)
    ):
        out[a].add((d, s))
    for a, rows in rows_by_annotator.items():
        by_sentence = defaultdict(list)
        for d, s, status in rows:
            by_sentence[(d, s)].append(status)
        for key, statuses in by_sentence.items():
            if "suggested" not in statuses:
                out[a].add(key)
    return out


def _with_sentence(db, spans):
    """Fill sentence_index of cross-sentence spans with the sentence of their start."""
    missing = defaultdict(set)
    for s in spans:
        if s["sentence_index"] is None:
            missing[s["document_id"]].add(s["start_cp"])
    for doc, cps in missing.items():
        found = eff.sentence_of(db, doc, cps)
        for s in spans:
            if s["document_id"] == doc and s["sentence_index"] is None:
                s["sentence_index"] = found[s["start_cp"]]
    return spans


def _span_rows(db, layer, annotators):
    rows = eff.annotator_spans(db, layer, annotators, statuses=None)
    return _with_sentence(
        db,
        [
            {
                **eff._span_dict(s),
                "status": s.status,
                "annotator_id": s.annotator_id,
            }
            for s in rows
        ],
    )


# ---- units per layer kind: {target key: {annotator: value}} plus target info ----


def token_units(db, layer, annotators):
    values, info = defaultdict(dict), {}
    rows = db.execute(
        select(
            Annotation.annotator_id,
            Annotation.document_id,
            Annotation.sentence_index,
            Annotation.token_index,
            Annotation.label,
            Annotation.head,
            Annotation.status,
        ).where(
            Annotation.layer_id == layer.id,
            Annotation.annotator_id.in_(annotators),
            Annotation.status != "suggested",
        )
    ).all()
    for a, d, s, t, label, head, status in rows:
        key = f"{d}:{s}:{t}"
        rejected = status == "rejected"
        values[key][a] = {
            "kappa": NONE if rejected else label,
            "value": {"label": None if rejected else label, "head": head},
        }
        info[key] = (d, s)
    return values, info, {a: sum(a in v for v in values.values()) for a in annotators}


def span_units(db, layer, annotators, lenient=False):
    rows = _span_rows(db, layer, annotators)
    by_a = defaultdict(list)
    for r in rows:
        by_a[r["annotator_id"]].append(
            (r["document_id"], r["sentence_index"], r["status"])
        )
    finished = _finished_sentences(db, layer, by_a)
    common = (
        set.intersection(*(finished[a] for a in annotators)) if annotators else set()
    )
    done = {a: len(finished[a]) for a in annotators}
    human = [
        r
        for r in rows
        if r["status"] in HUMAN and (r["document_id"], r["sentence_index"]) in common
    ]
    values, info = defaultdict(dict), {}
    if not lenient:
        per = defaultdict(lambda: defaultdict(list))
        for r in human:
            k = eff.span_key(r["document_id"], r["start_cp"], r["end_cp"])
            per[k][r["annotator_id"]].append(r)
            info[k] = (r["document_id"], r["sentence_index"])
        for k, by in per.items():
            for a in annotators:
                spans = by.get(a, [])
                labels = sorted({s["label"] for s in spans})
                values[k][a] = {
                    "kappa": "+".join(labels) if labels else NONE,
                    "value": {"label": labels[0], "attrs": spans[0]["attrs"]}
                    if labels
                    else None,
                }
        return values, info, done
    by_sentence = defaultdict(list)
    for r in human:
        by_sentence[(r["document_id"], r["sentence_index"])].append(r)
    for key, spans in by_sentence.items():
        spans.sort(key=lambda r: (r["start_cp"], r["end_cp"]))
        clusters, end = [], -1
        for r in spans:  # overlap chains
            if r["start_cp"] >= end:
                clusters.append([])
            clusters[-1].append(r)
            end = max(end, r["end_cp"])
        for c in clusters:
            k = eff.span_key(key[0], c[0]["start_cp"], max(r["end_cp"] for r in c))
            info[k] = key
            for a in annotators:
                labels = sorted({r["label"] for r in c if r["annotator_id"] == a})
                values[k][a] = {"kappa": "+".join(labels) if labels else NONE}
    return values, info, done


def relation_units(db, layer, annotators):
    from sqlalchemy.orm import aliased

    f, t = aliased(SpanAnnotation), aliased(SpanAnnotation)
    rows = db.execute(
        select(RelationAnnotation, f, t)
        .join(f, f.id == RelationAnnotation.from_span_id)
        .join(t, t.id == RelationAnnotation.to_span_id)
        .where(
            RelationAnnotation.layer_id == layer.id,
            RelationAnnotation.annotator_id.in_(annotators),
        )
    ).all()
    starts = _with_sentence(db, [eff._span_dict(x) for _, x, _ in rows])
    by_a, items = defaultdict(list), []
    for (r, a_span, b_span), fs in zip(rows, starts):
        sentence = (fs["document_id"], fs["sentence_index"])
        by_a[r.annotator_id].append((*sentence, r.status))
        items.append((r, a_span, b_span, sentence))
    finished = _finished_sentences(db, layer, by_a)
    common = (
        set.intersection(*(finished[a] for a in annotators)) if annotators else set()
    )
    per, info = defaultdict(lambda: defaultdict(set)), {}
    for r, a_span, b_span, sentence in items:
        if r.status not in HUMAN or sentence not in common:
            continue
        k = eff.relation_key(
            eff.span_key(a_span.document_id, a_span.start_cp, a_span.end_cp),
            eff.span_key(b_span.document_id, b_span.start_cp, b_span.end_cp),
        )
        per[k][r.annotator_id].add(r.label)
        info[k] = sentence
    values = defaultdict(dict)
    for k, by in per.items():
        for a in annotators:
            labels = sorted(by.get(a, ()))
            values[k][a] = {
                "kappa": "+".join(labels) if labels else NONE,
                "value": {"label": labels[0]} if labels else None,
            }
    return values, info, {a: len(finished[a]) for a in annotators}


def alignment_units(db, layer, annotators, word_pairs=False):
    """Sentence level: {src key: {annotator: target set}}; word_pairs: {(pair key, i, j): {annotator: 0/1}};
    pair level (for disagreements): {pair key: {annotator: links}}."""
    rows = db.scalars(
        select(AlignmentAnnotation).where(
            AlignmentAnnotation.layer_id == layer.id,
            AlignmentAnnotation.annotator_id.in_(annotators),
        )
    ).all()
    by_a = defaultdict(list)
    for r in rows:
        by_a[r.annotator_id].append((r.src_document_id, r.src_sentence_index, r.status))
    finished = _finished_sentences(db, layer, by_a)
    common = (
        set.intersection(*(finished[a] for a in annotators)) if annotators else set()
    )
    kept = [
        r
        for r in rows
        if (r.src_document_id, r.src_sentence_index) in common
        and eff.effective_status_value(r)
    ]
    targets = defaultdict(lambda: defaultdict(set))
    links = defaultdict(lambda: defaultdict(set))
    for r in kept:
        sk = eff.sentence_key(r.src_document_id, r.src_sentence_index)
        tgt = (str(r.tgt_document_id), r.tgt_sentence_index)
        targets[sk][r.annotator_id].add(tgt)
        if r.src_tokens:
            pk = eff.pair_key(
                r.src_document_id,
                r.src_sentence_index,
                r.tgt_document_id,
                r.tgt_sentence_index,
            )
            links[pk][r.annotator_id].add(
                (tuple(sorted(r.src_tokens)), tuple(sorted(r.tgt_tokens)))
            )
    done = {a: len(finished[a]) for a in annotators}
    info = {}
    for d, s in common:
        info[eff.sentence_key(d, s)] = (d, s)
    sentence_values = defaultdict(dict)
    for d, s in common:
        sk = eff.sentence_key(d, s)
        for a in annotators:
            tg = sorted(targets[sk].get(a, ()))
            sentence_values[sk][a] = {
                "kappa": "|".join(f"{x}:{y}" for x, y in tg) or NONE,
                "value": {"tgt": [list(x) for x in tg]},
            }
    pair_values = defaultdict(dict)
    for pk, by in links.items():
        src_part = pk.split(">")[0]
        doc, _, idx = src_part.rpartition(":")
        info[pk] = (UUID(doc), int(idx))
        for a in annotators:
            ls = sorted(by.get(a, ()))
            pair_values[pk][a] = {
                "value": {"links": [{"src": list(x), "tgt": list(y)} for x, y in ls]},
                "pairs": align.word_pairs(ls),
            }
    if not word_pairs:
        return sentence_values, pair_values, info, done
    units = defaultdict(dict)
    for pk, by in pair_values.items():
        every = set().union(*(v["pairs"] for v in by.values()))
        for i, j in every:
            for a in annotators:
                units[(pk, i, j)][a] = {
                    "kappa": "1" if (i, j) in by[a]["pairs"] else "0"
                }
    return units, info, done


# ---- routes ----


def _units(db, layer, annotators, lenient=False):
    if layer.kind in ("pos", "dep"):
        return token_units(db, layer, annotators)
    if layer.kind == "span":
        return span_units(db, layer, annotators, lenient)
    if layer.kind == "relation":
        return relation_units(db, layer, annotators)
    if layer.level == "word":
        return alignment_units(db, layer, annotators, word_pairs=True)
    values, _, info, done = alignment_units(db, layer, annotators)
    return values, info, done


def _summary(values, annotators):
    complete = {k: v for k, v in values.items() if all(a in v for a in annotators)}
    keys = sorted(complete, key=str)
    per = {str(a): [complete[k][a]["kappa"] for k in keys] for a in annotators}
    return ag.summary(per)


@router.get("/layers/{layer_id}/agreement")
def agreement(layer_id: UUID, user: CurrentUser, db: Db):
    layer = load_layer(db, layer_id, user)
    annotators = layer_annotators(layer)
    values, _, done = _units(db, layer, annotators)
    emails = dict(
        db.execute(select(User.id, User.email).where(User.id.in_(annotators))).all()
    )
    out = {
        "mode": layer.mode,
        "annotators": [
            {"user_id": a, "email": emails.get(a), "done": done.get(a, 0)}
            for a in annotators
        ],
        **_summary(values, annotators),
    }
    if layer.kind == "span":
        lenient, _, _ = span_units(db, layer, annotators, lenient=True)
        s = _summary(lenient, annotators)
        out["lenient"] = {"pairwise": s["pairwise"], "alpha": s["alpha"], "n": s["n"]}
    return out


def _disagreements(db, layer, annotators):
    """[(kind, key, (document_id, sentence_index), {annotator: value})] where the finished values differ."""
    out = []
    if layer.kind == "alignment":
        sentence_values, pair_values, info, _ = alignment_units(db, layer, annotators)
        groups = [("alignment", sentence_values), ("alignment", pair_values)]
    else:
        values, info, _ = _units(db, layer, annotators)
        groups = [(KIND_OF_LAYER[layer.kind], values)]
    for kind, values in groups:
        for key, by in values.items():
            if not all(a in by for a in annotators):
                continue
            shown = [by[a].get("value") for a in annotators]
            if any(v != shown[0] for v in shown[1:]):
                out.append((kind, key, info.get(key), dict(zip(annotators, shown))))
    out.sort(key=lambda x: (str(x[2][0]) if x[2] else "", x[2][1] if x[2] else 0, x[1]))
    return out


@router.get("/layers/{layer_id}/disagreements")
def disagreements(
    layer_id: UUID,
    user: CurrentUser,
    db: Db,
    cursor: Annotated[str | None, Query(max_length=20, pattern=r"^\d+$")] = None,
    page_size: Annotated[int, Query(ge=1, le=200)] = 50,
):
    """Targets finished by every annotator whose values differ; cursor = offset (next_cursor)."""
    layer = load_layer(db, layer_id, user)
    if not can_adjudicate(db, layer, user):
        raise forbidden()
    annotators = layer_annotators(layer)
    items = _disagreements(db, layer, annotators) if len(annotators) > 1 else []
    start = int(cursor or 0)
    page = items[start : start + page_size]
    adjudicated = eff._adjudications(db, layer, KIND_OF_LAYER[layer.kind])
    texts = {}
    keys = {x[2] for x in page if x[2]}
    if keys:
        texts = {
            (d, i): t
            for d, i, t in db.execute(
                select(Sentence.document_id, Sentence.idx, Sentence.text).where(
                    Sentence.document_id.in_({k[0] for k in keys})
                )
            )
            if (d, i) in keys
        }
    return {
        "items": [
            {
                "target_kind": kind,
                "target_key": key,
                "document_id": where[0] if where else None,
                "sentence_index": where[1] if where else None,
                "text": texts.get(where) if where else None,
                "values": [{"annotator_id": a, "value": v} for a, v in values.items()],
                "adjudicated": key in adjudicated,
                "final": adjudicated.get(key),
            }
            for kind, key, where, values in page
        ],
        "total": len(items),
        "next_cursor": str(start + page_size)
        if start + page_size < len(items)
        else None,
    }


class AdjudicateInput(BaseModel):
    target_kind: Literal["token", "span", "relation", "alignment"]
    target_key: str = Field(min_length=3, max_length=300)
    final: dict


def _uuid(x):
    try:
        return UUID(str(x))
    except ValueError:
        raise ApiError(422, "INVALID_TARGET", "target_key 格式不正确") from None


def _check_final(db, layer, kind, key, final):
    """Validated final value for a target (422 INVALID_TARGET / INVALID_LABEL)."""
    try:
        if kind == "token":
            doc, s, t = key.split(":")
            _uuid(doc), int(s), int(t)
            label = final.get("label")
            if label is not None:
                label = check_label(db, layer, label)
            head = final.get("head")
            if head is not None and (not isinstance(head, int) or head < 0):
                raise ApiError(422, "INVALID_HEAD", "head 须为非负整数")
            return {"label": label, "head": head}
        if kind == "span":
            doc, a, b = eff.parse_span_key(key)
            d = db.get(Document, doc)
            if (
                not d
                or d.corpus_id != layer.corpus_id
                or not 0 <= a < b <= d.char_count
            ):
                raise ApiError(422, "INVALID_TARGET", "片段范围无效")
            label = final.get("label")
            from services.api.spans import clean_attrs

            return {
                "label": check_label(db, layer, label) if label is not None else None,
                "attrs": clean_attrs(final.get("attrs")),
            }
        if kind == "relation":
            left, right = key.split(">")
            eff.parse_span_key(left), eff.parse_span_key(right)
            label = final.get("label")
            return {
                "label": check_label(db, layer, label) if label is not None else None
            }
        if ">" in key:
            if layer.level != "word":
                raise ApiError(422, "INVALID_TARGET", "句级对齐层没有词级目标")
            src, tgt = key.split(">")
            sd, _, si = src.rpartition(":")
            td, _, ti = tgt.rpartition(":")
            _uuid(sd), _uuid(td)
            n_src = _sentence_length(db, _uuid(sd), int(si))
            n_tgt = _sentence_length(db, _uuid(td), int(ti))
            links = align.clean_links(final.get("links") or [], n_src, n_tgt)
            return {"links": [{"src": list(x), "tgt": list(y)} for x, y in links]}
        doc, _, idx = key.rpartition(":")
        _uuid(doc), int(idx)
        tgt = [[str(_uuid(d)), int(i)] for d, i in final.get("tgt") or []]
        return {"tgt": tgt}
    except (ValueError, TypeError, AttributeError):
        raise ApiError(
            422, "INVALID_TARGET", "target_key 或 final 格式不正确"
        ) from None


@router.post("/layers/{layer_id}/adjudicate")
def adjudicate(layer_id: UUID, body: AdjudicateInput, user: CurrentUser, db: Db):
    human_only(user)
    layer = load_layer(db, layer_id, user, ("owner", "editor"), lock=True)
    if layer.mode != "multi":
        raise ApiError(422, "NOT_MULTI", "只有多人标注层需要仲裁")
    if body.target_kind != KIND_OF_LAYER[layer.kind]:
        raise ApiError(
            422, "INVALID_TARGET", f"该层的目标类型为 {KIND_OF_LAYER[layer.kind]}"
        )
    final = _check_final(db, layer, body.target_kind, body.target_key, body.final)
    now = datetime.now(UTC)
    stmt = insert(Adjudication).values(
        layer_id=layer.id,
        target_kind=body.target_kind,
        target_key=body.target_key,
        final=final,
        decided_by=user.id,
        decided_at=now,
    )
    row = db.execute(
        stmt.on_conflict_do_update(
            constraint="uq_adjudications_target",
            set_={"final": final, "decided_by": user.id, "decided_at": now},
        ).returning(Adjudication)
    ).scalar_one()
    layer.updated_at = now
    db.commit()
    return {
        "id": row.id,
        "layer_id": row.layer_id,
        "target_kind": row.target_kind,
        "target_key": row.target_key,
        "final": row.final,
        "decided_by": row.decided_by,
        "decided_at": row.decided_at,
    }
