"""Effective annotations in PostgreSQL (contracts/p3.md §二–§三), shared by search, statistics and export.

Effective value of a token for a layer: the annotation's label / head when its status is confirmed or modified;
for a pos layer a rejected annotation means no tag (NULL); otherwise the system value in `tokens` (pos, head,
deprel). Without a layer the system value is used. annotations.token_index is tokens.idx + 1.

Query attributes `{pos=, dep=, lemma=}` (engine.query) are resolved here: pos / dep compare the effective value
exactly (pos values arrive already expanded for the corpus tagset), lemma compares tokens.lemma case-insensitively.
- anchored queries: cwb.search finds the attribute slot's token in each hit and calls filter_tokens with the
  candidate (document_id, sentence_index, token_index) keys;
- pure attribute queries (one `{…}` slot, optionally with `/pos`, no +/- conditions): pg_search produces the
  hits from `tokens` alone, with the code points, counts, sort, paging and context of cwb.search.

P5 (contracts/p5.md): layers with mode = multi keep one set of annotations per annotator. Their effective value
for a target is the adjudication when there is one, else the value all annotators agree on (each annotator's
confirmed / modified value; tokens without agreement fall back to the system value, spans / relations / sentence
pairs without agreement are not effective). In single mode the annotations are shared (annotator = layer creator).
Effective spans and relations: status confirmed or modified. Effective alignments: confirmed or modified, or
still suggested when imported (source = system, from sentence_alignments).
Span labels `[标签]` (engine.query `#spans` lines): pure span queries produce one hit per effective span
(span_search); anchored ones keep hits whose slot token lies inside such a span (filter_span_tokens).
"""

import json
import random
from collections import defaultdict
from pathlib import Path
from typing import NamedTuple
from uuid import UUID

from sqlalchemy import (
    Integer,
    Text,
    and_,
    bindparam,
    case,
    cast,
    func,
    null,
    or_,
    select,
    text,
    tuple_,
    union_all,
)
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import aliased

from engine.model import Counts, Hit, SearchResult
from services.api.access import require_project
from services.api.errors import ApiError
from services.api.metadata import filter_clause
from services.api.models import (
    Adjudication,
    AlignmentAnnotation,
    Annotation,
    AnnotationLayer,
    Document,
    LabelSet,
    RelationAnnotation,
    Sentence,
    SpanAnnotation,
    Token,
)

HUMAN = ("confirmed", "modified")
LAYER_KEYS = ("pos", "dep", "span", "relation")


class EffLayer(NamedTuple):
    """What effective-value queries need to know about a layer; str() is the layer id (cache keys)."""

    id: UUID
    kind: str
    mode: str
    annotators: tuple
    created_by: UUID
    label_set_id: UUID | None
    name: str
    base_layer_id: UUID | None
    level: str | None
    corpus_id: UUID | None = None
    project_id: UUID | None = None

    def __str__(self):
        return str(self.id)


def eff_layer(layer) -> EffLayer:
    multi = layer.mode == "multi"
    return EffLayer(
        layer.id,
        layer.kind,
        layer.mode,
        tuple(layer.annotators or [layer.created_by]) if multi else (layer.created_by,),
        layer.created_by,
        layer.label_set_id,
        layer.name,
        layer.base_layer_id,
        layer.level,
        layer.corpus_id,
        layer.project_id,
    )


def effective_status(model):
    """Rows that count for a layer: confirmed / modified, or imported (source system) and not yet reviewed."""
    return or_(
        model.status.in_(HUMAN),
        and_(model.status == "suggested", model.source == "system"),
    )


PARA_MAX = 2000  # as engine.cwb
BATCH = 20000


def check_layers(db, layers, corpus, user) -> dict:
    """SearchRequest.layers → {"pos", "dep", "span", "relation": EffLayer|None}; each layer must be of that kind,
    on this corpus and readable by the user."""
    out = dict.fromkeys(LAYER_KEYS)
    for kind in out:
        layer_id = getattr(layers, kind, None) if layers else None
        if layer_id is None:
            continue
        layer = db.get(AnnotationLayer, layer_id)
        if not layer or layer.kind != kind or layer.corpus_id != corpus.id:
            raise ApiError(
                422, "INVALID_LAYER", f"layers.{kind} 不是该语料库的 {kind} 标注层"
            )
        require_project(db, layer.project_id, user)
        out[kind] = eff_layer(layer)
    return out


def default_layer(db, corpus, user, kind):
    """The most recently updated layer of a kind on the corpus in one of the user's projects (or None)."""
    from services.api.access import token_project
    from services.api.models import ProjectMember

    stmt = (
        select(AnnotationLayer)
        .join(
            ProjectMember,
            and_(
                ProjectMember.project_id == AnnotationLayer.project_id,
                ProjectMember.user_id == user.id,
            ),
        )
        .where(AnnotationLayer.kind == kind, AnnotationLayer.corpus_id == corpus.id)
        .order_by(AnnotationLayer.updated_at.desc(), AnnotationLayer.id)
        .limit(1)
    )
    if token_project(user) is not None:
        stmt = stmt.where(AnnotationLayer.project_id == token_project(user))
    layer = db.scalar(stmt)
    return eff_layer(layer) if layer else None


def _multi_tokens(layer: EffLayer):
    """Effective token rows of a multi-annotator layer: adjudications, else values every annotator agrees on."""
    a, j = Annotation, Adjudication
    rejected = a.status == "rejected"
    label = case((rejected, null()), else_=a.label)
    value = func.concat(
        func.coalesce(label, "∅"), "|", func.coalesce(cast(a.head, Text), "")
    )
    key = func.concat(
        cast(a.document_id, Text), ":", a.sentence_index, ":", a.token_index
    )
    adjudicated = select(j.target_key).where(
        j.layer_id == layer.id, j.target_kind == "token"
    )
    consensus = (
        select(
            a.document_id.label("document_id"),
            a.sentence_index.label("sentence_index"),
            a.token_index.label("token_index"),
            func.min(label).label("label"),
            func.min(a.head).label("head"),
            case((func.bool_and(rejected), "rejected"), else_="confirmed").label(
                "status"
            ),
        )
        .where(
            a.layer_id == layer.id,
            a.annotator_id.in_(layer.annotators),
            a.status != "suggested",
            key.not_in(adjudicated),
        )
        .group_by(a.document_id, a.sentence_index, a.token_index)
        .having(
            func.count(a.annotator_id.distinct()) == len(layer.annotators),
            func.count(value.distinct()) == 1,
        )
    )
    final_label = j.final["label"].astext
    adjudications = select(
        cast(func.split_part(j.target_key, ":", 1), PG_UUID),
        cast(func.split_part(j.target_key, ":", 2), Integer),
        cast(func.split_part(j.target_key, ":", 3), Integer),
        final_label,
        cast(j.final["head"].astext, Integer),
        case((final_label.is_(None), "rejected"), else_="confirmed"),
    ).where(j.layer_id == layer.id, j.target_kind == "token")
    return union_all(consensus, adjudications).subquery()


def _join_layer(stmt, layer):
    if getattr(layer, "mode", "single") == "multi":
        sq = _multi_tokens(layer)
        a, cond = sq.c, []
    else:
        a = aliased(Annotation)
        cond = [a.layer_id == getattr(layer, "id", layer)]
        sq = a
    stmt = stmt.outerjoin(
        sq,
        and_(
            *cond,
            a.document_id == Sentence.document_id,
            a.sentence_index == Sentence.idx,
            a.token_index == Token.idx + 1,
        ),
    )
    return stmt, a


def effective(stmt, layers):
    """Outer-join the layers onto a statement over Token ⋈ Sentence; returns (stmt, {pos, dep, head, lemma})."""
    cols = {
        "pos": Token.pos,
        "dep": Token.deprel,
        "head": Token.head,
        "lemma": Token.lemma,
    }
    if layers.get("pos"):
        stmt, a = _join_layer(stmt, layers["pos"])
        cols["pos"] = case(
            (a.status.in_(HUMAN), a.label),
            (a.status == "rejected", null()),
            else_=Token.pos,
        )
    if layers.get("dep"):
        stmt, a = _join_layer(stmt, layers["dep"])
        cols["dep"] = case((a.status.in_(HUMAN), a.label), else_=Token.deprel)
        cols["head"] = case((a.status.in_(HUMAN), a.head), else_=Token.head)
    return stmt, cols


def attr_clauses(cols, constraints):
    out = []
    for key, values in constraints.items():
        if key == "lemma":
            out.append(func.lower(cols["lemma"]).in_([v.lower() for v in values]))
        else:
            out.append(cols[key].in_(values))
    return out


def filter_tokens(db, layers, constraints, keys) -> set:
    """Candidate (document_id str, sentence_index, token_index 0-based) keys that satisfy the constraints."""
    keys, out = list(keys), set()
    for i in range(0, len(keys), BATCH):
        docs, sents, toks = zip(*keys[i : i + BATCH])
        c = select(
            func.unnest(
                cast(bindparam(None, list(docs), ARRAY(Text)), ARRAY(PG_UUID))
            ).label("doc"),
            func.unnest(bindparam(None, list(sents), ARRAY(Integer))).label("s"),
            func.unnest(bindparam(None, list(toks), ARRAY(Integer))).label("t"),
        ).subquery()
        stmt = (
            select(c.c.doc, c.c.s, c.c.t)
            .select_from(c)
            .join(
                Sentence, and_(Sentence.document_id == c.c.doc, Sentence.idx == c.c.s)
            )
            .join(Token, and_(Token.sentence_id == Sentence.id, Token.idx == c.c.t))
        )
        stmt, cols = effective(stmt, layers)
        out |= {
            (str(d), s, t)
            for d, s, t in db.execute(stmt.where(*attr_clauses(cols, constraints)))
        }
    return out


def scope_clauses(corpus, filt, fields):
    where = [Document.corpus_id == corpus.id]
    if filt:
        where.append(filter_clause(filt, fields))
    return where


def pg_search(
    db, corpus, filt, fields, atom, constraints, layers, req, page, page_size
):
    """Hits of a pure attribute query from `tokens`; same semantics as engine.cwb.search."""
    order = (Sentence.idx, Token.idx)
    extra = []
    if req.sort in ("left", "right"):
        fn = func.lag if req.sort == "left" else func.lead
        extra = [
            fn(Token.form, k)
            .over(partition_by=Sentence.document_id, order_by=order)
            .label(f"n{k}")
            for k in (1, 2, 3)
        ]
    stmt = (
        select(Document.id, Sentence.idx, Token.start_cp, Token.end_cp)
        .select_from(Token)
        .join(Sentence, Sentence.id == Token.sentence_id)
        .join(Document, Document.id == Sentence.document_id)
    )
    stmt, cols = effective(stmt, layers)
    where = scope_clauses(corpus, filt, fields)
    if extra:  # neighbours are taken before filtering, inside each document
        inner = stmt.add_columns(
            Document.created_at.label("dc"),
            Token.idx.label("t"),
            Token.pos.label("spos"),
            cols["pos"].label("pos"),
            cols["dep"].label("dep"),
            cols["lemma"].label("lemma"),
            *extra,
        ).where(*where)
        sq = inner.subquery()
        conds = attr_clauses({k: sq.c[k] for k in ("pos", "dep", "lemma")}, constraints)
        if atom.pos:
            conds.append(sq.c.spos.in_(atom.pos))
        stmt = (
            select(
                sq.c.id, sq.c.idx, sq.c.start_cp, sq.c.end_cp, sq.c.n1, sq.c.n2, sq.c.n3
            )
            .where(*conds)
            .order_by(sq.c.dc, sq.c.id, sq.c.idx, sq.c.t)
        )
    else:
        where += attr_clauses(cols, constraints)
        if atom.pos:
            where.append(Token.pos.in_(atom.pos))
        stmt = stmt.where(*where).order_by(Document.created_at, Document.id, *order)
    rows = db.execute(stmt).all()
    if extra:
        rows.sort(key=lambda r: [(w or "").casefold() for w in r[4:7]])
    elif req.sort == "random":
        random.Random(req.seed or 0).shuffle(rows)
    counts = Counts(
        len(rows), len({(r[0], r[1]) for r in rows}), len({r[0] for r in rows}), True
    )
    lo = (page - 1) * page_size
    return SearchResult(
        counts, _hits(db, rows[lo : lo + page_size], req.context), page, page_size
    )


def _hits(db, rows, ctx):
    doc_ids = {r[0] for r in rows}
    texts = {
        d.id: Path(d.text_path).read_text(encoding="utf-8")
        for d in db.scalars(select(Document).where(Document.id.in_(doc_ids)))
    }
    spans = {}
    if ctx.unit == "sentence" and rows:
        for doc, idx, a, b in db.execute(
            select(
                Sentence.document_id, Sentence.idx, Sentence.start_cp, Sentence.end_cp
            ).where(
                Sentence.document_id.in_(doc_ids),
                Sentence.idx.in_({r[1] for r in rows}),
            )
        ):
            spans[(doc, idx)] = (a, b)
    hits = []
    for doc, n, start, end, *_ in rows:
        text = texts[doc]
        if ctx.unit == "sentence":
            a, b = spans[(doc, n)]
            left, right = text[a:start], text[end:b]
        elif ctx.unit == "paragraph":
            left = text[max(0, start - PARA_MAX) : start].rsplit("\n", 1)[-1]
            right = text[end : end + PARA_MAX].split("\n", 1)[0]
        else:
            left, right = (
                text[max(0, start - ctx.size) : start],
                text[end : end + ctx.size],
            )
        hits.append(
            Hit(
                f"{doc}:{start}-{end}",
                str(doc),
                n,
                start,
                end,
                left,
                text[start:end],
                right,
            )
        )
    return hits


def frequency(db, corpus, filt, fields, unit, layers, pos_tags, top, min_freq):
    """Frequency of effective POS tags or deprels in a scope → (rows, row_count, totals); one row per value
    with frequency and document frequency. Tokens without a value are not listed but count in the total."""
    stmt = (
        select()
        .select_from(Token)
        .join(Sentence, Sentence.id == Token.sentence_id)
        .join(Document, Document.id == Sentence.document_id)
    )
    stmt, cols = effective(stmt, layers)
    value = cols["pos" if unit == "pos" else "dep"]
    where = [*scope_clauses(corpus, filt, fields), value.is_not(None)]
    if pos_tags:
        where.append(cols["pos"].in_(pos_tags))
    stmt = (
        stmt.add_columns(value, func.count(), func.count(Document.id.distinct()))
        .where(*where)
        .group_by(
            text("1")
        )  # the CASE carries bind parameters, so it cannot be repeated
        .having(func.count() >= min_freq)
    )
    counts = sorted(db.execute(stmt).all(), key=lambda r: (-r[1], r[0]))
    docs, sentences, tokens = db.execute(
        select(
            func.count(),
            func.coalesce(func.sum(Document.sentence_count), 0),
            func.coalesce(func.sum(Document.token_count), 0),
        ).where(*scope_clauses(corpus, filt, fields))
    ).one()
    totals = {"tokens": int(tokens), "sentences": int(sentences), "documents": docs}
    return counts[:top], len(counts), totals


def layer_tokens(db, document_ids, layers):
    """Effective tokens of documents: {document_id: {sentence_index: [(start, end, form, pos, lemma, head, deprel)]}}."""
    stmt = (
        select(
            Sentence.document_id, Sentence.idx, Token.start_cp, Token.end_cp, Token.form
        )
        .select_from(Token)
        .join(Sentence, Sentence.id == Token.sentence_id)
    )
    stmt, cols = effective(stmt, layers)
    stmt = stmt.add_columns(
        cols["pos"], cols["lemma"], cols["head"], cols["dep"]
    ).where(Sentence.document_id.in_([UUID(str(d)) for d in document_ids]))
    out = {}
    for doc, idx, *tok in db.execute(
        stmt.order_by(Sentence.document_id, Sentence.idx, Token.idx)
    ):
        out.setdefault(doc, {}).setdefault(idx, []).append(tok)
    return out


# ---------------------------------------------------------------- P5: spans, relations, alignments


def span_key(document_id, start, end) -> str:
    return f"{document_id}:{start}-{end}"


def parse_span_key(key: str) -> tuple[UUID, int, int]:
    doc, _, rng = key.rpartition(":")
    a, _, b = rng.partition("-")
    return UUID(doc), int(a), int(b)


def relation_key(from_key: str, to_key: str) -> str:
    return f"{from_key}>{to_key}"


def sentence_key(document_id, sentence_index) -> str:
    return f"{document_id}:{sentence_index}"


def pair_key(src_doc, src_idx, tgt_doc, tgt_idx) -> str:
    return f"{src_doc}:{src_idx}>{tgt_doc}:{tgt_idx}"


def _adjudications(db, layer, kind) -> dict:
    return dict(
        db.execute(
            select(Adjudication.target_key, Adjudication.final).where(
                Adjudication.layer_id == layer.id, Adjudication.target_kind == kind
            )
        ).all()
    )


def label_tree(db, label_set_id) -> dict:
    """{label id: {"name", "parent"}} of a label set."""
    s = db.get(LabelSet, label_set_id) if label_set_id else None
    return {
        x["id"]: {"name": x.get("name", x["id"]), "parent": x.get("parent")}
        for x in (s.labels if s else [])
    }


def resolve_labels(db, layer, path) -> set[str]:
    """`[A]` / `[A:B]` → label ids: the label matching the last element (id or name) and its descendants;
    with two elements the first is the layer name, the label set name or an ancestor label."""
    tree = label_tree(db, layer.label_set_id)
    set_name = db.scalar(select(LabelSet.name).where(LabelSet.id == layer.label_set_id))

    def find(x):
        return [k for k, v in tree.items() if x in (k, v["name"])]

    def ancestors(k):
        seen = []
        while (k := tree.get(k, {}).get("parent")) and k not in seen:
            seen.append(k)
        return seen

    *head, last = path
    found = find(last)
    if head:
        outer = head[0]
        if outer not in (layer.name, set_name):
            parents = set(find(outer))
            found = [k for k in found if parents & set(ancestors(k))]
    if not found:
        raise ApiError(
            422, "INVALID_LABEL", f"片段层 {layer.name} 的标签集中没有 {':'.join(path)}"
        )
    return {k for k in tree if k in found or set(found) & set(ancestors(k))}


def _attrs_match(attrs, wanted) -> bool:
    return all(str((attrs or {}).get(k)) in values for k, values in wanted.items())


def _span_dict(s) -> dict:
    return {
        "id": s.id,
        "document_id": s.document_id,
        "sentence_index": s.sentence_index,
        "start_cp": s.start_cp,
        "end_cp": s.end_cp,
        "label": s.label,
        "attrs": s.attrs or {},
    }


def annotator_spans(db, layer, annotators=None, document_ids=None, statuses=HUMAN):
    """Span rows of the layer (optionally of some annotators / documents / statuses)."""
    stmt = select(SpanAnnotation).where(SpanAnnotation.layer_id == layer.id)
    if annotators is not None:
        stmt = stmt.where(SpanAnnotation.annotator_id.in_(list(annotators)))
    if document_ids is not None:
        stmt = stmt.where(SpanAnnotation.document_id.in_(list(document_ids)))
    if statuses is not None:
        stmt = stmt.where(SpanAnnotation.status.in_(statuses))
    return db.scalars(
        stmt.order_by(
            SpanAnnotation.document_id, SpanAnnotation.start_cp, SpanAnnotation.id
        )
    ).all()


def effective_spans(db, layer, document_ids=None, labels=None, attrs=None) -> list:
    """Effective spans [{id, document_id, sentence_index, start_cp, end_cp, label, attrs}] by document and
    position; labels (ids) and attrs ({key: values}) filter them."""
    if layer.mode != "multi":
        stmt = select(SpanAnnotation).where(
            SpanAnnotation.layer_id == layer.id, SpanAnnotation.status.in_(HUMAN)
        )
        if document_ids is not None:
            stmt = stmt.where(SpanAnnotation.document_id.in_(list(document_ids)))
        if labels is not None:
            stmt = stmt.where(SpanAnnotation.label.in_(list(labels)))
        for key, values in (attrs or {}).items():
            stmt = stmt.where(SpanAnnotation.attrs[key].astext.in_(list(values)))
        rows = db.scalars(
            stmt.order_by(
                SpanAnnotation.document_id, SpanAnnotation.start_cp, SpanAnnotation.id
            )
        ).all()
        return [_span_dict(s) for s in rows]
    by_key = defaultdict(lambda: defaultdict(dict))
    sample = {}
    for s in annotator_spans(db, layer, layer.annotators, document_ids):
        k = span_key(s.document_id, s.start_cp, s.end_cp)
        by_key[k][s.annotator_id][s.label] = s
        sample.setdefault(k, s)
    out = []
    adjudicated = _adjudications(db, layer, "span")
    for k, final in adjudicated.items():
        doc, a, b = parse_span_key(k)
        if final.get("label") and (document_ids is None or doc in set(document_ids)):
            first = sample.get(k)
            out.append(
                {
                    "id": first.id if first else None,
                    "document_id": doc,
                    "sentence_index": first.sentence_index if first else None,
                    "start_cp": a,
                    "end_cp": b,
                    "label": final["label"],
                    "attrs": final.get("attrs") or {},
                }
            )
    n = len(layer.annotators)
    for k, per in by_key.items():
        if k in adjudicated or len(per) != n:
            continue
        label_sets = [frozenset(v) for v in per.values()]
        if len(set(label_sets)) != 1:
            continue
        for label in sorted(label_sets[0]):
            out.append(_span_dict(next(iter(per.values()))[label]))
    out = [
        s
        for s in out
        if (labels is None or s["label"] in labels)
        and _attrs_match(s["attrs"], attrs or {})
    ]
    out.sort(key=lambda s: (str(s["document_id"]), s["start_cp"], s["end_cp"]))
    return out


def effective_relations(db, layer, spans=None, endpoints=False) -> list:
    """Effective relations of a relation layer → [{id, label, from: span, to: span}], endpoints among the
    effective spans of the base layer (`spans`, computed when omitted). endpoints=True (exports): a relation
    whose endpoint span is not effective is kept with that span row, marked "effective": False."""
    base = db.get(AnnotationLayer, layer.base_layer_id)
    if base is None:
        return []
    if spans is None:
        spans = effective_spans(db, eff_layer(base))
    by_extent = {}
    for s in spans:
        by_extent.setdefault(span_key(s["document_id"], s["start_cp"], s["end_cp"]), s)
    f, t = aliased(SpanAnnotation), aliased(SpanAnnotation)
    stmt = (
        select(RelationAnnotation, f, t)
        .join(f, f.id == RelationAnnotation.from_span_id)
        .join(t, t.id == RelationAnnotation.to_span_id)
        .where(
            RelationAnnotation.layer_id == layer.id,
            RelationAnnotation.status.in_(HUMAN),
        )
        .order_by(RelationAnnotation.id)
    )
    if layer.mode == "multi":
        stmt = stmt.where(RelationAnnotation.annotator_id.in_(list(layer.annotators)))
    per = defaultdict(lambda: defaultdict(set))
    first, rows = {}, {}
    for r, a, b in db.execute(stmt).all():
        ka = span_key(a.document_id, a.start_cp, a.end_cp)
        kb = span_key(b.document_id, b.start_cp, b.end_cp)
        k = relation_key(ka, kb)
        per[k][r.annotator_id].add(r.label)
        first.setdefault((k, r.label), r.id)
        rows.setdefault(ka, a)
        rows.setdefault(kb, b)
    chosen = []
    if layer.mode != "multi":
        chosen = [
            (k, label) for k, v in per.items() for ls in v.values() for label in ls
        ]
    else:
        adjudicated = _adjudications(db, layer, "relation")
        for k, final in adjudicated.items():
            if final.get("label"):
                chosen.append((k, final["label"]))
        for k, v in per.items():
            sets = [frozenset(x) for x in v.values()]
            if (
                k not in adjudicated
                and len(v) == len(layer.annotators)
                and len(set(sets)) == 1
            ):
                chosen += [(k, label) for label in sorted(sets[0])]

    def end(key):
        if key in by_extent:
            return by_extent[key]
        if endpoints and key in rows:
            return {
                **_span_dict(rows[key]),
                "status": rows[key].status,
                "effective": False,
            }
        return None

    out = []
    for k, label in chosen:
        a, _, b = k.partition(">")
        if end(a) and end(b):
            out.append(
                {
                    "id": first.get((k, label)),
                    "label": label,
                    "from": end(a),
                    "to": end(b),
                }
            )
    out.sort(
        key=lambda r: (
            str(r["from"]["document_id"]),
            r["from"]["start_cp"],
            r["to"]["start_cp"],
        )
    )
    return out


def _pairs_of(rows):
    """Alignment rows → {pair key: {"pair": (src doc, src idx, tgt doc, tgt idx), "links": set, "score"}}."""
    out = {}
    for r in rows:
        pk = pair_key(
            r.src_document_id,
            r.src_sentence_index,
            r.tgt_document_id,
            r.tgt_sentence_index,
        )
        entry = out.setdefault(
            pk,
            {
                "pair": (
                    r.src_document_id,
                    r.src_sentence_index,
                    r.tgt_document_id,
                    r.tgt_sentence_index,
                ),
                "links": set(),
                "score": None,
                "has_pair_row": False,
            },
        )
        if r.src_tokens:
            entry["links"].add(
                (tuple(sorted(r.src_tokens)), tuple(sorted(r.tgt_tokens)))
            )
        else:
            entry["has_pair_row"] = True
            entry["score"] = r.score
    return out


def _alignment_view(entry) -> dict:
    sd, si, td, ti = entry["pair"]
    return {
        "src_document_id": sd,
        "src_sentence_index": si,
        "tgt_document_id": td,
        "tgt_sentence_index": ti,
        "links": sorted(entry["links"]),
        "score": entry["score"],
    }


def effective_alignments(db, layer, src_document_ids=None) -> list:
    """Effective sentence pairs [{src_document_id, src_sentence_index, tgt_document_id, tgt_sentence_index,
    links: [(src tokens, tgt tokens)], score}] in source order. A pair is effective when its pair row is, or (word
    layers) when it has effective links; links are those of effective link rows."""
    stmt = select(AlignmentAnnotation).where(
        AlignmentAnnotation.layer_id == layer.id, effective_status(AlignmentAnnotation)
    )
    if src_document_ids is not None:
        stmt = stmt.where(
            AlignmentAnnotation.src_document_id.in_(list(src_document_ids))
        )
    if layer.mode != "multi":
        pairs = _pairs_of(db.scalars(stmt).all())
        out = [_alignment_view(e) for e in pairs.values()]
    else:
        out = _multi_alignments(
            db,
            layer,
            db.scalars(
                stmt.where(AlignmentAnnotation.annotator_id.in_(list(layer.annotators)))
            ).all(),
            src_document_ids,
        )
    out.sort(
        key=lambda p: (
            str(p["src_document_id"]),
            p["src_sentence_index"],
            str(p["tgt_document_id"]),
            p["tgt_sentence_index"],
        )
    )
    return out


def _multi_alignments(db, layer, rows, src_document_ids):
    """Consensus per source sentence (its set of target sentences) and, in word layers, per pair (its links);
    adjudications decide where they exist."""
    by_annotator = defaultdict(list)
    for r in rows:
        by_annotator[r.annotator_id].append(r)
    pairs = {a: _pairs_of(rs) for a, rs in by_annotator.items()}
    n = len(layer.annotators)
    targets = defaultdict(dict)  # src key → annotator → frozenset of (tgt doc, tgt idx)
    for a, ps in pairs.items():
        for e in ps.values():
            sd, si, td, ti = e["pair"]
            targets[sentence_key(sd, si)].setdefault(a, set()).add((td, ti))
    adjudicated = _adjudications(db, layer, "alignment")
    chosen = []  # (src doc, src idx, tgt doc, tgt idx)
    for sk, final in adjudicated.items():
        if ">" in sk:
            continue
        doc, _, idx = sk.rpartition(":")
        for td, ti in final.get("tgt") or []:
            chosen.append((UUID(doc), int(idx), UUID(str(td)), int(ti)))
    for sk, per in targets.items():
        if sk in adjudicated or len(per) != n:
            continue
        sets = [frozenset(v) for v in per.values()]
        if len(set(sets)) == 1:
            doc, _, idx = sk.rpartition(":")
            chosen += [
                (UUID(doc), int(idx), td, ti) for td, ti in sorted(sets[0], key=str)
            ]
    out = []
    for sd, si, td, ti in chosen:
        if src_document_ids is not None and sd not in set(src_document_ids):
            continue
        pk = pair_key(sd, si, td, ti)
        if pk in adjudicated:
            links = {
                (tuple(sorted(x["src"])), tuple(sorted(x["tgt"])))
                for x in adjudicated[pk].get("links") or []
            }
        else:
            sets = [
                frozenset(ps[pk]["links"]) if pk in ps else frozenset()
                for ps in pairs.values()
            ]
            links = set(sets[0]) if len(pairs) == n and len(set(sets)) == 1 else set()
        score = next((ps[pk]["score"] for ps in pairs.values() if pk in ps), None)
        out.append(
            _alignment_view({"pair": (sd, si, td, ti), "links": links, "score": score})
        )
    return out


def sentence_of(db, document_id, cps) -> dict:
    """{code point: sentence index} of the sentences holding each code point of a document."""
    rows = db.execute(
        select(Sentence.idx, Sentence.start_cp, Sentence.end_cp)
        .where(Sentence.document_id == document_id)
        .order_by(Sentence.idx)
    ).all()
    out = {}
    for cp in cps:
        hit = next((i for i, a, b in rows if a <= cp < b), None)
        if hit is None:  # between sentences: the next one
            hit = next((i for i, a, _ in rows if a >= cp), rows[-1][0] if rows else 0)
        out[cp] = hit
    return out


def _scope_documents(db, corpus, filt, fields):
    return db.execute(
        select(Document.id, Document.created_at)
        .where(*scope_clauses(corpus, filt, fields))
        .order_by(Document.created_at, Document.id)
    ).all()


def scope_spans(db, corpus, filt, fields, layer, constraint) -> list:
    """Effective spans matching a `#spans` constraint inside a scope, in corpus order, each with
    sentence_index filled in."""
    docs = _scope_documents(db, corpus, filt, fields)
    order = {d: n for n, (d, _) in enumerate(docs)}
    labels = resolve_labels(db, layer, constraint["path"])
    spans = effective_spans(db, layer, list(order), labels, constraint["attrs"])
    missing = defaultdict(set)
    for s in spans:
        if s["sentence_index"] is None:
            missing[s["document_id"]].add(s["start_cp"])
    for doc, cps in missing.items():
        found = sentence_of(db, doc, cps)
        for s in spans:
            if s["document_id"] == doc and s["sentence_index"] is None:
                s["sentence_index"] = found[s["start_cp"]]
    spans.sort(key=lambda s: (order[s["document_id"]], s["start_cp"], s["end_cp"]))
    return spans


def span_search(db, corpus, filt, fields, layer, constraint, req, page, page_size):
    """Hits of a pure span query: one per effective span, hit = the span; counts, sort and context as
    cwb.search (left / right sort compare the 40 code points before / after the span)."""
    spans = scope_spans(db, corpus, filt, fields, layer, constraint)
    rows = [
        (s["document_id"], s["sentence_index"], s["start_cp"], s["end_cp"])
        for s in spans
    ]
    if req.sort in ("left", "right"):
        texts = _texts(db, {r[0] for r in rows})
        if req.sort == "left":
            rows.sort(
                key=lambda r: texts[r[0]][max(0, r[2] - 40) : r[2]][::-1].casefold()
            )
        else:
            rows.sort(key=lambda r: texts[r[0]][r[3] : r[3] + 40].casefold())
    elif req.sort == "random":
        random.Random(req.seed or 0).shuffle(rows)
    counts = Counts(
        len(rows), len({(r[0], r[1]) for r in rows}), len({r[0] for r in rows}), True
    )
    lo = (page - 1) * page_size
    return SearchResult(
        counts, _hits(db, rows[lo : lo + page_size], req.context), page, page_size
    )


def _texts(db, doc_ids) -> dict:
    return {
        d.id: Path(d.text_path).read_text(encoding="utf-8")
        for d in db.scalars(select(Document).where(Document.id.in_(list(doc_ids))))
    }


def filter_span_tokens(db, layer, constraint, keys) -> set:
    """Candidate (document_id str, sentence_index, token_index 0-based) keys whose token lies inside an
    effective span matching the constraint."""
    keys = list(keys)
    if not keys:
        return set()
    labels = resolve_labels(db, layer, constraint["path"])
    docs = {UUID(k[0]) for k in keys}
    by_doc = defaultdict(list)
    for s in effective_spans(db, layer, docs, labels, constraint["attrs"]):
        by_doc[str(s["document_id"])].append((s["start_cp"], s["end_cp"]))
    out = set()
    for i in range(0, len(keys), BATCH):
        part = [k for k in keys[i : i + BATCH] if k[0] in by_doc]
        if not part:
            continue
        rows = db.execute(
            select(
                Sentence.document_id,
                Sentence.idx,
                Token.idx,
                Token.start_cp,
                Token.end_cp,
            )
            .join(Token, Token.sentence_id == Sentence.id)
            .where(
                tuple_(Sentence.document_id, Sentence.idx, Token.idx).in_(
                    [(UUID(d), s, t) for d, s, t in part]
                )
            )
        ).all()
        for d, s, t, a, b in rows:
            if any(x <= a and b <= y for x, y in by_doc[str(d)]):
                out.add((str(d), s, t))
    return out


def span_positions(db, corpus, filt, fields, layer, constraint) -> list:
    """(document id str, token offset in the document) of the first token of each matching effective span, for
    engine.stats.distribution."""
    spans = scope_spans(db, corpus, filt, fields, layer, constraint)
    out = []
    by_doc = defaultdict(list)
    for s in spans:
        by_doc[s["document_id"]].append(s["start_cp"])
    for doc, starts in by_doc.items():
        toks = (
            db.execute(
                select(Token.end_cp)
                .join(Sentence, Sentence.id == Token.sentence_id)
                .where(Sentence.document_id == doc)
                .order_by(Sentence.idx, Token.idx)
            )
            .scalars()
            .all()
        )
        for cp in starts:
            k = next(
                (n for n, end in enumerate(toks) if end > cp), max(len(toks) - 1, 0)
            )
            out.append((str(doc), k))
    return out


def scope_totals(db, corpus, filt, fields) -> dict:
    docs, sentences, tokens = db.execute(
        select(
            func.count(),
            func.coalesce(func.sum(Document.sentence_count), 0),
            func.coalesce(func.sum(Document.token_count), 0),
        ).where(*scope_clauses(corpus, filt, fields))
    ).one()
    return {"tokens": int(tokens), "sentences": int(sentences), "documents": docs}


def label_frequency(db, corpus, filt, fields, layer, unit, top, min_freq):
    """span_label / relation_label frequency in a scope → (rows [(label, freq, doc freq)], row count, totals)."""
    docs = {d for d, _ in _scope_documents(db, corpus, filt, fields)}
    counts, doc_sets = defaultdict(int), defaultdict(set)
    if unit == "span_label":
        items = [
            (s["label"], s["document_id"]) for s in effective_spans(db, layer, docs)
        ]
    else:
        items = [
            (r["label"], r["from"]["document_id"])
            for r in effective_relations(db, layer)
            if r["from"]["document_id"] in docs
        ]
    for label, doc in items:
        counts[label] += 1
        doc_sets[label].add(doc)
    rows = sorted(
        ((k, v, len(doc_sets[k])) for k, v in counts.items() if v >= min_freq),
        key=lambda r: (-r[1], r[0]),
    )
    return rows[:top], len(rows), scope_totals(db, corpus, filt, fields)


def spans_json(constraint) -> str:
    return json.dumps(
        {
            "path": list(constraint["path"]),
            "attrs": {k: list(v) for k, v in constraint["attrs"].items()},
        },
        ensure_ascii=False,
    )


def effective_status_value(row) -> bool:
    """Python form of effective_status for one loaded row."""
    return row.status in HUMAN or (row.status == "suggested" and row.source == "system")
