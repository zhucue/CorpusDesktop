import uuid
from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter
from fastapi.responses import FileResponse
from sqlalchemy import exists, select

from services.api.access import (
    WRITE,
    Paging,
    check_token_project,
    project_role,
    require_project,
)
from services.api.auth import CurrentUser, Db
from services.api.errors import ApiError, forbidden, not_found
from services.api.models import AnnotationLayer, Corpus, Document, Job, KbDocument
from services.api.storage import export_path
from services.api.views import job_view

router = APIRouter(prefix="/api")

ACTIVE = ("queued", "running")
CORPUS_STATUS_FOR_KIND = {"import": "importing", "index": "indexing"}
EXPORT_TYPES = {
    "csv": "text/csv",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "conllu": "text/plain; charset=utf-8",
    "tbx": "application/xml",
    "md": "text/markdown; charset=utf-8",
    "brat": "application/zip",
    "json": "application/json",
    "tmx": "application/xml",
}


def enqueue(db, kind, params, owner_id, project_id, job_id=None):
    job = Job(
        id=job_id or uuid.uuid4(),
        kind=kind,
        params=params,
        owner_id=owner_id,
        project_id=project_id,
        state="queued",
        progress={"done": 0, "total": None, "message": ""},
    )
    db.add(job)
    db.flush()
    return job


def has_active_job(db, corpus_id, kinds, exclude=None):
    stmt = select(Job.id).where(
        Job.state.in_(ACTIVE),
        Job.kind.in_(kinds),
        Job.params["corpus_id"].astext == str(corpus_id),
    )
    if exclude:
        stmt = stmt.where(Job.id != exclude)
    return db.scalar(select(exists(stmt))) or False


def settle_corpus(db, corpus_id, stopped_job_id):
    """Corpus status after an import/index job stops without success."""
    corpus = db.get(Corpus, corpus_id)
    if not corpus:
        return
    if has_active_job(db, corpus_id, ["import"], stopped_job_id):
        corpus.status = "importing"
    elif has_active_job(db, corpus_id, ["index"], stopped_job_id):
        corpus.status = "indexing"
    elif db.scalar(select(exists().where(Document.corpus_id == corpus_id))):
        corpus.status = "stale"
    else:
        corpus.status = "empty"


def settle_layer(db, job, message):
    """Layer state after its pre-annotation job stops without success."""
    layer = db.get(AnnotationLayer, job.params["layer_id"])
    if (
        layer
        and layer.job_id == job.id
        and layer.status in ("created", "preannotating")
    ):
        layer.status, layer.error = "failed", message


def settle_kb_document(db, job, message):
    """Document state after its kb_import job stops without success: earlier chunks stay searchable."""
    doc = db.get(KbDocument, job.params["document_id"])
    if doc and doc.status != "ready":
        doc.status = "ready" if doc.chunk_count else "failed"
        doc.error = message


def _load(db, job_id, user, manage=False) -> Job:
    job = db.get(Job, job_id)
    if not job:
        raise not_found("任务")
    check_token_project(user, job.project_id)
    role = project_role(db, job.project_id, user) if job.project_id else None
    if job.project_id is not None and role is None:
        raise not_found("任务")  # also for its creator once removed from the project
    if job.owner_id == user.id:
        return job
    if job.project_id is None and not user.is_admin:
        raise not_found("任务")
    if manage and role not in WRITE and job.project_id is not None:
        raise forbidden()
    return job


@router.get("/projects/{project_id}/jobs")
def list_jobs(project_id: UUID, user: CurrentUser, db: Db, paging: Paging):
    require_project(db, project_id, user)
    stmt = (
        select(Job)
        .where(Job.project_id == project_id)
        .order_by(Job.created_at.desc(), Job.id)
    )
    return paging.run(db, stmt, job_view)


@router.get("/jobs/{job_id}")
def get_job(job_id: UUID, user: CurrentUser, db: Db):
    return job_view(_load(db, job_id, user))


@router.post("/jobs/{job_id}/cancel")
def cancel_job(job_id: UUID, user: CurrentUser, db: Db):
    job = _load(db, job_id, user, manage=True)
    db.refresh(job, with_for_update=True)
    if job.state not in ACTIVE:
        raise ApiError(409, "JOB_FINISHED", "任务已结束")
    job.state = "cancelled"
    job.finished_at = datetime.now(UTC)
    if job.kind in CORPUS_STATUS_FOR_KIND:
        settle_corpus(db, job.params["corpus_id"], job.id)
    if job.kind == "preannotate":
        settle_layer(db, job, "预标已取消")
    if job.kind == "kb_import":
        settle_kb_document(db, job, "导入已取消")
    db.commit()
    return job_view(job)


@router.post("/jobs/{job_id}/retry")
def retry_job(job_id: UUID, user: CurrentUser, db: Db):
    job = _load(db, job_id, user, manage=True)
    if job.state not in ("failed", "cancelled"):
        raise ApiError(409, "JOB_NOT_RETRYABLE", "只能重试失败或已取消的任务")
    if job.kind == "import" and db.scalar(
        select(
            exists().where(
                Job.state.in_(ACTIVE), Job.params["dir"].astext == job.params["dir"]
            )
        )
    ):
        raise ApiError(409, "JOB_IN_PROGRESS", "这批文件已在导入")
    if job.kind in CORPUS_STATUS_FOR_KIND:
        corpus = db.get(Corpus, job.params["corpus_id"])
        if not corpus:
            raise not_found("语料库")
        corpus.status = CORPUS_STATUS_FOR_KIND[job.kind]
        corpus.error = None
    if job.kind == "kb_import":
        doc = db.get(KbDocument, job.params["document_id"])
        if not doc:
            raise not_found("文档")
        doc.status, doc.error = "queued", None
    new = enqueue(db, job.kind, job.params, user.id, job.project_id)
    db.commit()
    return job_view(new)


@router.get("/jobs/{job_id}/download")
def download(job_id: UUID, user: CurrentUser, db: Db):
    job = _load(db, job_id, user)
    if job.kind != "export" or job.state != "succeeded":
        raise ApiError(409, "NO_FILE", "任务没有可下载的文件")
    fmt = job.params["format"]
    path = export_path(job.id, fmt)
    if not path.exists():
        raise not_found("导出文件")
    return FileResponse(
        path, media_type=EXPORT_TYPES[fmt], filename=job.result["filename"]
    )
