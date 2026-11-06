"""In-app feedback (contracts/p9.md §六): signed-in users send text with the page route and app version;
platform admins list it and mark it handled."""

import os
from datetime import UTC, datetime
from typing import Literal
from uuid import UUID

from fastapi import APIRouter
from pydantic import BaseModel, Field
from sqlalchemy import select

from services.api.access import Paging, human_only, project_role, require_admin
from services.api.auth import CurrentUser, Db
from services.api.errors import ApiError, not_found
from services.api.models import Feedback, Project, User
from services.api.views import user_view

router = APIRouter(prefix="/api")
MAX_TEXT = 2000


class FeedbackInput(BaseModel):
    text: str = Field(max_length=MAX_TEXT * 2)
    page: str = Field(default="", max_length=500)
    project_id: UUID | None = None


class FeedbackPatch(BaseModel):
    status: Literal["open", "done"] | None = None
    admin_note: str | None = Field(default=None, max_length=2000)


def feedback_view(f: Feedback, user=None, project_name=None):
    return {
        "id": f.id,
        "created_at": f.created_at,
        "user": user_view(user) if user else None,
        "project_id": f.project_id,
        "project_name": project_name,
        "page": f.page,
        "app_version": f.app_version,
        "text": f.text,
        "status": f.status,
        "admin_note": f.admin_note,
        "handled_at": f.handled_at,
    }


@router.post("/feedback")
def send_feedback(body: FeedbackInput, user: CurrentUser, db: Db):
    """Browser session only; project_id is kept only when the user is a member."""
    human_only(user)
    text = body.text.strip()
    if not 1 <= len(text) <= MAX_TEXT:
        raise ApiError(422, "VALIDATION_ERROR", f"反馈内容须为 1 到 {MAX_TEXT} 字")
    project_id = body.project_id
    if project_id and project_role(db, project_id, user) is None:
        project_id = None
    f = Feedback(
        user_id=user.id,
        project_id=project_id,
        page=body.page.strip(),
        app_version=(os.environ.get("APP_VERSION") or "dev").strip(),
        text=text,
    )
    db.add(f)
    db.commit()
    return feedback_view(f, user)


@router.get("/admin/feedback")
def list_feedback(
    user: CurrentUser,
    db: Db,
    paging: Paging,
    status: Literal["open", "done"] | None = None,
):
    require_admin(user)
    stmt = (
        select(Feedback, User, Project.name)
        .outerjoin(User, User.id == Feedback.user_id)
        .outerjoin(Project, Project.id == Feedback.project_id)
        .order_by(Feedback.created_at.desc(), Feedback.id.desc())
    )
    if status:
        stmt = stmt.where(Feedback.status == status)
    return paging.run(db, stmt, feedback_view)


@router.patch("/admin/feedback/{feedback_id}")
def update_feedback(feedback_id: int, body: FeedbackPatch, user: CurrentUser, db: Db):
    """status done sets handled_at, open clears it."""
    require_admin(user)
    f = db.get(Feedback, feedback_id, with_for_update=True)
    if not f:
        raise not_found("反馈")
    if body.status is not None and body.status != f.status:
        f.status = body.status
        f.handled_at = datetime.now(UTC) if body.status == "done" else None
    if body.admin_note is not None:
        f.admin_note = body.admin_note.strip()
    db.commit()
    project = db.get(Project, f.project_id) if f.project_id else None
    return feedback_view(
        f, db.get(User, f.user_id) if f.user_id else None, project and project.name
    )
