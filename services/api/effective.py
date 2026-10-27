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
"""

import random
from pathlib import Path
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
    select,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import aliased

from engine.model import Counts, Hit, SearchResult
from services.api.access import require_project
from services.api.errors import ApiError
from services.api.metadata import filter_clause
from services.api.models import Annotation, AnnotationLayer, Document, Sentence, Token

HUMAN = ("confirmed", "modified")
PARA_MAX = 2000  # as engine.cwb
BATCH = 20000


def check_layers(db, layers, corpus, user) -> dict:
    """SearchRequest.layers → {"pos": id|None, "dep": id|None}; each layer must be of that kind, on this corpus
    and readable by the user."""
    out = {"pos": None, "dep": None}
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
        out[kind] = layer.id
    return out


def _join_layer(stmt, layer_id):
    a = aliased(Annotation)
    stmt = stmt.outerjoin(
        a,
        and_(
            a.layer_id == layer_id,
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
