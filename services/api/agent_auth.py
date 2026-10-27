"""Agent tokens (contracts/p2.md §五): opaque, stored as SHA-256 in agent_tokens, valid 30 minutes.

Issued only to a cookie session; `Authorization: Bearer <token>` then acts as that user, limited to the
token's project (services.api.auth.current_user, services.api.access.check_token_project).
"""

import secrets
from datetime import UTC, datetime, timedelta
from uuid import UUID

from fastapi import APIRouter
from pydantic import BaseModel
from sqlalchemy import delete

from services.api.access import require_project, token_project
from services.api.auth import CurrentUser, Db, token_hash
from services.api.errors import forbidden
from services.api.models import AgentToken

router = APIRouter(prefix="/api/auth")
TOKEN_MINUTES = 30


class AgentTokenInput(BaseModel):
    project_id: UUID


@router.post("/agent-token")
def issue(body: AgentTokenInput, user: CurrentUser, db: Db):
    if token_project(user):
        raise forbidden()  # no refresh with a token: the agent re-issues from the user's cookie
    require_project(db, body.project_id, user)
    now = datetime.now(UTC)
    token = secrets.token_urlsafe(32)
    expires_at = now + timedelta(minutes=TOKEN_MINUTES)
    db.execute(delete(AgentToken).where(AgentToken.expires_at <= now))
    db.add(
        AgentToken(
            token_hash=token_hash(token),
            user_id=user.id,
            project_id=body.project_id,
            expires_at=expires_at,
        )
    )
    db.commit()
    return {"token": token, "expires_at": expires_at}
