from uuid import UUID

from fastapi import APIRouter
from pydantic import BaseModel, Field
from sqlalchemy import select

from services.api.access import WRITE, Paging, load_subcorpus, require_project
from services.api.auth import CurrentUser, Db
from services.api.errors import not_found
from services.api.metadata import field_types, subcorpus_stats, validate_filter
from services.api.models import Corpus, Subcorpus

router = APIRouter(prefix="/api")


class SubcorpusInput(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    corpus_id: UUID
    filter: dict


def subcorpus_view(db, sub):
    return {
        "id": sub.id,
        "project_id": sub.project_id,
        "corpus_id": sub.corpus_id,
        "name": sub.name,
        "filter": sub.filter,
        "stats": subcorpus_stats(db, sub),
    }


def project_corpus(db, project_id, corpus_id):
    """Corpus usable from a project: built-in or owned by that project."""
    corpus = db.get(Corpus, corpus_id)
    if not corpus or corpus.project_id not in (None, project_id):
        raise not_found("语料库")
    return corpus


@router.get("/projects/{project_id}/subcorpora")
def list_subcorpora(project_id: UUID, user: CurrentUser, db: Db, paging: Paging):
    require_project(db, project_id, user)
    stmt = (
        select(Subcorpus)
        .where(Subcorpus.project_id == project_id)
        .order_by(Subcorpus.created_at, Subcorpus.id)
    )
    return paging.run(db, stmt, lambda sub: subcorpus_view(db, sub))


@router.post("/projects/{project_id}/subcorpora")
def create_subcorpus(project_id: UUID, body: SubcorpusInput, user: CurrentUser, db: Db):
    require_project(db, project_id, user, WRITE)
    project_corpus(db, project_id, body.corpus_id)
    validate_filter(body.filter, field_types(db, body.corpus_id))
    sub = Subcorpus(
        project_id=project_id,
        corpus_id=body.corpus_id,
        name=body.name.strip(),
        filter=body.filter,
        created_by=user.id,
    )
    db.add(sub)
    db.commit()
    return subcorpus_view(db, sub)


@router.get("/subcorpora/{subcorpus_id}")
def get_subcorpus(subcorpus_id: UUID, user: CurrentUser, db: Db):
    return subcorpus_view(db, load_subcorpus(db, subcorpus_id, user))


@router.delete("/subcorpora/{subcorpus_id}", status_code=204)
def delete_subcorpus(subcorpus_id: UUID, user: CurrentUser, db: Db):
    db.delete(load_subcorpus(db, subcorpus_id, user, write=True))
    db.commit()
