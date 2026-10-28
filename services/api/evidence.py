"""Evidence basket (contracts/p2.md §四): pinned hits, stat rows and text, kept per project."""

from typing import Literal
from uuid import UUID

from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select

from services.api.access import (
    WRITE,
    Paging,
    human_only,
    load_corpus,
    require_project,
)
from services.api.auth import CurrentUser, Db
from services.api.errors import forbidden, not_found
from services.api.jobs import enqueue
from services.api.models import Document, Evidence, StatResult
from services.api.views import evidence_view, job_view

router = APIRouter(prefix="/api")

PIN = ("owner", "editor", "annotator")


class EvidenceRef(BaseModel):
    model_config = ConfigDict(extra="forbid")
    search_query: str | None = Field(default=None, max_length=1000)
    scope: dict | None = None
    hit_id: str | None = Field(default=None, max_length=200)
    document_id: UUID | None = None
    start_cp: int | None = Field(default=None, ge=0)
    end_cp: int | None = Field(default=None, ge=0)
    stat_id: UUID | None = None
    row_key: str | None = Field(default=None, max_length=2000)


class EvidenceInput(BaseModel):
    kind: Literal["hit", "stat_row", "text"]
    ref: EvidenceRef = EvidenceRef()
    text: str = Field(min_length=1, max_length=20000)
    source: str = Field(max_length=1000)
    note: str | None = Field(default=None, max_length=5000)


class ExportInput(BaseModel):
    format: Literal["csv", "xlsx", "docx"]


@router.get("/projects/{project_id}/evidence")
def list_evidence(project_id: UUID, user: CurrentUser, db: Db, paging: Paging):
    require_project(db, project_id, user)
    stmt = (
        select(Evidence)
        .where(Evidence.project_id == project_id)
        .order_by(Evidence.created_at.desc(), Evidence.id)
    )
    return paging.run(db, stmt, evidence_view)


@router.post("/projects/{project_id}/evidence")
def create_evidence(project_id: UUID, body: EvidenceInput, user: CurrentUser, db: Db):
    require_project(db, project_id, user, PIN)
    ref = body.ref
    if ref.document_id:  # the pinned document must be readable by this user
        doc = db.get(Document, ref.document_id)
        if not doc:
            raise not_found("文档")
        load_corpus(db, doc.corpus_id, user)
    if ref.stat_id:
        stat = db.get(StatResult, ref.stat_id)
        if not stat or stat.project_id != project_id:
            raise not_found("统计结果")
    item = Evidence(
        project_id=project_id,
        kind=body.kind,
        ref=ref.model_dump(mode="json", exclude_none=True),
        text=body.text,
        source=body.source,
        note=body.note,
        created_by=user.id,
    )
    db.add(item)
    db.commit()
    return evidence_view(item)


@router.delete("/evidence/{evidence_id}", status_code=204)
def delete_evidence(evidence_id: UUID, user: CurrentUser, db: Db):
    human_only(user)
    item = db.get(Evidence, evidence_id)
    if not item:
        raise not_found("证据")
    role = require_project(db, item.project_id, user)
    if role not in WRITE and item.created_by != user.id:
        raise forbidden()
    db.delete(item)
    db.commit()


@router.post("/projects/{project_id}/evidence/export")
def export_evidence(project_id: UUID, body: ExportInput, user: CurrentUser, db: Db):
    require_project(db, project_id, user)
    params = {
        "source": "evidence",
        "project_id": str(project_id),
        "format": body.format,
    }
    job = enqueue(db, "export", params, user.id, project_id)
    db.commit()
    return job_view(job)
