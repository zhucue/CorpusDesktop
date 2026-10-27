"""Terms (contracts/p4.md §四 术语): CRUD, extraction jobs, corpus examples, export jobs.

Write roles as for documents; confirming needs a cookie session. An agent token may list terms, create drafts
and start extraction; editing, confirming, deleting and adding examples are cookie-only.
"""

import re
from datetime import UTC, datetime
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Query
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import Text, cast, or_, select
from sqlalchemy.exc import IntegrityError

from engine.kb.terms import lang_code
from services.api.access import READ, WRITE, Paging, load_corpus, require_project
from services.api.auth import CurrentUser, Db
from services.api.errors import ApiError, forbidden, not_found
from services.api.jobs import enqueue
from services.api.kb import EDIT, cookie_only, is_bearer
from services.api.models import Document, KbDocument, KbTerm, Subcorpus
from services.api.search import Scope, resolve_scope
from services.api.views import job_view, term_view

router = APIRouter(prefix="/api")

MAX_EXAMPLES = 50
_CJK = re.compile(r"[㐀-䶿一-鿿豈-﫿]")


def now():
    return datetime.now(UTC)


def guess_language(term):
    return "zh" if _CJK.search(term) else "en"


class Translation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    language: str = Field(min_length=1, max_length=20)
    text: str = Field(min_length=1, max_length=500)


class Example(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: str = Field(min_length=1, max_length=5000)
    source: str = Field(default="", max_length=1000)
    hit_id: str | None = Field(default=None, max_length=200)
    document_id: UUID | None = None
    start_cp: int | None = Field(default=None, ge=0)
    end_cp: int | None = Field(default=None, ge=0)


class TermFields(BaseModel):
    model_config = ConfigDict(extra="forbid")
    translations: list[Translation] | None = Field(default=None, max_length=20)
    definition: str | None = Field(default=None, max_length=5000)
    domain: str | None = Field(default=None, max_length=200)
    examples: list[Example] | None = Field(default=None, max_length=MAX_EXAMPLES)
    source: Literal["manual", "corpus", "literature", "model"] | None = None
    status: Literal["draft", "confirmed"] | None = None


class TermInput(TermFields):
    term: str = Field(min_length=1, max_length=200)
    language: str | None = Field(default=None, min_length=1, max_length=20)


class TermPatch(TermFields):
    term: str | None = Field(default=None, min_length=1, max_length=200)
    language: str | None = Field(default=None, min_length=1, max_length=20)


class ExtractInput(BaseModel):
    source: Literal["corpus", "literature"]
    scope: Scope | None = None
    document_ids: list[UUID] | None = Field(default=None, min_length=1, max_length=20)
    method: Literal["pos_pattern", "model"] = "pos_pattern"
    top: int = Field(default=100, ge=1, le=500)
    min_freq: int = Field(default=2, ge=1)
    language: str | None = Field(
        default=None, max_length=20
    )  # only candidates in this language

    @model_validator(mode="after")
    def by_source(self):
        if self.source == "corpus" and self.scope is None:
            raise ValueError("source=corpus 须提供 scope")
        if self.source == "literature" and (
            not self.document_ids or self.method != "model"
        ):
            raise ValueError("source=literature 须提供 document_ids 且 method=model")
        return self


class ExportInput(BaseModel):
    format: Literal["csv", "xlsx", "tbx"]
    status: Literal["draft", "confirmed"] | None = None


def _load(db, term_id, user, roles) -> tuple[KbTerm, str]:
    term = db.get(KbTerm, term_id)
    if not term:
        raise not_found("术语")
    return term, require_project(db, term.project_id, user, roles)


def _check_examples(db, user, examples):
    for e in examples or []:
        if e.document_id:  # a corpus document the user can read
            doc = db.get(Document, e.document_id)
            if not doc:
                raise not_found("文档")
            load_corpus(db, doc.corpus_id, user)


def _apply(term, body, user, fields):
    for key in fields:
        value = getattr(body, key)
        if key in ("translations", "examples"):  # None clears to []
            value = [v.model_dump(mode="json", exclude_none=True) for v in value or []]
        elif key in ("term", "language") and value is not None:
            value = value.strip()
        setattr(term, key, value)
    if "status" in fields:
        term.confirmed_by = user.id if term.status == "confirmed" else None


def _commit(db):
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise ApiError(409, "TERM_EXISTS", "该语言下已有同名术语") from None


@router.get("/projects/{project_id}/kb/terms")
def list_terms(
    project_id: UUID,
    user: CurrentUser,
    db: Db,
    paging: Paging,
    q: str | None = Query(default=None, max_length=200),
    status: Literal["draft", "confirmed"] | None = None,
    language: str | None = Query(default=None, max_length=20),
):
    require_project(db, project_id, user)
    stmt = select(KbTerm).where(KbTerm.project_id == project_id)
    if q:
        pattern = (
            "%" + q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
        )
        stmt = stmt.where(
            or_(
                KbTerm.term.ilike(pattern),
                cast(KbTerm.translations, Text).ilike(pattern),
            )
        )
    if status:
        stmt = stmt.where(KbTerm.status == status)
    if language:
        stmt = stmt.where(KbTerm.language == lang_code(language))
    # newest first; one extraction job writes its drafts with created_at decreasing by rank
    stmt = stmt.order_by(KbTerm.created_at.desc(), KbTerm.term, KbTerm.id)
    return paging.run(db, stmt, term_view)


@router.get("/kb/terms/{term_id}")
def get_term(term_id: UUID, user: CurrentUser, db: Db):
    return term_view(_load(db, term_id, user, READ)[0])


@router.post("/projects/{project_id}/kb/terms")
def create_term(project_id: UUID, body: TermInput, user: CurrentUser, db: Db):
    require_project(db, project_id, user, EDIT)
    if is_bearer(user) and body.status == "confirmed":
        raise forbidden()
    _check_examples(db, user, body.examples)
    term = KbTerm(
        project_id=project_id,
        term=body.term.strip(),
        language=lang_code(body.language)
        if body.language
        else guess_language(body.term),
        status=body.status or "draft",
        source=body.source or ("model" if is_bearer(user) else "manual"),
        created_by=user.id,
    )
    fields = [
        k
        for k in ("translations", "definition", "domain", "examples")
        if k in body.model_fields_set
    ]
    _apply(term, body, user, fields)
    if term.status == "confirmed":
        term.confirmed_by = user.id
    db.add(term)
    _commit(db)
    return term_view(term)


@router.patch("/kb/terms/{term_id}")
def patch_term(term_id: UUID, body: TermPatch, user: CurrentUser, db: Db):
    term, _ = _load(db, term_id, user, EDIT)
    cookie_only(user)
    _check_examples(db, user, body.examples)
    fields = [
        k
        for k in body.model_fields_set
        if getattr(body, k) is not None or k in ("definition", "domain")
    ]
    if "language" in fields:
        body.language = lang_code(body.language)
    _apply(term, body, user, fields)
    term.updated_at = now()
    _commit(db)
    return term_view(term)


@router.delete("/kb/terms/{term_id}", status_code=204)
def delete_term(term_id: UUID, user: CurrentUser, db: Db):
    term, role = _load(db, term_id, user, READ)
    cookie_only(user)
    if role not in WRITE and term.created_by != user.id:
        raise forbidden()
    db.delete(term)
    db.commit()


@router.post("/kb/terms/{term_id}/examples")
def add_example(term_id: UUID, body: Example, user: CurrentUser, db: Db):
    term, _ = _load(db, term_id, user, EDIT)
    cookie_only(user)
    _check_examples(db, user, [body])
    if len(term.examples) >= MAX_EXAMPLES:
        raise ApiError(422, "TOO_MANY_EXAMPLES", f"每个术语最多 {MAX_EXAMPLES} 条例句")
    term.examples = [*term.examples, body.model_dump(mode="json", exclude_none=True)]
    term.updated_at = now()
    db.commit()
    return term_view(term)


@router.post("/projects/{project_id}/kb/terms/extract")
def extract(project_id: UUID, body: ExtractInput, user: CurrentUser, db: Db):
    require_project(db, project_id, user, EDIT)
    if body.source == "corpus":
        corpus, _ = resolve_scope(db, body.scope, user)  # access and index checks
        if (
            body.scope.subcorpus_id
            and db.get(Subcorpus, body.scope.subcorpus_id).project_id != project_id
        ):
            raise forbidden()
        if corpus.project_id not in (None, project_id):
            raise forbidden()
    else:
        docs = db.scalars(
            select(KbDocument).where(KbDocument.id.in_(body.document_ids))
        ).all()
        if len(docs) != len(set(body.document_ids)) or any(
            d.project_id != project_id for d in docs
        ):
            raise not_found("文档")
        if any(not d.chunk_count for d in docs):
            raise ApiError(409, "DOCUMENT_NOT_READY", "文档尚未导入完成")
    params = {"project_id": str(project_id), **body.model_dump(mode="json")}
    job = enqueue(db, "kb_extract", params, user.id, project_id)
    db.commit()
    return job_view(job)


@router.post("/projects/{project_id}/kb/terms/export")
def export_terms(project_id: UUID, body: ExportInput, user: CurrentUser, db: Db):
    require_project(db, project_id, user)
    params = {"source": "kb_terms", "project_id": str(project_id), **body.model_dump()}
    job = enqueue(db, "export", params, user.id, project_id)
    db.commit()
    return job_view(job)
