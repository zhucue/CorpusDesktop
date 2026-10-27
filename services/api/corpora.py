import json
import shutil
import uuid
from pathlib import Path, PurePath
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, File, Form, Query, Request, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import or_, select, update

from services.api.access import WRITE, Paging, load_corpus, require_project
from services.api.auth import CurrentUser, Db
from services.api.errors import ApiError, forbidden, not_found
from services.api.jobs import ACTIVE, enqueue, has_active_job
from services.api.metadata import metadata_fields
from services.api.models import Corpus, Document, Job
from services.api.storage import corpus_dir, upload_dir
from services.api.views import corpus_view, document_view, job_view

router = APIRouter(prefix="/api")

FORMATS = {".txt", ".docx", ".csv", ".tsv", ".conllu", ".tmx"}
MAX_UPLOAD = 500 * 1024 * 1024


class CorpusInput(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    language: str = Field(min_length=1, max_length=20)
    description: str = Field(default="", max_length=2000)


class DocumentPatch(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=500)
    metadata: dict | None = None


def _create(db, project_id, body):
    corpus = Corpus(
        project_id=project_id,
        name=body.name.strip(),
        language=body.language.strip(),
        description=body.description,
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
    if not user.is_admin:
        raise forbidden()
    return _create(db, None, body)


@router.get("/corpora/{corpus_id}")
def get_corpus(corpus_id: UUID, user: CurrentUser, db: Db):
    return corpus_view(load_corpus(db, corpus_id, user))


@router.delete("/corpora/{corpus_id}", status_code=204)
def delete_corpus(corpus_id: UUID, user: CurrentUser, db: Db):
    corpus = load_corpus(db, corpus_id, user, write=True)
    db.execute(
        update(Job)
        .where(Job.state.in_(ACTIVE), Job.params["corpus_id"].astext == str(corpus_id))
        .values(state="cancelled")
    )
    db.delete(corpus)
    db.commit()
    shutil.rmtree(corpus_dir(corpus_id), ignore_errors=True)


def _save_upload(db, corpus, user, files, language, metadata):
    job_id = uuid.uuid4()
    target = upload_dir(job_id)
    target.mkdir(parents=True)
    names = []
    for i, f in enumerate(files):
        name = PurePath(f.filename.replace("\\", "/")).name
        if name in names:
            name = f"{i}_{name}"
        with open(target / name, "wb") as out:
            shutil.copyfileobj(f.file, out)
        names.append(name)
    job = enqueue(
        db,
        "import",
        {
            "corpus_id": str(corpus.id),
            "dir": str(target),
            "files": names,
            "language": language or corpus.language,
            "metadata": metadata,
        },
        user.id,
        corpus.project_id,
        job_id,
    )
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
):
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
    return _save_upload(db, corpus, user, files, (language or "").strip() or None, meta)


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
    corpus = load_corpus(db, corpus_id, user, write=True)
    doc = _document(db, corpus_id, document_id)
    path = doc.text_path
    db.delete(doc)
    _mark_stale(corpus)
    db.commit()
    Path(path).unlink(missing_ok=True)


@router.post("/corpora/{corpus_id}/reindex")
def reindex(corpus_id: UUID, user: CurrentUser, db: Db):
    corpus = load_corpus(db, corpus_id, user, write=True)
    if has_active_job(db, corpus_id, ["import", "index"]):
        raise ApiError(409, "JOB_IN_PROGRESS", "语料库正在导入或索引")
    job = enqueue(
        db, "index", {"corpus_id": str(corpus_id)}, user.id, corpus.project_id
    )
    corpus.status = "indexing"
    corpus.error = None
    db.commit()
    return job_view(job)


@router.get("/corpora/{corpus_id}/metadata-fields")
def get_metadata_fields(corpus_id: UUID, user: CurrentUser, db: Db):
    load_corpus(db, corpus_id, user)
    return metadata_fields(db, corpus_id)
