"""Job handlers. Each handler ends with one transaction that locks the job row,
writes results and marks the job succeeded, so a cancel either wins entirely or not at all."""

import csv
import json
import shutil
import uuid
from datetime import datetime
from itertools import islice
from pathlib import Path

from docx import Document as DocxDocument
from docx.oxml.ns import qn
from docx.shared import Pt
from openpyxl import Workbook
from openpyxl.cell import WriteOnlyCell
from openpyxl.styles import Font
from sqlalchemy import exists, func, insert, select

from engine import cwb, nlp, parsers, stats
from engine import model as em
from services.api.db import session, transaction
from services.api.jobs import enqueue
from services.api.metadata import field_types
from services.api.models import (
    Corpus,
    Document,
    Evidence,
    Job,
    Sentence,
    SentenceAlignment,
    StatResult,
    Subcorpus,
    Token,
    User,
)
from services.api.search import (
    ExportInput,
    Scope,
    compile_query,
    corpus_tagset,
    enrich,
    resolve_scope,
    run_search,
    scope_filter,
)
from services.api.storage import (
    corpus_key,
    export_path,
    index_dir,
    stats_path,
    text_path,
)
from services.worker.main import JobFailed

EXPORT_PAGE = 1000
EXPORT_COUNT_TIMEOUT = 600
LOAD_BATCH = 500


def _corpus(db, corpus_id):
    corpus = db.get(Corpus, corpus_id)
    if not corpus:
        raise JobFailed("CORPUS_DELETED", "语料库已删除")
    return corpus


# ---- import ----


def _parse_batch(run):
    params = run.params
    folder = Path(params["dir"])
    names = params["files"]
    # Tatoeba sentences + links files are parsed together as one directory.
    targets = (
        [folder]
        if any("links" in n.lower() for n in names)
        else [folder / n for n in names]
    )
    documents, alignments = [], []
    for i, path in enumerate(targets):
        run.progress(i, len(targets), f"解析 {path.name}")
        try:
            docs, links = parsers.parse(
                path, language=params["language"], metadata=params["metadata"]
            )
        except parsers.ParseError as e:
            raise JobFailed("PARSE_ERROR", str(e)) from e
        documents += docs
        alignments += links
    if not documents:
        raise JobFailed("EMPTY_IMPORT", "文件中没有可导入的文本")
    return documents, alignments


def _write_documents(db, corpus_id, documents, written):
    """Insert documents/sentences/tokens; returns sentence ids keyed by external id."""
    by_external = {}
    for doc in documents:
        doc_id = uuid.uuid4()
        path = text_path(corpus_id, doc_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(doc.text, encoding="utf-8", newline="")
        written.append(path)
        db.execute(
            insert(Document),
            {
                "id": doc_id,
                "corpus_id": corpus_id,
                "title": doc.title,
                "language": doc.language,
                "meta": doc.metadata,
                "external_id": doc.external_id,
                "text_path": str(path),
                "char_count": len(doc.text),
                "sentence_count": len(doc.sentences),
                "token_count": sum(len(s.tokens) for s in doc.sentences),
            },
        )
        if not doc.sentences:
            continue
        ids = db.scalars(
            insert(Sentence).returning(Sentence.id, sort_by_parameter_order=True),
            [
                {
                    "document_id": doc_id,
                    "idx": i,
                    "start_cp": s.start,
                    "end_cp": s.end,
                    "text": doc.text[s.start : s.end],
                }
                for i, s in enumerate(doc.sentences)
            ],
        ).all()
        tokens = [
            {
                "sentence_id": sid,
                "idx": j,
                "start_cp": t.start,
                "end_cp": t.end,
                "form": t.form,
                "pos": t.pos,
                "lemma": t.lemma,
                "head": t.head,
                "deprel": t.deprel,
            }
            for sid, s in zip(ids, doc.sentences)
            for j, t in enumerate(s.tokens)
        ]
        if tokens:
            db.execute(insert(Token), tokens)
        for sid, s in zip(ids, doc.sentences):
            if s.external_id:
                by_external[s.external_id] = sid
    return by_external


def run_import(run):
    corpus_id = uuid.UUID(run.params["corpus_id"])
    documents, alignments = _parse_batch(run)
    total = len(documents)
    for i, doc in enumerate(documents):
        if i % 20 == 0:
            run.progress(i, total, "标注")
        nlp.annotate(doc)
    run.progress(total, total, "写入")
    written = []
    try:
        with transaction() as db:
            run.lock(db)
            corpus = _corpus(db, corpus_id)
            by_external = _write_documents(db, corpus_id, documents, written)
            pairs = {
                (by_external[a.src_external_id], by_external[a.tgt_external_id])
                for a in alignments
                if a.src_external_id in by_external and a.tgt_external_id in by_external
            }
            if pairs:
                db.execute(
                    insert(SentenceAlignment),
                    [{"src_sentence_id": s, "tgt_sentence_id": t} for s, t in pairs],
                )
                corpus.parallel = True
            index_queued = db.scalar(
                select(
                    exists().where(
                        Job.kind == "index",
                        Job.state == "queued",
                        Job.params["corpus_id"].astext == str(corpus_id),
                    )
                )
            )
            if not index_queued:
                enqueue(
                    db,
                    "index",
                    {"corpus_id": str(corpus_id)},
                    run.owner_id,
                    run.project_id,
                )
            corpus.status, corpus.error = "indexing", None
            run.succeed(
                db,
                {
                    "documents": total,
                    "sentences": sum(len(d.sentences) for d in documents),
                    "tokens": sum(
                        len(s.tokens) for d in documents for s in d.sentences
                    ),
                    "alignments": len(pairs),
                },
            )
    except BaseException:
        for path in written:
            path.unlink(missing_ok=True)
        raise
    shutil.rmtree(run.params["dir"], ignore_errors=True)


# ---- index ----


def _load_documents(doc_ids, run):
    """Stream engine Documents from the database in id order, LOAD_BATCH at a time."""
    total = len(doc_ids)
    it = iter(doc_ids)
    done = 0
    while batch := list(islice(it, LOAD_BATCH)):
        run.progress(done, total, "建索引")
        with session() as db:
            docs = {
                d.id: d
                for d in db.scalars(select(Document).where(Document.id.in_(batch)))
            }
            sentences = db.scalars(
                select(Sentence)
                .where(Sentence.document_id.in_(batch))
                .order_by(Sentence.document_id, Sentence.idx)
            ).all()
            tokens = db.scalars(
                select(Token)
                .join(Sentence, Sentence.id == Token.sentence_id)
                .where(Sentence.document_id.in_(batch))
                .order_by(Token.sentence_id, Token.idx)
            ).all()
        by_sentence = {}
        for t in tokens:
            by_sentence.setdefault(t.sentence_id, []).append(
                em.Token(t.start_cp, t.end_cp, t.form, t.pos, t.lemma, t.head, t.deprel)
            )
        by_doc = {}
        for s in sentences:
            by_doc.setdefault(s.document_id, []).append(
                em.Sentence(s.start_cp, s.end_cp, by_sentence.get(s.id, []))
            )
        for doc_id in batch:
            d = docs.get(doc_id)
            if d is None:
                raise JobFailed("DOCUMENTS_CHANGED", "建索引期间文档被删除，请重试")
            yield em.Document(
                title=d.title,
                language=d.language,
                text=Path(d.text_path).read_text(encoding="utf-8"),
                metadata=d.meta,
                sentences=by_doc.get(doc_id, []),
                external_id=d.external_id,
            )
        done += len(batch)


def run_index(run):
    corpus_id = uuid.UUID(run.params["corpus_id"])
    with transaction() as db:
        _corpus(db, corpus_id).status = "indexing"
        doc_ids = db.scalars(
            select(Document.id)
            .where(Document.corpus_id == corpus_id)
            .order_by(Document.created_at, Document.id)
        ).all()
    info = None
    if doc_ids:
        info = cwb.build(
            index_dir(corpus_id),
            corpus_key(corpus_id),
            _load_documents(doc_ids, run),
            [str(i) for i in doc_ids],
        )
    with transaction() as db:
        run.lock(db)
        corpus = _corpus(db, corpus_id)
        docs, sentences, tokens = db.execute(
            select(
                func.count(),
                func.coalesce(func.sum(Document.sentence_count), 0),
                func.coalesce(func.sum(Document.token_count), 0),
            ).where(Document.corpus_id == corpus_id)
        ).one()
        corpus.stats = {
            "documents": docs,
            "sentences": int(sentences),
            "tokens": int(tokens),
        }
        corpus.index_version = info.index_version if info else None
        corpus.status = "ready" if info else "empty"
        corpus.error = None
        run.succeed(db, {**corpus.stats, "index_version": corpus.index_version})


# ---- export ----

FIXED_COLUMNS = [
    ("hit_id", "命中 ID"),
    ("document_title", "文档"),
    ("document_id", "文档 ID"),
    ("sentence_index", "句序"),
    ("start_cp", "起始码点"),
    ("end_cp", "结束码点"),
    ("left", "左语境"),
    ("match", "命中"),
    ("right", "右语境"),
    ("aligned", "对齐句"),
]


def _rows(items):
    meta_keys = sorted({k for item in items for k in item["metadata"]})
    header = [title for _, title in FIXED_COLUMNS] + meta_keys
    rows = []
    for item in items:
        values = {
            **item,
            "aligned": "\n".join(
                f"[{a['language']}] {a['text']}" for a in item["aligned"]
            ),
        }
        row = [values[key] for key, _ in FIXED_COLUMNS]
        row += [_cell(item["metadata"].get(k)) for k in meta_keys]
        rows.append(row)
    return header, rows


def _cell(value):
    return (
        value if value is None or isinstance(value, str | int | float) else str(value)
    )


def _write_csv(path, header, rows):
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(header)
        writer.writerows(rows)


def _write_xlsx(path, header, rows, sheet="检索结果"):
    wb = Workbook(write_only=True)
    ws = wb.create_sheet(sheet)
    title_font = Font(name="宋体", bold=True)
    cells = []
    for title in header:
        cell = WriteOnlyCell(ws, value=title)
        cell.font = title_font
        cells.append(cell)
    ws.append(cells)
    for row in rows:
        ws.append(row)
    wb.save(path)


def run_export(run):
    req = ExportInput.model_validate(run.params)  # seed pinned at enqueue
    items, hits = [], None
    with session() as db:
        user = db.get(User, run.owner_id)
        corpus, restrict = resolve_scope(db, req.scope, user)
        cqp = compile_query(req.query, corpus_tagset(corpus))
        page = 1
        while True:
            result = run_search(
                corpus, restrict, cqp, req, page, EXPORT_PAGE, EXPORT_COUNT_TIMEOUT
            )
            if hits is None:
                hits = result.counts.hits
            items += enrich(db, result.items)
            run.progress(len(items), hits, "导出")
            if len(result.items) < EXPORT_PAGE:
                break
            page += 1
    header, rows = _rows(items)
    _finish_export(run, "检索结果", header, rows, {"hits": hits})


def _finish_export(run, name, header, rows, extra=None):
    fmt = run.params["format"]
    path = export_path(run.id, fmt)
    path.parent.mkdir(parents=True, exist_ok=True)
    if fmt == "csv":
        _write_csv(path, header, rows)
    elif fmt == "xlsx":
        _write_xlsx(path, header, rows, name)
    else:
        _write_docx(path, name, header, rows)
    filename = f"{name}-{datetime.now():%Y%m%d-%H%M}.{fmt}"
    with transaction() as db:
        run.lock(db)
        run.succeed(db, {"rows": len(rows), **(extra or {}), "filename": filename})


def _write_docx(path, title, header, rows):
    """One block per row: the first column as a paragraph, the others as `label：value` lines. 宋体, no fills."""
    doc = DocxDocument()
    normal = doc.styles["Normal"]
    normal.font.name = "宋体"
    normal.element.rPr.rFonts.set(qn("w:eastAsia"), "宋体")
    heading = doc.add_paragraph().add_run(title)
    heading.bold, heading.font.size = True, Pt(16)
    for i, row in enumerate(rows, 1):
        doc.add_paragraph(f"{i}. {row[0]}")
        for label, value in zip(header[1:], row[1:]):
            if value not in (None, ""):
                doc.add_paragraph(f"{label}：{value}")
    doc.save(path)


def run_export_stats(run):
    with session() as db:
        stat = db.get(StatResult, uuid.UUID(run.params["stat_id"]))
        if not stat:
            raise JobFailed("STAT_DELETED", "统计结果已删除")
        columns, path = stat.columns, Path(stat.rows_path)
    data = json.loads(path.read_text(encoding="utf-8"))["rows"]
    header = [c["label"] for c in columns] + ["查询式"]
    rows = [
        [_cell(r["values"].get(c["key"])) for c in columns] + [r["search_query"]]
        for r in data
    ]
    _finish_export(run, "统计结果", header, rows)


def run_export_evidence(run):
    with session() as db:
        items = db.scalars(
            select(Evidence)
            .where(Evidence.project_id == uuid.UUID(run.params["project_id"]))
            .order_by(Evidence.created_at, Evidence.id)
        ).all()
    header = ["原文", "出处", "查询式", "备注"]
    rows = [[e.text, e.source, e.ref.get("search_query"), e.note] for e in items]
    _finish_export(run, "证据篮", header, rows)


EXPORTS = {
    "search": run_export,
    "stats": run_export_stats,
    "evidence": run_export_evidence,
}


def run_any_export(run):
    EXPORTS[run.params.get("source", "search")](run)


# ---- stats ----


def _scope_info(db, scope: Scope, corpus):
    sub = db.get(Subcorpus, scope.subcorpus_id) if scope.subcorpus_id else None
    info = {
        "corpus_id": str(corpus.id),
        "subcorpus_id": str(sub.id) if sub else None,
        "name": sub.name if sub else corpus.name,
    }
    if scope.filter is not None:
        info["filter"] = scope.filter
    return info


def _compute(p, target, reference, numeric):
    method, top = p["method"], p["top"]
    if method == "frequency":
        return stats.frequency(target, p["unit"], p["pos"], top, p["min_freq"])
    if method == "ngrams":
        return stats.ngrams(
            target, p["n"], p["unit"], p["pos_pattern"], top, p["min_freq"]
        )
    if method == "collocations":
        return stats.collocations(
            target,
            p["node"],
            p["window"],
            p["unit"],
            p["pos"],
            p["measures"],
            p["min_freq"],
            top,
        )
    if method == "keywords":
        return stats.keywords(
            target, reference, p["unit"], p["measure"], p["min_freq"], top
        )
    return stats.distribution(
        target, p["query"], p["field"], p["bins"], numeric=numeric, top=top
    )


def run_stats(run):
    p = run.params
    method = p["method"]
    scope = Scope.model_validate(p["target"] if method == "keywords" else p["scope"])
    params = {k: v for k, v in p.items() if k != "method"}
    reference = numeric = None
    with session() as db:
        user = db.get(User, run.owner_id)
        corpus, restrict = resolve_scope(db, scope, user)
        target = stats.Scope(index_dir(corpus.id), corpus_key(corpus.id), restrict)
        info, base_filter = _scope_info(db, scope, corpus), scope_filter(db, scope)
        index_version = corpus.index_version
        if method == "keywords":
            ref_scope = Scope.model_validate(p["reference"])
            ref_corpus, ref_restrict = resolve_scope(db, ref_scope, user)
            reference = stats.Scope(
                index_dir(ref_corpus.id), corpus_key(ref_corpus.id), ref_restrict
            )
            params["reference"] = _scope_info(db, ref_scope, ref_corpus)
        if method == "distribution":
            numeric = field_types(db, corpus.id).get(p["field"]) == "number"
    run.progress(0, None, "计算")
    try:
        table = _compute(p, target, reference, numeric)
    except ValueError as e:  # includes query.QueryError
        raise JobFailed("STATS_INVALID", str(e)) from e
    search_scope = scope.model_dump(mode="json", exclude_none=True)
    for row in table.rows:
        row["search_scope"] = search_scope
        if "bin_value" in row:  # distribution by field: temporary filter for that value
            filt = {**base_filter, p["field"]: row.pop("bin_value")}
            row["search_scope"] = {"corpus_id": str(corpus.id), "filter": filt}
    stat_id = uuid.uuid4()
    path = stats_path(stat_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"rows": table.rows}, ensure_ascii=False), encoding="utf-8"
    )
    try:
        with transaction() as db:
            run.lock(db)
            db.add(
                StatResult(
                    id=stat_id,
                    project_id=run.project_id,
                    method=method,
                    params=params,
                    scope=info,
                    index_version=index_version,
                    totals=table.totals,
                    columns=table.columns,
                    rows_path=str(path),
                    row_count=table.row_count,
                    created_by=run.owner_id,
                )
            )
            run.succeed(db, {"stat_id": str(stat_id)})
    except BaseException:
        path.unlink(missing_ok=True)
        raise


HANDLERS = {
    "import": run_import,
    "index": run_index,
    "export": run_any_export,
    "stats": run_stats,
}
