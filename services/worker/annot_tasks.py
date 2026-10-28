"""P5 jobs (contracts/p5.md §三): span / relation / alignment pre-annotation and brat / JSON / TMX / XLSX exports.

Pre-annotation works per sentence (alignment: per source sentence / sentence pair). Without `sentence_range`
a run only fills sentences that have no rows in the layer yet, so a retried job continues where it stopped;
with `sentence_range` those sentences are redone: their suggested rows are replaced, reviewed rows stay and
identical suggestions are not added again. In multi mode every annotator gets the same suggestions.

Chat model calls carry up to BATCH sentences; an answer that is not a JSON array is asked again once, then the
batch's sentences are recorded in progress.failed_sentences (also when the model returns an HTTP error). Items
are checked against the sentence text (engine.annotate / engine.align.clean_links); invalid ones are dropped and
counted in the job result.
"""

import io
import json
import uuid
import zipfile
from collections import defaultdict
from datetime import datetime
from pathlib import Path

from lxml import etree
from openpyxl import Workbook
from openpyxl.cell import WriteOnlyCell
from openpyxl.styles import Font
from sqlalchemy import delete, func, insert, select, tuple_
from sqlalchemy.orm import aliased

from engine import align
from engine import annotate as ann
from engine.kb import embed
from services.api import effective as eff
from services.api.annotations import refresh_progress
from services.api.annotators import layer_annotators
from services.api.db import session, transaction
from services.api.models import (
    AlignmentAnnotation,
    AnnotationLayer,
    Corpus,
    Document,
    KbDocument,
    LabelSet,
    RelationAnnotation,
    Sentence,
    SentenceAlignment,
    SpanAnnotation,
    Token,
    User,
)
from services.api.storage import export_path
from services.worker import llm
from services.worker.main import Cancelled, JobFailed, log

BATCH = 10
GUIDELINE_CHARS = 2000
FAILED_KEEP = 500
EMBED_SOURCE = "model:minilm"

SPAN_SYSTEM = "你是语言学标注助手。按给定标签集和标注规范在句子中标出片段。只输出 JSON 数组，不输出其他文字。"
SPAN_PROMPT = """标签集（label 只能用这些 id）：
{labels}
{guideline}
请标注下面每个句子。输出 JSON 数组，每个元素为 {{"id": 句子编号, "text": 片段原文（与句中字符完全一致）, "start": 片段在该句中的起始位置（从 0 起按字符计）, "end": 结束位置（不含）, "label": 标签 id, "attrs": {{}}}}。一个句子可有多个片段；没有可标注的片段时不要为它输出元素。

句子：
{sentences}"""
RELATION_SYSTEM = "你是语言学标注助手。按给定关系标签判断片段之间的有向关系。只输出 JSON 数组，不输出其他文字。"
RELATION_PROMPT = """关系标签（label 只能用这些 id）：
{labels}
{guideline}
下面每个句子列出了已标注的片段（编号从 1 起）。请找出片段之间成立的有向关系，输出 JSON 数组，每个元素为 {{"id": 句子编号, "from": 起点片段编号, "to": 终点片段编号, "label": 关系标签 id}}。没有关系时不要为该句输出元素。

{sentences}"""
WORD_SYSTEM = "你是双语词对齐助手。只输出 JSON 数组，不输出其他文字。"
WORD_PROMPT = """为下面每个句对做词级对齐。token 以“序号:词形”给出，序号从 1 起。输出 JSON 数组，每个元素为 {{"id": 句对编号, "src": [源语 token 序号…], "tgt": [目标语 token 序号…]}}，一个元素表示一组互译的词（可一对多、多对多）；标点和无对应的词不输出。

{pairs}"""


def _label_lines(labels):
    lines = []
    for k, v in labels.items():
        line = f"- {k}"
        if v.get("name") and v["name"] != k:
            line += f"（{v['name']}）"
        if v.get("description"):
            line += f"：{v['description']}"
        if v.get("parent"):
            line += f"（上级：{v['parent']}）"
        lines.append(line)
    return "\n".join(lines)


def _guideline(text):
    return f"\n标注规范摘录：\n{text}\n" if text else ""


class RequestError(str):
    """Error text of a failed model request (HTTP / connection), as opposed to an unusable answer."""


def _ask(system, prompt, run_label):
    """Model answer as a JSON array; one more request when it is not. Returns (items | None, error), the error
    a RequestError when the request itself failed."""
    error = ""
    for _ in (1, 2):
        try:
            answer = llm.chat(system, prompt, temperature=0)
        except JobFailed as e:
            if e.code == "MODEL_UNAVAILABLE":
                raise
            error = RequestError(e.message)
            log.info("%s: model request failed: %s", run_label, e.message[:200])
            continue
        try:
            return llm.json_array(answer), ""
        except JobFailed as e:
            error = e.message
            log.info("%s: model answer rejected: %s", run_label, e.message[:200])
    return None, error


# ---- layer info ----


def _layer_info(db, layer):
    labels = {}
    if layer.label_set_id:
        s = db.get(LabelSet, layer.label_set_id)
        labels = {x["id"]: x for x in s.labels}
    guideline = ""
    if layer.guideline_document_id:
        g = db.get(KbDocument, layer.guideline_document_id)
        if g is not None:
            text = g.body or ""
            if not text and g.text_path and Path(g.text_path).exists():
                text = Path(g.text_path).read_text(encoding="utf-8")
            guideline = text.strip()[:GUIDELINE_CHARS]
    return {
        "id": layer.id,
        "kind": layer.kind,
        "level": layer.level,
        "mode": layer.mode,
        "annotators": layer_annotators(layer),
        "created_by": layer.created_by,
        "corpus_id": layer.corpus_id,
        "tgt_corpus_id": layer.tgt_corpus_id,
        "base_layer_id": layer.base_layer_id,
        "labels": labels,
        "guideline": guideline,
    }


def _documents(db, corpus_id, ids):
    stmt = select(Document.id).where(Document.corpus_id == corpus_id)
    if ids:
        stmt = stmt.where(Document.id.in_([uuid.UUID(str(i)) for i in ids]))
    return db.scalars(stmt.order_by(Document.created_at, Document.id)).all()


def _sentences(db, doc_ids, rng):
    stmt = (
        select(Sentence.document_id, Sentence.idx, Sentence.start_cp, Sentence.text)
        .join(Document, Document.id == Sentence.document_id)
        .where(Sentence.document_id.in_(doc_ids))
        .order_by(Document.created_at, Sentence.document_id, Sentence.idx)
    )
    if rng:
        stmt = stmt.where(Sentence.idx >= rng["start"], Sentence.idx < rng["end"])
    return db.execute(stmt).all()


# ---- spans ----


def _span_batch(run, info, batch, model):
    texts = {n: s.text for n, s in enumerate(batch, 1)}
    prompt = SPAN_PROMPT.format(
        labels=_label_lines(info["labels"]),
        guideline=_guideline(info["guideline"]),
        sentences=json.dumps(
            [{"id": n, "text": t} for n, t in texts.items()], ensure_ascii=False
        ),
    )
    items, error = _ask(SPAN_SYSTEM, prompt, f"job {run.id}")
    if items is None:
        return None, 0, error
    found, dropped = ann.clean_spans(items, texts, info["labels"])
    return found, dropped, ""


def _write_spans(db, info, batch, found, model, redo):
    keys = [(s.document_id, s.idx) for s in batch]
    if redo:
        db.execute(
            delete(SpanAnnotation).where(
                SpanAnnotation.layer_id == info["id"],
                SpanAnnotation.status == "suggested",
                tuple_(SpanAnnotation.document_id, SpanAnnotation.sentence_index).in_(
                    keys
                ),
            )
        )
    kept = {
        (r.annotator_id, r.document_id, r.start_cp, r.end_cp, r.label)
        for r in db.scalars(
            select(SpanAnnotation).where(
                SpanAnnotation.layer_id == info["id"],
                tuple_(SpanAnnotation.document_id, SpanAnnotation.sentence_index).in_(
                    keys
                ),
            )
        )
    }
    rows = []
    for n, s in enumerate(batch, 1):
        for a, b, label, attrs in found.get(n, []):
            start, end = s.start_cp + a, s.start_cp + b
            for annotator in info["annotators"]:
                if (annotator, s.document_id, start, end, label) in kept:
                    continue
                rows.append(
                    {
                        "layer_id": info["id"],
                        "annotator_id": annotator,
                        "document_id": s.document_id,
                        "sentence_index": s.idx,
                        "start_cp": start,
                        "end_cp": end,
                        "label": label,
                        "attrs": attrs,
                        "model_label": label,
                        "model_attrs": attrs,
                        "source": model,
                        "status": "suggested",
                    }
                )
    if rows:
        db.execute(insert(SpanAnnotation), rows)
    return len(rows)


def _span_job(run, info, docs, rng):
    with session() as db:
        sentences = _sentences(db, docs, rng)
        done = set(
            db.execute(
                select(SpanAnnotation.document_id, SpanAnnotation.sentence_index)
                .where(SpanAnnotation.layer_id == info["id"])
                .distinct()
            ).all()
        )
    todo = [s for s in sentences if rng or (s.document_id, s.idx) not in done]
    model = f"model:{llm.model_id()}"
    stats = {"sentences": len(todo), "written": 0, "dropped": 0}
    failed, errors = [], []
    for i in range(0, len(todo), BATCH):
        run.progress(i, len(todo), "预标")
        batch = todo[i : i + BATCH]
        found, dropped, error = _span_batch(run, info, batch, model)
        if found is None:
            failed += batch
            errors.append(error)
            continue
        stats["dropped"] += dropped
        with transaction() as db:
            layer = db.get(AnnotationLayer, info["id"], with_for_update=True)
            if layer is None:
                raise JobFailed("LAYER_DELETED", "标注层已删除")
            stats["written"] += _write_spans(db, info, batch, found, model, bool(rng))
            refresh_progress(db, layer)
    return stats, failed, errors, llm.model_id()


# ---- relations ----


def _base_spans(db, info, docs):
    """{annotator group (tuple): {(doc, sentence idx): [span rows]}} of the base layer's non-rejected spans."""
    base = db.get(AnnotationLayer, info["base_layer_id"])
    if base is None:
        raise JobFailed("LAYER_DELETED", "片段层已删除")
    groups = (
        [(tuple(info["annotators"]), base.created_by)]
        if base.mode != "multi"
        else [((a,), a) for a in info["annotators"]]
    )
    out = {}
    for group, owner in groups:
        rows = db.scalars(
            select(SpanAnnotation)
            .where(
                SpanAnnotation.layer_id == base.id,
                SpanAnnotation.annotator_id == owner,
                SpanAnnotation.status != "rejected",
                SpanAnnotation.document_id.in_(docs),
            )
            .order_by(
                SpanAnnotation.document_id, SpanAnnotation.start_cp, SpanAnnotation.id
            )
        ).all()
        by_sentence = defaultdict(list)
        for r in rows:
            if r.sentence_index is not None:
                by_sentence[(r.document_id, r.sentence_index)].append(r)
        out[group] = by_sentence
    return out


def _relation_job(run, info, docs, rng):
    with session() as db:
        sentences = {(s.document_id, s.idx): s for s in _sentences(db, docs, rng)}
        groups = _base_spans(db, info, docs)
        f = aliased(SpanAnnotation)
        done = set(
            db.execute(
                select(f.document_id, f.sentence_index)
                .join(RelationAnnotation, RelationAnnotation.from_span_id == f.id)
                .where(RelationAnnotation.layer_id == info["id"])
                .distinct()
            ).all()
        )
    model = f"model:{llm.model_id()}"
    stats = {"sentences": 0, "written": 0, "dropped": 0}
    failed, errors = [], []
    work = []
    for group, by_sentence in groups.items():
        for key, spans in by_sentence.items():
            if key in sentences and len(spans) >= 2 and (rng or key not in done):
                work.append((group, sentences[key], spans))
    stats["sentences"] = len(work)
    for i in range(0, len(work), BATCH):
        run.progress(i, len(work), "预标")
        batch = work[i : i + BATCH]
        blocks = []
        for n, (_, s, spans) in enumerate(batch, 1):
            listed = "\n".join(
                f"  {k}. 「{s.text[r.start_cp - s.start_cp : r.end_cp - s.start_cp]}」 {r.label}"
                for k, r in enumerate(spans, 1)
            )
            blocks.append(f"句子 {n}：{s.text}\n片段：\n{listed}")
        prompt = RELATION_PROMPT.format(
            labels=_label_lines(info["labels"]),
            guideline=_guideline(info["guideline"]),
            sentences="\n\n".join(blocks),
        )
        items, error = _ask(RELATION_SYSTEM, prompt, f"job {run.id}")
        if items is None:
            failed += [s for _, s, _ in batch]
            errors.append(error)
            continue
        found, dropped = ann.clean_relations(
            items, {n: len(sp) for n, (_, _, sp) in enumerate(batch, 1)}, info["labels"]
        )
        stats["dropped"] += dropped
        with transaction() as db:
            layer = db.get(AnnotationLayer, info["id"], with_for_update=True)
            if layer is None:
                raise JobFailed("LAYER_DELETED", "标注层已删除")
            span_ids = [r.id for _, _, sp in batch for r in sp]
            if rng:
                db.execute(
                    delete(RelationAnnotation).where(
                        RelationAnnotation.layer_id == info["id"],
                        RelationAnnotation.status == "suggested",
                        RelationAnnotation.from_span_id.in_(span_ids),
                    )
                )
            kept = set(
                db.execute(
                    select(
                        RelationAnnotation.annotator_id,
                        RelationAnnotation.from_span_id,
                        RelationAnnotation.to_span_id,
                        RelationAnnotation.label,
                    ).where(
                        RelationAnnotation.layer_id == info["id"],
                        RelationAnnotation.from_span_id.in_(span_ids),
                    )
                ).all()
            )
            rows = []
            for n, (group, _, spans) in enumerate(batch, 1):
                for a, b, label in found.get(n, []):
                    for annotator in group:
                        key = (annotator, spans[a].id, spans[b].id, label)
                        if key in kept:
                            continue
                        rows.append(
                            {
                                "layer_id": info["id"],
                                "annotator_id": annotator,
                                "from_span_id": spans[a].id,
                                "to_span_id": spans[b].id,
                                "label": label,
                                "model_label": label,
                                "source": model,
                                "status": "suggested",
                            }
                        )
            if rows:
                db.execute(insert(RelationAnnotation), rows)
            stats["written"] += len(rows)
            refresh_progress(db, layer)
    return stats, failed, errors, llm.model_id()


# ---- alignment ----


def _target_documents(db, info, sources):
    """{source document: target document} for documents without stored sentence alignments: same title, else
    the same position among the target corpus's remaining documents."""
    targets = db.execute(
        select(Document.id, Document.title)
        .where(Document.corpus_id == info["tgt_corpus_id"], Document.id.not_in(sources))
        .order_by(Document.created_at, Document.id)
    ).all()
    titles = {
        d: t
        for d, t in db.execute(
            select(Document.id, Document.title).where(Document.id.in_(sources))
        )
    }
    out, used = {}, set()
    for s in sources:
        match = next(
            (d for d, t in targets if t == titles.get(s) and d not in used), None
        )
        if match:
            out[s] = match
            used.add(match)
    rest = [d for d, _ in targets if d not in used]
    for s in [s for s in sources if s not in out]:
        if rest:
            out[s] = rest.pop(0)
    return out


def _stored_pairs(db, info, doc_id):
    src, tgt = aliased(Sentence), aliased(Sentence)
    return db.execute(
        select(src.idx, tgt.document_id, tgt.idx)
        .select_from(SentenceAlignment)
        .join(src, src.id == SentenceAlignment.src_sentence_id)
        .join(tgt, tgt.id == SentenceAlignment.tgt_sentence_id)
        .join(Document, Document.id == tgt.document_id)
        .where(src.document_id == doc_id, Document.corpus_id == info["tgt_corpus_id"])
        .order_by(src.idx, tgt.document_id, tgt.idx)
    ).all()


def _texts_of(db, doc_id):
    return [
        (i, t)
        for i, t in db.execute(
            select(Sentence.idx, Sentence.text)
            .where(Sentence.document_id == doc_id)
            .order_by(Sentence.idx)
        )
    ]


def _embed(texts):
    try:
        out = []
        for i in range(0, len(texts), embed.BATCH):
            out += embed.embed(texts[i : i + embed.BATCH])
        return out
    except embed.EmbedUnavailable as e:
        raise JobFailed("EMBED_UNAVAILABLE", str(e)) from e


def _sentence_alignment(run, info, docs, rng):
    """Pair rows for source sentences without rows (or in the range): stored alignments, else MiniLM
    candidates. Returns (pairs written, sources used)."""
    with session() as db:
        has_rows = set(
            db.execute(
                select(
                    AlignmentAnnotation.src_document_id,
                    AlignmentAnnotation.src_sentence_index,
                )
                .where(AlignmentAnnotation.layer_id == info["id"])
                .distinct()
            ).all()
        )
        stored = {d: _stored_pairs(db, info, d) for d in docs}
        pairing = _target_documents(db, info, [d for d in docs if not stored[d]])
    written, used = 0, set()
    for k, doc_id in enumerate(docs):
        run.progress(k, len(docs), "句级对齐")
        in_range = (
            (lambda i: rng["start"] <= i < rng["end"]) if rng else (lambda i: True)
        )
        if stored[doc_id]:
            pairs = [(si, td, ti, None, "system") for si, td, ti in stored[doc_id]]
            used.add("sentence_alignments")
        elif doc_id in pairing:
            with session() as db:
                src = _texts_of(db, doc_id)
                tgt = _texts_of(db, pairing[doc_id])
            vectors = _embed([t for _, t in src] + [t for _, t in tgt])
            matches = align.match_sentences(
                [t for _, t in src],
                [t for _, t in tgt],
                vectors[: len(src)],
                vectors[len(src) :],
            )
            pairs = [
                (src[i][0], pairing[doc_id], tgt[j][0], score, EMBED_SOURCE)
                for i, j, score in matches
            ]
            used.add("MiniLM")
        else:
            pairs = []
        pairs = [
            p
            for p in pairs
            if in_range(p[0]) and (rng or (doc_id, p[0]) not in has_rows)
        ]
        with transaction() as db:
            layer = db.get(AnnotationLayer, info["id"], with_for_update=True)
            if layer is None:
                raise JobFailed("LAYER_DELETED", "标注层已删除")
            if rng:
                db.execute(
                    delete(AlignmentAnnotation).where(
                        AlignmentAnnotation.layer_id == info["id"],
                        AlignmentAnnotation.status == "suggested",
                        AlignmentAnnotation.src_document_id == doc_id,
                        AlignmentAnnotation.src_sentence_index >= rng["start"],
                        AlignmentAnnotation.src_sentence_index < rng["end"],
                        func.cardinality(AlignmentAnnotation.src_tokens) == 0,
                    )
                )
            kept = set(
                db.execute(
                    select(
                        AlignmentAnnotation.annotator_id,
                        AlignmentAnnotation.src_sentence_index,
                        AlignmentAnnotation.tgt_document_id,
                        AlignmentAnnotation.tgt_sentence_index,
                    ).where(
                        AlignmentAnnotation.layer_id == info["id"],
                        AlignmentAnnotation.src_document_id == doc_id,
                        func.cardinality(AlignmentAnnotation.src_tokens) == 0,
                    )
                ).all()
            )
            rows = [
                {
                    "layer_id": info["id"],
                    "annotator_id": a,
                    "src_document_id": doc_id,
                    "src_sentence_index": si,
                    "tgt_document_id": td,
                    "tgt_sentence_index": ti,
                    "src_tokens": [],
                    "tgt_tokens": [],
                    "score": score,
                    "source": source,
                    "status": "suggested",
                }
                for si, td, ti, score, source in pairs
                for a in info["annotators"]
                if (a, si, td, ti) not in kept
            ]
            if rows:
                db.execute(insert(AlignmentAnnotation), rows)
            written += len(rows)
            refresh_progress(db, layer)
    return written, used


def _tokens_of(db, keys):
    out = defaultdict(list)
    for d, i, form in db.execute(
        select(Sentence.document_id, Sentence.idx, Token.form)
        .join(Token, Token.sentence_id == Sentence.id)
        .where(tuple_(Sentence.document_id, Sentence.idx).in_(list(keys)))
        .order_by(Sentence.document_id, Sentence.idx, Token.idx)
    ):
        out[(d, i)].append(form)
    return out


def _word_alignment(run, info, docs, rng):
    """Model word links for the layer's sentence pairs (pairs of the first annotator, not rejected) that have
    no links yet, or in the range."""
    A = AlignmentAnnotation
    with session() as db:
        stmt = select(
            A.src_document_id,
            A.src_sentence_index,
            A.tgt_document_id,
            A.tgt_sentence_index,
        ).where(
            A.layer_id == info["id"],
            A.annotator_id == info["annotators"][0],
            A.status != "rejected",
            func.cardinality(A.src_tokens) == 0,
            A.src_document_id.in_(docs),
        )
        if rng:
            stmt = stmt.where(
                A.src_sentence_index >= rng["start"], A.src_sentence_index < rng["end"]
            )
        pairs = db.execute(stmt.order_by(A.src_document_id, A.src_sentence_index)).all()
        linked = set(
            db.execute(
                select(
                    A.src_document_id,
                    A.src_sentence_index,
                    A.tgt_document_id,
                    A.tgt_sentence_index,
                )
                .where(A.layer_id == info["id"], func.cardinality(A.src_tokens) > 0)
                .distinct()
            ).all()
        )
    order = {d: n for n, d in enumerate(docs)}
    todo = sorted(
        (tuple(p) for p in pairs if rng or tuple(p) not in linked),
        key=lambda p: (order[p[0]], p[1], str(p[2]), p[3]),
    )
    model = f"model:{llm.model_id()}"
    stats = {"pairs": len(todo), "written": 0, "dropped": 0}
    failed, errors = [], []
    for i in range(0, len(todo), BATCH):
        run.progress(i, len(todo), "词级对齐")
        batch = todo[i : i + BATCH]
        with session() as db:
            toks = _tokens_of(
                db, {(p[0], p[1]) for p in batch} | {(p[2], p[3]) for p in batch}
            )
        blocks = [
            {
                "id": n,
                "src": " ".join(
                    f"{k}:{w}" for k, w in enumerate(toks[(p[0], p[1])], 1)
                ),
                "tgt": " ".join(
                    f"{k}:{w}" for k, w in enumerate(toks[(p[2], p[3])], 1)
                ),
            }
            for n, p in enumerate(batch, 1)
        ]
        items, error = _ask(
            WORD_SYSTEM,
            WORD_PROMPT.format(pairs=json.dumps(blocks, ensure_ascii=False, indent=0)),
            f"job {run.id}",
        )
        if items is None:
            failed += batch
            errors.append(error)
            continue
        by_id = defaultdict(list)
        for item in items:
            if isinstance(item, dict) and isinstance(item.get("id"), int):
                by_id[item["id"]].append(item)
            else:
                stats["dropped"] += 1
        with transaction() as db:
            layer = db.get(AnnotationLayer, info["id"], with_for_update=True)
            if layer is None:
                raise JobFailed("LAYER_DELETED", "标注层已删除")
            rows = []
            for n, p in enumerate(batch, 1):
                links = align.clean_links(
                    by_id.get(n, []), len(toks[(p[0], p[1])]), len(toks[(p[2], p[3])])
                )
                stats["dropped"] += len(by_id.get(n, [])) - len(links)
                where = [
                    A.layer_id == info["id"],
                    A.src_document_id == p[0],
                    A.src_sentence_index == p[1],
                    A.tgt_document_id == p[2],
                    A.tgt_sentence_index == p[3],
                    func.cardinality(A.src_tokens) > 0,
                ]
                if rng:
                    db.execute(delete(A).where(*where, A.status == "suggested"))
                kept = {
                    (a, tuple(s), tuple(t))
                    for a, s, t in db.execute(
                        select(A.annotator_id, A.src_tokens, A.tgt_tokens).where(*where)
                    )
                }
                for s_tok, t_tok in links:
                    for a in info["annotators"]:
                        if (a, s_tok, t_tok) in kept:
                            continue
                        rows.append(
                            {
                                "layer_id": info["id"],
                                "annotator_id": a,
                                "src_document_id": p[0],
                                "src_sentence_index": p[1],
                                "tgt_document_id": p[2],
                                "tgt_sentence_index": p[3],
                                "src_tokens": list(s_tok),
                                "tgt_tokens": list(t_tok),
                                "source": model,
                                "status": "suggested",
                            }
                        )
            if rows:
                db.execute(insert(A), rows)
            stats["written"] += len(rows)
            refresh_progress(db, layer)
    return stats, [(p[0], p[1]) for p in failed], errors


def _alignment_job(run, info, docs, rng):
    written, used = _sentence_alignment(run, info, docs, rng)
    stats = {"pairs_written": written}
    failed, errors, model = [], [], " + ".join(sorted(used)) or "none"
    if info["level"] == "word":
        word, failed, errors = _word_alignment(run, info, docs, rng)
        stats.update({"word_" + k: v for k, v in word.items()})
        model = f"{model} + {llm.model_id()}"
    return stats, failed, errors, model


# ---- entry ----


def run_preannotate_p5(run):
    layer_id = uuid.UUID(run.params["layer_id"])
    rng = run.params.get("sentence_range")
    with transaction() as db:
        layer = db.get(AnnotationLayer, layer_id, with_for_update=True)
        if not layer:
            raise JobFailed("LAYER_DELETED", "标注层已删除")
        layer.status, layer.error, layer.job_id = "preannotating", None, run.id
        info = _layer_info(db, layer)
        ids = run.params.get("document_ids") or layer.document_ids
        docs = _documents(db, layer.corpus_id, ids)
    try:
        if info["kind"] == "span":
            stats, failed, errors, model = _span_job(run, info, docs, rng)
        elif info["kind"] == "relation":
            stats, failed, errors, model = _relation_job(run, info, docs, rng)
        else:
            stats, failed, errors, model = _alignment_job(run, info, docs, rng)
        failed_keys = [
            {"document_id": str(f[0]), "sentence_index": f[1]}
            if isinstance(f, tuple)
            else {"document_id": str(f.document_id), "sentence_index": f.idx}
            for f in failed
        ]
        attempted = stats.get("sentences", stats.get("word_pairs", 0))
        if (
            errors
            and all(isinstance(e, RequestError) for e in errors)
            and len(failed_keys) >= attempted > 0
        ):  # the model could not be reached at all
            raise JobFailed(
                "MODEL_ERROR", f"所有句子的模型调用都失败：{errors[-1][:300]}"
            )
        with transaction() as db:
            run.lock(db)
            layer = db.get(AnnotationLayer, layer_id, with_for_update=True)
            if not layer:
                raise JobFailed("LAYER_DELETED", "标注层已删除")
            refresh_progress(db, layer)
            layer.progress = {
                **layer.progress,
                "failed_sentences": failed_keys[:FAILED_KEEP],
            }
            layer.status, layer.source_model = "ready", model
            run.succeed(
                db,
                {
                    "layer_id": str(layer_id),
                    "documents": len(docs),
                    **stats,
                    "failed_sentences": len(failed_keys),
                    "total": layer.progress["total"],
                },
            )
    except BaseException as e:
        message = (
            "预标已取消"
            if isinstance(e, Cancelled)
            else getattr(e, "message", str(e))[:500]
        )
        with transaction() as db:
            layer = db.get(AnnotationLayer, layer_id, with_for_update=True)
            if layer:
                layer.status, layer.error = "failed", message
        raise


# ---- exports ----


def _safe(name, limit=60):
    return (
        "".join(c if c.isalnum() or c in "-_" else "_" for c in name)[:limit] or "layer"
    )


def _stamp():
    return f"{datetime.now():%Y%m%d-%H%M}"


def _finish(run, filename, extra):
    with transaction() as db:
        run.lock(db)
        run.succeed(db, {**extra, "filename": filename})


def _notice(db, *corpus_ids):
    """Source / license lines of the corpora (services.worker.tasks.source_notice); [] when none has them."""
    from services.worker.tasks import source_notice  # tasks imports this module

    return source_notice(db, corpus_ids)


def _export_docs(db, layer, params):
    ids = params.get("document_ids") or layer.document_ids
    stmt = select(Document).where(Document.corpus_id == layer.corpus_id)
    if ids:
        stmt = stmt.where(Document.id.in_([uuid.UUID(str(i)) for i in ids]))
    return db.scalars(stmt.order_by(Document.created_at, Document.id)).all()


def _span_and_relation_layers(db, layer):
    """(span layer, [relation layers]) of an export: a span layer alone, or a relation layer on its base."""
    if layer.kind == "span":
        return layer, []
    return db.get(AnnotationLayer, layer.base_layer_id), [layer]


EXPORT_SCOPE = {
    "pos": "已确认、已修改的词取人工值；未校对的词取系统层自动值（语料自带，或预标写入的 jieba / Stanza 结果）",
    "dep": "已确认、已修改的词取人工值；未校对的词取系统层自动值（语料自带，或预标写入的 jieba / Stanza 结果）",
    "span": "已确认、已修改的片段；多人层为各标注者一致或已仲裁的片段；未校对的建议不导出",
    "relation": (
        "已确认、已修改的关系及其端点片段；端点片段未确认时随关系导出并标为未确认；"
        "多人层为各标注者一致或已仲裁的关系；未校对的建议不导出"
    ),
    "alignment": (
        "已确认、已修改的对齐和未校对的导入句对；多人层为各标注者一致或已仲裁的结果；"
        "未校对的模型建议不导出"
    ),
}
ANNOTATORS_SCOPE = "annotators：每位标注者自己的全部行（含建议、拒绝），用于复核一致性"


def _endpoint_spans(relations):
    """Endpoint spans of exported relations that are not effective themselves (by extent)."""
    out = {}
    for r in relations:
        for end in (r["from"], r["to"]):
            if end.get("effective") is False:
                out.setdefault(
                    eff.span_key(end["document_id"], end["start_cp"], end["end_cp"]),
                    end,
                )
    return list(out.values())


def _fragments(text, a, b):
    """brat fragments of [a, b): split at line breaks (brat spans cannot cross them)."""
    out, start = [], a
    for i in range(a, b):
        if text[i] == "\n":
            if i > start:
                out.append((start, i))
            start = i + 1
    if b > start:
        out.append((start, b))
    return out or [(a, b)]


ENDPOINT_NOTE = "端点片段未确认，仅作为已确认关系的端点导出"


def brat_ann(text, spans, relations):
    """.ann text: one T line per span (code-point offsets, fragments split at line breaks), an AnnotatorNotes
    line for endpoint-only spans ("effective": False) and one R line per relation whose spans are listed."""
    lines, tid, notes = [], {}, 0
    for n, s in enumerate(spans, 1):
        frags = _fragments(text, s["start_cp"], s["end_cp"])
        tid[eff.span_key(s["document_id"], s["start_cp"], s["end_cp"])] = f"T{n}"
        where = ";".join(f"{a} {b}" for a, b in frags)
        body = " ".join(text[a:b] for a, b in frags).replace("\t", " ")
        lines.append(f"T{n}\t{s['label']} {where}\t{body}")
        if s.get("effective") is False:
            notes += 1
            lines.append(f"#{notes}\tAnnotatorNotes T{n}\t{ENDPOINT_NOTE}")
    count = 0
    for r in relations:
        a = tid.get(
            eff.span_key(
                r["from"]["document_id"], r["from"]["start_cp"], r["from"]["end_cp"]
            )
        )
        b = tid.get(
            eff.span_key(r["to"]["document_id"], r["to"]["start_cp"], r["to"]["end_cp"])
        )
        if a and b:
            count += 1
            lines.append(f"R{count}\t{r['label']} Arg1:{a} Arg2:{b}")
    return "".join(line + "\n" for line in lines), count


def run_export_brat(run, layer_id):
    """Span layer: its effective spans. Relation layer: its effective relations with the base layer's
    effective spans, plus endpoint spans that are not effective themselves (with an AnnotatorNotes line)."""
    with session() as db:
        layer = db.get(AnnotationLayer, layer_id)
        if layer is None:
            raise JobFailed("LAYER_DELETED", "标注层已删除")
        span_layer, rel_layers = _span_and_relation_layers(db, layer)
        if span_layer is None:
            raise JobFailed("LAYER_DELETED", "片段层已删除")
        docs = _export_docs(db, span_layer, run.params)
        doc_ids = {d.id for d in docs}
        spans = eff.effective_spans(db, eff.eff_layer(span_layer), list(doc_ids))
        relations = [
            r
            for rl in rel_layers
            for r in eff.effective_relations(
                db, eff.eff_layer(rl), spans, endpoints=True
            )
            if r["from"]["document_id"] in doc_ids
        ]
        endpoints = _endpoint_spans(relations)
        labels = [x["id"] for x in db.get(LabelSet, span_layer.label_set_id).labels]
        rel_labels = sorted(
            {
                x["id"]
                for rl in rel_layers
                for x in db.get(LabelSet, rl.label_set_id).labels
            }
        )
        name = layer.name
        notice = _notice(db, span_layer.corpus_id)
    path = export_path(run.id, "brat")
    path.parent.mkdir(parents=True, exist_ok=True)
    total_spans = total_rel = 0
    by_doc = defaultdict(list)
    for s in sorted(
        spans + endpoints,
        key=lambda s: (str(s["document_id"]), s["start_cp"], s["end_cp"]),
    ):
        by_doc[s["document_id"]].append(s)
    rel_by_doc = defaultdict(list)
    for r in relations:
        rel_by_doc[r["from"]["document_id"]].append(r)
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        for n, d in enumerate(docs, 1):
            run.progress(n - 1, len(docs), "导出")
            text = Path(d.text_path).read_text(encoding="utf-8")
            stem = f"{n:03d}-{_safe(d.title, 40)}"
            ann_text, nrel = brat_ann(
                text, by_doc.get(d.id, []), rel_by_doc.get(d.id, [])
            )
            z.writestr(f"{stem}.txt", text.encode("utf-8"))
            z.writestr(f"{stem}.ann", ann_text.encode("utf-8"))
            total_spans += len(by_doc.get(d.id, []))
            total_rel += nrel
        conf = "".join(f"# {line}\n" for line in notice)
        conf += f"# 导出口径：{EXPORT_SCOPE[layer.kind]}\n"
        conf += "[entities]\n" + "".join(f"{x}\n" for x in labels)
        conf += "\n[relations]\n" + "".join(
            f"{x}\tArg1:<ENTITY>, Arg2:<ENTITY>\n" for x in rel_labels
        )
        conf += "\n[events]\n\n[attributes]\n"
        z.writestr("annotation.conf", conf.encode("utf-8"))
        if notice:
            z.writestr("README.txt", "".join(f"{x}\n" for x in notice).encode("utf-8"))
    _finish(
        run,
        f"{_safe(name)}-brat-{_stamp()}.zip",
        {
            "documents": len(docs),
            "spans": total_spans,
            "endpoint_spans": len(endpoints),
            "relations": total_rel,
            "offsets": "code points",
        },
    )


def _xlsx_sheet(wb, title, header, rows, notice=()):
    ws = wb.create_sheet(title)
    for line in notice:
        ws.append([line])
    if notice:
        ws.append([])
    font = Font(name="宋体", bold=True)
    cells = []
    for h in header:
        c = WriteOnlyCell(ws, value=h)
        c.font = font
        cells.append(c)
    ws.append(cells)
    for r in rows:
        ws.append(r)


def run_export_xlsx(run, layer_id):
    """Label × document counts of effective spans (plus a 合计 column and row) and the span list."""
    with session() as db:
        layer = db.get(AnnotationLayer, layer_id)
        span_layer, _ = _span_and_relation_layers(db, layer)
        docs = _export_docs(db, span_layer, run.params)
        spans = eff.effective_spans(db, eff.eff_layer(span_layer), [d.id for d in docs])
        labels = [x["id"] for x in db.get(LabelSet, span_layer.label_set_id).labels]
        sentences = {
            (d, i): t
            for d, i, t in db.execute(
                select(Sentence.document_id, Sentence.idx, Sentence.text).where(
                    Sentence.document_id.in_([d.id for d in docs])
                )
            )
        }
        name = span_layer.name
        notice = _notice(db, span_layer.corpus_id)
    counts = defaultdict(lambda: defaultdict(int))
    for s in spans:
        counts[s["label"]][s["document_id"]] += 1
    order = labels + sorted(k for k in counts if k not in labels)
    header = ["标签", *(d.title for d in docs), "合计"]
    rows = [
        [label, *(counts[label][d.id] for d in docs), sum(counts[label].values())]
        for label in order
    ]
    rows.append(
        ["合计", *(sum(counts[x][d.id] for x in order) for d in docs), len(spans)]
    )
    texts = {d.id: Path(d.text_path).read_text(encoding="utf-8") for d in docs}
    titles = {d.id: d.title for d in docs}
    span_rows = [
        [
            titles[s["document_id"]],
            s["sentence_index"],
            s["start_cp"],
            s["end_cp"],
            texts[s["document_id"]][s["start_cp"] : s["end_cp"]],
            s["label"],
            json.dumps(s["attrs"], ensure_ascii=False) if s["attrs"] else "",
            sentences.get((s["document_id"], s["sentence_index"]), ""),
        ]
        for s in spans
    ]
    wb = Workbook(write_only=True)
    _xlsx_sheet(wb, "偏误分布", header, rows, notice)
    _xlsx_sheet(
        wb,
        "片段",
        ["文档", "句序", "起始码点", "结束码点", "片段", "标签", "属性", "所在句"],
        span_rows,
        notice,
    )
    path = export_path(run.id, "xlsx")
    path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(path)
    _finish(
        run,
        f"{_safe(name)}-分布-{_stamp()}.xlsx",
        {"rows": len(order), "spans": len(spans)},
    )


def _str_ids(d):
    return {
        k: str(v) if k.endswith("document_id") and v is not None else v
        for k, v in d.items()
    }


def _layer_entry(db, x, doc_ids):
    """Effective annotations of one layer for the JSON export."""
    e = eff.eff_layer(x)
    entry = {
        "id": str(x.id),
        "name": x.name,
        "kind": x.kind,
        "mode": x.mode,
        "label_set_id": str(x.label_set_id) if x.label_set_id else None,
        "scope": EXPORT_SCOPE[x.kind],
    }
    id_set = set(doc_ids)
    if x.kind == "span":
        entry["spans"] = [_str_ids(s) for s in eff.effective_spans(db, e, doc_ids)]
    elif x.kind == "relation":
        base = db.get(AnnotationLayer, x.base_layer_id)
        spans = eff.effective_spans(db, eff.eff_layer(base), doc_ids) if base else []
        entry["base_layer_id"] = str(x.base_layer_id)
        entry["base_layer_name"] = base.name if base else None
        entry["relations"] = [
            {
                "id": r["id"],
                "label": r["label"],
                "from": _str_ids({"effective": True, **r["from"]}),
                "to": _str_ids({"effective": True, **r["to"]}),
            }
            for r in eff.effective_relations(db, e, spans, endpoints=True)
            if r["from"]["document_id"] in id_set
        ]
    elif x.kind == "alignment":
        entry["level"] = x.level
        entry["tgt_corpus_id"] = str(x.tgt_corpus_id)
        entry["token_index_base"] = 1
        entry["alignments"] = [
            {
                **_str_ids(p),
                "links": [{"src": list(a), "tgt": list(b)} for a, b in p["links"]],
            }
            for p in eff.effective_alignments(db, e, doc_ids)
        ]
    else:
        toks = eff.layer_tokens(db, doc_ids, {"pos": None, "dep": None, x.kind: e})
        entry["token_index_base"] = 1
        entry["tokens"] = [
            {
                "document_id": str(d),
                "sentence_index": s,
                "token_index": n,
                "form": t[2],
                "label": t[3] if x.kind == "pos" else t[6],
                **({"head": t[5]} if x.kind == "dep" else {}),
            }
            for d, sents in toks.items()
            for s, items in sents.items()
            for n, t in enumerate(items, 1)
        ]
    return entry


def _annotator_rows(db, x, doc_ids):
    """{annotator id: [rows]} of a multi-annotator layer: every row of each listed annotator, any status."""
    annotators = list(layer_annotators(x))
    out = {a: [] for a in annotators}
    common = {"status", "source", "model_label", "label"}
    if x.kind == "span":
        for s in eff.annotator_spans(db, x, annotators, doc_ids, statuses=None):
            out[s.annotator_id].append(
                {
                    **_str_ids(eff._span_dict(s)),
                    **{k: getattr(s, k) for k in common},
                }
            )
    elif x.kind == "relation":
        f, t = aliased(SpanAnnotation), aliased(SpanAnnotation)
        for r, a, b in db.execute(
            select(RelationAnnotation, f, t)
            .join(f, f.id == RelationAnnotation.from_span_id)
            .join(t, t.id == RelationAnnotation.to_span_id)
            .where(
                RelationAnnotation.layer_id == x.id,
                RelationAnnotation.annotator_id.in_(annotators),
                f.document_id.in_(doc_ids),
            )
            .order_by(f.document_id, f.start_cp, RelationAnnotation.id)
        ).all():
            out[r.annotator_id].append(
                {
                    "id": r.id,
                    **{k: getattr(r, k) for k in common},
                    "from": _str_ids({**eff._span_dict(a), "label": a.label}),
                    "to": _str_ids({**eff._span_dict(b), "label": b.label}),
                }
            )
    elif x.kind == "alignment":
        for r in db.scalars(
            select(AlignmentAnnotation)
            .where(
                AlignmentAnnotation.layer_id == x.id,
                AlignmentAnnotation.annotator_id.in_(annotators),
                AlignmentAnnotation.src_document_id.in_(doc_ids),
            )
            .order_by(
                AlignmentAnnotation.src_document_id,
                AlignmentAnnotation.src_sentence_index,
                AlignmentAnnotation.id,
            )
        ):
            out[r.annotator_id].append(
                {
                    "id": r.id,
                    "src_document_id": str(r.src_document_id),
                    "src_sentence_index": r.src_sentence_index,
                    "tgt_document_id": str(r.tgt_document_id),
                    "tgt_sentence_index": r.tgt_sentence_index,
                    "src_tokens": list(r.src_tokens or []),
                    "tgt_tokens": list(r.tgt_tokens or []),
                    "status": r.status,
                    "source": r.source,
                }
            )
    emails = dict(
        db.execute(select(User.id, User.email).where(User.id.in_(annotators))).all()
    )
    return [
        {"annotator_id": str(a), "email": emails.get(a), "rows": rows}
        for a, rows in out.items()
    ]


def run_export_json(run, layer_id):
    """The selected layer only: its effective annotations over the layer's documents (a relation layer carries
    its endpoint spans in each relation). params.annotators on a multi-annotator layer adds each annotator's
    own rows."""
    with session() as db:
        layer = db.get(AnnotationLayer, layer_id)
        if layer is None:
            raise JobFailed("LAYER_DELETED", "标注层已删除")
        docs = _export_docs(db, layer, run.params)
        doc_ids = [d.id for d in docs]
        entry = _layer_entry(db, layer, doc_ids)
        raw = run.params.get("annotators") and layer.mode == "multi"
        if raw:
            entry["annotators"] = _annotator_rows(db, layer, doc_ids)
        corpus = db.get(Corpus, layer.corpus_id)
        data = {
            "corpus": {
                "id": str(corpus.id),
                "name": corpus.name,
                "language": corpus.language,
            },
            "scope": [EXPORT_SCOPE[layer.kind], *([ANNOTATORS_SCOPE] if raw else [])],
            "offsets": "code points",
            "sentence_index_base": 0,
            "documents": [
                {
                    "id": str(d.id),
                    "title": d.title,
                    "language": d.language,
                    "text": Path(d.text_path).read_text(encoding="utf-8"),
                }
                for d in docs
            ],
            "layers": [entry],
        }
        notice = _notice(
            db, layer.corpus_id, *([layer.tgt_corpus_id] if layer.tgt_corpus_id else [])
        )
        if notice:
            data = {"source": notice, **data}
        name = layer.name
    path = export_path(run.id, "json")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=1, default=str), encoding="utf-8"
    )
    _finish(
        run,
        f"{_safe(name)}-{_stamp()}.json",
        {"documents": len(docs), "layers": 1, "annotators": bool(raw)},
    )


XML_LANG = "{http://www.w3.org/XML/1998/namespace}lang"


def run_export_tmx(run, layer_id):
    """TMX 1.4: one <tu> per effective sentence pair; word layers add <prop type="x-word-alignment"> with
    1-based "i-j" word pairs."""
    with session() as db:
        layer = db.get(AnnotationLayer, layer_id)
        docs = _export_docs(db, layer, run.params)
        pairs = eff.effective_alignments(db, eff.eff_layer(layer), [d.id for d in docs])
        keys = {(p["src_document_id"], p["src_sentence_index"]) for p in pairs} | {
            (p["tgt_document_id"], p["tgt_sentence_index"]) for p in pairs
        }
        texts = {}
        if keys:
            texts = {
                (d, i): t
                for d, i, t in db.execute(
                    select(Sentence.document_id, Sentence.idx, Sentence.text).where(
                        tuple_(Sentence.document_id, Sentence.idx).in_(list(keys))
                    )
                )
            }
        langs = dict(
            db.execute(
                select(Document.id, Document.language).where(
                    Document.id.in_({k[0] for k in keys} or {uuid.uuid4()})
                )
            ).all()
        )
        name = layer.name
        notice = _notice(db, layer.corpus_id, layer.tgt_corpus_id)
    src_lang = langs.get(pairs[0]["src_document_id"], "und") if pairs else "und"
    root = etree.Element("tmx", version="1.4")
    header = etree.SubElement(
        root,
        "header",
        creationtool="corpus-workbench",
        creationtoolversion="1.0",
        datatype="plaintext",
        segtype="sentence",
        adminlang="zh-CN",
        srclang=src_lang,
        **{"o-tmf": "corpus-workbench"},
    )
    for line in notice:
        etree.SubElement(header, "note").text = line
    etree.SubElement(header, "prop", type="x-scope").text = EXPORT_SCOPE["alignment"]
    etree.SubElement(
        header, "prop", type="x-source-format"
    ).text = "x-source / x-target：文档 id:句序号，句序号从 0 起"
    if layer.level == "word":
        etree.SubElement(header, "prop", type="x-word-alignment-format").text = (
            "i-j：源语词序号-目标语词序号，从 1 起，与 CoNLL-U 的 ID 列一致；"
            "Pharaoh 格式从 0 起，换用时两边各减 1"
        )
    body = etree.SubElement(root, "body")
    for p in pairs:
        src = (p["src_document_id"], p["src_sentence_index"])
        tgt = (p["tgt_document_id"], p["tgt_sentence_index"])
        tu = etree.SubElement(body, "tu")
        etree.SubElement(tu, "prop", type="x-source").text = f"{src[0]}:{src[1]}"
        etree.SubElement(tu, "prop", type="x-target").text = f"{tgt[0]}:{tgt[1]}"
        if p["score"] is not None:
            etree.SubElement(tu, "prop", type="x-score").text = f"{p['score']:.4f}"
        if layer.level == "word":
            etree.SubElement(tu, "prop", type="x-word-alignment").text = " ".join(
                f"{i}-{j}" for i, j in sorted(align.word_pairs(p["links"]))
            )
        for key in (src, tgt):
            tuv = etree.SubElement(tu, "tuv", {XML_LANG: langs.get(key[0], "und")})
            etree.SubElement(tuv, "seg").text = texts.get(key, "")
    path = export_path(run.id, "tmx")
    path.parent.mkdir(parents=True, exist_ok=True)
    buf = io.BytesIO()
    etree.ElementTree(root).write(
        buf, xml_declaration=True, encoding="UTF-8", pretty_print=True
    )
    path.write_bytes(buf.getvalue())
    _finish(run, f"{_safe(name)}-{_stamp()}.tmx", {"rows": len(pairs)})


EXPORTS = {
    "brat": run_export_brat,
    "xlsx": run_export_xlsx,
    "json": run_export_json,
    "tmx": run_export_tmx,
}
