"""Dedicated host interface. Credentials never enter model arguments or events."""

import hmac
import json
import os
from datetime import timedelta
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Request, Response
from pydantic import Field, ValidationError, field_validator
from sqlalchemy import select
from starlette.concurrency import run_in_threadpool

from services.api import agent_checkpoints as checkpoints
from services.api import agent_config
from services.api import agent_control as control
from services.api.agent_models import AgentCredential, AgentEvent, AgentInvocation
from services.api.agent_routes import Strict
from services.api.auth import token_hash
from services.api.errors import ApiError
from services.api.jobs import EmptyBody

router = APIRouter(prefix="/internal/agent", tags=["internal agent host"])


class ClaimInput(Strict):
    host_id: UUID


class ClaimNextInput(ClaimInput):
    config_id: str = Field(pattern=r"^(local-fixture-v1|openai-[a-f0-9]{48})$")


class SuspendInput(Strict):
    checkpoint_id: UUID


class InvocationInput(Strict):
    request_key: UUID
    tool_call_id: str = Field(min_length=1, max_length=160)
    tool_name: str = Field(min_length=1, max_length=80)
    arguments: dict

    @field_validator("arguments")
    @classmethod
    def bounded(cls, value):
        if len(json.dumps(value, ensure_ascii=False).encode()) > 32768:
            raise ValueError("Tool input is too large")
        return value


class EventInput(Strict):
    event_id: UUID
    kind: Literal["sdk.agent_end", "sdk.agent_settled"]


class CheckpointInput(Strict):
    request_key: UUID
    base_checkpoint_id: UUID | None
    runtime_manifest: dict
    session_jsonl: str = Field(min_length=1, max_length=checkpoints.MAX_BYTES)


class SettleInput(Strict):
    checkpoint_id: UUID | None = None


class ReviewInput(Strict):
    reason: Literal[
        "CHECKPOINT_RESTORE_FAILED",
        "SDK_CONTEXT_UNCERTAIN",
        "JOB_NOT_SUCCEEDED",
        "MODEL_AUTH_FAILED",
        "MODEL_RATE_LIMITED",
        "MODEL_TIMEOUT",
        "MODEL_REQUEST_FAILED",
        "MODEL_RESPONSE_INVALID",
    ]


def bearer(request):
    auth = request.headers.get("authorization", "")
    return auth[7:] if auth.startswith("Bearer ") else ""


def require_host(request):
    configured = os.environ.get("AGENT_HOST_KEY", "")
    if len(configured) < 32 or not hmac.compare_digest(bearer(request), configured):
        raise ApiError(401, "HOST_AUTH_REQUIRED", "Authenticated host required")


@router.post("/claim-next")
def claim_next(body: ClaimNextInput, request: Request, response: Response):
    require_host(request)
    response.headers["Cache-Control"] = "no-store"
    return control.claim_next(body.host_id, body.config_id)


@router.post("/runs/{run_id}/claim")
def claim(run_id: UUID, body: ClaimInput, request: Request, response: Response):
    require_host(request)
    response.headers["Cache-Control"] = "no-store"
    return control.claim(run_id, body.host_id)


@router.post("/runs/{run_id}/heartbeat")
def heartbeat(run_id: UUID, body: EmptyBody, request: Request):
    error = None
    with control.execution(run_id, bearer(request)) as (db, owner, run, _actor, tools):
        try:
            checkpoints.check_context(db, owner, run, tools)
        except ApiError as exc:
            control.stop(db, owner, run, "WAITING_REVIEW", exc.code)
            error = exc
        else:
            run.lease_expires_at = min(
                control.now() + timedelta(seconds=control.LEASE_SECONDS),
                run.active_deadline_at,
            )
        result = control.run_view(run)
    if error:
        raise error
    return result


@router.post("/runs/{run_id}/renew")
def renew(run_id: UUID, body: EmptyBody, request: Request, response: Response):
    token = bearer(request)
    response.headers["Cache-Control"] = "no-store"
    with control.execution(run_id, token) as (db, owner, run, _actor, tools):
        agent_config.require_runtime(run.config_id)
        checkpoints.check_context(db, owner, run, tools)
        credential = db.get(AgentCredential, token_hash(token))
        credential.expires_at = min(
            control.now() + timedelta(seconds=control.CREDENTIAL_SECONDS),
            run.active_deadline_at,
        )
        return {
            "execution_token": token,
            "credential_expires_at": credential.expires_at.isoformat(),
        }


@router.post("/runs/{run_id}/invocations")
def invoke(run_id: UUID, body: InvocationInput, request: Request):
    with control.execution(run_id, bearer(request)) as (db, owner, run, actor, tools):
        return control.invoke(db, owner, run, actor, tools, body)


@router.get("/runs/{run_id}/invocations/{invocation_id}")
def reconcile(run_id: UUID, invocation_id: UUID, request: Request):
    with control.execution(run_id, bearer(request)) as (
        db,
        _owner,
        _run,
        _actor,
        tools,
    ):
        row = db.get(AgentInvocation, invocation_id)
        if row is None or row.run_id != run_id or row.tool_name not in tools:
            raise ApiError(404, "INVOCATION_NOT_FOUND", "Invocation is not accessible")
        from services.api.agent_tools import revalidate_result

        revalidate_result(db, _owner, _actor, row)
        return row.response


@router.post("/runs/{run_id}/events")
def event(run_id: UUID, body: EventInput, request: Request):
    with control.execution(run_id, bearer(request)) as (db, _owner, run, actor, _tools):
        previous = db.get(AgentEvent, body.event_id)
        if previous:
            if previous.run_id != run_id or previous.kind != body.kind:
                raise ApiError(409, "EVENT_CONFLICT", "Event identifier already used")
            return {"event_id": str(previous.id), "sequence": previous.sequence}
        run.event_sequence += 1
        row = AgentEvent(
            id=body.event_id,
            run_id=run_id,
            actor_id=actor.id,
            sequence=run.event_sequence,
            kind=body.kind,
            payload={},
            created_at=control.now(),
        )
        db.add(row)
        return {"event_id": str(row.id), "sequence": row.sequence}


@router.get("/runs/{run_id}/checkpoint")
def get_checkpoint(run_id: UUID, request: Request, response: Response):
    response.headers["Cache-Control"] = "no-store"
    error = None
    with control.execution(run_id, bearer(request)) as (db, owner, run, _actor, tools):
        try:
            row, raw = checkpoints.load_resume(db, owner, run, tools)
            result = {
                "checkpoint": checkpoints.view(row),
                "session_jsonl": raw.decode("utf-8") if raw else None,
            }
        except ApiError as exc:
            control.stop(db, owner, run, "WAITING_REVIEW", exc.code)
            error = exc
    if error:
        raise error
    return result


@router.post("/runs/{run_id}/checkpoint")
async def put_checkpoint(run_id: UUID, request: Request, response: Response):
    response.headers["Cache-Control"] = "no-store"
    # Read a bounded JSON envelope before decoding. The SDK JSONL is capped again
    # in UTF-8 bytes; no request-spooled private file is created.
    content = bytearray()
    async for chunk in request.stream():
        content.extend(chunk)
        if len(content) > 2 * checkpoints.MAX_BYTES:
            raise ApiError(
                413, "CHECKPOINT_TOO_LARGE", "Checkpoint envelope exceeds limit"
            )
    try:
        body = CheckpointInput.model_validate_json(content)
    except ValidationError:
        raise ApiError(
            422, "CHECKPOINT_INPUT_INVALID", "Invalid checkpoint envelope"
        ) from None
    token = bearer(request)

    def write():
        with control.execution(run_id, token) as (db, owner, run, _actor, tools):
            return checkpoints.store(db, owner, run, tools, body, token)

    return await run_in_threadpool(write)


@router.post("/runs/{run_id}/review")
def review(run_id: UUID, body: ReviewInput, request: Request):
    with control.execution(run_id, bearer(request)) as (db, owner, run, actor, _tools):
        if body.reason == "JOB_NOT_SUCCEEDED":
            from services.api import agent_waiting

            refs = agent_waiting.references(db, owner, run, actor)
            if not any(ref["state"] in {"FAILED", "CANCELLED"} for ref in refs):
                raise ApiError(
                    409,
                    "WAITING_JOB_MISMATCH",
                    "No registered background job failed or was cancelled",
                )
        has_invocation = (
            db.scalar(
                select(AgentInvocation.id)
                .where(AgentInvocation.run_id == run.id)
                .limit(1)
            )
            is not None
        )
        state = (
            "FAILED"
            if body.reason.startswith("MODEL_")
            and not has_invocation
            and not run.resume_checkpoint_id
            else "WAITING_REVIEW"
        )
        control.stop(db, owner, run, state, body.reason)
        return control.run_view(run)


@router.post("/runs/{run_id}/suspend")
def suspend(run_id: UUID, body: SuspendInput, request: Request):
    with control.execution(run_id, bearer(request), allow_waiting=True) as (
        db,
        owner,
        run,
        actor,
        tools,
    ):
        return checkpoints.suspend(db, owner, run, actor, tools, body.checkpoint_id)


@router.post("/runs/{run_id}/settle")
def settle(run_id: UUID, body: SettleInput, request: Request):
    with control.execution(run_id, bearer(request), allow_succeeded=True) as (
        db,
        owner,
        run,
        _actor,
        tools,
    ):
        if run.state == "SUCCEEDED":
            if body.checkpoint_id != run.final_checkpoint_id:
                raise ApiError(
                    409,
                    "CHECKPOINT_CONFLICT",
                    "Run already published a different checkpoint",
                )
            row = checkpoints.get_row(db, owner, run.final_checkpoint_id)
            checkpoints.check_dependencies(db, owner, tools, row.dependencies)
            return control.run_view(run)
        checkpoints.settled_sequence(db, run)
        if body.checkpoint_id is None:
            control.stop(db, owner, run, "WAITING_REVIEW", "CHECKPOINT_NOT_IMPLEMENTED")
            return control.run_view(run)
        return checkpoints.publish(db, owner, run, tools, body.checkpoint_id)
