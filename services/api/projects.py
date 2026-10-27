"""Project operations share RLS and policy checks with material/job handlers."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from services.api.auth import CurrentActor
from services.api.db import lock_actor, lock_project, transaction
from services.api.errors import ApiError
from services.api.models import Project, ProjectMember, User

router = APIRouter(prefix="/api/v1/projects", tags=["projects"])


class ProjectInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=160)

    @field_validator("name")
    @classmethod
    def nonempty(cls, value):
        if not value.strip():
            raise ValueError("Name required")
        return value.strip()


class Permissions(BaseModel):
    upload: bool
    manage_members: bool
    read_jobs: bool


class ProjectView(BaseModel):
    id: UUID
    name: str
    owner_id: UUID
    role: Literal["owner", "editor", "viewer"]
    created_at: datetime
    permissions: Permissions


class ProjectList(BaseModel):
    items: list[ProjectView]


class MemberInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    role: Literal["editor", "viewer"]


class MemberView(BaseModel):
    user_id: UUID
    email: str
    role: Literal["owner", "editor", "viewer"]


class MemberList(BaseModel):
    items: list[MemberView]


def project_role(session, actor_id, project):
    if project.owner_id == actor_id:
        return "owner"
    member = session.get(ProjectMember, (project.id, actor_id))
    return member.role if member else None


def require_project(
    session: Session, actor_id: UUID, project_id: UUID, *, write=False, owner=False
) -> Project:
    if write or owner:
        lock_actor(session, actor_id)
        lock_project(session, project_id)
    active = session.scalar(select(User.is_active).where(User.id == actor_id))
    if not active:
        raise ApiError(401, "AUTH_REQUIRED", "Sign in required")
    project = session.get(Project, project_id)
    if project is None:
        raise ApiError(404, "PROJECT_NOT_FOUND", "Project not found")
    role = project_role(session, actor_id, project)
    if not role:
        raise ApiError(404, "PROJECT_NOT_FOUND", "Project not found")
    if (owner and role != "owner") or (write and role not in {"owner", "editor"}):
        raise ApiError(403, "PROJECT_FORBIDDEN", "Project permission required")
    return project


def view(session, actor_id, project):
    role = project_role(session, actor_id, project)
    return ProjectView(
        id=project.id,
        name=project.name,
        owner_id=project.owner_id,
        role=role,
        created_at=project.created_at,
        permissions=Permissions(
            upload=role in {"owner", "editor"},
            manage_members=role == "owner",
            read_jobs=True,
        ),
    )


@router.post("", status_code=201, response_model=ProjectView)
def create_project(body: ProjectInput, actor: CurrentActor):
    with transaction(actor.id) as session:
        lock_actor(session, actor.id)
        if not session.scalar(select(User.is_active).where(User.id == actor.id)):
            raise ApiError(401, "AUTH_REQUIRED", "Sign in required")
        project = Project(name=body.name, owner_id=actor.id)
        session.add(project)
        session.flush()
        session.add(
            ProjectMember(
                project_id=project.id, user_id=actor.id, owner_id=actor.id, role="owner"
            )
        )
        session.flush()
        return view(session, actor.id, project)


@router.get("", response_model=ProjectList)
def list_projects(actor: CurrentActor):
    with transaction(actor.id) as session:
        return ProjectList(
            items=[
                view(session, actor.id, project)
                for project in session.scalars(
                    select(Project).order_by(Project.created_at, Project.id)
                )
            ]
        )


@router.get("/{project_id}", response_model=ProjectView)
def get_project(project_id: UUID, actor: CurrentActor):
    with transaction(actor.id) as session:
        return view(session, actor.id, require_project(session, actor.id, project_id))


@router.get("/{project_id}/members", response_model=MemberList)
def list_members(project_id: UUID, actor: CurrentActor):
    with transaction(actor.id) as session:
        require_project(session, actor.id, project_id, owner=True)
        rows = session.execute(
            select(ProjectMember, User.email)
            .join(User, User.id == ProjectMember.user_id)
            .where(ProjectMember.project_id == project_id)
            .order_by(User.email)
        )
        return MemberList(
            items=[
                MemberView(user_id=member.user_id, email=email, role=member.role)
                for member, email in rows
            ]
        )


@router.put("/{project_id}/members/{user_id}", response_model=MemberView)
def set_member(project_id: UUID, user_id: UUID, body: MemberInput, actor: CurrentActor):
    with transaction(actor.id) as session:
        project = require_project(session, actor.id, project_id, owner=True)
        if user_id == project.owner_id:
            raise ApiError(409, "OWNER_IMMUTABLE", "Project owner cannot be changed")
        user = session.get(User, user_id)
        if not user or not user.is_active:
            raise ApiError(404, "ACCOUNT_NOT_FOUND", "Active account not found")
        member = session.get(ProjectMember, (project_id, user_id))
        if member:
            member.role = body.role
        else:
            session.add(
                ProjectMember(
                    project_id=project_id,
                    user_id=user_id,
                    owner_id=project.owner_id,
                    role=body.role,
                )
            )
        session.flush()
        return MemberView(user_id=user_id, email=user.email, role=body.role)


@router.delete("/{project_id}/members/{user_id}", status_code=204)
def remove_member(project_id: UUID, user_id: UUID, actor: CurrentActor):
    with transaction(actor.id) as session:
        project = require_project(session, actor.id, project_id, owner=True)
        if user_id == project.owner_id:
            raise ApiError(409, "OWNER_IMMUTABLE", "Project owner cannot be changed")
        member = session.get(ProjectMember, (project_id, user_id))
        if not member:
            raise ApiError(404, "MEMBER_NOT_FOUND", "Member not found")
        session.delete(member)
