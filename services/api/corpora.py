import json
import shutil
import uuid
from pathlib import Path, PurePath
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, File, Form, Query, Request, UploadFile
from pydantic import BaseModel, Field, ValidationError
from sqlalchemy import or_, select, update

from services.api.access import (
    WRITE,
    Paging,
    human_only,
    load_corpus,
    require_project,
    token_project,
)
from services.api.auth import CurrentUser, Db
from services.api.errors import ApiError, forbidden, not_found
from services.api.jobs import (
    ACTIVE,
    corpus_tokens,
    enqueue,
    has_active_job,
    live_index,
    retry_job,
)
from services.api.metadata import metadata_fields
from services.api.models import (
    Corpus,
    Document,
    Job,
    Sentence,
    SentenceAlignment,
    Token,
)
from services.api.storage import corpus_dir, upload_dir
from services.api.views import corpus_view, document_view, job_view

router = APIRouter(prefix="/api")

FORMATS = {".txt", ".docx", ".csv", ".tsv", ".conllu", ".tmx"}
TABLES = {".csv", ".tsv"}
MAX_UPLOAD = 500 * 1024 * 1024
PREVIEW_BYTES = (
    256 * 1024
)  # the web client sends at most this much of a table for preview
AUTO = "auto"  # upload/corpus language: detected per document from its text


class TableMapping(BaseModel):
    """CSV/TSV columns for one upload batch; see engine/parsers/table.py."""

    text: list[str] = Field(min_length=1, max_length=2)
    title: str | None = None
    language: str | None = None
    metadata: list[str] | None = None  # None = every other column


class CorpusMeta(BaseModel):
    """Source and license shown on the corpus page and written into exports."""

    license: str | None = Field(default=None, max_length=200)
    attribution: str | None = Field(default=None, max_length=2000)
    source_url: str | None = Field(default=None, max_length=1000)
    version: str | None = Field(default=None, max_length=200)


class CorpusInput(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    language: str = Field(min_length=1, max_length=20)
    description: str = Field(default="", max_length=2000)
    meta: CorpusMeta | None = None


class DocumentPatch(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=500)
    metadata: dict | None = None


def _create(db, project_id, body):
    corpus = Corpus(
        project_id=project_id,
        name=body.name.strip(),
        language=body.language.strip(),
        description=body.description,
        meta=body.meta.model_dump(exclude_none=True) if body.meta else {},
        status="empty",
    )
    db.add(corpus)
    db.commit()
    return corpus_view(corpus)


def _mark_stale(corpus):
    if corpus.status == "ready":
        corpus.status = "stale"


@router.get("/corpora")
def list_corpora(
    user: CurrentUser, db: Db, paging: Paging, project_id: UUID | None = None
):
    scope = Corpus.project_id.is_(None)
    if project_id:
        require_project(db, project_id, user)
        scope = or_(scope, Corpus.project_id == project_id)
    stmt = (
        select(Corpus)
        .where(scope)
        .order_by(Corpus.project_id.is_not(None), Corpus.created_at, Corpus.id)
    )
    return paging.run(db, stmt, corpus_view)


@router.post("/projects/{project_id}/corpora")
def create_corpus(project_id: UUID, body: CorpusInput, user: CurrentUser, db: Db):
    require_project(db, project_id, user, WRITE)
    return _create(db, project_id, body)


@router.post("/corpora")
def create_builtin_corpus(body: CorpusInput, user: CurrentUser, db: Db):
    if not user.is_admin or token_project(user):
        raise forbidden()
    return _create(db, None, body)


@router.get("/corpora/{corpus_id}")
def get_corpus(corpus_id: UUID, user: CurrentUser, db: Db):
    return corpus_view(load_corpus(db, corpus_id, user))


@router.delete("/corpora/{corpus_id}", status_code=204)
def delete_corpus(corpus_id: UUID, user: CurrentUser, db: Db):
    human_only(user)
    corpus = load_corpus(db, corpus_id, user, write=True)
    db.execute(
        update(Job)
        .where(Job.state.in_(ACTIVE), Job.params["corpus_id"].astext == str(corpus_id))
        .values(state="cancelled")
    )
    db.delete(corpus)
    db.commit()
    shutil.rmtree(corpus_dir(corpus_id), ignore_errors=True)


def _save_upload(db, corpus, user, files, language, metadata, mapping):
    job_id = uuid.uuid4()
    target = upload_dir(job_id)
    target.mkdir(parents=True)
    names, size = [], 0
    for i, f in enumerate(files):
        name = PurePath(f.filename.replace("\\", "/")).name
        if name in names:
            name = f"{i}_{name}"
        with open(target / name, "wb") as out:
            shutil.copyfileobj(f.file, out)
            size += out.tell()
        names.append(name)
    language = language or corpus.language
    job = enqueue(
        db,
        "import",
        {
            "corpus_id": str(corpus.id),
            "dir": str(target),
            "files": names,
            # None: detect per document (engine.nlp.detect_language)
            "language": None if language == AUTO else language,
            "metadata": metadata,
            "bytes": size,  # short-lane rule, services.api.jobs.small_heavy
            **({"mapping": mapping} if mapping else {}),
        },
        user.id,
        corpus.project_id,
        job_id,
    )
    if not live_index(corpus):  # a searchable corpus keeps serving its index meanwhile
        corpus.status = "importing"
    corpus.error = None
    db.commit()
    return job_view(job)


@router.post("/corpora/{corpus_id}/documents")
def upload_documents(
    corpus_id: UUID,
    request: Request,
    user: CurrentUser,
    db: Db,
    files: Annotated[list[UploadFile], File()],
    language: Annotated[str | None, Form(max_length=20)] = None,
    metadata: Annotated[str | None, Form()] = None,
    mapping: Annotated[str | None, Form()] = None,
):
    human_only(user)
    corpus = load_corpus(db, corpus_id, user, write=True)
    if int(request.headers.get("content-length") or 0) > MAX_UPLOAD:
        raise ApiError(413, "TOO_LARGE", "单次上传不超过 500 MB")
    files = [f for f in files if f.filename]
    if not files:
        raise ApiError(422, "NO_FILES", "请选择文件")
    for f in files:
        name = f.filename.lower()
        if not (PurePath(name).suffix in FORMATS or name.endswith(".tsv.bz2")):
            raise ApiError(422, "UNSUPPORTED_FORMAT", f"不支持的文件格式：{f.filename}")
    try:
        meta = json.loads(metadata or "{}")
    except json.JSONDecodeError:
        meta = None
    if not isinstance(meta, dict):
        raise ApiError(422, "INVALID_METADATA", "metadata 须为 JSON 对象")
    table_mapping = None
    if mapping:
        try:
            table_mapping = TableMapping.model_validate_json(mapping).model_dump()
        except ValidationError as e:
            raise ApiError(
                422,
                "INVALID_MAPPING",
                "mapping 须为 {text: [1–2 列], title, language, metadata}",
            ) from e
    return _save_upload(
        db, corpus, user, files, (language or "").strip() or None, meta, table_mapping
    )


@router.post("/imports/preview")
async def preview_table(user: CurrentUser, file: Annotated[UploadFile, File()]):
    """Header, first rows and default column mapping of a CSV/TSV (or its first PREVIEW_BYTES)."""
    from engine.parsers import ParseError, table

    human_only(user)
    name = PurePath((file.filename or "").replace("\\", "/")).name
    if PurePath(name.lower()).suffix not in TABLES:
        raise ApiError(422, "UNSUPPORTED_FORMAT", f"只有 CSV/TSV 需要列映射：{name}")
    data = await file.read(PREVIEW_BYTES)
    try:
        return table.preview(data, name, partial=len(data) >= PREVIEW_BYTES)
    except ParseError as e:
        raise ApiError(422, "PARSE_ERROR", str(e)) from e


@router.get("/corpora/{corpus_id}/documents")
def list_documents(
    corpus_id: UUID,
    user: CurrentUser,
    db: Db,
    paging: Paging,
    q: Annotated[str | None, Query(max_length=200)] = None,
):
    load_corpus(db, corpus_id, user)
    stmt = select(Document).where(Document.corpus_id == corpus_id)
    if q:
        pattern = (
            "%" + q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
        )
        stmt = stmt.where(Document.title.ilike(pattern))
    return paging.run(
        db, stmt.order_by(Document.created_at, Document.id), document_view
    )


def _document(db, corpus_id, document_id):
    doc = db.get(Document, document_id)
    if not doc or doc.corpus_id != corpus_id:
        raise not_found("文档")
    return doc


@router.get("/corpora/{corpus_id}/documents/{document_id}")
def get_document(corpus_id: UUID, document_id: UUID, user: CurrentUser, db: Db):
    load_corpus(db, corpus_id, user)
    return document_view(_document(db, corpus_id, document_id))


@router.get("/corpora/{corpus_id}/documents/{document_id}/sentences")
def list_sentences(
    corpus_id: UUID, document_id: UUID, user: CurrentUser, db: Db, paging: Paging
):
    """Stored sentences of one document in order, with aligned sentences of parallel corpora."""
    corpus = load_corpus(db, corpus_id, user)
    _document(db, corpus_id, document_id)
    stmt = (
        select(Sentence)
        .where(Sentence.document_id == document_id)
        .order_by(Sentence.idx)
    )
    page = paging.run(
        db, stmt, lambda s: {"id": s.id, "idx": s.idx, "text": s.text, "aligned": []}
    )
    if corpus.parallel and page["items"]:
        by_id = {s["id"]: s for s in page["items"]}
        for mine, other in (
            (SentenceAlignment.src_sentence_id, SentenceAlignment.tgt_sentence_id),
            (SentenceAlignment.tgt_sentence_id, SentenceAlignment.src_sentence_id),
        ):
            for sid, text, language in db.execute(
                select(mine, Sentence.text, Document.language)
                .join(Sentence, Sentence.id == other)
                .join(Document, Document.id == Sentence.document_id)
                .where(mine.in_(list(by_id)))
            ):
                by_id[sid]["aligned"].append({"language": language, "text": text})
    return page


@router.get("/corpora/{corpus_id}/documents/{document_id}/sentences/{sentence_index}")
def get_sentence(
    corpus_id: UUID, document_id: UUID, sentence_index: int, user: CurrentUser, db: Db
):
    """One stored sentence with its system tokens (index/head 1-based as in CoNLL-U, head 0 = root), no layer
    needed: read-only view of corpora that ship with POS / dependencies (UD) for the assistant and viewers."""
    load_corpus(db, corpus_id, user)
    _document(db, corpus_id, document_id)
    s = db.scalar(
        select(Sentence).where(
            Sentence.document_id == document_id, Sentence.idx == sentence_index
        )
    )
    if s is None:
        raise not_found("句子")
    tokens = db.scalars(
        select(Token).where(Token.sentence_id == s.id).order_by(Token.idx)
    ).all()
    return {
        "document_id": document_id,
        "sentence_index": s.idx,
        "text": s.text,
        "start_cp": s.start_cp,
        "end_cp": s.end_cp,
        "tokens": [
            {
                "index": t.idx + 1,
                "form": t.form,
                "pos": t.pos,
                "lemma": t.lemma,
                "head": t.head,
                "deprel": t.deprel,
            }
            for t in tokens
        ],
    }


@router.patch("/corpora/{corpus_id}/documents/{document_id}")
def patch_document(
    corpus_id: UUID, document_id: UUID, body: DocumentPatch, user: CurrentUser, db: Db
):
    corpus = load_corpus(db, corpus_id, user, write=True)
    doc = _document(db, corpus_id, document_id)
    if body.title is not None:
        doc.title = body.title.strip()
    if body.metadata is not None:
        doc.meta = body.metadata
    _mark_stale(corpus)
    db.commit()
    return document_view(doc)


@router.delete("/corpora/{corpus_id}/documents/{document_id}", status_code=204)
def delete_document(corpus_id: UUID, document_id: UUID, user: CurrentUser, db: Db):
    human_only(user)
    corpus = load_corpus(db, corpus_id, user, write=True)
    doc = _document(db, corpus_id, document_id)
    path = doc.text_path
    db.delete(doc)
    _mark_stale(corpus)
    db.commit()
    Path(path).unlink(missing_ok=True)


@router.post("/corpora/{corpus_id}/reindex")
def reindex(corpus_id: UUID, user: CurrentUser, db: Db):
    human_only(user)
    corpus = load_corpus(db, corpus_id, user, write=True)
    if has_active_job(db, corpus_id, ["import", "index"]):
        raise ApiError(409, "JOB_IN_PROGRESS", "语料库正在导入或索引")
    job = enqueue(
        db,
        "index",
        {"corpus_id": str(corpus_id), "tokens": corpus_tokens(db, corpus_id)},
        user.id,
        corpus.project_id,
    )
    if not live_index(corpus):
        corpus.status = "indexing"
    corpus.error = None
    db.commit()
    return job_view(job)


@router.post("/corpora/{corpus_id}/retry")
def retry_corpus(corpus_id: UUID, user: CurrentUser, db: Db):
    """Retry the failed corpus's latest import/index job (same params, so an import keeps its
    files and column mapping)."""
    human_only(user)
    load_corpus(db, corpus_id, user, write=True)
    job = db.scalar(
        select(Job)
        .where(
            Job.kind.in_(["import", "index"]),
            Job.params["corpus_id"].astext == str(corpus_id),
        )
        .order_by(Job.created_at.desc())
        .limit(1)
    )
    if job is None or job.state not in ("failed", "cancelled"):
        raise ApiError(409, "JOB_NOT_RETRYABLE", "没有可重试的导入或索引任务")
    return retry_job(job.id, user, db)


@router.get("/corpora/{corpus_id}/metadata-fields")
def get_metadata_fields(corpus_id: UUID, user: CurrentUser, db: Db):
    load_corpus(db, corpus_id, user)
    return metadata_fields(db, corpus_id)
