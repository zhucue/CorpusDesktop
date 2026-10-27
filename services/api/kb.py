"""Knowledge base (contracts/p4.md §四): documents, chunks, hybrid search, note refs, note export.

Files and URLs are parsed, chunked and embedded by the worker (`kb_import`); notes and guidelines are indexed the
same way after every body change. Roles: viewer reads, searches and exports; annotator / editor / owner write;
delete needs owner / editor or the creator. An agent token (Bearer) may read, search, create and append notes,
add note refs and start summaries; uploads, URL imports, guidelines, re-imports and deletes are cookie-only.
"""

import json
import shutil
import uuid
from datetime import UTC, datetime
from pathlib import PurePath
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Query, Request
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy import exists, func, literal_column, or_, select, text, update
from starlette.datastructures import UploadFile

from engine.kb import embed
from engine.kb import parse as kbparse
from engine.kb import text as kbtext
from services.api.access import READ, WRITE, Paging, require_project, token_project
from services.api.auth import CurrentUser, Db
from services.api.errors import ApiError, forbidden, not_found
from services.api.jobs import ACTIVE, enqueue
from services.api.models import (
    Evidence,
    Job,
    KbChunk,
    KbDocument,
    KbTerm,
    LabelSet,
    NoteRef,
    StatResult,
)
from services.api.storage import kb_dir
from services.api.views import (
    chunk_view,
    job_view,
    kb_document_view,
    note_ref_view,
    term_view,
)

router = APIRouter(prefix="/api")

EDIT = ("owner", "editor", "annotator")
MAX_FILE = 50 * 1024 * 1024
MAX_FILES = 20
PREVIEW = 2000
CANDIDATES = 50
RRF_K = 60
TEXT_KINDS = ("note", "guideline")
BUSY = ("queued", "parsing", "embedding")
Kind = Literal["literature", "guideline", "note", "url"]


def now():
    return datetime.now(UTC)


def is_bearer(user):
    return token_project(user) is not None


def cookie_only(user):
    if is_bearer(user):
        raise forbidden()


def load_document(db, document_id, user, roles=READ, lock=False):
    doc = db.get(KbDocument, document_id, with_for_update=lock)
    if not doc:
        raise not_found("文档")
    return doc, require_project(db, doc.project_id, user, roles)


def active_job(db, document_id, kinds, states=ACTIVE):
    return db.scalar(
        select(
            exists().where(
                Job.kind.in_(kinds),
                Job.state.in_(states),
                Job.params["document_id"].astext == str(document_id),
            )
        )
    )


def import_jobs(db, document_ids):
    """{document id: id of its latest queued / running kb_import job}."""
    if not document_ids:
        return {}
    rows = db.execute(
        select(Job.params["document_id"].astext, Job.id)
        .where(
            Job.kind == "kb_import",
            Job.state.in_(ACTIVE),
            Job.params["document_id"].astext.in_([str(i) for i in document_ids]),
        )
        .order_by(Job.created_at)
    ).all()
    return {UUID(d): j for d, j in rows}


def enqueue_import(db, doc, user_id):
    doc.status, doc.error = "queued", None
    return enqueue(
        db, "kb_import", {"document_id": str(doc.id)}, user_id, doc.project_id
    )


def reindex_text(db, doc, user_id):
    """After a note / guideline body change: one queued re-index is enough."""
    if not active_job(db, doc.id, ["kb_import"], ["queued"]):
        enqueue_import(db, doc, user_id)


# ---- documents ----


class UrlInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    url: str = Field(min_length=1, max_length=2000)
    title: str | None = Field(default=None, min_length=1, max_length=500)
    meta: dict = {}
    force: bool = False  # import again although the project already has this URL


class TextInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["note", "guideline"]
    title: str = Field(min_length=1, max_length=500)
    body: str = Field(default="", max_length=1_000_000)
    meta: dict = {}


class DocumentPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str | None = Field(default=None, min_length=1, max_length=500)
    body: str | None = Field(default=None, max_length=1_000_000)
    meta: dict | None = None  # merged into meta; a null value removes the key


def _check_meta(db, project_id, meta):
    if len(json.dumps(meta, ensure_ascii=False)) > 20000:
        raise ApiError(422, "VALIDATION_ERROR", "meta 过大")
    label_set_id = meta.get("label_set_id")
    if label_set_id is not None:
        try:
            ls = db.get(LabelSet, UUID(str(label_set_id)))
        except ValueError:
            ls = None
        if not ls or ls.project_id not in (None, project_id):
            raise ApiError(422, "INVALID_LABEL_SET", "标签集不存在")


@router.get("/projects/{project_id}/kb/documents")
def list_documents(
    project_id: UUID,
    user: CurrentUser,
    db: Db,
    paging: Paging,
    kind: Kind | None = None,
    q: str | None = Query(default=None, max_length=200),
):
    require_project(db, project_id, user)
    stmt = select(KbDocument).where(KbDocument.project_id == project_id)
    if kind:
        stmt = stmt.where(KbDocument.kind == kind)
    if q:
        pattern = (
            "%" + q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
        )
        stmt = stmt.where(
            or_(KbDocument.title.ilike(pattern), KbDocument.source.ilike(pattern))
        )
    stmt = stmt.order_by(KbDocument.updated_at.desc(), KbDocument.id)
    page = paging.run(db, stmt, lambda d: d)
    jobs = import_jobs(db, [d.id for d in page["items"] if d.status in BUSY])
    page["items"] = [
        kb_document_view(d, **({"job_id": jobs[d.id]} if d.id in jobs else {}))
        for d in page["items"]
    ]
    return page


def _upload(db, project_id, user, files, kind):
    require_project(db, project_id, user, EDIT)
    cookie_only(user)
    if not files:
        raise ApiError(422, "NO_FILES", "请选择文件")
    if len(files) > MAX_FILES:
        raise ApiError(422, "TOO_MANY_FILES", f"一次最多上传 {MAX_FILES} 个文件")
    for f in files:
        if not kbparse.kind_of(f.filename):
            raise ApiError(422, "UNSUPPORTED_FORMAT", f"不支持的文件格式：{f.filename}")
        if (f.size or 0) > MAX_FILE:
            raise ApiError(413, "TOO_LARGE", f"{f.filename} 超过 50 MB")
    items, written = [], []
    try:
        for f in files:
            name = PurePath(f.filename.replace("\\", "/")).name
            doc = KbDocument(
                id=uuid.uuid4(),
                project_id=project_id,
                kind=kind,
                title=PurePath(name).stem or name,
                source=name,
                meta={},
                status="queued",
                created_by=user.id,
            )
            folder = kb_dir(doc.id)
            folder.mkdir(parents=True, exist_ok=True)
            written.append(folder)
            path = folder / ("source" + PurePath(name).suffix.lower())
            with open(path, "wb") as out:
                shutil.copyfileobj(f.file, out)
            doc.file_path = str(path)
            db.add(doc)
            db.flush()
            job = enqueue_import(db, doc, user.id)
            items.append(kb_document_view(doc, job_id=job.id))
        db.commit()
    except BaseException:
        db.rollback()
        for folder in written:
            shutil.rmtree(folder, ignore_errors=True)
        raise
    return {"items": items, "total": len(items)}


def _check_duplicate_url(db, project_id, url):
    """409 DUPLICATE_URL when the project already has a URL document with the same normalized URL."""
    key = kbparse.normalize_url(url)
    for doc_id, title, source in db.execute(
        select(KbDocument.id, KbDocument.title, KbDocument.source).where(
            KbDocument.project_id == project_id, KbDocument.kind == "url"
        )
    ):
        if kbparse.normalize_url(source) == key:
            raise ApiError(
                409,
                "DUPLICATE_URL",
                f"该网址已导入：{title}（{doc_id}），重新导入请加 force",
            )


def _create_json(db, project_id, user, data):
    try:
        body = (
            UrlInput.model_validate(data)
            if "url" in data
            else TextInput.model_validate(data)
        )
    except ValidationError as e:
        first = e.errors()[0]
        field = ".".join(str(p) for p in first["loc"])
        raise ApiError(
            422,
            "VALIDATION_ERROR",
            f"{field}: {first['msg']}" if field else first["msg"],
        )
    require_project(db, project_id, user, EDIT)
    _check_meta(db, project_id, body.meta)
    if isinstance(body, UrlInput):
        cookie_only(user)
        try:
            url = kbparse.check_public_url(body.url)
        except kbparse.ParseError as e:
            raise ApiError(422, "INVALID_URL", str(e))
        if not body.force:
            _check_duplicate_url(db, project_id, url)
        doc = KbDocument(
            project_id=project_id,
            kind="url",
            title=(body.title or url).strip(),
            source=url,
            meta=body.meta,
            status="queued",
            created_by=user.id,
        )
    else:
        if body.kind == "guideline":
            cookie_only(user)
        doc = KbDocument(
            project_id=project_id,
            kind=body.kind,
            title=body.title.strip(),
            source="",
            body=body.body,
            meta=body.meta,
            status="queued",
            created_by=user.id,
        )
    db.add(doc)
    db.flush()
    job = enqueue_import(db, doc, user.id)
    db.commit()
    return kb_document_view(
        doc, job_id=job.id, **({"body": doc.body} if doc.kind in TEXT_KINDS else {})
    )


@router.post("/projects/{project_id}/kb/documents")
async def create_document(
    project_id: UUID, request: Request, user: CurrentUser, db: Db
):
    """multipart `files` (+ optional `kind`: literature | guideline) → {items: [KbDocument + job_id]};
    JSON {url[, title, meta]} or {kind: note | guideline, title, body, meta?} → KbDocument + job_id."""
    if request.headers.get("content-type", "").startswith("multipart/form-data"):
        if int(request.headers.get("content-length") or 0) > MAX_FILE * MAX_FILES:
            raise ApiError(413, "TOO_LARGE", "上传内容过大")
        form = await request.form(max_files=MAX_FILES + 1, max_fields=10)
        kind = form.get("kind") or "literature"
        if kind not in ("literature", "guideline"):
            raise ApiError(422, "VALIDATION_ERROR", "kind 须为 literature 或 guideline")
        files = [
            f for f in form.getlist("files") if isinstance(f, UploadFile) and f.filename
        ]
        try:
            return await run_in_threadpool(_upload, db, project_id, user, files, kind)
        finally:
            await form.close()
    try:
        data = await request.json()
    except ValueError:
        raise ApiError(
            422, "VALIDATION_ERROR", "请求体须为 JSON 或 multipart"
        ) from None
    if not isinstance(data, dict):
        raise ApiError(422, "VALIDATION_ERROR", "请求体须为 JSON 对象")
    return await run_in_threadpool(_create_json, db, project_id, user, data)


@router.get("/kb/documents/{document_id}")
def get_document(document_id: UUID, user: CurrentUser, db: Db):
    doc, _ = load_document(db, document_id, user)
    extra = {}
    if doc.status in BUSY and (job := import_jobs(db, [doc.id]).get(doc.id)):
        extra["job_id"] = job
    if doc.kind in TEXT_KINDS:
        extra["body"] = doc.body or ""
    else:
        preview = ""
        if doc.text_path:
            try:
                with open(doc.text_path, encoding="utf-8") as f:
                    preview = f.read(PREVIEW)
            except FileNotFoundError:
                pass
        extra["text_preview"] = preview
    if doc.kind == "note":
        refs = db.scalars(
            select(NoteRef).where(NoteRef.note_id == doc.id).order_by(NoteRef.id)
        ).all()
        extra["refs"] = [note_ref_view(r) for r in refs]
    return kb_document_view(doc, **extra)


@router.patch("/kb/documents/{document_id}")
def patch_document(document_id: UUID, body: DocumentPatch, user: CurrentUser, db: Db):
    doc, _ = load_document(db, document_id, user, EDIT, lock=True)
    if is_bearer(user) and doc.kind != "note":
        raise forbidden()
    if body.body is not None and doc.kind not in TEXT_KINDS:
        raise ApiError(422, "VALIDATION_ERROR", "只有笔记和规范有正文")
    if body.title is not None:
        doc.title = body.title.strip()
    if body.meta is not None:
        merged = {**doc.meta, **body.meta}
        merged = {k: v for k, v in merged.items() if v is not None}
        _check_meta(db, doc.project_id, merged)
        doc.meta = merged
    if body.body is not None and body.body != doc.body:
        doc.body = body.body
        reindex_text(db, doc, user.id)
    doc.updated_at = now()
    db.commit()
    return kb_document_view(
        doc, **({"body": doc.body or ""} if doc.kind in TEXT_KINDS else {})
    )


@router.delete("/kb/documents/{document_id}", status_code=204)
def delete_document(document_id: UUID, user: CurrentUser, db: Db):
    doc, role = load_document(db, document_id, user)
    cookie_only(user)
    if role not in WRITE and doc.created_by != user.id:
        raise forbidden()
    db.execute(
        update(Job)
        .where(Job.state.in_(ACTIVE), Job.params["document_id"].astext == str(doc.id))
        .values(state="cancelled", finished_at=now())
    )
    db.delete(doc)
    db.commit()
    shutil.rmtree(kb_dir(document_id), ignore_errors=True)


@router.post("/kb/documents/{document_id}/reimport")
def reimport(document_id: UUID, user: CurrentUser, db: Db):
    doc, _ = load_document(db, document_id, user, EDIT, lock=True)
    cookie_only(user)
    if active_job(db, doc.id, ["kb_import"]):
        raise ApiError(409, "JOB_IN_PROGRESS", "文档正在导入")
    job = enqueue_import(db, doc, user.id)
    db.commit()
    return job_view(job)


@router.get("/kb/documents/{document_id}/chunks")
def list_chunks(document_id: UUID, user: CurrentUser, db: Db, paging: Paging):
    load_document(db, document_id, user)
    stmt = (
        select(KbChunk)
        .where(KbChunk.document_id == document_id)
        .order_by(KbChunk.ordinal)
    )
    return paging.run(db, stmt, chunk_view)


@router.post("/kb/documents/{document_id}/summarize")
def summarize(document_id: UUID, user: CurrentUser, db: Db):
    doc, _ = load_document(db, document_id, user, EDIT)
    if not doc.chunk_count:
        raise ApiError(409, "DOCUMENT_NOT_READY", "文档尚未导入完成")
    if active_job(db, doc.id, ["kb_summarize"]):
        raise ApiError(409, "JOB_IN_PROGRESS", "摘要任务正在进行")
    job = enqueue(
        db, "kb_summarize", {"document_id": str(doc.id)}, user.id, doc.project_id
    )
    db.commit()
    return job_view(job)


# ---- note refs and export ----


class RefInput(BaseModel):
    kind: Literal["search", "stat", "evidence", "chunk", "term"]
    ref: dict = {}


def _evidence_block(text_, source, search_query=None):
    quoted = "\n".join(
        "> " + line if line.strip() else ">" for line in text_.strip().split("\n")
    )
    tail = f"> —— {source}" if source else ""
    if search_query:
        tail += ("；" if tail else "> —— ") + f"查询式：`{search_query}`"
    return quoted + ("\n>\n" + tail if tail else "")


def _resolve_ref(db, note, kind, ref):
    """Validate a ref against the note's project and capture what an export needs."""
    ref = dict(ref)
    if len(json.dumps(ref, ensure_ascii=False)) > 30000:
        raise ApiError(422, "VALIDATION_ERROR", "ref 过大")

    def get(model, key, what):
        try:
            obj = db.get(model, UUID(str(ref[key]))) if ref.get(key) else None
        except ValueError:
            obj = None
        if not obj or getattr(obj, "project_id", note.project_id) != note.project_id:
            raise not_found(what)
        return obj

    if kind == "evidence":
        if ref.get("evidence_id"):
            ev = get(Evidence, "evidence_id", "证据")
            ref |= {"text": ev.text, "source": ev.source}
            if ev.ref.get("search_query"):
                ref["search_query"] = ev.ref["search_query"]
            if ev.ref.get("scope"):
                ref["scope"] = ev.ref["scope"]
        if not isinstance(ref.get("text"), str) or not ref["text"].strip():
            raise ApiError(422, "VALIDATION_ERROR", "证据引用须含 evidence_id 或 text")
    elif kind == "stat" and ref.get("stat_id"):
        stat = get(StatResult, "stat_id", "统计结果")
        ref.setdefault("method", stat.method)
        ref.setdefault("scope", stat.scope)
    elif kind == "chunk" and ref.get("chunk_id"):
        chunk = (
            db.get(KbChunk, int(ref["chunk_id"]))
            if str(ref["chunk_id"]).isdigit()
            else None
        )
        doc = db.get(KbDocument, chunk.document_id) if chunk else None
        if not doc or doc.project_id != note.project_id:
            raise not_found("知识片段")
        ref |= {
            "document_id": str(doc.id),
            "title": doc.title,
            "locator": chunk.locator,
        }
        ref.setdefault("text", chunk.text)
    elif kind == "term" and ref.get("term_id"):
        term = get(KbTerm, "term_id", "术语")
        ref.setdefault("term", term.term)
    return ref


@router.post("/kb/documents/{note_id}/refs")
def add_ref(note_id: UUID, body: RefInput, user: CurrentUser, db: Db):
    """Store a ref; an evidence ref also appends the evidence text and its source to the note body."""
    note, _ = load_document(db, note_id, user, EDIT, lock=True)
    if note.kind != "note":
        raise ApiError(422, "NOT_A_NOTE", "只能向笔记添加引用")
    ref = _resolve_ref(db, note, body.kind, body.ref)
    item = NoteRef(note_id=note.id, kind=body.kind, ref=ref)
    db.add(item)
    if body.kind == "evidence":
        block = _evidence_block(ref["text"], ref.get("source"), ref.get("search_query"))
        current = (note.body or "").rstrip()
        note.body = (current + "\n\n" if current else "") + block + "\n"
        note.updated_at = now()
        reindex_text(db, note, user.id)
    db.commit()
    return note_ref_view(item)


class NoteExportInput(BaseModel):
    format: Literal["docx", "md"]


@router.post("/kb/documents/{document_id}/export")
def export_note(document_id: UUID, body: NoteExportInput, user: CurrentUser, db: Db):
    doc, _ = load_document(db, document_id, user)
    if doc.kind not in TEXT_KINDS:
        raise ApiError(422, "NOT_A_NOTE", "只能导出笔记或规范")
    params = {"source": "kb_note", "document_id": str(doc.id), "format": body.format}
    job = enqueue(db, "export", params, user.id, doc.project_id)
    db.commit()
    return job_view(job)


# ---- hybrid search ----


class SearchInput(BaseModel):
    q: str = Field(min_length=1, max_length=1000)
    kinds: list[Kind] | None = None
    document_ids: list[UUID] | None = Field(default=None, max_length=500)
    top_k: int = Field(default=8, ge=1, le=50)
    mode: Literal["hybrid", "vector", "keyword"] = "hybrid"


def warm_embeddings():
    """Load jieba and (if the worker has already downloaded it) the embedding model at startup."""
    kbtext.query_words("语料库")
    try:
        embed.load(download=False)
    except embed.EmbedUnavailable:
        pass


def _vector_hits(db, where, q):
    """[(chunk id, cosine similarity)] of the current embedding model, best first."""
    vec = embed.embed([q], download=False)[0]
    db.execute(text("SET LOCAL hnsw.ef_search = 200"))
    db.execute(text("SET LOCAL hnsw.iterative_scan = strict_order"))
    dist = KbChunk.embedding.cosine_distance(vec)
    rows = db.execute(
        select(KbChunk.id, dist)
        .join(KbDocument, KbDocument.id == KbChunk.document_id)
        .where(*where, KbChunk.embed_model == embed.model_name())
        .order_by(dist, KbChunk.id)
        .limit(CANDIDATES)
    ).all()
    return [(cid, 1 - d) for cid, d in rows]


def _keyword_hits(db, where, words):
    """[(chunk id, ts_rank)] for an OR of the query words, best first."""
    q = kbtext.tsquery(words)
    if not q:
        return []
    tsq = func.to_tsquery(literal_column("'simple'::regconfig"), q)
    rank = func.ts_rank(KbChunk.tsv, tsq)
    rows = db.execute(
        select(KbChunk.id, rank)
        .join(KbDocument, KbDocument.id == KbChunk.document_id)
        .where(*where, KbChunk.tsv.op("@@")(tsq))
        .order_by(rank.desc(), KbChunk.id)
        .limit(CANDIDATES)
    ).all()
    return [(cid, float(r)) for cid, r in rows]


def match_terms(db, project_id, q, limit=5):
    """Terms equal to q, starting with q, or contained in q: exact first, confirmed first, longer first."""
    q = q.strip()
    pattern = q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
    exact = func.lower(KbTerm.term) == q.lower()
    stmt = (
        select(KbTerm)
        .where(
            KbTerm.project_id == project_id,
            or_(
                exact,
                KbTerm.term.ilike(pattern),
                func.strpos(func.lower(q), func.lower(KbTerm.term)) > 0,
            ),
        )
        .order_by(
            exact.desc(),
            (KbTerm.status == "confirmed").desc(),
            func.length(KbTerm.term).desc(),
            KbTerm.term,
        )
        .limit(limit)
    )
    return db.scalars(stmt).all()


def search_kb(db, project_id, body: SearchInput):
    where = [KbDocument.project_id == project_id]
    if body.kinds:
        where.append(KbDocument.kind.in_(body.kinds))
    if body.document_ids:
        where.append(KbDocument.id.in_(body.document_ids))
    words = kbtext.query_words(body.q)
    mode, warning = body.mode, None
    vector = keyword = []
    if mode in ("hybrid", "vector"):
        try:
            vector = _vector_hits(db, where, body.q)
        except embed.EmbedUnavailable:
            mode, warning = "keyword", "EMBED_UNAVAILABLE"
    if mode in ("hybrid", "keyword"):
        keyword = _keyword_hits(db, where, words)
    scores = {}
    if mode == "hybrid":
        for hits in (vector, keyword):
            for rank, (cid, _) in enumerate(hits, 1):
                scores[cid] = scores.get(cid, 0.0) + 1 / (RRF_K + rank)
    else:
        scores = dict(vector if mode == "vector" else keyword)
    top = sorted(scores, key=lambda cid: (-scores[cid], cid))[: body.top_k]
    chunks = {c.id: c for c in db.scalars(select(KbChunk).where(KbChunk.id.in_(top)))}
    docs = {
        d.id: d
        for d in db.scalars(
            select(KbDocument).where(
                KbDocument.id.in_({c.document_id for c in chunks.values()})
            )
        )
    }
    items = []
    for cid in top:
        c = chunks[cid]
        d = docs[c.document_id]
        items.append(
            {
                "chunk": chunk_view(c, scores[cid]),
                "document": {
                    "id": d.id,
                    "title": d.title,
                    "kind": d.kind,
                    "source": d.source,
                },
                "score": scores[cid],
                "highlight": kbtext.highlight(c.text, words),
            }
        )
    result = {
        "items": items,
        "terms": [term_view(t) for t in match_terms(db, project_id, body.q)],
        "mode": mode,
    }
    if warning:
        result["warning"] = warning
    return result


@router.post("/projects/{project_id}/kb/search")
def search(project_id: UUID, body: SearchInput, user: CurrentUser, db: Db):
    require_project(db, project_id, user)
    return search_kb(db, project_id, body)
