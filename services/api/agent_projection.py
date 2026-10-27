"""Authorized browser projection; the private SDK file is never a response."""

from sqlalchemy import select, tuple_

from services.api import agent_checkpoints as checkpoints
from services.api.agent_models import AgentInvocation, AgentRun
from services.api.agent_tools import revalidate_result
from services.api.errors import ApiError


def page_runs(db, session_id, before, limit):
    statement = select(AgentRun).where(AgentRun.session_id == session_id)
    if before:
        anchor = db.get(AgentRun, before)
        if anchor is None or anchor.session_id != session_id:
            raise ApiError(
                422, "CURSOR_INVALID", "Run cursor does not belong to this session"
            )
        statement = statement.where(
            tuple_(AgentRun.created_at, AgentRun.id) < (anchor.created_at, anchor.id)
        )
    return list(
        db.scalars(
            statement.order_by(AgentRun.created_at.desc(), AgentRun.id.desc()).limit(
                limit + 1
            )
        )
    )


def result_view(entry):
    data = entry.response.get("data") or {}
    for field, kind in (
        ("export_id", "export"),
        ("note_id", "note"),
        ("evidence_id", "evidence"),
        ("material_id", "material"),
        ("snapshot_id", "snapshot"),
        ("query_run_id", "query"),
        ("job_id", "job"),
    ):
        if data.get(field):
            return {"kind": kind, "resource_id": str(data[field])}
    if entry.tool_name in {"projects.get", "projects.create"} and data.get("id"):
        return {"kind": "project", "resource_id": str(data["id"])}
    return None


def messages(db, owner, run, actor, tools):
    checkpoints.check_context(db, owner, run, tools)
    projected_tools = []
    for row in db.scalars(
        select(AgentInvocation)
        .where(AgentInvocation.run_id == run.id)
        .order_by(AgentInvocation.created_at, AgentInvocation.id)
    ):
        revalidate_result(db, owner, actor, row)
        projected_tools.append(
            {
                "invocation_id": str(row.id),
                "tool_name": row.tool_name,
                "status": row.response["result"]["status"],
                "result_view": result_view(row),
            }
        )
    assistant = []
    ident = run.final_checkpoint_id or run.resume_checkpoint_id
    if ident:
        checkpoint = checkpoints.get_row(db, owner, ident)
        checkpoints.check_dependencies(db, owner, tools, checkpoint.dependencies)
        rows = checkpoints.parsed(
            checkpoints.read_bytes(checkpoint), checkpoint.runtime_manifest
        )
        _, base = checkpoints.load_base(db, owner, run, tools, history=True)
        base_length = (
            len(checkpoints.parsed(base, checkpoint.runtime_manifest)) if base else 1
        )
        for row in rows[base_length:]:
            message = row.get("message", {})
            if message.get("role") != "assistant":
                continue
            value = "".join(
                item["text"]
                for item in message["content"]
                if item.get("type") == "text"
            )
            if value:
                assistant.append({"id": row["id"], "text": value})
    return {
        "run_id": str(run.id),
        "user_message": run.user_message,
        "assistant_messages": assistant,
        "tools": projected_tools,
        "state": run.state,
        "created_at": run.created_at.isoformat(),
    }
