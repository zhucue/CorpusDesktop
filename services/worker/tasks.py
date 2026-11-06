"""Job handlers. Each handler ends with one transaction that locks the job row,
writes results and marks the job succeeded, so a cancel either wins entirely or not at all."""

import csv
import itertools
import json
import shutil
import time
import uuid
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

from docx import Document as DocxDocument
from docx.oxml.ns import qn
from docx.shared import Pt
from openpyxl import Workbook
from openpyxl.cell import WriteOnlyCell
from openpyxl.styles import Font
from sqlalchemy import bindparam, func, insert, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert

from engine import cwb, nlp, parsers, query, stats
from engine import model as em
from engine.conllu import write_conllu
from services.api import effective, semantic
from services.api.annotations import (
    add_document_counts,
    document_counts,
    is_zh,
    refresh_progress,
)
from services.api.annotators import layer_annotators
from services.api.db import session, transaction
from services.api.jobs import corpus_tokens, enqueue, live_index
from services.api.metadata import field_types
from services.api.models import (
    Annotation,
    AnnotationLayer,
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
    LayersInput,
    Scope,
    corpus_tagset,
    enrich,
    plan_query,
    resolve_scope,
    scope_filter,
    with_span_layer,
)
from services.api.storage import (
    corpus_key,
    export_path,
    index_dir,
    stats_path,
    text_path,
)
from services.worker import annot_tasks, kb_tasks
from services.worker.main import Cancelled, JobFailed, log

EXPORT_PAGE = 1000
EXPORT_COUNT_TIMEOUT = 600
LOAD_BATCH = 500
# token rows read per index load round; a larger document loads alone
LOAD_TOKENS = 1_000_000
WRITE_SENTENCES = 5000  # sentences (with their tokens) per INSERT round at import
PROGRESS_SECONDS = 2.0


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
        run.progress(i, len(targets), f"解析 {path.name}", "个文件")
        try:
            docs, links = parsers.parse(
                path,
                language=params["language"],
                metadata=params["metadata"],
                mapping=params.get("mapping"),
            )
        except parsers.ParseError as e:
            raise JobFailed("PARSE_ERROR", str(e)) from e
        except Exception as e:  # a malformed file must not surface as INTERNAL
            log.exception("parsing %s failed", path)
            raise JobFailed("PARSE_ERROR", f"{path.name} 无法解析：{e}"[:500]) from e
        if path.suffix.lower() == ".tmx":
            other = _unsupported(docs)
            if other:
                raise JobFailed(
                    "LANGUAGE_UNSUPPORTED", f"TMX 含暂不支持的语言：{'、'.join(other)}"
                )
        documents += docs
        alignments += links
    if not documents:
        raise JobFailed("EMPTY_IMPORT", "文件中没有可导入的文本")
    return documents, alignments


def _tokenized(doc):
    """CoNLL-U: tokens and annotation come with the file, so any language is stored as is."""
    return bool(doc.sentences) and all(s.tokens for s in doc.sentences)


def _unsupported(documents):
    """Language codes outside engine.nlp.SUPPORTED among documents that need annotation, sorted."""
    return sorted(
        {
            nlp.lang_code(d.language)
            for d in documents
            if d.language and not _tokenized(d)
        }
        - set(nlp.SUPPORTED)
    )


def _check_upload_language(params):
    """An upload whose given language is not supported fails at once, unless every file is CoNLL-U."""
    language = params.get("language")
    if not language or nlp.lang_code(language) in nlp.SUPPORTED:
        return
    if all(n.lower().endswith(".conllu") for n in params["files"]):
        return
    raise JobFailed("LANGUAGE_UNSUPPORTED", nlp.unsupported_message([language]))


def _check_languages(documents):
    """Documents to annotate: an unsupported language fails the import; documents without a language must
    be detectable (engine.nlp.language_problem), documents with one must not be mostly in another script."""
    other = _unsupported(documents)
    if other:
        raise JobFailed("LANGUAGE_UNSUPPORTED", nlp.unsupported_message(other))
    for d in documents:
        if _tokenized(d):
            continue
        problem = nlp.language_problem(d.text, d.language or None)
        if problem:
            raise JobFailed("LANGUAGE_UNSUPPORTED", f"{d.title}：{problem}")


DUPLICATES_LISTED = 20  # duplicate documents named in the import result
HASH_LOOKUP = 5000  # hashes per lookup query


def _stored_hashes(db, corpus_id, hashes) -> set:
    """Those of hashes that documents of the corpus already have."""
    unique, found = list(set(hashes)), set()
    for i in range(0, len(unique), HASH_LOOKUP):
        found.update(
            db.scalars(
                select(Document.content_hash).where(
                    Document.corpus_id == corpus_id,
                    Document.content_hash.in_(unique[i : i + HASH_LOOKUP]),
                )
            )
        )
    return found


def _aligned_groups(documents, alignments) -> list[list[int]]:
    """Document indexes grouped by sentence alignment (TMX, Tatoeba): linked documents form one group,
    every other document is a group of its own; groups in document order."""
    parent = list(range(len(documents)))

    def root(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    owner = {
        s.external_id: i
        for i, d in enumerate(documents)
        for s in d.sentences
        if s.external_id
    }
    for a in alignments:
        if a.src_external_id in owner and a.tgt_external_id in owner:
            parent[root(owner[a.src_external_id])] = root(owner[a.tgt_external_id])
    groups: dict[int, list[int]] = {}
    for i in range(len(documents)):
        groups.setdefault(root(i), []).append(i)
    return sorted(groups.values())


def _skip_duplicates(db, corpus_id, documents, alignments):
    """Leave out documents whose normalized text (engine.parsers.content_hash) is already in the corpus or
    earlier in this batch. Aligned documents (the sides of a TMX or Tatoeba import) are skipped only when
    every side is a duplicate; otherwise all sides are imported, so no alignment is lost. Returns (kept
    documents, sources of the skipped ones: file or "file #row")."""
    hashes = [parsers.content_hash(d.text) for d in documents]
    seen = _stored_hashes(db, corpus_id, hashes)
    keep = [False] * len(documents)
    for group in _aligned_groups(documents, alignments):
        if not all(hashes[i] in seen for i in group):
            for i in group:
                keep[i] = True
        seen.update(hashes[i] for i in group)
    kept = [d for d, k in zip(documents, keep) if k]
    skipped = [parsers.source_of(d) for d, k in zip(documents, keep) if not k]
    return kept, skipped


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
                "content_hash": parsers.content_hash(doc.text),
                "char_count": len(doc.text),
                "sentence_count": len(doc.sentences),
                "token_count": sum(len(s.tokens) for s in doc.sentences),
            },
        )
        for k in range(0, len(doc.sentences), WRITE_SENTENCES):
            part = doc.sentences[k : k + WRITE_SENTENCES]
            ids = db.scalars(
                insert(Sentence).returning(Sentence.id, sort_by_parameter_order=True),
                [
                    {
                        "document_id": doc_id,
                        "idx": k + i,
                        "start_cp": s.start,
                        "end_cp": s.end,
                        "text": doc.text[s.start : s.end],
                    }
                    for i, s in enumerate(part)
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
                for sid, s in zip(ids, part)
                for j, t in enumerate(s.tokens)
            ]
            if tokens:
                db.execute(insert(Token), tokens)
            for sid, s in zip(ids, part):
                if s.external_id:
                    by_external[s.external_id] = sid
    return by_external


def run_import(run):
    corpus_id = uuid.UUID(run.params["corpus_id"])
    _check_upload_language(run.params)
    documents, alignments = _parse_batch(run)
    # the same text twice (already in the corpus, or twice in this batch) is imported once; checked here so
    # duplicates are not annotated, and again under the corpus lock before writing (concurrent imports)
    with session() as db:
        documents, skipped = _skip_duplicates(db, corpus_id, documents, alignments)
    _check_languages(documents)
    # progress in characters so one large document (Tatoeba: one per language) still advances
    chars = sum(len(d.text) for d in documents)
    done, last = 0, 0.0

    def report(offset):
        nonlocal last
        run.check()  # between Stanza chunks
        if time.monotonic() - last >= PROGRESS_SECONDS:
            last = time.monotonic()
            run.progress(done + offset, chars, "分句与标注", "字")

    def downloading(message):  # first use of a Stanza language: "下载 fr 模型"
        run.progress(done, chars, message, "字")

    # language "auto" (or a CSV row without one): detect from the text
    for d in documents:
        if not d.language:
            d.language = nlp.detect_language(d.text)

    # CoNLL-U arrives tokenized and is stored as is, whatever its language
    todo = [d for d in documents if not _tokenized(d)]
    done = chars - sum(len(d.text) for d in todo)
    report(0)
    try:  # Stanza batches paragraphs across documents (many short CSV rows)
        with nlp.notifying(downloading):
            nlp.annotate_many(todo, report)
    except nlp.ModelError as e:
        raise JobFailed("MODEL_UNAVAILABLE", str(e)) from e
    except ValueError as e:  # e.g. a language without an annotation model
        raise JobFailed("ANNOTATE_ERROR", str(e)[:500]) from e
    run.progress(chars, chars, "写入", "字")
    written = []
    try:
        with transaction() as db:
            run.lock(db)
            # one import writes into a corpus at a time (worker and worker-light may run two); the
            # duplicate check is repeated under this lock against what the other one wrote meanwhile
            corpus = db.get(Corpus, corpus_id, with_for_update=True)
            if not corpus:
                raise JobFailed("CORPUS_DELETED", "语料库已删除")
            documents, late = _skip_duplicates(db, corpus_id, documents, alignments)
            skipped += late
            total = len(documents)
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
            if corpus.language in ("auto", "") and documents:
                shares = Counter()
                for d in documents:
                    shares[nlp.lang_code(d.language)] += len(d.text)
                corpus.language = shares.most_common(1)[0][0] or corpus.language
            # nothing new (all duplicates) leaves a searchable index as it is
            if documents or not live_index(corpus):
                index_job = db.scalar(
                    select(Job).where(
                        Job.kind == "index",
                        Job.state == "queued",
                        Job.params["corpus_id"].astext == str(corpus_id),
                    )
                )
                tokens = corpus_tokens(db, corpus_id)
                if index_job is None:
                    enqueue(
                        db,
                        "index",
                        {"corpus_id": str(corpus_id), "tokens": tokens},
                        run.owner_id,
                        run.project_id,
                    )
                else:
                    index_job.params = {**index_job.params, "tokens": tokens}
            # a searchable corpus keeps serving its old index until the new one is in
            if not live_index(corpus):
                corpus.status = "indexing"
            corpus.error = None
            run.succeed(
                db,
                {
                    "documents": total,
                    "sentences": sum(len(d.sentences) for d in documents),
                    "tokens": sum(
                        len(s.tokens) for d in documents for s in d.sentences
                    ),
                    "alignments": len(pairs),
                    "skipped_duplicates": len(skipped),
                    "duplicates": skipped[:DUPLICATES_LISTED],
                },
            )
    except BaseException:
        for path in written:
            path.unlink(missing_ok=True)
        raise
    shutil.rmtree(run.params["dir"], ignore_errors=True)


# ---- index ----


def _load_batches(docs):
    """Group (id, token_count) rows into load rounds of at most LOAD_BATCH documents and LOAD_TOKENS
    tokens; a document larger than LOAD_TOKENS is a round of its own."""
    batch, tokens = [], 0
    for doc_id, n in docs:
        if batch and (len(batch) >= LOAD_BATCH or tokens + n > LOAD_TOKENS):
            yield batch
            batch, tokens = [], 0
        batch.append(doc_id)
        tokens += n
    if batch:
        yield batch


def _load_documents(docs, run):
    """Stream (document id, engine Document) from the database in the given order, one load round at a time.
    Rows are read as plain tuples; ORM objects for millions of tokens would not fit in memory. A document
    deleted since the list was read is left out: the deletion queued another index build."""
    total = len(docs)
    done = 0
    for batch in _load_batches(docs):
        run.progress(done, total, "建索引", "篇")
        with session() as db:
            rows = {
                r.id: r
                for r in db.execute(
                    select(
                        Document.id,
                        Document.title,
                        Document.language,
                        Document.meta,
                        Document.external_id,
                        Document.text_path,
                    ).where(Document.id.in_(batch))
                )
            }
            sentences = db.execute(
                select(
                    Sentence.id,
                    Sentence.document_id,
                    Sentence.start_cp,
                    Sentence.end_cp,
                )
                .where(Sentence.document_id.in_(batch))
                .order_by(Sentence.document_id, Sentence.idx)
            ).all()
            by_sentence = {}
            for sid, *fields in db.execute(
                select(
                    Token.sentence_id,
                    Token.start_cp,
                    Token.end_cp,
                    Token.form,
                    Token.pos,
                    Token.lemma,
                    Token.head,
                    Token.deprel,
                )
                .join(Sentence, Sentence.id == Token.sentence_id)
                .where(Sentence.document_id.in_(batch))
                .order_by(Token.sentence_id, Token.idx)
                .execution_options(yield_per=50_000)
            ):
                by_sentence.setdefault(sid, []).append(em.Token(*fields))
        by_doc = {}
        for sid, doc_id, a, b in sentences:
            by_doc.setdefault(doc_id, []).append(
                em.Sentence(a, b, by_sentence.pop(sid, []))
            )
        del sentences
        for doc_id in batch:
            d = rows.get(doc_id)
            try:
                text = d and Path(d.text_path).read_text(encoding="utf-8")
            except FileNotFoundError:
                text = None
            if d is None or text is None:
                log.info("index: document %s deleted meanwhile, left out", doc_id)
                continue
            yield (
                str(doc_id),
                em.Document(
                    title=d.title,
                    language=d.language,
                    text=text,
                    metadata=d.meta,
                    sentences=by_doc.pop(doc_id, []),
                    external_id=d.external_id,
                ),
            )
        done += len(batch)


def run_index(run):
    corpus_id = uuid.UUID(run.params["corpus_id"])
    with transaction() as db:
        corpus = _corpus(db, corpus_id)
        if not live_index(corpus):
            corpus.status = "indexing"
        docs = db.execute(
            select(Document.id, Document.token_count)
            .where(Document.corpus_id == corpus_id)
            .order_by(Document.created_at, Document.id)
        ).all()
    info = None
    stream = _load_documents(docs, run)
    first = next(stream, None)  # None: no documents, or all deleted meanwhile
    if first is not None:
        # documents and their ids from one stream (tee keeps the two in step)
        a, b = itertools.tee(itertools.chain([first], stream))
        info = cwb.build(
            index_dir(corpus_id),
            corpus_key(corpus_id),
            (doc for _, doc in a),
            (i for i, _ in b),
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
        stats = {"documents": docs, "sentences": int(sentences), "tokens": int(tokens)}
        if corpus.parallel:
            stats["pairs"] = _pair_count(db, corpus_id)
        corpus.stats = stats
        corpus.meta = corpus_profile(db, corpus, info.tagset if info else None)
        corpus.index_version = info.index_version if info else None
        corpus.status = "ready" if info else "empty"
        corpus.error = None
        semantic.mark_stale(db, corpus)
        run.succeed(db, {**corpus.stats, "index_version": corpus.index_version})


def _pair_count(db, corpus_id):
    """Sentence pairs whose source sentence is in the corpus (parallel corpora)."""
    return db.scalar(
        select(func.count())
        .select_from(SentenceAlignment)
        .join(Sentence, Sentence.id == SentenceAlignment.src_sentence_id)
        .join(Document, Document.id == Sentence.document_id)
        .where(Document.corpus_id == corpus_id)
    )


PROFILE_SENTENCES = 3000


def corpus_profile(db, corpus, tagset):
    """corpus.meta with the index profile filled in: tagset (upos | jieba | mixed, as the query engine
    resolves POS), languages (document language codes by text share), script of the Chinese text
    (simplified | traditional | mixed; absent without enough Chinese) and indexed_at."""
    meta = {
        k: v
        for k, v in (corpus.meta or {}).items()
        if k not in ("tagset", "script", "languages", "indexed_at")
    }
    shares, raw_zh = Counter(), []
    for raw, chars in db.execute(
        select(Document.language, func.sum(Document.char_count))
        .where(Document.corpus_id == corpus.id)
        .group_by(Document.language)
    ):
        code = nlp.lang_code(raw)
        shares[code] += int(chars or 0)
        if code == "zh":
            raw_zh.append(raw)
    if not shares:
        return meta
    meta["languages"] = [c for c, _ in shares.most_common() if c]
    if tagset:
        meta["tagset"] = tagset
    if raw_zh:
        # spread the sample over the whole corpus: the first sentences can be all one script (Tatoeba)
        zh = (
            select(Sentence.id, Sentence.text)
            .join(Document, Document.id == Sentence.document_id)
            .where(Document.corpus_id == corpus.id, Document.language.in_(raw_zh))
            .subquery()
        )
        n = db.scalar(select(func.count()).select_from(zh)) or 0
        step = max(1, n // PROFILE_SENTENCES)
        sample = db.scalars(
            select(zh.c.text)
            .where(func.mod(zh.c.id, step) == 0)
            .limit(PROFILE_SENTENCES)
        ).all()
        script = nlp.detect_script("".join(sample))
        if script:
            meta["script"] = script
    meta["indexed_at"] = datetime.now(UTC).isoformat(timespec="seconds")
    return meta


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
            "sentence_index": item["sentence_index"] + 1,  # 句 n in the KWIC, from 1
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


FORMULA_START = ("=", "+", "-", "@", "\t", "\r")


def excel_safe(value):
    """Spreadsheet formula injection: text starting with = + - @, a tab or a carriage return gets a leading
    apostrophe so Excel shows it as text; numbers and other values are unchanged."""
    if isinstance(value, str) and value.startswith(FORMULA_START):
        return "'" + value
    return value


def safe_rows(rows):
    return [[excel_safe(v) for v in row] for row in rows]


def _write_csv(path, header, rows, notice=()):
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f)
        if notice:
            writer.writerows([[excel_safe(line)] for line in notice] + [[]])
        writer.writerow([excel_safe(h) for h in header])
        writer.writerows(safe_rows(rows))


def _write_xlsx(path, header, rows, sheet="检索结果", notice=()):
    wb = Workbook(write_only=True)
    ws = wb.create_sheet(sheet)
    title_font = Font(name="宋体", bold=True)
    for line in notice:
        ws.append([excel_safe(line)])
    if notice:
        ws.append([])
    cells = []
    for title in header:
        cell = WriteOnlyCell(ws, value=excel_safe(title))
        cell.font = title_font
        cells.append(cell)
    ws.append(cells)
    for row in rows:
        ws.append([excel_safe(v) for v in row])
    wb.save(path)


SORT_NAMES = {"position": "按出处", "left": "按左语境", "right": "按右语境"}


def _export_result_rows(rows_dir):
    """The rows of the API's finished result set named by the job (services.api.search.SearchCache), or None
    when there is none or the API has evicted it meanwhile."""
    from services.api.search import SearchCache

    if not rows_dir:
        return None
    path = Path(rows_dir).resolve()
    if path.parent != SearchCache.root().resolve():
        return None
    try:
        return cwb.read_rows(path, 0)
    except FileNotFoundError:
        return None


def _export_head(db, corpus, req, text, counts, at):
    """The line above an exported search table: what was searched and counted (as the source lines)."""
    info = _scope_info(db, req.scope, corpus)
    scope = info["name"]
    if req.scope.filter is not None:
        scope += f"（临时筛选 {json.dumps(req.scope.filter, ensure_ascii=False)}）"
    parts = [f"查询式：{req.query}"]
    if text != req.query:
        parts.append(f"简繁通查：{text}")
    parts.append(f"范围：{scope}")
    if req.aligned is not None:
        op = "含" if req.aligned.op == "+" else "不含"
        parts.append(f"译文条件：{op} {req.aligned.query}")
    parts += [f"命中：{counts.hits}", f"句：{counts.sentences}"]
    parts.append(f"文档：{counts.documents}")
    sort = SORT_NAMES.get(req.sort) or f"随机（种子 {req.seed}）"
    parts.append(f"排序：{sort}")
    parts.append(f"导出时间：{at:%Y-%m-%d %H:%M} UTC")
    parts.append(f"索引版本：{corpus.index_version or '—'}")
    return "；".join(parts)


def run_export(run):
    """Hits of a search (contracts/p11.md §一): the rows of the API's finished result set (params.rows_dir),
    else the complete rows computed once; texts and context are read EXPORT_PAGE rows at a time. The file
    opens with the query, scope, translation condition, counts, sort, export time and index version, then the
    source lines; 句序 counts from 1 as in the KWIC."""
    import subprocess

    from services.api.search import (
        complete_rows,
        plan_search,
        rows_hits,
        search_context,
        too_many_text,
        variants_on,
    )

    req = ExportInput.model_validate(run.params)  # seed and 简繁通查 pinned at enqueue
    items = []
    with session() as db:
        user = db.get(User, run.owner_id)
        corpus, restrict = resolve_scope(db, req.scope, user)
        tagset = corpus_tagset(corpus)
        text, ast, cqp = plan_search(corpus, req, tagset)
        layers = effective.check_layers(db, req.layers, corpus, user)
        with_span_layer(db, cqp, layers, corpus, user)
        aligned = req.aligned
        if aligned is not None and variants_on(corpus, req):
            try:
                expanded = query.script_variants(aligned.query, tagset)
                aligned = aligned.model_copy(update={"query": expanded})
            except query.QueryError:
                pass  # plan_aligned reports it
        keep = _aligned_keep(db, corpus, user, aligned, layers, req.scope)
        rows = None
        if run.params.get("rows_index_version") == corpus.index_version:
            rows = _export_result_rows(run.params.get("rows_dir"))
        if rows is None:  # no stored rows, or the index was rebuilt since
            try:
                rows = complete_rows(
                    db,
                    corpus,
                    restrict,
                    ast,
                    cqp,
                    layers,
                    req,
                    keep,
                    EXPORT_COUNT_TIMEOUT,
                    run.cancel,
                )
            except subprocess.TimeoutExpired as e:
                raise JobFailed(
                    "TIMEOUT",
                    f"检索超时（{EXPORT_COUNT_TIMEOUT} 秒），请缩小范围或加条件",
                ) from e
            except cwb.TooManyHits as e:
                raise JobFailed("TOO_MANY_HITS", too_many_text(e)) from e
        counts = cwb.count_rows(rows)
        ctx = search_context(corpus, req)
        for i in range(0, len(rows), EXPORT_PAGE):
            run.check()
            chunk = rows_hits(db, corpus, ast, cqp, rows[i : i + EXPORT_PAGE], ctx)
            items += enrich(db, chunk)
            run.progress(len(items), counts.hits, "导出")
        head = _export_head(db, corpus, req, text, counts, datetime.now(UTC))
        notice = [head, *source_notice(db, [corpus.id])]
    run.check()
    header, out = _rows(items)
    _finish_export(run, "检索结果", header, out, {"hits": counts.hits}, notice)


def _aligned_keep(db, corpus, user, aligned, layers, scope=None):
    """Sentences of a translation condition (contracts/p8.md §四) for export and distribution; None without
    one. Engine timeouts fail the job."""
    import subprocess

    from services.api.errors import ApiError
    from services.api.search import aligned_keep, plan_aligned

    if aligned is None:
        return None
    try:
        plan = plan_aligned(db, corpus, user, aligned, layers, scope)
        return aligned_keep(db, corpus, plan, EXPORT_COUNT_TIMEOUT)
    except ApiError as e:
        raise JobFailed(e.code, e.message) from e
    except subprocess.TimeoutExpired as e:
        raise JobFailed("TIMEOUT", "译文条件检索超时，请缩小条件") from e
    except cwb.TooManyHits as e:
        raise JobFailed("TOO_MANY_HITS", "译文条件命中过多，请加条件") from e


SOURCE_FIELDS = (
    ("license", "许可"),
    ("attribution", "署名"),
    ("source_url", "链接"),
    ("version", "版本"),
)


def source_notice(db, corpus_ids):
    """One line per corpus that has a license or attribution (Corpus.meta), for the top of exports."""
    lines = []
    for cid in dict.fromkeys(str(c) for c in corpus_ids if c):
        corpus = db.get(Corpus, uuid.UUID(cid))
        meta = (corpus.meta or {}) if corpus else {}
        if not (meta.get("license") or meta.get("attribution")):
            continue
        parts = [f"来源：{corpus.name}"]
        parts += [f"{label}：{meta[k]}" for k, label in SOURCE_FIELDS if meta.get(k)]
        lines.append("；".join(parts))
    return lines


def _finish_export(run, name, header, rows, extra=None, notice=()):
    """notice: source / license lines written above the table (csv, xlsx) or under the title (docx)."""
    fmt = run.params["format"]
    path = export_path(run.id, fmt)
    path.parent.mkdir(parents=True, exist_ok=True)
    if fmt == "csv":
        _write_csv(path, header, rows, notice)
    elif fmt == "xlsx":
        _write_xlsx(path, header, rows, name, notice)
    else:
        _write_docx(path, name, header, rows, notice)
    filename = f"{name}-{datetime.now():%Y%m%d-%H%M}.{fmt}"
    with transaction() as db:
        run.lock(db)
        run.succeed(db, {"rows": len(rows), **(extra or {}), "filename": filename})


def _write_docx(path, title, header, rows, notice=()):
    """One block per row: the first column as a paragraph, the others as `label：value` lines. 宋体, no fills."""
    doc = DocxDocument()
    normal = doc.styles["Normal"]
    normal.font.name = "宋体"
    normal.element.rPr.rFonts.set(qn("w:eastAsia"), "宋体")
    heading = doc.add_paragraph().add_run(title)
    heading.bold, heading.font.size = True, Pt(16)
    for line in notice:
        doc.add_paragraph(line)
    for i, row in enumerate(rows, 1):
        doc.add_paragraph(f"{i}. {row[0]}")
        for label, value in zip(header[1:], row[1:]):
            if value not in (None, ""):
                doc.add_paragraph(f"{label}：{value}")
    doc.save(path)


def run_export_stats(run):
    """Rows of a StatResult; the file opens with the method, parameters, scope and token totals (punctuation
    included), then the source / license lines. Decimal values are rounded to 2 places (4 for the measures
    between −1 and 1: DP, DPnorm, Juilland D, ΔP, Dice). Translation rows add the translation condition."""
    methods = {
        "frequency": "频次",
        "ngrams": "n-gram",
        "collocations": "搭配",
        "keywords": "关键词",
        "distribution": "分布",
        "breakdown": "命中分解",
        "translations": "译法",
        "text_metrics": "文本指标",
        "vocab_profile": "词汇等级",
        "compare": "多项对比",
        "word_sketch": "Word Sketch",
        "sketch_diff": "近义词对比",
    }
    units = {
        "word": "词形",
        "lemma": "词元",
        "pos": "词性",
        "deprel": "依存关系",
        "span_label": "片段标签",
        "relation_label": "关系标签",
    }
    measures = {
        "logdice": "logDice",
        "mi": "MI",
        "t": "t 值",
        "ll": "LL",
        "log_ratio": "Log Ratio",
        "mi3": "MI3",
        "delta_p": "ΔP",
        "z": "z 值",
        "pct_diff": "%DIFF",
        "odds_ratio": "Odds Ratio",
        "dice": "Dice",
    }
    by_labels = {
        "word": "词形",
        "lemma": "词元",
        "pos": "词性",
        "left1": "左一词",
        "right1": "右一词",
    }
    directions = {"negative": "参照多于目标", "both": "双向"}
    fine = {"dp", "dp_norm", "juilland_d", "delta_p_node", "delta_p_coll", "dice"}
    fine |= {"ttr", "sttr", "lexical_density"}  # text metrics between 0 and 1
    with session() as db:
        stat = db.get(StatResult, uuid.UUID(run.params["stat_id"]))
        if not stat:
            raise JobFailed("STAT_DELETED", "统计结果已删除")
        columns, path = stat.columns, Path(stat.rows_path)
        p, method, totals = stat.params or {}, stat.method, stat.totals or {}
        reference = p.get("reference") or {}
        scope_name, created = stat.scope.get("name", ""), stat.created_at
        index_version = stat.index_version
        notice = source_notice(
            db, [stat.scope.get("corpus_id"), reference.get("corpus_id")]
        )
    label = methods.get(method, method)
    parts = []
    if method == "ngrams":
        parts.append(f"n={p.get('n')}")
    if p.get("unit"):
        parts.append(f"单位 {units.get(p['unit'], p['unit'])}")
    if p.get("node"):
        parts.append(f"节点词 {p['node']}")
    if p.get("window"):
        parts.append(f"窗口 ±{p['window']}")
    if p.get("query"):
        parts.append(f"查询式 {p['query']}")
    if p.get("pos"):
        parts.append(f"词性 {p['pos']}")
    if p.get("pos_pattern"):
        parts.append("词性模式 " + " ".join(t or "*" for t in p["pos_pattern"]))
    if p.get("contains"):
        parts.append(f"包含词 {p['contains']}")
    if method == "collocations" and p.get("measures"):
        parts.append(f"排序指标 {measures.get(p['measures'][0], p['measures'][0])}")
    if method in ("keywords", "translations") and p.get("measure"):
        parts.append(f"指标 {measures.get(p['measure'], p['measure'])}")
    if method == "keywords" and p.get("direction") in directions:
        parts.append(f"方向 {directions[p['direction']]}")
    if method == "keywords" and p.get("items"):
        parts.append("指定词 " + "、".join(p["items"]))
    if method == "breakdown" and p.get("by"):
        by = p["by"]
        parts.append(f"按 {by_labels.get(by) or by.removeprefix('meta:')}")
    if method == "text_metrics":
        if p.get("group_by"):
            parts.append(f"按 {p['group_by']} 分组")
        parts.append(f"STTR 窗口 {p.get('sttr_window', 1000)}")
    if method == "vocab_profile":
        vl = p.get("vocab_list") or {}
        by = p.get("by", "corpus")
        names = {"corpus": "全部", "document": "每篇文档"}
        parts.append(f"词表 {vl.get('name', '')}（{vl.get('license') or '—'}）")
        parts.append(f"按 {names.get(by, by)}")
    if method == "compare":
        items = p.get("items") or []
        parts.append(
            "对比项 " + "、".join(f"{i['label']}：{i['query']}" for i in items)
        )
        if p.get("by"):
            parts.append(f"按 {p['by']}")
        tests = {"mann_whitney": "Mann-Whitney U", "spearman": "Spearman ρ"}
        if p.get("test") in tests:
            parts.append(f"检验 {tests[p['test']]}")
    if method == "word_sketch" and p.get("lemma"):
        parts.append(f"词元 {p['lemma']}")
    if method == "sketch_diff":
        parts.append(f"词元 {p.get('lemma_a')} 对 {p.get('lemma_b')}")
    if method == "translations" and p.get("target_language"):
        parts.append(f"译文语言 {p['target_language']}")
    if method == "frequency" and p.get("dispersion"):
        kind = p.get("parts", "document")
        names = {"document": "文档", "segments": "等分 10 段"}
        parts.append(f"离散度部分 {names.get(kind) or kind.removeprefix('field:')}")
    if method == "distribution":
        field = p.get("field")
        parts.append("按 文档位置" if field == "position" else f"按 {field}")
        if field == "position" and p.get("bins"):
            parts.append(f"区间 {p['bins']}")
    if p.get("min_freq") is not None:
        parts.append(f"最低频次 {p['min_freq']}")
    if p.get("top"):
        parts.append(f"显示前 {p['top']}")
    if p.get("exclude_punct"):
        parts.append("排除标点和数字")
    # word / lemma values (contracts/p11.md §一); results stored before the option say nothing
    cased = p.get("unit") in ("word", "lemma") or (
        method == "breakdown" and p.get("by") in ("word", "lemma", "left1", "right1")
    )
    if "case_sensitive" in p and cased:
        parts.append(f"区分大小写：{'是' if p['case_sensitive'] else '否'}")
    head = [f"统计：{label}（{'；'.join(parts)}）"]
    head.append(f"范围：{scope_name}，{totals.get('tokens', 0):,} 词（含标点）")
    if reference:
        ref_tokens = (totals.get("reference") or {}).get("tokens", 0)
        head.append(f"参照：{reference.get('name', '')}，{ref_tokens:,} 词（含标点）")
    at = created.astimezone(UTC)
    head.append(f"索引版本：{index_version or '—'}；计算时间：{at:%Y-%m-%d %H:%M} UTC")
    run.check()
    data = json.loads(path.read_text(encoding="utf-8"))["rows"]
    header = [c["label"] for c in columns] + ["查询式"]
    aligned = method == "translations"
    if aligned:
        header.append("译文条件")

    def value(key, v):
        v = _cell(v)
        return round(v, 4 if key in fine else 2) if isinstance(v, float) else v

    def condition(r):
        cond = r.get("search_aligned")
        return f"{cond['op']}{cond['query']}" if cond else None

    rows = [
        [value(c["key"], r["values"].get(c["key"])) for c in columns]
        + [r["search_query"]]
        + ([condition(r)] if aligned else [])
        for r in data
    ]
    _finish_export(run, f"统计-{label}", header, rows, notice=[*head, *notice])


def run_export_evidence(run):
    with session() as db:
        items = db.scalars(
            select(Evidence)
            .where(Evidence.project_id == uuid.UUID(run.params["project_id"]))
            .order_by(Evidence.created_at, Evidence.id)
        ).all()
        # source / license lines for the corpora behind pinned hits and stat rows
        corpus_ids = []
        for e in items:
            if e.ref.get("document_id"):
                doc = db.get(Document, uuid.UUID(e.ref["document_id"]))
                corpus_ids.append(doc and doc.corpus_id)
            if e.ref.get("stat_id"):
                stat = db.get(StatResult, uuid.UUID(e.ref["stat_id"]))
                if stat:
                    reference = (stat.params or {}).get("reference") or {}
                    corpus_ids += [
                        stat.scope.get("corpus_id"),
                        reference.get("corpus_id"),
                    ]
        notice = source_notice(db, corpus_ids)
    run.check()
    # hits pinned with their sentence (services.api.evidence.sentence_evidence): 原文 is that sentence alone,
    # 命中 the matched text, 译文 the aligned sentences; older items and other kinds keep their text
    header = ["原文", "命中", "译文", "出处", "查询式", "备注"]
    rows = []
    for e in items:
        sentence, (a, b) = e.ref.get("sentence"), e.ref.get("match") or (0, 0)
        aligned = "\n".join(
            f"[{x['language']}] {x['text']}" for x in e.ref.get("aligned") or []
        )
        rows.append(
            [
                sentence or e.text,
                sentence[a:b] if sentence else None,
                aligned or None,
                e.source,
                e.ref.get("search_query"),
                e.note,
            ]
        )
    if run.params["format"] != "docx":
        _finish_export(run, "证据篮", header, rows, notice=notice)
        return
    path = export_path(run.id, "docx")
    path.parent.mkdir(parents=True, exist_ok=True)
    _write_evidence_docx(path, items, header, rows, notice)
    with transaction() as db:
        run.lock(db)
        run.succeed(
            db,
            {
                "rows": len(rows),
                "filename": f"证据篮-{datetime.now():%Y%m%d-%H%M}.docx",
            },
        )


def _write_evidence_docx(path, items, header, rows, notice):
    """Like _write_docx, with the hit in bold inside its sentence and no separate 命中 line."""
    doc = DocxDocument()
    normal = doc.styles["Normal"]
    normal.font.name = "宋体"
    normal.element.rPr.rFonts.set(qn("w:eastAsia"), "宋体")
    heading = doc.add_paragraph().add_run("证据篮")
    heading.bold, heading.font.size = True, Pt(16)
    for line in notice:
        doc.add_paragraph(line)
    for i, (e, row) in enumerate(zip(items, rows), 1):
        p = doc.add_paragraph(f"{i}. ")
        sentence, span = e.ref.get("sentence"), e.ref.get("match")
        if sentence and span:
            a, b = span
            p.add_run(sentence[:a])
            p.add_run(sentence[a:b]).bold = True
            p.add_run(sentence[b:])
        else:
            p.add_run(row[0])
        for label, value in zip(header[2:], row[2:]):
            if value not in (None, ""):
                doc.add_paragraph(f"{label}：{value}")
    doc.save(path)


def _conllu_doc_id(doc, used):
    """`# newdoc id` / sent_id prefix: the document's external id (UD sources) or its title, whitespace as
    `_`; a repeated title gets -2, -3…"""
    base = "_".join((doc.external_id or doc.title or "doc").split()) or "doc"
    out, n = base, 1
    while out in used:
        n += 1
        out = f"{base}-{n}"
    used.add(out)
    return out


def run_export_layer(run):
    """CoNLL-U of a layer's documents with effective values: this layer's confirmed / modified annotations,
    otherwise the system values in `tokens` (for the other kind always the system values). Other formats
    (brat, json, tmx, xlsx): services.worker.annot_tasks."""
    fmt = run.params.get("format", "conllu")
    if fmt != "conllu":
        return annot_tasks.EXPORTS[fmt](run, uuid.UUID(run.params["layer_id"]))
    with session() as db:
        layer = db.get(AnnotationLayer, uuid.UUID(run.params["layer_id"]))
        if not layer:
            raise JobFailed("LAYER_DELETED", "标注层已删除")
        ids = run.params.get("document_ids") or layer.document_ids
        stmt = select(Document).where(Document.corpus_id == layer.corpus_id)
        if ids:
            stmt = stmt.where(Document.id.in_(ids))
        docs = db.scalars(stmt.order_by(Document.created_at, Document.id)).all()
        layers = {"pos": None, "dep": None, layer.kind: effective.eff_layer(layer)}
        name, kind = layer.name, layer.kind
        notice = source_notice(db, [layer.corpus_id])
    parts, sentences, tokens = [f"# {line}\n" for line in notice], 0, 0
    parts.append(f"# 导出口径：{annot_tasks.EXPORT_SCOPE[kind]}\n")
    used = set()
    for i in range(0, len(docs), LOAD_BATCH):
        batch = docs[i : i + LOAD_BATCH]
        run.progress(i, len(docs), "导出")
        with session() as db:
            toks = effective.layer_tokens(db, [d.id for d in batch], layers)
            spans = db.execute(
                select(
                    Sentence.document_id,
                    Sentence.idx,
                    Sentence.start_cp,
                    Sentence.end_cp,
                )
                .where(Sentence.document_id.in_([d.id for d in batch]))
                .order_by(Sentence.document_id, Sentence.idx)
            ).all()
        by_doc = {}
        for doc_id, idx, a, b in spans:
            sent_toks = [em.Token(*t) for t in toks.get(doc_id, {}).get(idx, [])]
            by_doc.setdefault(doc_id, []).append(em.Sentence(a, b, sent_toks))
        out = []
        for d in batch:
            sents = by_doc.get(d.id, [])
            sentences += sum(1 for x in sents if x.tokens)
            tokens += sum(len(x.tokens) for x in sents)
            out.append(
                em.Document(
                    d.title,
                    d.language,
                    Path(d.text_path).read_text(encoding="utf-8"),
                    {},
                    sents,
                    _conllu_doc_id(d, used),
                )
            )
        parts.append(write_conllu(out))
    path = export_path(run.id, "conllu")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(parts), encoding="utf-8", newline="\n")
    safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in name)
    filename = f"{safe}-{datetime.now():%Y%m%d-%H%M}.conllu"
    with transaction() as db:
        run.lock(db)
        run.succeed(db, {"rows": sentences, "tokens": tokens, "filename": filename})


TIDY_NAME = "tidy_data"
TIDY_METRIC_UNITS = {
    "words": "词",
    "mean_sentence_length": "词/句",
    "mean_dependency_distance": "词",
    "flesch_kincaid_grade": "年级",
}


def _snake(text):
    import re

    return re.sub(r"[^\w]+", "_", str(text).strip().lower()).strip("_") or "field"


def run_export_tidy(run):
    """Tidy data (contracts/p10.md §三): one row per document of the scope (corpus order) with its metadata
    fields, tokens and sentences, per query hits and hits per million tokens (counted as search counts them),
    and with metrics=true the text metrics (engine.metrics, STTR window 1000). The codebook lists every
    column: name, meaning, unit, query. csv: zip of tidy_data.csv and tidy_data.codebook.csv (UTF-8, no BOM)
    plus source.txt when the corpus has a license; xlsx: sheets data, codebook (and source)."""
    import zipfile

    from engine import metrics

    p = run.params
    queries, layers = p.get("queries") or [], p.get("query_layers") or []
    with stats.cancellable(run.cancel), session() as db:
        user = db.get(User, run.owner_id)
        scope = Scope.model_validate(p["scope"])
        corpus, restrict = resolve_scope(db, scope, user)
        target = stats.Scope(index_dir(corpus.id), corpus_key(corpus.id), restrict)
        notice = source_notice(db, [corpus.id])
        info = _scope_docs(db, corpus, scope)
        counts = []
        for i, q in enumerate(queries):
            run.progress(i, len(queries), f"统计查询 {i + 1}")
            item_layers = layers[i] if i < len(layers) else None
            try:
                hits, _ = _doc_hits(db, q, item_layers, corpus, scope, user, target)
            except ValueError as e:
                raise JobFailed("EXPORT_INVALID", f"{q}：{e}") from e
            counts.append(hits)
        doc_metrics = {}
        if p.get("metrics"):
            run.progress(0, len(info), "计算文本指标", "篇")
            check = _ticker(run, len(info))
            for doc in _index_docs(target, info):
                check()
                doc_metrics[doc.id] = metrics.document_metrics(doc)
    meta_keys = sorted({k for v in info.values() for k in v[2]})
    columns = [  # (name, meaning, unit, query)
        ("document_id", "文档 ID", "", ""),
        ("title", "文档标题", "", ""),
        ("language", "语言代码", "", ""),
    ]
    used = {c[0] for c in columns}
    meta_names = []
    for k in meta_keys:
        name, n = f"meta_{_snake(k)}", 2
        while name in used:
            name, n = f"meta_{_snake(k)}_{n}", n + 1
        used.add(name)
        meta_names.append(name)
        columns.append((name, f"元数据字段：{k}", "", ""))
    columns += [
        ("tokens", "词数（含标点，每百万词的分母）", "词", ""),
        ("sentences", "句数", "句", ""),
    ]
    for i, q in enumerate(queries, 1):
        columns += [
            (f"q{i}_hits", f"查询 {i} 的命中数（同检索计数）", "次", q),
            (
                f"q{i}_pm",
                f"查询 {i} 每百万词命中数 = 命中数 / 词数 × 10⁶",
                "次/百万词",
                q,
            ),
        ]
    if p.get("metrics"):
        columns += [
            (m, metrics.LABELS[m], TIDY_METRIC_UNITS.get(m, ""), "")
            for m in metrics.METRICS
            if m != "sentences"
        ]
    rows = []
    for doc_id, (title, language, meta, tokens, sentences) in info.items():
        row = [doc_id, title, language]
        row += [_cell(meta.get(k)) for k in meta_keys]
        row += [tokens, sentences]
        for hits in counts:
            h = hits.get(doc_id, 0)
            row += [h, h / tokens * 1e6 if tokens else None]
        if p.get("metrics"):
            m = doc_metrics.get(doc_id) or {}
            row += [m.get(k) for k in metrics.METRICS if k != "sentences"]
        rows.append(row)
    run.check()
    header = [c[0] for c in columns]
    book_header = ["column", "description", "unit", "query"]
    book = [list(c) for c in columns]
    fmt = p["format"]
    path = export_path(run.id, fmt)
    path.parent.mkdir(parents=True, exist_ok=True)
    if fmt == "zip":
        import io

        def csv_bytes(head, body):
            buf = io.StringIO(newline="")
            writer = csv.writer(buf)
            writer.writerow([excel_safe(h) for h in head])
            writer.writerows(safe_rows(body))
            return buf.getvalue().encode("utf-8")

        with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
            z.writestr(f"{TIDY_NAME}.csv", csv_bytes(header, rows))
            z.writestr(f"{TIDY_NAME}.codebook.csv", csv_bytes(book_header, book))
            if notice:
                z.writestr("source.txt", "\n".join(notice) + "\n")
    else:
        wb = Workbook(write_only=True)
        title_font = Font(name="宋体", bold=True)
        sheets = [("data", header, rows), ("codebook", book_header, book)]
        if notice:
            sheets.append(("source", ["source"], [[line] for line in notice]))
        for name, head, body in sheets:
            ws = wb.create_sheet(name)
            cells = []
            for title in head:
                cell = WriteOnlyCell(ws, value=excel_safe(title))
                cell.font = title_font
                cells.append(cell)
            ws.append(cells)
            for r in body:
                ws.append([excel_safe(v) for v in r])
        wb.save(path)
    filename = f"整洁数据-{datetime.now():%Y%m%d-%H%M}.{fmt}"
    with transaction() as db:
        run.lock(db)
        run.succeed(
            db,
            {"rows": len(rows), "columns": len(columns), "filename": filename},
        )


EXPORTS = {
    "search": run_export,
    "stats": run_export_stats,
    "tidy": run_export_tidy,
    "evidence": run_export_evidence,
    "layer": run_export_layer,
    "kb_terms": kb_tasks.run_export_terms,
    "kb_note": kb_tasks.run_export_note,
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


def _compute(p, target, reference, numeric, positions=None):
    method, top = p["method"], p["top"]
    punct = p.get("exclude_punct", False)  # jobs queued before the option: kept
    case = {"case_sensitive": p.get("case_sensitive", False)}  # contracts/p11.md §一
    if method == "frequency":
        return stats.frequency(
            target,
            p["unit"],
            p["pos"],
            top,
            p["min_freq"],
            exclude_punct=punct,
            parts=p.get("parts", "document"),
            dispersion=p.get("dispersion", False),  # jobs queued before P8: none
            **case,
        )
    if method == "ngrams":
        return stats.ngrams(
            target,
            p["n"],
            p["unit"],
            p["pos_pattern"],
            top,
            p["min_freq"],
            contains=p.get("contains"),
            exclude_punct=punct,
            **case,
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
            exclude_punct=punct,
            **case,
        )
    if method == "keywords":
        return stats.keywords(
            target,
            reference,
            p["unit"],
            p["measure"],
            p["min_freq"],
            top,
            exclude_punct=punct,
            direction=p.get("direction", "positive"),
            items=p.get("items"),
            **case,
        )
    return stats.distribution(
        target,
        p["query"],
        p["field"],
        p["bins"],
        numeric=numeric,
        top=top,
        positions=positions,
    )


def _label_frequency(db, p, corpus, scope, user):
    """span_label / relation_label frequency of effective spans / relations in a scope."""
    layers = effective.check_layers(
        db, LayersInput.model_validate(p.get("layers") or {}), corpus, user
    )
    kind = p["unit"].split("_")[0]
    layer = layers[kind]
    if layer is None:
        raise JobFailed("INVALID_LAYER", f"缺少 {kind} 标注层")
    filt = scope_filter(db, scope)
    fields = field_types(db, corpus.id) if filt else {}
    counts, row_count, totals = effective.label_frequency(
        db, corpus, filt, fields, layer, p["unit"], p["top"], p["min_freq"]
    )
    rows = []
    for value, freq, docs in counts:
        per_million = freq / totals["tokens"] * 1e6 if totals["tokens"] else 0.0
        q = (
            f"[{value}]"
            if kind == "span" and _plain(value) and "[" not in value
            else None
        )
        rows.append(
            {
                "key": value,
                "values": {
                    "item": value,
                    "freq": freq,
                    "per_million": per_million,
                    "doc_freq": docs,
                },
                "search_query": q,
            }
        )
    columns = [
        {"key": "item", "label": "标签", "type": "string"},
        {"key": "freq", "label": "频次", "type": "number"},
        {"key": "per_million", "label": "每百万词", "type": "number"},
        {"key": "doc_freq", "label": "文档频率", "type": "number"},
    ]
    return stats.Table(columns, rows, row_count, totals)


def _span_positions(db, p, corpus, scope, user):
    """Token positions of the spans of a pure `[标签]` distribution query (None for other queries); with a
    translation condition (`aligned`) the positions of the filtered hits."""
    if not p.get("query"):
        return None
    if p.get("aligned"):
        return _aligned_positions(db, p, corpus, scope, user)
    ast, cqp = plan_query(p["query"], corpus_tagset(corpus))
    spans = query.spans(cqp)
    if not spans or not query.pure_span(ast):
        return None
    layers = effective.check_layers(
        db, LayersInput.model_validate(p.get("layers") or {}), corpus, user
    )
    with_span_layer(db, cqp, layers, corpus, user)
    filt = scope_filter(db, scope)
    fields = field_types(db, corpus.id) if filt else {}
    return effective.span_positions(db, corpus, filt, fields, layers["span"], spans[0])


def _aligned_positions(db, p, corpus, scope, user):
    """(document id, token offset in the document) of the hits of a distribution query that pass its
    translation condition, for engine.stats.distribution(positions=)."""
    import subprocess

    from services.api.search import AlignedInput, attr_filter_for

    ast, cqp = plan_query(p["query"], corpus_tagset(corpus))
    if query.spans(cqp) and query.pure_span(ast):
        raise JobFailed("STATS_INVALID", "带译文条件的分布不支持单独的 [标签] 查询")
    layers = effective.check_layers(
        db, LayersInput.model_validate(p.get("layers") or {}), corpus, user
    )
    with_span_layer(db, cqp, layers, corpus, user)
    keep = _aligned_keep(
        db, corpus, user, AlignedInput.model_validate(p["aligned"]), layers, scope
    )
    _, restrict = resolve_scope(db, scope, user)
    ix, key = index_dir(corpus.id), corpus_key(corpus.id)
    try:
        rows = cwb.query_rows(
            ix,
            key,
            cqp,
            restrict=restrict,
            timeout=EXPORT_COUNT_TIMEOUT,
            attr_filter=attr_filter_for(db, cqp, layers),
            aligned=keep,
            cancel=stats.cancel_event(),
        )
    except subprocess.TimeoutExpired as e:
        raise JobFailed("TIMEOUT", "检索超时，请缩小范围或加条件") from e
    starts = cwb.doc_starts(ix, key)
    return [(d, m - starts[d]) for m, _, d, _ in rows if d in starts]


def _pg_frequency(db, p, corpus, scope, user):
    """Frequency of effective POS tags (with layers.pos) or deprels, counted in PostgreSQL."""
    layers = effective.check_layers(
        db, LayersInput.model_validate(p.get("layers") or {}), corpus, user
    )
    tagset = corpus_tagset(corpus)
    pos_tags = query.resolve_pos(p["pos"], tagset) if p.get("pos") else None
    filt = scope_filter(db, scope)
    fields = field_types(db, corpus.id) if filt else {}
    counts, row_count, totals = effective.frequency(
        db, corpus, filt, fields, p["unit"], layers, pos_tags, p["top"], p["min_freq"]
    )
    rows = []
    for value, freq, docs in counts:
        if p["unit"] == "pos":
            q = (
                f"{{pos={value}}}"
                if _plain(value) and _resolves(value, tagset)
                else None
            )
        else:
            cond = f"pos={p['pos']}," if p.get("pos") else ""
            q = f"{{{cond}dep={value}}}" if _plain(value) else None
        per_million = freq / totals["tokens"] * 1e6 if totals["tokens"] else 0.0
        values = {
            "item": value,
            "freq": freq,
            "per_million": per_million,
            "doc_freq": docs,
        }
        rows.append({"key": value, "values": values, "search_query": q})
    columns = [
        {"key": "item", "label": "项", "type": "string"},
        {"key": "freq", "label": "频次", "type": "number"},
        {"key": "per_million", "label": "每百万词", "type": "number"},
        {"key": "doc_freq", "label": "文档频率", "type": "number"},
    ]
    return stats.Table(columns, rows, row_count, totals)


def _plain(value):
    return not any(c in value for c in ' ,{}|=/"')


def _resolves(value, tagset):
    try:
        return query.resolve_pos(value, tagset) == (value,)
    except query.QueryError:
        return False


def _hit_filter(db, p, corpus, user):
    """attr_filter for the `{…}` / `[…]` slots of a breakdown / translation query (layers stored by the api)."""
    from services.api.search import attr_filter_for

    _, cqp = plan_query(p["query"], corpus_tagset(corpus))
    layers = effective.check_layers(
        db, LayersInput.model_validate(p.get("layers") or {}), corpus, user
    )
    with_span_layer(db, cqp, layers, corpus, user)
    return attr_filter_for(db, cqp, layers)


def _breakdown(db, p, corpus, user, target):
    """Hit breakdown (contracts/p8.md §一); hits as search counts them, failing past SEARCH_MAX_HITS."""
    from services.api.search import MAX_HITS

    by = p["by"]
    numeric = (
        by.startswith("meta:") and field_types(db, corpus.id).get(by[5:]) == "number"
    )
    return stats.breakdown(
        target,
        p["query"],
        by,
        p["top"],
        p["min_freq"],
        numeric=numeric,
        attr_filter=_hit_filter(db, p, corpus, user),
        max_hits=MAX_HITS,
        case_sensitive=p.get("case_sensitive", False),
    )


def _chunks(items, size=2000):
    items = list(items)
    return [items[i : i + size] for i in range(0, len(items), size)]


def _translations(db, p, corpus, scope, user, target, params):
    """Translation statistics (contracts/p8.md §四, engine.translations): the hits' sentences, their aligned
    sentences in the target language and those sentences' tokens, then N and b over the scope."""
    from sqlalchemy import distinct, tuple_, union
    from sqlalchemy.orm import aliased

    from engine import translations
    from services.api.search import MAX_HITS

    rows, scope_totals = stats.hit_rows(
        target, p["query"], _hit_filter(db, p, corpus, user), MAX_HITS
    )
    keys = {(uuid.UUID(d), n) for _, _, d, n in rows}
    sentence_doc = {}  # hit sentence id → document id
    for chunk in _chunks(keys):
        sentence_doc.update(
            db.execute(
                select(Sentence.id, Sentence.document_id).where(
                    tuple_(Sentence.document_id, Sentence.idx).in_(chunk)
                )
            ).all()
        )
    doc_lang = dict(
        db.execute(
            select(Document.id, Document.language).where(
                Document.id.in_(set(sentence_doc.values()))
            )
        ).all()
    )
    other_s, other_d, link = aliased(Sentence), aliased(Document), SentenceAlignment
    sides = (
        (link.src_sentence_id, link.tgt_sentence_id),
        (link.tgt_sentence_id, link.src_sentence_id),
    )
    links = []  # (hit sentence, aligned sentence, its language)
    for chunk in _chunks(sentence_doc):
        for mine, other in sides:
            links += db.execute(
                select(mine, other, other_d.language)
                .select_from(link)
                .join(other_s, other_s.id == other)
                .join(other_d, other_d.id == other_s.document_id)
                .where(mine.in_(chunk))
            ).all()
    lang = p.get("target_language")
    if lang is None:
        others = Counter(
            lg for h, _, lg in links if lg != doc_lang.get(sentence_doc[h])
        )
        lang = others.most_common(1)[0][0] if others else None
    params["target_language"] = lang
    hit_targets = {h: [] for h in sentence_doc}
    for h, o, lg in links:
        if lg == lang:
            hit_targets[h].append(o)
    unit_col = Token.form if p["unit"] == "word" else Token.lemma
    # case variants merge unless case_sensitive (contracts/p11.md §一): keys lower-cased, spellings kept
    merge = not p.get("case_sensitive", False)
    key_col = func.lower(unit_col) if merge else unit_col
    fold, names = stats.folder(not merge), stats.Spellings()
    target_values = {}
    for chunk in _chunks({o for os in hit_targets.values() for o in os}):
        for sid, value in db.execute(
            select(Token.sentence_id, unit_col).where(
                Token.sentence_id.in_(chunk), unit_col.is_not(None)
            )
        ):
            target_values.setdefault(sid, set()).add(fold(value))
            names.add(fold(value), value, 1)
    a, n = translations.cooccurrence(
        hit_targets, target_values, p.get("exclude_punct", True)
    )
    # N and b: scope sentences aligned to a target-language sentence, and those whose aligned ones hold w
    filt = scope_filter(db, scope)
    fields = field_types(db, corpus.id) if filt else {}
    where = effective.scope_clauses(corpus, filt, fields)

    def pairs(mine, other):
        return (
            select(mine.label("sid"), other.label("tid"))
            .select_from(link)
            .join(Sentence, Sentence.id == mine)
            .join(Document, Document.id == Sentence.document_id)
            .join(other_s, other_s.id == other)
            .join(other_d, other_d.id == other_s.document_id)
            .where(*where, other_d.language == lang)
        )

    universe = union(*(pairs(m, o) for m, o in sides)).subquery()
    total = db.scalar(select(func.count(distinct(universe.c.sid)))) if lang else 0
    b = {}
    for chunk in _chunks(translations.candidates(a, p["min_freq"])):
        b.update(
            db.execute(
                select(key_col, func.count(distinct(universe.c.sid)))
                .select_from(universe)
                .join(Token, Token.sentence_id == universe.c.tid)
                .where(key_col.in_(chunk))
                .group_by(key_col)
            ).all()
        )
    totals = {
        **scope_totals,
        "hits": len(rows),
        "hit_sentences": len(sentence_doc),
        "aligned_sentences": n,
        "unaligned": len(sentence_doc) - n,
        "target_language": lang,
        "scope_aligned_sentences": total,
    }
    return translations.table(
        a,
        n,
        b,
        total,
        query_text=p["query"],
        unit=p["unit"],
        measure=p["measure"],
        top=p["top"],
        min_freq=p["min_freq"],
        totals=totals,
        spellings={k: names.all(k) for k in a} if merge else None,
    )


# ---- P10 statistics (contracts/p10.md §一、二、四、五) ----

P10_METHODS = ("text_metrics", "vocab_profile", "compare", "word_sketch", "sketch_diff")
LAYER_DOC_BATCH = 200  # documents per read of a dependency layer's effective tokens


def _ticker(run, total):
    """check() for the engine's per-document loops: cancellation, and progress every PROGRESS_SECONDS."""
    state = {"done": 0, "last": time.monotonic()}

    def check():
        run.check()
        state["done"] += 1
        if time.monotonic() - state["last"] >= PROGRESS_SECONDS:
            state["last"] = time.monotonic()
            run.progress(state["done"], total, "计算", "篇")

    return check


def _scope_docs(db, corpus, scope):
    """{document id: (title, language, metadata, tokens, sentences)} of a scope, in corpus order."""
    filt = scope_filter(db, scope)
    fields = field_types(db, corpus.id) if filt else {}
    rows = db.execute(
        select(
            Document.id,
            Document.title,
            Document.language,
            Document.meta,
            Document.token_count,
            Document.sentence_count,
        )
        .where(*effective.scope_clauses(corpus, filt, fields))
        .order_by(Document.created_at, Document.id)
    )
    return {str(i): (t, lg, m or {}, n, s) for i, t, lg, m, n, s in rows}


def _index_docs(target, info):
    """engine.metrics.Doc of the scope: system tokens from the index, title / language / metadata from the
    database (documents deleted since the index was built are left out)."""
    from engine.metrics import Doc

    for doc_id, sents in stats.documents(target):
        if doc_id in info:
            title, language, meta = info[doc_id][:3]
            yield Doc(doc_id, title, language, meta, sents)


def _layer_docs(db, info, layers):
    """engine.metrics.Doc with the effective tokens of the layers (dependency layer), from PostgreSQL."""
    from engine.metrics import Doc

    for chunk in _chunks(info, LAYER_DOC_BATCH):
        tokens = effective.layer_tokens(db, chunk, layers)
        for doc_id in chunk:
            by_sentence = tokens.get(uuid.UUID(doc_id), {})
            sents = [
                [
                    (form, pos, lemma, head, dep)
                    for _, _, form, pos, lemma, head, dep in toks
                ]
                for _, toks in sorted(by_sentence.items())
            ]
            title, language, meta = info[doc_id][:3]
            yield Doc(doc_id, title, language, meta, sents)


def _p10(db, run, corpus, scope, user, target, params):
    p, method = run.params, run.params["method"]
    if method == "compare":
        return _compare(db, run, user, params)
    info = _scope_docs(db, corpus, scope)
    check = _ticker(run, len(info))
    filt = scope_filter(db, scope)
    scope_totals = effective.scope_totals(
        db, corpus, filt, field_types(db, corpus.id) if filt else {}
    )
    if method == "text_metrics":
        from engine import metrics

        table = metrics.table(
            _index_docs(target, info),
            p.get("metrics"),
            p.get("group_by"),
            p.get("sttr_window", 1000),
            check=check,
        )
    elif method == "vocab_profile":
        table = _vocab_profile(db, p, target, info, check, params)
    else:
        table = _sketch(db, p, corpus, user, target, info, check)
    table.totals = {**scope_totals, **table.totals}
    return table


def _vocab_profile(db, p, target, info, check, params):
    from engine import vocab
    from services.api.models import VocabEntry, VocabList

    v = db.get(VocabList, uuid.UUID(p["list_id"]))
    if v is None:
        raise JobFailed("VOCAB_DELETED", "词表已删除")
    entries = dict(
        db.execute(
            select(VocabEntry.form, VocabEntry.level).where(VocabEntry.list_id == v.id)
        ).all()
    )
    params["vocab_list"] = {
        "id": str(v.id),
        "name": v.name,
        "language": v.language,
        "source": v.source,
        "license": v.license,
        "builtin": v.project_id is None,
    }
    return vocab.profile(
        _index_docs(target, info),
        entries,
        list(v.levels),
        v.language,
        p.get("by", "corpus"),
        check=check,
    )


def _sketch(db, p, corpus, user, target, info, check):
    """Word Sketch / sketch diff: the dependency layer of layers.dep (set by the api for corpora without system
    dependencies), else the index's system dependencies."""
    from engine import sketch

    tags = None
    if p.get("pos"):
        tags = set(query.resolve_pos(p["pos"], corpus_tagset(corpus)))
    dep = (p.get("layers") or {}).get("dep")
    if dep:
        layers = effective.check_layers(
            db, LayersInput.model_validate(p["layers"]), corpus, user
        )
        docs = _layer_docs(db, info, layers)
    else:
        docs = _index_docs(target, info)
    if p["method"] == "word_sketch":
        return sketch.sketch(
            docs, p["lemma"].strip(), tags, p["min_freq"], p["top"], check, dep
        )
    return sketch.diff(
        docs,
        p["lemma_a"].strip(),
        p["lemma_b"].strip(),
        tags,
        p["min_freq"],
        p["top"],
        check,
        dep,
    )


def _doc_hits(db, text, item_layers, corpus, scope, user, target):
    """(hits per document id, tokens per document id) of a query in a scope, counted as search counts them:
    a whole `{…}` / `[…]` query from PostgreSQL (effective annotations), others with CWB; more than
    SEARCH_MAX_HITS hits raise ValueError."""
    from services.api.search import MAX_HITS, pg_answered, pure_attr

    ast, cqp = plan_query(text, corpus_tagset(corpus))
    if not pg_answered(ast, cqp):
        attr_filter = _hit_filter(
            db, {"query": text, "layers": item_layers}, corpus, user
        )
        hits, sizes, _ = stats.doc_hits(target, text, attr_filter, MAX_HITS)
        return hits, sizes
    _, sizes, _ = stats.doc_hits(target, None)
    layers = effective.check_layers(
        db, LayersInput.model_validate(item_layers or {}), corpus, user
    )
    with_span_layer(db, cqp, layers, corpus, user)
    filt = scope_filter(db, scope)
    fields = field_types(db, corpus.id) if filt else {}
    if query.spans(cqp) and query.pure_span(ast):
        found = effective.scope_spans(
            db, corpus, filt, fields, layers["span"], query.spans(cqp)[0]
        )
        docs = [str(s["document_id"]) for s in found]
    else:
        assert pure_attr(ast)
        rows = effective.pg_rows(
            db,
            corpus,
            filt,
            fields,
            ast.anchor.items[0][0],
            query.attrs(cqp)[0],
            layers,
            limit=MAX_HITS + 1,
        )
        docs = [str(r[0]) for r in rows]
    if len(docs) > MAX_HITS:
        raise ValueError(f"命中超过 {MAX_HITS}，请缩小范围或加条件")
    return Counter(d for d in docs if d in sizes), sizes


def _compare(db, run, user, params):
    """Each item's hits per document (as search counts them, failing past SEARCH_MAX_HITS) and the scope's
    tokens per document from the index; metadata from the database when grouping by a field."""
    from engine import compare

    p = run.params
    by, layers = p.get("by"), p.get("query_layers") or [None] * len(p["items"])
    items, numeric = [], bool(by)
    for item, item_layers in zip(p["items"], layers):
        run.check()
        sc = Scope.model_validate(item["scope"])
        corpus, restrict = resolve_scope(db, sc, user)
        target = stats.Scope(index_dir(corpus.id), corpus_key(corpus.id), restrict)
        hits, sizes = _doc_hits(
            db, item["query"], item_layers, corpus, sc, user, target
        )
        meta = {}
        if by:
            meta = {d: v[2] for d, v in _scope_docs(db, corpus, sc).items()}
            numeric = numeric and field_types(db, corpus.id).get(by) == "number"
        items.append(
            {
                "label": item["label"],
                "scope_name": _scope_info(db, sc, corpus)["name"],
                "query": item["query"],
                "hits": hits,
                "sizes": sizes,
                "meta": meta,
                "search_query": item["query"],
                "search_scope": sc.model_dump(mode="json", exclude_none=True),
                "corpus_id": str(corpus.id),
                "base_filter": scope_filter(db, sc),
            }
        )
    params["item_scopes"] = [it["scope_name"] for it in items]
    return compare.table(items, by, numeric, p.get("test", "none"))


def run_stats(run):
    """CWB scans, CQP runs and the engine's loops stop soon after a cancel (run.cancel, contracts/p9.md §七)."""
    with stats.cancellable(run.cancel):
        _run_stats(run)


def _run_stats(run):
    p = run.params
    method = p["method"]
    scope = Scope.model_validate(p["target"] if method == "keywords" else p["scope"])
    params = {k: v for k, v in p.items() if k != "method"}
    reference = numeric = table = positions = None
    pg = method == "frequency" and (
        p["unit"] == "deprel"
        or (p["unit"] == "pos" and (p.get("layers") or {}).get("pos"))
    )
    labels = method == "frequency" and p["unit"] in ("span_label", "relation_label")
    with session() as db:
        user = db.get(User, run.owner_id)
        corpus, restrict = resolve_scope(db, scope, user)
        if labels:
            table = _label_frequency(db, p, corpus, scope, user)
        elif pg:
            table = _pg_frequency(db, p, corpus, scope, user)
        if method == "distribution":
            positions = _span_positions(db, p, corpus, scope, user)
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
        # breakdown / translations: attribute filters and aligned sentences read the database
        if method in ("breakdown", "translations"):
            run.progress(0, None, "计算")
            try:
                if method == "breakdown":
                    table = _breakdown(db, p, corpus, user, target)
                else:
                    table = _translations(db, p, corpus, scope, user, target, params)
            except ValueError as e:
                raise JobFailed("STATS_INVALID", str(e)) from e
        # P10: documents from the index (or a dependency layer) with their metadata from the database
        if method in P10_METHODS:
            run.progress(0, None, "计算")
            try:
                table = _p10(db, run, corpus, scope, user, target, params)
            except ValueError as e:
                raise JobFailed("STATS_INVALID", str(e)) from e
    run.progress(0, None, "计算")
    try:
        table = table or _compute(p, target, reference, numeric, positions)
    except ValueError as e:  # includes query.QueryError
        raise JobFailed("STATS_INVALID", str(e)) from e
    search_scope = scope.model_dump(mode="json", exclude_none=True)
    for row in table.rows:
        row.setdefault(
            "search_scope", search_scope
        )  # comparison rows carry their item's scope
        # by field (distribution, breakdown meta:): temporary filter for that value
        if "bin_value" in row:
            field = p["field"] if method == "distribution" else p["by"][5:]
            filt = {**base_filter, field: row.pop("bin_value")}
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


# ---- pre-annotation ----


def _layer(db, layer_id, lock=False):
    layer = db.get(AnnotationLayer, layer_id, with_for_update=lock)
    if not layer:
        raise JobFailed("LAYER_DELETED", "标注层已删除")
    return layer


def _document_tokens(db, doc_id):
    return db.execute(
        select(
            Sentence.idx, Token.idx, Token.id, Token.start_cp, Token.end_cp, Token.form
        )
        .add_columns(Token.pos, Token.lemma, Token.head, Token.deprel)
        .join(Token, Token.sentence_id == Sentence.id)
        .where(Sentence.document_id == doc_id)
        .order_by(Sentence.idx, Token.idx)
    ).all()


def _parse_zh(rows, check=None, tick=None):
    """Stanza zh dependencies for a document's stored jieba tokens → {token id: (head, deprel)}. Parsed in
    chunks of nlp.BATCH sentences; check() runs before each (cancellation), tick(sentences parsed) after each."""
    sentences = {}
    for idx, _, tid, a, b, form, pos, lemma, _, _ in rows:
        sentences.setdefault(idx, []).append((tid, em.Token(a, b, form, pos, lemma)))
    sents = [
        em.Sentence(t[0][1].start, t[-1][1].end, [x for _, x in t])
        for t in sentences.values()
    ]
    for i in range(0, len(sents), nlp.BATCH):
        if check is not None:
            check()
        nlp.annotate_dependencies_zh(
            em.Document("", "zh", "", {}, sents[i : i + nlp.BATCH])
        )
        if tick is not None:
            tick(min(i + nlp.BATCH, len(sents)))
    return {tid: (t.head, t.deprel) for toks in sentences.values() for tid, t in toks}


def _preannotation(kind, doc_id, language, check=None, tick=None):
    """Pre-annotation rows of one document (read and, for Chinese dependencies, parsed outside any lock)
    and the Stanza values to write back into `tokens` ({token id: (head, deprel)} or None)."""
    with session() as db:
        rows = _document_tokens(db, doc_id)
    source, parsed = "system", None
    if (
        kind == "dep"
        and is_zh(language)
        and any(r.deprel is None or r.head is None for r in rows)
    ):
        parsed, source = _parse_zh(rows, check, tick), "model:stanza-zh"
    values = []
    for idx, t_idx, tid, _, _, _, pos, _, head, deprel in rows:
        if kind == "pos":
            label, head = pos, None
        else:
            head, label = parsed[tid] if parsed else (head, deprel)
        values.append(
            {
                "document_id": doc_id,
                "sentence_index": idx,
                "token_index": t_idx + 1,
                "label": label,
                "head": head,
                "model_label": label,
                "model_head": head,
                "source": source,
                "status": "suggested",
            }
        )
    return values, parsed


def _write_preannotation(db, layer_id, values, parsed, annotators):
    conn = db.connection()
    if parsed:  # fill the system layer where it has no dependencies yet
        conn.execute(
            update(Token)
            .where(Token.id == bindparam("tid"))
            .values(
                head=func.coalesce(Token.head, bindparam("h")),
                deprel=func.coalesce(Token.deprel, bindparam("d")),
            ),
            [{"tid": tid, "h": h, "d": d} for tid, (h, d) in parsed.items()],
        )
    if not values:
        return
    stmt = pg_insert(Annotation)
    conn.execute(
        stmt.on_conflict_do_update(
            constraint="uq_annotations_token",
            set_={
                "label": stmt.excluded.label,
                "head": stmt.excluded.head,
                "model_label": stmt.excluded.model_label,
                "model_head": stmt.excluded.model_head,
                "source": stmt.excluded.source,
                "revision": Annotation.revision + 1,
                "updated_at": func.now(),
            },
            where=Annotation.status == "suggested",
        ),
        [
            {"layer_id": layer_id, "annotator_id": a, **v}
            for a in annotators
            for v in values
        ],
    )


def run_preannotate(run):
    """Fill a layer from `tokens` (contracts/p3.md §三): pos = tokens.pos; dep = tokens.head / deprel, or for
    Chinese documents without dependencies Stanza zh over the stored jieba tokens (also written back to
    `tokens`). Re-runs only overwrite tokens still `suggested`. One transaction per document; layer.progress
    adds each document's change and is recounted once at the end. Job progress counts sentences, also within
    a document while Stanza parses it (a corpus of one large document shows progress too)."""
    layer_id = uuid.UUID(run.params["layer_id"])
    with session() as db:
        token_kind = _layer(db, layer_id).kind in ("pos", "dep")
    if not token_kind:
        return annot_tasks.run_preannotate_p5(run)
    with transaction() as db:
        layer = _layer(db, layer_id, lock=True)
        layer.status, layer.error, layer.job_id = "preannotating", None, run.id
        kind = layer.kind
        annotators = layer_annotators(layer)
        ids = run.params.get("document_ids") or layer.document_ids
        stmt = select(Document.id, Document.language, Document.sentence_count).where(
            Document.corpus_id == layer.corpus_id
        )
        if ids:
            stmt = stmt.where(Document.id.in_(ids))
        docs = db.execute(stmt.order_by(Document.created_at, Document.id)).all()
    total = sum(n or 0 for _, _, n in docs)
    try:
        done = 0
        for doc_id, language, n in docs:
            run.progress(done, total, "预标", "句")

            def tick(k, base=done):
                run.progress(base + k, total, "依存分析", "句")

            values, parsed = _preannotation(kind, doc_id, language, run.check, tick)
            with transaction() as db:
                layer = _layer(db, layer_id, lock=True)
                before = document_counts(db, layer, doc_id)
                _write_preannotation(db, layer_id, values, parsed, annotators)
                add_document_counts(layer, before, document_counts(db, layer, doc_id))
            done += n or 0
        with transaction() as db:
            run.lock(db)
            layer = _layer(db, layer_id, lock=True)
            refresh_progress(db, layer)
            layer.status = "ready"
            run.succeed(
                db,
                {
                    "layer_id": str(layer_id),
                    "documents": len(docs),
                    "tokens": layer.progress["total"],
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


HANDLERS = {
    "import": run_import,
    "index": run_index,
    "export": run_any_export,
    "stats": run_stats,
    "preannotate": run_preannotate,
    "kb_import": kb_tasks.run_kb_import,
    "kb_summarize": kb_tasks.run_kb_summarize,
    "kb_extract": kb_tasks.run_kb_extract,
}
