import shutil
from typing import Literal
from uuid import UUID

from fastapi import APIRouter
from pydantic import BaseModel, Field
from sqlalchemy import delete, func, select

from services.api.access import MANAGE, Paging, require_project, token_project
from services.api.auth import CurrentUser, Db
from services.api.errors import ApiError, forbidden, not_found
from services.api.label_sets import human_only
from services.api.models import (
    AnnotationLayer,
    Corpus,
    Job,
    KbDocument,
    KbTerm,
    Project,
    ProjectMember,
    User,
)
from services.api.storage import corpus_dir, data_dir, kb_dir, upload_dir
from services.api.views import project_view

router = APIRouter(prefix="/api/projects")


class ProjectInput(BaseModel):
    name: str = Field(min_length=1, max_length=200)


class MemberInput(BaseModel):
    role: Literal["owner", "editor", "annotator", "viewer"]


def member_view(user, role):
    return {"user_id": user.id, "email": user.email, "role": role}


@router.get("")
def list_projects(user: CurrentUser, db: Db, paging: Paging):
    stmt = (
        select(Project, ProjectMember.role)
        .join(ProjectMember, ProjectMember.project_id == Project.id)
        .where(ProjectMember.user_id == user.id)
        .order_by(Project.created_at, Project.id)
    )
    if token_project(user):
        stmt = stmt.where(Project.id == token_project(user))
    return paging.run(db, stmt, project_view)


@router.post("")
def create_project(body: ProjectInput, user: CurrentUser, db: Db):
    if token_project(user):
        raise forbidden()
    project = Project(name=body.name.strip(), created_by=user.id)
    db.add(project)
    db.flush()
    db.add(ProjectMember(project_id=project.id, user_id=user.id, role="owner"))
    db.commit()
    return project_view(project, "owner")


@router.get("/{project_id}")
def get_project(project_id: UUID, user: CurrentUser, db: Db):
    role = require_project(db, project_id, user)
    return project_view(db.get(Project, project_id), role)


@router.patch("/{project_id}")
def rename_project(project_id: UUID, body: ProjectInput, user: CurrentUser, db: Db):
    human_only(user)
    role = require_project(db, project_id, user, MANAGE)
    project = db.get(Project, project_id)
    project.name = body.name.strip()
    db.commit()
    return project_view(project, role)


def _count(db, model, *where):
    return db.scalar(select(func.count()).select_from(model).where(*where)) or 0


@router.get("/{project_id}/usage")
def project_usage(project_id: UUID, user: CurrentUser, db: Db):
    """What deleting the project removes: corpora, annotation layers, notes, other KB documents, terms, members."""
    require_project(db, project_id, user)
    kb = KbDocument.project_id == project_id
    return {
        "corpora": _count(db, Corpus, Corpus.project_id == project_id),
        "layers": _count(db, AnnotationLayer, AnnotationLayer.project_id == project_id),
        "notes": _count(db, KbDocument, kb, KbDocument.kind == "note"),
        "kb_documents": _count(db, KbDocument, kb, KbDocument.kind != "note"),
        "terms": _count(db, KbTerm, KbTerm.project_id == project_id),
        "members": _count(db, ProjectMember, ProjectMember.project_id == project_id),
    }


@router.delete("/{project_id}", status_code=204)
def delete_project(project_id: UUID, user: CurrentUser, db: Db):
    """Owner only, cookie session only. Everything of the project goes (database rows cascade) and so do its
    corpus, knowledge base, upload and export files."""
    human_only(user)
    require_project(db, project_id, user, MANAGE)
    corpora = db.scalars(select(Corpus.id).where(Corpus.project_id == project_id)).all()
    docs = db.scalars(select(KbDocument.id).where(KbDocument.project_id == project_id)).all()
    jobs = db.scalars(select(Job.id).where(Job.project_id == project_id)).all()
    # layers first: their label sets (also project rows) are referenced with ON DELETE RESTRICT
    db.execute(delete(AnnotationLayer).where(AnnotationLayer.project_id == project_id))
    db.delete(db.get(Project, project_id))
    db.commit()
    for cid in corpora:
        shutil.rmtree(corpus_dir(cid), ignore_errors=True)
    for did in docs:
        shutil.rmtree(kb_dir(did), ignore_errors=True)
    for jid in jobs:
        shutil.rmtree(upload_dir(jid), ignore_errors=True)
        for f in (data_dir() / "exports").glob(f"{jid}.*"):
            f.unlink(missing_ok=True)


@router.get("/{project_id}/members")
def list_members(project_id: UUID, user: CurrentUser, db: Db, paging: Paging):
    require_project(db, project_id, user)
    stmt = (
        select(User, ProjectMember.role)
        .join(ProjectMember, ProjectMember.user_id == User.id)
        .where(ProjectMember.project_id == project_id)
        .order_by(User.email)
    )
    return paging.run(db, stmt, member_view)


def _check_last_owner(db, project_id, user_id):
    owners = db.scalars(
        select(ProjectMember.user_id)
        .where(ProjectMember.project_id == project_id, ProjectMember.role == "owner")
        .with_for_update()
    ).all()
    if owners == [user_id]:
        raise ApiError(409, "LAST_OWNER", "项目至少保留一名所有者")


@router.put("/{project_id}/members/{user_id}")
def put_member(
    project_id: UUID, user_id: UUID, body: MemberInput, user: CurrentUser, db: Db
):
    # membership changes only from a cookie session, never an agent token
    human_only(user)
    require_project(db, project_id, user, MANAGE)
    target = db.get(User, user_id)
    if not target:
        raise not_found("用户")
    member = db.get(ProjectMember, (project_id, user_id))
    if member is None:
        member = ProjectMember(project_id=project_id, user_id=user_id, role=body.role)
        db.add(member)
    elif member.role != body.role:
        if member.role == "owner":
            _check_last_owner(db, project_id, user_id)
        member.role = body.role
    db.commit()
    return member_view(target, member.role)


@router.delete("/{project_id}/members/{user_id}", status_code=204)
def delete_member(project_id: UUID, user_id: UUID, user: CurrentUser, db: Db):
    # membership changes only from a cookie session, never an agent token
    human_only(user)
    require_project(db, project_id, user, MANAGE)
    member = db.get(ProjectMember, (project_id, user_id))
    if member is None:
        raise not_found("成员")
    if member.role == "owner":
        _check_last_owner(db, project_id, user_id)
    db.delete(member)
    db.commit()
