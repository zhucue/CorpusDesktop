from typing import Literal
from uuid import UUID

from fastapi import APIRouter
from pydantic import BaseModel, Field
from sqlalchemy import select

from services.api.access import MANAGE, Paging, require_project, token_project
from services.api.auth import CurrentUser, Db
from services.api.errors import ApiError, forbidden, not_found
from services.api.label_sets import human_only
from services.api.models import Project, ProjectMember, User
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
