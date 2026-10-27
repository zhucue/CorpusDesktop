"""User-owned fixed-scope sessions and durable run inspection/cancellation."""

from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Query
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select, tuple_
from sqlalchemy.exc import SQLAlchemyError

from contracts.agent import (
    EventList,
    MessageList,
    RunInput,
    RunList,
    RuntimeView,
    RunView,
    SessionInput,
    SessionList,
    SessionView,
)
from services.api import (
    agent_checkpoints,
    agent_config,
    agent_projection,
    agent_waiting,
)
from services.api import agent_control as control
from services.api.agent_models import (
    AgentEvent,
    AgentInvocation,
    AgentSession,
)
from services.api.agent_tools import revalidate_result
from services.api.auth import CurrentActor
from services.api.db import bound_transaction, transaction
from services.api.errors import ApiError
from services.api.job_models import Job
from services.api.jobs import EmptyBody
from services.api.jobs import cancel as cancel_job

router = APIRouter(prefix="/api/v1/agent", tags=["agent control foundation"])


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


@router.get("/runtime", response_model=RuntimeView)
def runtime(actor: CurrentActor):
    return agent_config.runtime_view()


@router.get("/sessions", response_model=SessionList)
def sessions(
    actor: CurrentActor,
    scope_kind: Literal["account", "platform", "project"] | None = None,
    project_id: UUID | None = None,
    before: UUID | None = None,
    limit: int = Query(20, ge=1, le=50),
):
    with transaction(actor.id) as db:
        query = select(AgentSession).where(AgentSession.actor_id == actor.id)
        if scope_kind:
            query = query.where(AgentSession.scope["scope_kind"].astext == scope_kind)
        if project_id:
            query = query.where(
                AgentSession.scope["project_id"].astext == str(project_id)
            )
        if before:
            anchor = db.get(AgentSession, before)
            if anchor is None or anchor.actor_id != actor.id:
                raise ApiError(
                    422, "CURSOR_INVALID", "Session cursor is not accessible"
                )
            query = query.where(
                tuple_(AgentSession.created_at, AgentSession.id)
                < (anchor.created_at, anchor.id)
            )
        rows = list(
            db.scalars(
                query.order_by(
                    AgentSession.created_at.desc(), AgentSession.id.desc()
                ).limit(limit + 1)
            )
        )
        return {
            "items": [control.session_view(row) for row in rows[:limit]],
            "next_before": str(rows[limit - 1].id) if len(rows) > limit else None,
        }


@router.get("/sessions/{session_id}/runs", response_model=RunList)
def runs(
    session_id: UUID,
    actor: CurrentActor,
    before: UUID | None = None,
    limit: int = Query(20, ge=1, le=50),
):
    with transaction(actor.id) as db:
        owner, _, tools = control.load_owned(db, actor.id, session_id)
        rows = agent_projection.page_runs(db, session_id, before, limit)
        items = []
        for row in rows[:limit]:
            try:
                agent_checkpoints.check_context(db, owner, row, tools)
            except ApiError:
                continue
            items.append(control.run_view(row))
        return {
            "items": items,
            "next_before": str(rows[limit - 1].id) if len(rows) > limit else None,
        }


@router.get("/sessions/{session_id}/messages", response_model=MessageList)
def messages(
    session_id: UUID,
    actor: CurrentActor,
    before: UUID | None = None,
    limit: int = Query(20, ge=1, le=50),
):
    with transaction(actor.id) as db:
        owner, current_actor, tools = control.load_owned(db, actor.id, session_id)
        rows = agent_projection.page_runs(db, session_id, before, limit)
        # On revoked history return an explicit error, never a partial conversation
        # which could make the remaining assistant prose appear independently safe.
        items = [
            agent_projection.messages(db, owner, row, current_actor, tools)
            for row in rows[:limit]
        ]
        return {
            "items": items,
            "next_before": str(rows[limit - 1].id) if len(rows) > limit else None,
        }


@router.post("/sessions", status_code=201, response_model=SessionView)
def create_session(body: SessionInput, actor: CurrentActor):
    return control.create_session(actor.id, body.scope.model_dump(mode="json"))


@router.get("/sessions/{session_id}", response_model=SessionView)
def get_session(session_id: UUID, actor: CurrentActor):
    with transaction(actor.id) as db:
        row, _, _ = control.load_owned(db, actor.id, session_id)
        return control.session_view(row)


@router.post("/sessions/{session_id}/runs", status_code=201, response_model=RunView)
def create_run(session_id: UUID, body: RunInput, actor: CurrentActor):
    result = control.create_run(
        actor.id, session_id, body.request_key, body.message, body.scope_digest
    )
    if result.get("busy"):
        raise ApiError(
            409, "SESSION_BUSY", "Session has an active run or requires review"
        )
    return result


@router.get("/runs/{run_id}", response_model=RunView)
def get_run(run_id: UUID, actor: CurrentActor):
    with transaction(actor.id) as db:
        owner, run, current_actor, tools = control.load_run(db, actor.id, run_id)
        agent_checkpoints.check_context(db, owner, run, tools)
        control.expire(db, owner, run)
        result = control.run_view(run)
        if run.state == "WAITING_JOB":
            result["waiting_jobs"] = agent_waiting.references(
                db, owner, run, current_actor
            )
        return result


@router.get("/runs/{run_id}/events", response_model=EventList)
def events(run_id: UUID, actor: CurrentActor, after: int = Query(0, ge=0)):
    with transaction(actor.id) as db:
        owner, run, _, tools = control.load_run(db, actor.id, run_id)
        agent_checkpoints.check_context(db, owner, run, tools)
        rows = list(
            db.scalars(
                select(AgentEvent)
                .where(AgentEvent.run_id == run_id, AgentEvent.sequence > after)
                .order_by(AgentEvent.sequence)
                .limit(100)
            )
        )
        return {
            "items": [
                {
                    "event_id": str(row.id),
                    "sequence": row.sequence,
                    "kind": row.kind,
                    "payload": row.payload,
                    "created_at": row.created_at.isoformat(),
                }
                for row in rows
            ],
            "next_after": rows[-1].sequence if rows else after,
        }


@router.get("/runs/{run_id}/invocations/{invocation_id}")
def invocation(run_id: UUID, invocation_id: UUID, actor: CurrentActor):
    with transaction(actor.id) as db:
        owner, run, current_actor, tools = control.load_run(db, actor.id, run_id)
        agent_checkpoints.check_context(db, owner, run, tools)
        row = db.get(AgentInvocation, invocation_id)
        if row is None or row.run_id != run_id:
            raise ApiError(404, "INVOCATION_NOT_FOUND", "Invocation not found")
        revalidate_result(db, owner, current_actor, row)
        return row.response


@router.post("/runs/{run_id}/cancel", response_model=RunView)
def cancel(run_id: UUID, body: EmptyBody, actor: CurrentActor):
    with transaction(actor.id) as db:
        owner, run, current_actor, _ = control.load_run(db, actor.id, run_id)
        if run.state not in {"CANCELLED", "SUCCEEDED", "FAILED"}:
            control.stop(db, owner, run, "CANCELLED", "USER_CANCELLED")
            # Only jobs whose business action was created by this invocation are
            # exclusive. A pre-existing/retried job must continue independently.
            with bound_transaction(actor.id, db):
                for entry in db.scalars(
                    select(AgentInvocation).where(AgentInvocation.run_id == run_id)
                ):
                    result = entry.response["result"]
                    if result["status"] != "accepted" or entry.tool_name not in {
                        "uploads.complete",
                        "imports.start",
                        "exports.create",
                    }:
                        continue
                    job = db.get(Job, UUID(result["job_id"]))
                    if (
                        job
                        and job.action_id == entry.action_id
                        and job.actor_id == actor.id
                        and job.state in {"QUEUED", "RUNNING"}
                    ):
                        try:
                            with db.begin_nested():
                                cancel_job(
                                    job.id,
                                    EmptyBody(),
                                    current_actor,
                                    "agent-cancel:" + str(run.id) + ":" + str(job.id),
                                )
                        except (ApiError, SQLAlchemyError):
                            # Stopping the run must remain possible after a role
                            # downgrade. Worker publication still checks current
                            # authorization; do not impersonate a project owner.
                            control.emit(
                                db,
                                run,
                                "job.cancel_not_applied",
                                {"job_id": str(job.id)},
                            )
        return control.run_view(run)
