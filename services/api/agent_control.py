"""Fenced PG control, invocation reconciliation and conservative completion."""

import hashlib
import json
import secrets
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from fastapi.encoders import jsonable_encoder
from pydantic import ValidationError
from sqlalchemy import select, text
from sqlalchemy.exc import SQLAlchemyError

from services.api import agent_config, agent_waiting
from services.api.agent_models import (
    AgentCredential,
    AgentEvent,
    AgentInvocation,
    AgentRun,
    AgentSession,
)
from services.api.agent_tools import WRITES, allowed_tools, dispatch
from services.api.auth import Actor, token_hash
from services.api.db import bound_transaction, lock_actor, lock_project, transaction
from services.api.errors import ApiError
from services.api.job_models import Action
from services.api.models import User
from services.api.projects import project_role, require_project

LEASE_SECONDS = 60
CREDENTIAL_SECONDS = 300


def now():
    return datetime.now(UTC)


def digest(value):
    return hashlib.sha256(
        json.dumps(
            value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
        ).encode()
    ).hexdigest()


def authorize(db, actor_id, scope):
    lock_actor(db, actor_id)
    user = db.scalar(
        select(User)
        .where(User.id == actor_id)
        .execution_options(populate_existing=True)
    )
    if not user or not user.is_active:
        raise ApiError(
            403, "AGENT_AUTH_REVOKED", "Execution authorization is no longer valid"
        )
    role = None
    if scope["scope_kind"] == "project":
        project_id = UUID(scope["project_id"])
        lock_project(db, project_id)
        project = require_project(db, actor_id, project_id)
        role = project_role(db, actor_id, project)
    elif scope["scope_kind"] == "platform" and not user.is_platform_admin:
        raise ApiError(
            403, "ADMIN_REQUIRED", "Current administrator permission required"
        )
    return Actor(user.id, user.email, user.is_platform_admin, ""), allowed_tools(
        scope, role
    )


def load_owned(db, actor_id, session_id):
    row = db.get(AgentSession, session_id)
    if row is None or row.actor_id != actor_id:
        raise ApiError(404, "AGENT_SESSION_NOT_FOUND", "Session is not accessible")
    actor, tools = authorize(db, actor_id, row.scope)
    row = db.scalar(
        select(AgentSession)
        .where(AgentSession.id == session_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    return row, actor, tools


def load_run(db, actor_id, run_id):
    run = db.get(AgentRun, run_id)
    if run is None or run.actor_id != actor_id:
        raise ApiError(404, "AGENT_RUN_NOT_FOUND", "Run is not accessible")
    owner, actor, tools = load_owned(db, actor_id, run.session_id)
    run = db.scalar(
        select(AgentRun)
        .where(AgentRun.id == run_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    return owner, run, actor, tools


def emit(db, run, kind, payload=None):
    run.event_sequence += 1
    run.updated_at = now()
    db.add(
        AgentEvent(
            run_id=run.id,
            actor_id=run.actor_id,
            sequence=run.event_sequence,
            kind=kind,
            payload=payload or {},
            created_at=now(),
        )
    )


def stop(db, owner, run, state, reason):
    owner.lease_epoch += 1
    run.state, run.reason = state, reason
    run.lease_expires_at, run.host_id = None, None
    if state in {"CANCELLED", "SUCCEEDED", "FAILED"} and owner.active_run_id == run.id:
        owner.active_run_id = None
    emit(db, run, "run." + state.lower(), {"reason": reason})


def expire(db, owner, run):
    if run.state == "WAITING_JOB" and run.wait_deadline_at <= now():
        stop(db, owner, run, "WAITING_REVIEW", "WAIT_DEADLINE_EXCEEDED")
        return True
    if run.state == "RUNNING" and (
        run.lease_expires_at <= now()
        or (run.active_deadline_at and run.active_deadline_at <= now())
    ):
        stop(db, owner, run, "WAITING_REVIEW", "LEASE_EXPIRED_NO_CHECKPOINT")
        return True
    return False


def session_view(row):
    return {
        "session_id": str(row.id),
        "config_id": row.config_id,
        "scope": row.scope,
        "scope_digest": row.scope_digest,
        "active_run_id": str(row.active_run_id) if row.active_run_id else None,
        "latest_checkpoint_id": str(row.latest_checkpoint_id)
        if row.latest_checkpoint_id
        else None,
        "lease_epoch": row.lease_epoch,
        "created_at": row.created_at.isoformat(),
    }


def run_view(run):
    return {
        "run_id": str(run.id),
        "session_id": str(run.session_id),
        "config_id": run.config_id,
        "resume_checkpoint_id": str(run.resume_checkpoint_id)
        if run.resume_checkpoint_id
        else None,
        "waiting_jobs": run.waiting_jobs or [],
        "active_deadline_at": run.active_deadline_at.isoformat()
        if run.active_deadline_at
        else None,
        "wait_deadline_at": run.wait_deadline_at.isoformat()
        if run.wait_deadline_at
        else None,
        "state": run.state,
        "reason": run.reason,
        "scope_digest": run.scope_digest,
        "lease_epoch": run.lease_epoch,
        "lease_expires_at": run.lease_expires_at.isoformat()
        if run.lease_expires_at
        else None,
        "event_sequence": run.event_sequence,
        "allowed_tools": run.allowed_tools,
        "base_checkpoint_id": str(run.base_checkpoint_id)
        if run.base_checkpoint_id
        else None,
        "final_checkpoint_id": str(run.final_checkpoint_id)
        if run.final_checkpoint_id
        else None,
        "created_at": run.created_at.isoformat(),
        "updated_at": run.updated_at.isoformat(),
    }


def create_session(actor_id, scope):
    config = agent_config.runtime_view()
    agent_config.require_runtime()
    with transaction(actor_id) as db:
        authorize(db, actor_id, scope)
        row = AgentSession(
            actor_id=actor_id,
            scope=scope,
            scope_digest=digest(scope),
            config_id=config["config_id"],
            lease_epoch=0,
            created_at=now(),
        )
        db.add(row)
        db.flush()
        return session_view(row)


def create_run(actor_id, session_id, request_key, message, scope_digest):
    with transaction(actor_id) as db:
        owner, _, tools = load_owned(db, actor_id, session_id)
        if scope_digest != owner.scope_digest:
            raise ApiError(
                409,
                "SESSION_SCOPE_CHANGED",
                "Message scope differs from the fixed session scope",
            )
        request_digest = digest(
            {
                "message": message,
                "scope_digest": scope_digest,
                "config_id": owner.config_id,
            }
        )
        previous = db.scalar(
            select(AgentRun).where(
                AgentRun.session_id == session_id, AgentRun.request_key == request_key
            )
        )
        if previous:
            if previous.request_digest != request_digest:
                raise ApiError(
                    409,
                    "RUN_REQUEST_CONFLICT",
                    "Request key is already bound to different message input",
                )
            expire(db, owner, previous)
            return run_view(previous)
        if owner.active_run_id:
            active = db.get(AgentRun, owner.active_run_id)
            expire(db, owner, active)
            # WAITING_REVIEW also blocks continuation until explicitly cancelled.
            return {"busy": True, "run": run_view(active)}
        agent_config.require_runtime()
        if owner.config_id != agent_config.runtime_view()["config_id"]:
            raise ApiError(
                409,
                "AGENT_CONFIG_CHANGED",
                "Create a new session for the current model configuration",
            )
        agent_config.require_runtime(owner.config_id)
        run = AgentRun(
            id=uuid4(),
            session_id=session_id,
            actor_id=actor_id,
            request_key=request_key,
            request_digest=request_digest,
            user_message=message,
            config_id=owner.config_id,
            waiting_jobs=[],
            scope_digest=owner.scope_digest,
            state="QUEUED",
            allowed_tools=tools,
            lease_epoch=owner.lease_epoch,
            base_checkpoint_id=owner.latest_checkpoint_id,
            event_sequence=0,
            created_at=now(),
            updated_at=now(),
        )
        db.add(run)
        db.flush()
        owner.active_run_id = run.id
        emit(db, run, "run.queued")
        return run_view(run)


def claim(run_id, host_id):
    result = _claim(run_id, host_id)
    if result.get("review_error"):
        raise result["review_error"]
    if result.get("pending"):
        raise ApiError(409, "JOBS_PENDING", "Required jobs are still running")
    return result


def claim_next(host_id, config_id):
    agent_config.require_runtime(config_id)
    # Candidate selection does not hold task locks before actor/project locks.
    # The existing claim transaction decides the single winner of a race.
    # Enumerate in bounded pages without retaining a transaction while trying
    # candidates. QUEUED takes priority; no fixed first-100 waiting starvation.
    for state in ("QUEUED", "WAITING_JOB"):
        after = None
        while True:
            with transaction() as db:
                db.execute(text("SELECT set_config('app.agent_host','true',true)"))
                query = select(AgentRun.id).where(
                    AgentRun.config_id == config_id, AgentRun.state == state
                )
                if after:
                    query = query.where(AgentRun.id > after)
                candidates = list(db.scalars(query.order_by(AgentRun.id).limit(100)))
            for candidate in candidates:
                try:
                    return {"grant": claim(candidate, host_id)}
                except ApiError as exc:
                    if exc.status not in {401, 403, 404, 409}:
                        raise
            if len(candidates) < 100:
                break
            after = candidates[-1]
    return {"grant": None}


def _claim(run_id, host_id):
    from services.api import agent_checkpoints as checkpoints

    agent_config.require_runtime()
    # This lookup is reachable only after the dedicated host key was authenticated.
    with transaction() as db:
        db.execute(text("SELECT set_config('app.agent_host','true',true)"))
        hint = db.get(AgentRun, run_id)
        if hint is None:
            raise ApiError(404, "AGENT_RUN_NOT_FOUND", "Run not found")
        actor_id = hint.actor_id
    result = None
    with transaction(actor_id) as db:
        owner, run, actor, current_tools = load_run(db, actor_id, run_id)
        agent_config.require_runtime(run.config_id)
        if expire(db, owner, run):
            result = {"expired": True}
        elif (
            run.state not in {"QUEUED", "WAITING_JOB"} or owner.active_run_id != run.id
        ):
            raise ApiError(409, "SESSION_BUSY", "Run is not claimable")
        else:
            if run.state == "WAITING_JOB":
                try:
                    refs = agent_waiting.references(db, owner, run, actor)
                    if agent_waiting.immutable_identity(
                        refs
                    ) != agent_waiting.immutable_identity(run.waiting_jobs):
                        raise ApiError(
                            409, "WAITING_JOB_MISMATCH", "Waiting task identity changed"
                        )
                    if not agent_waiting.ready(refs):
                        run.waiting_jobs = refs
                        return {"pending": True}
                    checkpoints.load_resume(
                        db, owner, run, current_tools, validate_ledger=True
                    )
                except ApiError as exc:
                    stop(db, owner, run, "WAITING_REVIEW", exc.code)
                    return {"review_error": exc}
                run.waiting_jobs = refs
            owner.lease_epoch += 1
            run.lease_epoch = owner.lease_epoch
            run.allowed_tools = sorted(set(run.allowed_tools) & set(current_tools))
            run.state, run.host_id = "RUNNING", host_id
            run.active_deadline_at = now() + timedelta(
                seconds=agent_config.ACTIVE_SECONDS
            )
            run.lease_expires_at = now() + timedelta(seconds=LEASE_SECONDS)
            token = secrets.token_urlsafe(48)
            credential_expiry = now() + timedelta(seconds=CREDENTIAL_SECONDS)
            db.add(
                AgentCredential(
                    token_hash=token_hash(token),
                    run_id=run.id,
                    actor_id=actor_id,
                    session_id=owner.id,
                    scope_digest=owner.scope_digest,
                    lease_epoch=run.lease_epoch,
                    expires_at=credential_expiry,
                )
            )
            emit(db, run, "run.claimed", {"lease_epoch": run.lease_epoch})
            result = {
                **run_view(run),
                "scope": owner.scope,
                "execution_token": token,
                "credential_expires_at": credential_expiry.isoformat(),
                "runtime_manifest": agent_config.require_runtime(run.config_id),
                "base_checkpoint": None,
                "resume_checkpoint": None,
                "user_message": run.user_message,
                "continuation_message": agent_config.continuation_message(run),
            }
            try:
                checkpoint, _ = checkpoints.load_base(db, owner, run, current_tools)
                result["base_checkpoint"] = checkpoints.view(checkpoint)
                if run.resume_checkpoint_id:
                    resume, _ = checkpoints.load_resume(db, owner, run, current_tools)
                    result["resume_checkpoint"] = checkpoints.view(resume)
            except ApiError as exc:
                stop(db, owner, run, "WAITING_REVIEW", exc.code)
                result = {"review_error": exc}
    if result.get("expired"):
        raise ApiError(409, "RUN_REVIEW_REQUIRED", "Expired run requires manual review")
    if result.get("review_error"):
        raise result["review_error"]
    return result


@contextmanager
def execution(run_id, token, *, allow_succeeded=False, allow_waiting=False):
    if not token or len(token) > 128:
        raise ApiError(
            401, "EXECUTION_CREDENTIAL_INVALID", "Execution credential required"
        )
    hashed = token_hash(token)
    with transaction() as db:
        db.execute(
            text("SELECT set_config('app.agent_token_hash',:value,true)"),
            {"value": hashed},
        )
        hint = db.get(AgentCredential, hashed)
        if hint is None or hint.run_id != run_id:
            raise ApiError(
                401, "EXECUTION_CREDENTIAL_INVALID", "Execution credential required"
            )
        actor_id = hint.actor_id
    expired = False
    with transaction(actor_id) as db:
        owner, run, actor, tools = load_run(db, actor_id, run_id)
        agent_config.require_runtime(run.config_id)
        credential = db.get(AgentCredential, hashed)
        expired = expire(db, owner, run)
        if not expired:
            succeeded_read = (allow_succeeded and run.state == "SUCCEEDED") or (
                allow_waiting and run.state == "WAITING_JOB"
            )
            if (
                not credential
                or credential.expires_at <= now()
                or (run.state != "RUNNING" and not succeeded_read)
                or (not succeeded_read and owner.active_run_id != run.id)
                or (not succeeded_read and credential.lease_epoch != owner.lease_epoch)
                or credential.lease_epoch != run.lease_epoch
                or credential.session_id != owner.id
                or credential.scope_digest != owner.scope_digest
                or run.scope_digest != owner.scope_digest
                or run.config_id != owner.config_id
            ):
                raise ApiError(
                    401, "EXECUTION_FENCED", "Execution credential expired or revoked"
                )
            with bound_transaction(actor_id, db):
                original_deadline = run.lease_expires_at
                original_credential_deadline = credential.expires_at
                yield db, owner, run, actor, tools
                if (
                    (original_deadline and original_deadline <= now())
                    or original_credential_deadline <= now()
                    or (
                        run.state == "RUNNING"
                        and run.active_deadline_at
                        and run.active_deadline_at <= now()
                    )
                ):
                    raise ApiError(
                        401, "EXECUTION_FENCED", "Execution expired before commit"
                    )
    if expired:
        raise ApiError(401, "EXECUTION_FENCED", "Execution lease expired")


def invoke(db, owner, run, actor, current_tools, body):
    if body.tool_name not in run.allowed_tools or body.tool_name not in current_tools:
        raise ApiError(
            403, "TOOL_NOT_ALLOWED", "Tool is outside the current execution grant"
        )
    args_digest = digest({"tool": body.tool_name, "arguments": body.arguments})
    previous = db.scalar(
        select(AgentInvocation).where(
            AgentInvocation.run_id == run.id,
            AgentInvocation.request_key == body.request_key,
        )
    )
    if previous:
        if (
            previous.arguments_digest != args_digest
            or previous.tool_call_id != body.tool_call_id
        ):
            raise ApiError(
                409,
                "INVOCATION_CONFLICT",
                "Registration key already used with different input",
            )
        from services.api.agent_tools import revalidate_result

        revalidate_result(db, owner, actor, previous)
        return previous.response
    invocation_id = uuid4()
    action_id = uuid4() if body.tool_name in WRITES else None
    base = {
        "invocation_id": str(invocation_id),
        "action_id": str(action_id) if action_id else None,
        "scope_ref": owner.scope,
        "scope_effect": {"kind": "none"},
        "version_refs": [],
    }
    try:
        # A business/SQL error rolls back only the business attempt. The enclosing
        # transaction can still commit its failed invocation, with no partial write.
        with db.begin_nested():
            data = jsonable_encoder(
                dispatch(
                    db, actor, owner.scope, body.tool_name, body.arguments, action_id
                )
            )
            db.flush()
            if action_id and isinstance(data, dict):
                business_action = db.scalar(
                    select(Action).where(
                        Action.actor_id == actor.id,
                        Action.operation == body.tool_name,
                        Action.idempotency_key == str(action_id),
                    )
                )
                actual_id = (
                    business_action.id if business_action else data.get("action_id")
                )
                if actual_id:
                    action_id = UUID(str(actual_id))
                    base["action_id"] = str(action_id)
                data.pop("action_id", None)
            if body.tool_name == "uploads.create":
                data = {key: data[key] for key in ("upload_id", "project_id", "state")}
                data["next_action"] = "browser_file_transfer"
        accepted = body.tool_name in {
            "exports.create",
            "imports.start",
            "snapshots.create",
            "uploads.complete",
            "jobs.retry",
            "sync.start",
            "indexes.build",
        } and data.get("state") in {"QUEUED", "RUNNING", "PREPARING"}
        response = {**base, "status": "accepted" if accepted else "succeeded"}
        if accepted:
            response["job_id"] = data["job_id"]
        else:
            response.update(
                result_ref="agent-invocation:" + str(invocation_id),
                evidence_refs=[],
                method_summary="Authenticated business API result; not model-generated evidence.",
                result_view={
                    "kind": "business_result",
                    "resource_id": str(invocation_id),
                },
            )
        if body.tool_name == "projects.create":
            response["scope_effect"] = {
                "kind": "produces_scope",
                "target_scope": {
                    "scope_kind": "project",
                    "project_id": data["id"],
                    "snapshot_ids": [],
                    "material_revision_ids": [],
                    "alignment_overlay_revision": None,
                },
            }
        elif body.tool_name == "snapshots.create":
            response["scope_effect"] = {
                "kind": "produces_scope",
                "target_scope": {
                    "scope_kind": "project",
                    "project_id": owner.scope["project_id"],
                    "snapshot_ids": [data["snapshot_id"]],
                    "material_revision_ids": [],
                    "alignment_overlay_revision": None,
                },
            }
    except (ApiError, ValidationError, SQLAlchemyError) as exc:
        code = (
            exc.code
            if isinstance(exc, ApiError)
            else "INVALID_TOOL_INPUT"
            if isinstance(exc, ValidationError)
            else "BUSINESS_TRANSACTION_FAILED"
        )
        response = {
            **base,
            "status": "failed",
            "error": {
                "code": code,
                "message": exc.message
                if isinstance(exc, ApiError)
                else "Business operation was rejected",
                "request_id": str(uuid4()),
                "field_errors": [],
                "retryable": False,
            },
        }
        data = None
    output = {"result": response, "data": data}
    db.add(
        AgentInvocation(
            id=invocation_id,
            run_id=run.id,
            actor_id=actor.id,
            request_key=body.request_key,
            tool_call_id=body.tool_call_id,
            tool_name=body.tool_name,
            arguments_digest=args_digest,
            action_id=action_id,
            response=output,
            created_at=now(),
        )
    )
    emit(
        db,
        run,
        "tool." + response["status"],
        {
            "invocation_id": str(invocation_id),
            "action_id": str(action_id) if action_id else None,
            "tool_name": body.tool_name,
        },
    )
    return output
