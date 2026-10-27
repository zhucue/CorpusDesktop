"""Bounded, immutable SDK files. Only PG publication makes a checkpoint current."""

import hashlib
import io
import json
import os
from uuid import UUID, uuid4

from botocore.exceptions import BotoCoreError, ClientError
from sqlalchemy import select

from services.api import agent_config, storage
from services.api import agent_control as control
from services.api.agent_models import AgentCheckpoint, AgentEvent, AgentInvocation
from services.api.db import lock_project
from services.api.errors import ApiError
from services.api.index_models import IndexRun
from services.api.job_models import Job
from services.api.projects import require_project
from services.api.source_sync_models import SyncRun

MAX_BYTES = 8 * 1024 * 1024
RUNTIME_MANIFEST = agent_config.FIXTURE_MANIFEST
# The resource policy means no discovered extensions/skills/prompts/AGENTS,
# compaction, model-network or automatic model retry. It is a trusted host policy,
# not authorization for a model to select its own resources.


def fail(code, message, status=409):
    raise ApiError(status, code, message)


def view(row):
    if row is None:
        return None
    return {
        "checkpoint_id": str(row.id),
        "sha256": row.sha256,
        "byte_size": row.byte_size,
        "sdk_session_id": str(row.sdk_session_id),
        "leaf_id": row.leaf_id,
        "runtime_manifest": row.runtime_manifest,
    }


def parsed(raw, manifest=None):
    manifest = RUNTIME_MANIFEST if manifest is None else manifest
    try:
        agent_config.manifest_config_id(manifest)
        if not raw or len(raw) > MAX_BYTES:
            raise ValueError()
        rows = [json.loads(line) for line in raw.decode("utf-8").splitlines()]
        header = rows[0]
        if header.get("type") != "session" or header.get("version") != 3:
            raise ValueError()
        UUID(header["id"])
        if not isinstance(header.get("cwd"), str) or not header.get("timestamp"):
            raise ValueError()
        ids, parent = set(), None
        for row in rows[1:]:
            ident = row.get("id")
            if (
                not isinstance(ident, str)
                or not 1 <= len(ident) <= 160
                or ident in ids
                or row.get("parentId") != parent
                or not row.get("timestamp")
            ):
                raise ValueError()
            ids.add(ident)
            parent = ident
            kind = row.get("type")
            if kind == "model_change":
                if (row.get("provider"), row.get("modelId")) != (
                    manifest["provider"],
                    manifest["model"],
                ):
                    raise ValueError()
            elif kind == "thinking_level_change":
                if row.get("thinkingLevel") != "off":
                    raise ValueError()
            elif kind == "message":
                message = row["message"]
                if message.get("role") not in {
                    "system",
                    "user",
                    "assistant",
                    "toolResult",
                }:
                    raise ValueError()
                role, content = message["role"], message.get("content")
                if role == "system":
                    if not isinstance(content, str):
                        raise ValueError()
                elif role == "user" and isinstance(content, str):
                    pass
                else:
                    if not isinstance(content, list) or not content:
                        raise ValueError()
                    for item in content:
                        if not isinstance(item, dict):
                            raise TypeError()
                        if item.get("type") == "text":
                            if not isinstance(item.get("text"), str):
                                raise ValueError()
                        elif role == "assistant" and item.get("type") == "toolCall":
                            if not all(
                                isinstance(item.get(k), str) and item[k]
                                for k in ("id", "name")
                            ) or not isinstance(item.get("arguments"), dict):
                                raise ValueError()
                        else:
                            raise ValueError()
                if role == "assistant" and message.get("stopReason") not in {
                    "stop",
                    "toolUse",
                }:
                    raise ValueError()
                if message.get("role") == "assistant" and (
                    message.get("provider"),
                    message.get("model"),
                ) != (manifest["provider"], manifest["model"]):
                    raise ValueError()
                if (
                    role == "assistant"
                    and manifest.get("model_api")
                    and message.get("api") != manifest["model_api"]
                ):
                    raise ValueError()
            else:
                # A linear, uncompacted file is the implemented subset. Never
                # discard branches/context edits and pretend the context survived.
                raise ValueError()
        last = rows[-1].get("message", {})
        if last.get("role") != "assistant" or last.get("stopReason") != "stop":
            raise ValueError()
        return rows
    except (ValueError, KeyError, TypeError, AttributeError, UnicodeError):
        fail(
            "CHECKPOINT_FORMAT_UNSUPPORTED",
            "A complete linear Pi v3 session is required",
            422,
        )


def check_dependencies(db, owner, tools, dependencies):
    if not set(dependencies["tools"]).issubset(tools):
        fail(
            "CHECKPOINT_AUTH_CHANGED", "Historical tool context is no longer authorized"
        )
    # The server derives project IDs from real stored results. New unrelated
    # memberships do not invalidate old context. Lock in stable order so a
    # concurrent member removal cannot race the bytes returned or pointer commit.
    for project_id in sorted(dependencies["project_ids"]):
        ident = UUID(project_id)
        lock_project(db, ident)
        try:
            require_project(db, owner.actor_id, ident)
        except ApiError:
            fail(
                "CHECKPOINT_AUTH_CHANGED",
                "Historical project context is no longer authorized",
            )

    # Outcome metadata retains all source dependencies before any source locks.
    from services.api import agent_tools
    from services.api.research_models import QueryRun, Snapshot

    outcome_rows = []
    for ident in dependencies.get("invocation_ids", []):
        invocation = db.get(AgentInvocation, UUID(ident))
        if not invocation or invocation.actor_id != owner.actor_id:
            fail("CHECKPOINT_AUTH_CHANGED", "Historical invocation is unavailable")
        data = invocation.response.get("data") or {}
        if data and (
            invocation.tool_name.startswith(("evidence.", "notes.", "exports."))
            or data.get("export_id")
        ):
            outcome_rows.append(data)
            _, qids = agent_tools.outcome_refs(
                db, UUID(owner.scope["project_id"]), data
            )
            for qid in qids:
                query = db.get(QueryRun, UUID(qid))
                snapshot = db.get(Snapshot, query.snapshot_id) if query else None
                if (
                    not snapshot
                    or str(snapshot.project_id) != owner.scope["project_id"]
                ):
                    fail("CHECKPOINT_AUTH_CHANGED", "Outcome snapshot is unavailable")
                dependencies.setdefault("manifest_mount_ids", []).extend(
                    m["mount_id"]
                    for m in snapshot.manifest["members"]
                    if m["kind"] == "whole_source_mount"
                )
                dependencies.setdefault("material_revision_ids", []).extend(
                    m["material_revision_id"]
                    for m in snapshot.manifest["members"]
                    if m["kind"] == "private_revision"
                )

    from services.api.materials import load_revision

    for revision_id in dependencies.get("material_revision_ids", []):
        try:
            load_revision(db, UUID(owner.scope["project_id"]), UUID(revision_id))
        except ApiError:
            fail(
                "CHECKPOINT_AUTH_CHANGED",
                "Private material revision is no longer accessible",
            )
    from services.api.source_mounts import check_manifest_dependencies

    mount_ids = dependencies.get("manifest_mount_ids", [])
    if mount_ids:
        try:
            check_manifest_dependencies(
                db, owner.actor_id, UUID(owner.scope["project_id"]), mount_ids
            )
        except ApiError:
            fail(
                "CHECKPOINT_AUTH_CHANGED",
                "Historical mounted source is no longer authorized",
            )
    from types import SimpleNamespace

    for data in outcome_rows:
        try:
            agent_tools.revalidate_outcomes(
                db, owner, SimpleNamespace(id=owner.actor_id), data
            )
        except ApiError:
            fail("CHECKPOINT_AUTH_CHANGED", "Historical outcome authorization changed")


def get_row(db, owner, checkpoint_id, *, execution=False):
    row = db.get(AgentCheckpoint, checkpoint_id) if checkpoint_id else None
    if not row or row.session_id != owner.id or row.actor_id != owner.actor_id:
        fail("CHECKPOINT_NOT_FOUND", "Checkpoint is not accessible")
    try:
        matches = (
            agent_config.manifest_config_id(row.runtime_manifest) == owner.config_id
        )
    except (ValueError, TypeError, AttributeError):
        matches = False
    if not matches or (
        execution
        and row.runtime_manifest != agent_config.require_runtime(owner.config_id)
    ):
        fail("CHECKPOINT_RUNTIME_MISMATCH", "Checkpoint runtime is incompatible")
    return row


def read_bytes(row):
    try:
        stream = storage.read_private(row.object_key, row.version_id, row.etag)
        try:
            raw = stream.read(MAX_BYTES + 1)
        finally:
            stream.close()
    except (BotoCoreError, ClientError, OSError, ValueError):
        fail(
            "CHECKPOINT_STORAGE_UNAVAILABLE",
            "Private checkpoint could not be read",
            503,
        )
    if len(raw) != row.byte_size or hashlib.sha256(raw).hexdigest() != row.sha256:
        fail("CHECKPOINT_INTEGRITY_FAILED", "Private checkpoint checksum failed")
    return raw


def inspect_transcript(db, owner, run, tools, raw, base_raw=None):
    manifest = agent_config.require_runtime(run.config_id)
    rows = parsed(raw, manifest)
    if UUID(rows[0]["id"]) != owner.id:
        fail(
            "CHECKPOINT_SESSION_MISMATCH",
            "SDK session header does not match this session",
        )
    if base_raw:
        baseline = parsed(base_raw, manifest)
        if rows[: len(baseline)] != baseline or len(rows) <= len(baseline):
            fail(
                "CHECKPOINT_BASE_MISMATCH",
                "Checkpoint must extend the fixed base without rewriting it",
            )
    manifest_mount_ids = set()
    material_revision_ids = set()
    calls, resolved, invocation_ids, project_ids, used_tools = (
        {},
        set(),
        set(),
        set(),
        set(),
    )
    for entry in rows[1:]:
        if entry["type"] != "message":
            continue
        message = entry["message"]
        if message["role"] == "assistant":
            for item in message.get("content", []):
                if item.get("type") == "toolCall":
                    ident = item.get("id")
                    if not isinstance(ident, str) or ident in calls:
                        fail(
                            "CHECKPOINT_TOOL_MISMATCH", "Duplicate or invalid tool call"
                        )
                    calls[ident] = item
        elif message["role"] == "toolResult":
            call_id = message.get("toolCallId")
            call = calls.get(call_id)
            output = message.get("details")
            try:
                invocation_id = UUID(output["result"]["invocation_id"])
                row = db.get(AgentInvocation, invocation_id)
                if not row:
                    raise ValueError()
                from services.api.agent_models import AgentRun

                source_run = db.get(AgentRun, row.run_id)
                if not source_run or source_run.session_id != owner.id:
                    raise ValueError()
                name = row.tool_name.replace(".", "_")
                content = message["content"]
                if (
                    not call
                    or call_id in resolved
                    or invocation_id in invocation_ids
                    or row.tool_call_id != call_id
                    or call.get("name") != name
                    or message.get("toolName") != name
                    or row.arguments_digest
                    != control.digest(
                        {"tool": row.tool_name, "arguments": call["arguments"]}
                    )
                    or output != row.response
                    or len(content) != 1
                    or content[0].get("type") != "text"
                    or json.loads(content[0]["text"]) != row.response
                    or bool(message.get("isError"))
                ):
                    raise ValueError()
            except (ValueError, TypeError, KeyError, AttributeError):
                fail(
                    "CHECKPOINT_TOOL_MISMATCH",
                    "Archived tool output differs from the invocation ledger",
                )
            resolved.add(call_id)
            invocation_ids.add(invocation_id)
            used_tools.add(row.tool_name)
            data = output.get("data") or {}
            if row.tool_name == "mounts.manifest" and data:
                manifest_mount_ids.add(data["mount_id"])
            if (
                row.tool_name
                in {
                    "snapshots.create",
                    "snapshots.get",
                    "corpus.describe",
                    "results.get",
                }
                and data
            ):
                from services.api.research_models import Snapshot

                snapshot = db.get(Snapshot, UUID(data["snapshot_id"]))
                if (
                    not snapshot
                    or str(snapshot.project_id) != owner.scope["project_id"]
                ):
                    fail(
                        "CHECKPOINT_AUTH_CHANGED",
                        "Research snapshot is no longer accessible",
                    )
                material_revision_ids.update(
                    member["material_revision_id"]
                    for member in snapshot.manifest["members"]
                    if member["kind"] == "private_revision"
                )
                manifest_mount_ids.update(
                    member["mount_id"]
                    for member in snapshot.manifest["members"]
                    if member["kind"] == "whole_source_mount"
                )
            if row.tool_name in {
                "imports.start",
                "imports.get",
                "materials.list",
                "materials.get",
            } or data.get("import_id"):
                for item in data.get("items", [data]):
                    material_revision_ids.update(
                        r
                        for r in [item.get("material_revision_id")]
                        + [v["material_revision_id"] for v in item.get("revisions", [])]
                        if r
                    )
            if row.tool_name == "projects.list":
                project_ids.update(item["id"] for item in data.get("items", []))
            elif row.tool_name in {"projects.get", "projects.create"} and data:
                project_ids.add(data["id"])
    if calls.keys() != resolved:
        fail(
            "CHECKPOINT_TOOL_UNRESOLVED", "Checkpoint contains an unresolved tool call"
        )
    current = set(
        db.scalars(select(AgentInvocation.id).where(AgentInvocation.run_id == run.id))
    )
    if current - invocation_ids:
        fail("CHECKPOINT_TOOL_UNRESOLVED", "Checkpoint omits committed invocations")
    # A new run may only extend its fixed published ancestor, never import a
    # cancelled/unpublished run's results even if it belongs to the same actor.
    base_ids = set()
    if base_raw:
        for entry in parsed(base_raw, manifest)[1:]:
            msg = entry.get("message", {})
            if msg.get("role") == "toolResult":
                base_ids.add(UUID(msg["details"]["result"]["invocation_id"]))
    if invocation_ids != current | base_ids:
        fail("CHECKPOINT_TOOL_MISMATCH", "Checkpoint includes an unrelated invocation")
    dependencies = {
        "tools": sorted(used_tools),
        "manifest_mount_ids": sorted(manifest_mount_ids),
        "material_revision_ids": sorted(material_revision_ids),
        "project_ids": sorted(project_ids),
        "invocation_ids": sorted(str(x) for x in invocation_ids),
    }
    check_dependencies(db, owner, tools, dependencies)
    return rows, dependencies


def load_base(db, owner, run, tools, *, history=False):
    if not run.base_checkpoint_id:
        return None, None
    row = get_row(db, owner, run.base_checkpoint_id, execution=not history)
    check_dependencies(db, owner, tools, row.dependencies)
    raw = read_bytes(row)
    parsed(raw, row.runtime_manifest)
    return row, raw


def load_resume(db, owner, run, tools, *, validate_ledger=False):
    if not run.resume_checkpoint_id:
        return load_base(db, owner, run, tools)
    row = get_row(db, owner, run.resume_checkpoint_id, execution=True)
    if row.run_id != run.id or row.base_checkpoint_id != run.base_checkpoint_id:
        fail("CHECKPOINT_BASE_MISMATCH", "Resume checkpoint belongs to another run")
    check_dependencies(db, owner, tools, row.dependencies)
    raw = read_bytes(row)
    parsed(raw, row.runtime_manifest)
    if validate_ledger:
        _, base_raw = load_base(db, owner, run, tools)
        inspect_transcript(db, owner, run, tools, raw, base_raw)
    return row, raw


def inspect_user_input(run, raw, ancestor_raw):
    from services.api.agent_config import continuation_message

    manifest = agent_config.require_runtime(run.config_id)
    rows = parsed(raw, manifest)
    ancestor = parsed(ancestor_raw, manifest) if ancestor_raw else rows[:1]
    if rows[: len(ancestor)] != ancestor or len(rows) <= len(ancestor):
        fail(
            "CHECKPOINT_BASE_MISMATCH",
            "Resume file must extend its exact immutable ancestor",
        )
    users = [
        r["message"]["content"]
        for r in rows[len(ancestor) :]
        if r.get("type") == "message" and r["message"].get("role") == "user"
    ]
    values = [u if isinstance(u, str) else "".join(x["text"] for x in u) for u in users]
    if values != [continuation_message(run) or run.user_message]:
        fail(
            "CHECKPOINT_MESSAGE_MISMATCH",
            "SDK user input differs from the persisted message or trusted continuation",
        )


def check_context(db, owner, run, tools):
    """Before every model request: current tools and historical read dependencies."""
    dependencies = {
        "tools": [],
        "project_ids": [],
        "manifest_mount_ids": [],
        "material_revision_ids": [],
        "invocation_ids": [],
    }
    if run.base_checkpoint_id:
        row = get_row(db, owner, run.base_checkpoint_id)
        dependencies = {
            "tools": list(row.dependencies["tools"]),
            "invocation_ids": list(row.dependencies.get("invocation_ids", [])),
            "material_revision_ids": list(
                row.dependencies.get("material_revision_ids", [])
            ),
            "manifest_mount_ids": list(row.dependencies.get("manifest_mount_ids", [])),
            "project_ids": list(row.dependencies["project_ids"]),
        }
    for row in db.scalars(
        select(AgentInvocation).where(AgentInvocation.run_id == run.id)
    ):
        dependencies["tools"].append(row.tool_name)
        dependencies["invocation_ids"].append(str(row.id))
        data = row.response.get("data") or {}
        if row.tool_name == "mounts.manifest" and data:
            dependencies["manifest_mount_ids"].append(data["mount_id"])
        if (
            row.tool_name
            in {"snapshots.create", "snapshots.get", "corpus.describe", "results.get"}
            and data
        ):
            from services.api.research_models import Snapshot

            snapshot = db.get(Snapshot, UUID(data["snapshot_id"]))
            if not snapshot or str(snapshot.project_id) != owner.scope["project_id"]:
                fail(
                    "CHECKPOINT_AUTH_CHANGED",
                    "Research snapshot is no longer accessible",
                )
            dependencies["material_revision_ids"].extend(
                member["material_revision_id"]
                for member in snapshot.manifest["members"]
                if member["kind"] == "private_revision"
            )
            dependencies["manifest_mount_ids"].extend(
                member["mount_id"]
                for member in snapshot.manifest["members"]
                if member["kind"] == "whole_source_mount"
            )
        if row.tool_name in {
            "imports.start",
            "imports.get",
            "materials.list",
            "materials.get",
        } or data.get("import_id"):
            for item in data.get("items", [data]):
                dependencies["material_revision_ids"].extend(
                    r
                    for r in [item.get("material_revision_id")]
                    + [v["material_revision_id"] for v in item.get("revisions", [])]
                    if r
                )
        if row.tool_name == "projects.list":
            dependencies["project_ids"].extend(
                item["id"] for item in data.get("items", [])
            )
        elif row.tool_name in {"projects.get", "projects.create"} and data:
            dependencies["project_ids"].append(data["id"])
    dependencies["project_ids"] = sorted(set(dependencies["project_ids"]))
    check_dependencies(db, owner, tools, dependencies)


def settled_sequence(db, run):
    events = list(
        db.scalars(
            select(AgentEvent)
            .where(AgentEvent.run_id == run.id)
            .order_by(AgentEvent.sequence)
        )
    )
    settled = max(
        (e.sequence for e in events if e.kind == "sdk.agent_settled"), default=0
    )
    tool = max((e.sequence for e in events if e.kind.startswith("tool.")), default=0)
    if not settled or settled <= tool:
        fail("AGENT_NOT_SETTLED", "A settled boundary after all tool calls is required")
    return settled


def store(db, owner, run, tools, body, token):
    manifest = agent_config.require_runtime(run.config_id)
    if body.runtime_manifest != manifest:
        fail(
            "CHECKPOINT_RUNTIME_MISMATCH",
            "Runtime manifest is not the configured host policy",
        )
    if body.base_checkpoint_id != run.base_checkpoint_id:
        fail("CHECKPOINT_BASE_MISMATCH", "Checkpoint base does not match this run")
    raw = body.session_jsonl.encode("utf-8")
    if len(raw) > MAX_BYTES:
        fail("CHECKPOINT_TOO_LARGE", "Checkpoint exceeds 8 MiB", 413)
    host_key = os.environ.get("AGENT_HOST_KEY", "")
    if token.encode() in raw or (host_key and host_key.encode() in raw):
        fail(
            "CHECKPOINT_CONTAINS_CREDENTIAL",
            "Execution credentials cannot be archived",
            422,
        )
    digest = hashlib.sha256(raw).hexdigest()
    previous = db.scalar(
        select(AgentCheckpoint).where(
            AgentCheckpoint.run_id == run.id,
            AgentCheckpoint.request_key == body.request_key,
        )
    )
    if previous:
        if (
            previous.sha256 != digest
            or previous.base_checkpoint_id != body.base_checkpoint_id
        ):
            fail(
                "CHECKPOINT_CONFLICT",
                "Checkpoint key was already used for different bytes",
            )
        check_dependencies(db, owner, tools, previous.dependencies)
        read_bytes(previous)
        return view(previous)
    sequence = settled_sequence(db, run)
    _, base_raw = load_base(db, owner, run, tools)
    _, ancestor_raw = load_resume(db, owner, run, tools)
    inspect_user_input(run, raw, ancestor_raw)
    rows, dependencies = inspect_transcript(db, owner, run, tools, raw, base_raw)
    ident = uuid4()
    key = f"agent-checkpoints/{owner.id}/{run.id}/{ident}.jsonl"
    try:
        version, etag = storage.put_private(
            key, io.BytesIO(raw), len(raw), "application/x-ndjson"
        )
    except (BotoCoreError, ClientError, OSError, ValueError):
        # The object may exist after an ACK timeout. No pointer is published.
        # A repeat uses the same logical key but a fresh immutable storage key;
        # unreferenced objects need explicit retention cleanup, never guessing.
        fail(
            "CHECKPOINT_STORE_UNCERTAIN",
            "Checkpoint storage was not confirmed; no pointer was published",
            503,
        )
    row = AgentCheckpoint(
        id=ident,
        session_id=owner.id,
        run_id=run.id,
        actor_id=run.actor_id,
        request_key=body.request_key,
        base_checkpoint_id=run.base_checkpoint_id,
        lease_epoch=run.lease_epoch,
        event_sequence=sequence,
        object_key=key,
        version_id=version,
        etag=etag,
        sha256=digest,
        byte_size=len(raw),
        sdk_session_id=UUID(rows[0]["id"]),
        leaf_id=rows[-1]["id"],
        runtime_manifest=manifest,
        dependencies=dependencies,
        created_at=control.now(),
    )
    read_bytes(row)
    db.add(row)
    db.flush()
    control.emit(
        db, run, "checkpoint.stored", {"checkpoint_id": str(ident), "sha256": digest}
    )
    return view(row)


def necessary_results(db, run):
    invocations = list(
        db.scalars(select(AgentInvocation).where(AgentInvocation.run_id == run.id))
    )
    for row in invocations:
        result = row.response["result"]
        if result["status"] == "accepted":
            if row.tool_name == "exports.create" or (
                row.response.get("data") or {}
            ).get("export_id"):
                job = db.get(Job, UUID(result["job_id"]))
                if not job or job.state in {"QUEUED", "RUNNING"}:
                    fail("JOBS_PENDING", "Required export is incomplete")
                if job.kind != "EXPORT" or job.state != "SUCCEEDED":
                    fail("JOB_NOT_SUCCEEDED", "Required export did not succeed")
                if not any(
                    i.tool_name in {"exports.get", "jobs.get"}
                    and i.response["result"]["status"] == "succeeded"
                    and (i.response.get("data") or {}).get("export_id") == str(job.id)
                    and i.response["data"].get("state") == "SUCCEEDED"
                    for i in invocations
                ):
                    fail(
                        "JOB_RESULT_NOT_OBSERVED",
                        "Successful export metadata must be observed",
                    )
                continue
            if row.tool_name == "imports.start" or row.response.get("data", {}).get(
                "import_id"
            ):
                job = db.get(Job, UUID(result["job_id"]))
                if not job or job.state in {"QUEUED", "RUNNING"}:
                    fail("JOBS_PENDING", "Required TXT import is incomplete")
                if job.state != "SUCCEEDED":
                    fail("JOB_NOT_SUCCEEDED", "TXT import did not succeed")
                revision_id = job.result["material_revision_id"]
                if not any(
                    i.tool_name == "imports.get"
                    and i.response["result"]["status"] == "succeeded"
                    and (i.response.get("data") or {}).get("material_revision_id")
                    == revision_id
                    for i in invocations
                ):
                    fail(
                        "JOB_RESULT_NOT_OBSERVED", "Imported revision must be observed"
                    )
                continue
            if row.tool_name == "snapshots.create":
                from services.api.research_models import ResearchTask

                task = db.get(ResearchTask, UUID(result["job_id"]))
                if not task or task.state in {"QUEUED", "RUNNING"}:
                    fail("JOBS_PENDING", "Required snapshot preparation is incomplete")
                if task.state != "SUCCEEDED":
                    fail("JOB_NOT_SUCCEEDED", "Snapshot preparation did not succeed")
                if not any(
                    item.tool_name in {"snapshots.get", "corpus.describe"}
                    and item.response["result"]["status"] == "succeeded"
                    and (item.response.get("data") or {}).get("snapshot_id")
                    == str(task.snapshot_id)
                    and item.response["data"].get("state") == "READY"
                    for item in invocations
                ):
                    fail(
                        "JOB_RESULT_NOT_OBSERVED",
                        "Prepared snapshot must be read into the context",
                    )
                continue
            is_index = row.tool_name == "indexes.build" or (
                row.tool_name == "jobs.retry"
                and "index_run_id" in (row.response.get("data") or {})
            )
            is_sync = row.tool_name == "sync.start" or (
                row.tool_name == "jobs.retry"
                and result["scope_ref"]["scope_kind"] == "platform"
                and not is_index
            )
            job = db.get(
                IndexRun if is_index else SyncRun if is_sync else Job,
                UUID(result["job_id"]),
            )
            if not job or job.state in {"QUEUED", "RUNNING"}:
                fail("JOBS_PENDING", "Required background jobs have not completed")
            if job.state != "SUCCEEDED" or not job.result:
                fail("JOB_NOT_SUCCEEDED", "A required background job did not succeed")
            observed = any(
                item.tool_name
                == (
                    "indexes.report"
                    if is_index
                    else "sync.report"
                    if is_sync
                    else "jobs.get"
                )
                and item.response["result"]["status"] == "succeeded"
                and (item.response.get("data") or {}).get(
                    "id" if is_sync or is_index else "job_id"
                )
                == str(job.id)
                and item.response["data"].get("state") == "SUCCEEDED"
                and item.response["data"].get("result") == job.result
                for item in invocations
            )
            if not observed:
                fail(
                    "JOB_RESULT_NOT_OBSERVED",
                    "The successful background result must be read into the SDK context",
                )
        elif result["status"] not in {"succeeded", "failed"}:
            fail("TOOL_RESULTS_NOT_SUCCESSFUL", "A tool result requires review")


def publish(db, owner, run, tools, checkpoint_id):
    row = get_row(db, owner, checkpoint_id, execution=True)
    if (
        row.run_id != run.id
        or row.lease_epoch != run.lease_epoch
        or row.base_checkpoint_id != run.base_checkpoint_id
        or owner.latest_checkpoint_id != run.base_checkpoint_id
    ):
        fail(
            "CHECKPOINT_FENCED",
            "Checkpoint does not belong to the current writer and base",
        )
    sequence = settled_sequence(db, run)
    if sequence != row.event_sequence:
        fail("CHECKPOINT_STALE", "A newer SDK boundary requires a new checkpoint")
    _, base_raw = load_base(db, owner, run, tools)
    raw = read_bytes(row)
    _, ancestor_raw = load_resume(db, owner, run, tools)
    inspect_user_input(run, raw, ancestor_raw)
    inspect_transcript(db, owner, run, tools, raw, base_raw)
    necessary_results(db, run)
    owner.latest_checkpoint_id = row.id
    run.final_checkpoint_id = row.id
    control.stop(db, owner, run, "SUCCEEDED", "CHECKPOINT_PUBLISHED")
    return control.run_view(run)


def suspend(db, owner, run, actor, tools, checkpoint_id):
    from datetime import timedelta

    from services.api import agent_config, agent_waiting

    if run.state == "WAITING_JOB":
        if run.resume_checkpoint_id != checkpoint_id:
            fail("CHECKPOINT_CONFLICT", "Run is already waiting on another checkpoint")
        load_resume(db, owner, run, tools, validate_ledger=True)
        return control.run_view(run)
    row = get_row(db, owner, checkpoint_id, execution=True)
    if (
        row.run_id != run.id
        or row.lease_epoch != run.lease_epoch
        or row.base_checkpoint_id != run.base_checkpoint_id
    ):
        fail("CHECKPOINT_FENCED", "Checkpoint is not from this execution")
    if row.event_sequence != settled_sequence(db, run):
        fail("CHECKPOINT_STALE", "A newer settled checkpoint is required")
    _, base_raw = load_base(db, owner, run, tools)
    _, ancestor_raw = load_resume(db, owner, run, tools)
    raw = read_bytes(row)
    inspect_user_input(run, raw, ancestor_raw)
    inspect_transcript(db, owner, run, tools, raw, base_raw)
    refs = agent_waiting.references(db, owner, run, actor)
    if not refs:
        fail(
            "WAITING_JOB_REQUIRED", "There is no registered background job to wait for"
        )
    run.resume_checkpoint_id = row.id
    run.waiting_jobs = refs
    if run.wait_deadline_at is None:
        run.wait_deadline_at = control.now() + timedelta(
            seconds=agent_config.WAIT_SECONDS
        )
    control.stop(db, owner, run, "WAITING_JOB", "REGISTERED_JOBS_PENDING")
    return control.run_view(run)
