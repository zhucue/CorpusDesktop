"""Server-derived accepted-job references; no host-selected task or report route."""

from uuid import UUID

from sqlalchemy import select

from services.api.agent_models import AgentInvocation
from services.api.errors import ApiError
from services.api.index_models import IndexRun
from services.api.job_models import Job
from services.api.research_models import ResearchTask
from services.api.source_sync_models import SyncRun


def references(db, owner, run, actor):
    from services.api.agent_tools import revalidate_result

    refs = []
    for entry in db.scalars(
        select(AgentInvocation)
        .where(AgentInvocation.run_id == run.id)
        .order_by(AgentInvocation.created_at, AgentInvocation.id)
    ):
        result = entry.response["result"]
        if result["status"] != "accepted":
            continue
        revalidate_result(db, owner, actor, entry)
        data = entry.response.get("data") or {}
        ident = UUID(result["job_id"])
        if entry.tool_name == "snapshots.create":
            kind, model, tool = "research", ResearchTask, "snapshots.get"
            args = {"snapshot_id": data["snapshot_id"]}
        elif entry.tool_name == "indexes.build" or data.get("index_run_id"):
            kind, model, tool = "index", IndexRun, "indexes.report"
            args = {"index_run_id": str(ident)}
        elif entry.tool_name == "sync.start" or data.get("sync_run_id"):
            kind, model, tool = "sync", SyncRun, "sync.report"
            args = {"sync_run_id": str(ident)}
        elif entry.tool_name == "exports.create" or data.get("export_id"):
            kind, model, tool = "job", Job, "exports.get"
            args = {"export_id": str(ident)}
        elif entry.tool_name == "imports.start" or data.get("import_id"):
            kind, model, tool = "job", Job, "imports.get"
            args = {"import_id": str(ident)}
        else:
            kind, model, tool = "job", Job, "jobs.get"
            args = {"job_id": str(ident)}
        task = db.get(model, ident)
        if task is None:
            raise ApiError(
                409,
                "WAITING_JOB_UNAVAILABLE",
                "Required background job is no longer accessible",
            )
        refs.append(
            {
                "invocation_id": str(entry.id),
                "job_id": str(ident),
                "kind": kind,
                "report_tool": tool,
                "report_arguments": args,
                "state": task.state,
            }
        )
    return refs


def ready(refs):
    return bool(refs) and all(
        ref["state"] not in {"QUEUED", "RUNNING", "PREPARING"} for ref in refs
    )


def immutable_identity(refs):
    return [{k: v for k, v in ref.items() if k != "state"} for ref in refs]
