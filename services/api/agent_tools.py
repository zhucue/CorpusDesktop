"""A closed, typed dispatch table to the same handlers used by the browser."""

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from contracts.outcomes import (
    EvidenceInput,
    ExportInput,
    NoteAccept,
    NoteInput,
    NoteUpdate,
)
from services.api import (
    catalog,
    exports,
    index_builds,
    jobs,
    materials,
    outcomes,
    projects,
    research,
    source_mounts,
    source_releases,
    source_sync,
    uploads,
)
from services.api.errors import ApiError
from services.api.job_models import Job, Upload


class StrictInput(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Empty(StrictInput):
    pass


class Member(StrictInput):
    user_id: UUID


class MemberUpdate(Member):
    role: Literal["editor", "viewer"]


class UploadRef(StrictInput):
    upload_id: UUID


class JobRef(StrictInput):
    job_id: UUID


class JobList(StrictInput):
    cursor: str | None = Field(default=None, max_length=512)
    page_size: int = Field(default=50, ge=1, le=100)


class SyncRef(StrictInput):
    sync_run_id: UUID


class SyncSource(StrictInput):
    source_id: Literal["D12"]


class SyncList(SyncSource, JobList):
    pass


class IndexRef(StrictInput):
    index_run_id: UUID


class IndexBuild(SyncSource):
    acquisition_id: UUID


class IndexList(SyncSource, JobList):
    task_kind: Literal["source_index"]


class SourceRef(StrictInput):
    source_id: str = Field(pattern=catalog.SOURCE_ID_PATTERN)


class SourceVersions(SourceRef, JobList):
    pass


class SourceList(JobList):
    q: str | None = Field(default=None, max_length=160)
    language: str | None = Field(default=None, max_length=48)
    category: str | None = Field(default=None, max_length=48)
    status: catalog.IntegrationStatus | None = None
    capability: catalog.Capability | None = None


class CatalogUpdate(SourceRef, catalog.CatalogUpdate):
    pass


class PolicyRef(SourceRef):
    policy_kind: Literal["source"]
    acquisition_id: UUID


class PolicyUpdate(PolicyRef):
    expected_revision: int = Field(ge=0)
    decision: Literal["allow", "deny"]
    review_note: str = Field(min_length=1, max_length=4000)
    evidence_urls: list[str] = Field(min_length=1, max_length=12)


class ReleasePublish(SourceRef, source_releases.PublishInput):
    pass


class ReleaseRef(SourceRef):
    release_id: UUID


class MountRef(StrictInput):
    mount_id: UUID


class SnapshotRef(StrictInput):
    snapshot_id: UUID


class ResultRef(StrictInput):
    result_set_id: UUID


class ImportRef(StrictInput):
    import_id: UUID


class MaterialRef(StrictInput):
    material_id: UUID


class ContextRef(ResultRef):
    ordinal: int = Field(ge=0)


class EvidenceRef(StrictInput):
    evidence_id: UUID


class NoteRef(StrictInput):
    note_id: UUID
    revision: int | None = Field(default=None, ge=1)


class NoteUpdateTool(NoteUpdate):
    note_id: UUID


class NoteAcceptTool(NoteAccept):
    note_id: UUID


class ExportRef(StrictInput):
    export_id: UUID


SCHEMAS = {
    "evidence.create": EvidenceInput,
    "evidence.list": JobList,
    "evidence.get": EvidenceRef,
    "notes.create": NoteInput,
    "notes.update": NoteUpdateTool,
    "notes.accept": NoteAcceptTool,
    "notes.get": NoteRef,
    "notes.list": JobList,
    "exports.create": ExportInput,
    "exports.get": ExportRef,
    "exports.list": JobList,
    "imports.start": materials.ImportInput,
    "imports.get": ImportRef,
    "materials.list": JobList,
    "materials.get": MaterialRef,
    "snapshots.create": research.SnapshotInput,
    "snapshots.get": SnapshotRef,
    "corpus.describe": SnapshotRef,
    "corpus.search": research.QueryInput,
    "results.get": ResultRef,
    "results.context": ContextRef,
    "policies.get": PolicyRef,
    "policies.update": PolicyUpdate,
    "releases.publish": ReleasePublish,
    "releases.get": ReleaseRef,
    "mounts.list": JobList,
    "mounts.get": MountRef,
    "mounts.manifest": MountRef,
    "mounts.create": source_mounts.MountInput,
    "mounts.remove": MountRef,
    "indexes.build": IndexBuild,
    "indexes.report": IndexRef,
    "sync.start": SyncSource,
    "sync.report": SyncRef,
    "account.get": Empty,
    "projects.list": Empty,
    "projects.create": projects.ProjectInput,
    "projects.get": Empty,
    "members.list": Empty,
    "members.update": MemberUpdate,
    "members.remove": Member,
    "uploads.create": uploads.CreateUpload,
    "uploads.complete": UploadRef,
    "jobs.list": JobList,
    "jobs.get": JobRef,
    "jobs.cancel": JobRef,
    "jobs.retry": JobRef,
    "sources.list": SourceList,
    "sources.get": SourceRef,
    "sources.versions": SourceVersions,
    "catalog.create": catalog.CatalogCreate,
    "catalog.update": CatalogUpdate,
}
WRITES = {
    "evidence.create",
    "notes.create",
    "notes.update",
    "notes.accept",
    "exports.create",
    "imports.start",
    "snapshots.create",
    "policies.update",
    "releases.publish",
    "mounts.create",
    "mounts.remove",
    "indexes.build",
    "sync.start",
    "projects.create",
    "members.update",
    "members.remove",
    "uploads.create",
    "uploads.complete",
    "jobs.cancel",
    "jobs.retry",
    "catalog.create",
    "catalog.update",
}
SOURCE_READS = {"sources.list", "sources.get", "sources.versions", "releases.get"}


def allowed_tools(scope, role=None):
    base = {"account.get"} | SOURCE_READS
    if scope["scope_kind"] == "account":
        return sorted(base | {"projects.list", "projects.create"})
    if scope["scope_kind"] == "platform":
        return sorted(
            base
            | {
                "policies.get",
                "policies.update",
                "releases.publish",
                "catalog.create",
                "catalog.update",
                "sync.start",
                "sync.report",
                "indexes.build",
                "indexes.report",
                "jobs.list",
                "jobs.get",
                "jobs.cancel",
                "jobs.retry",
            }
        )
    base |= {
        "evidence.list",
        "notes.list",
        "exports.create",
        "exports.list",
        "exports.get",
        "jobs.cancel",
        "jobs.retry",
        "imports.get",
        "materials.list",
        "materials.get",
        "snapshots.get",
        "corpus.describe",
        "results.get",
        "projects.get",
        "jobs.list",
        "jobs.get",
        "mounts.list",
        "mounts.get",
        "mounts.manifest",
    }
    if role in {"owner", "editor"}:
        base |= {
            "evidence.create",
            "imports.start",
            "snapshots.create",
            "uploads.create",
            "uploads.complete",
            "jobs.cancel",
            "jobs.retry",
            "mounts.create",
            "mounts.remove",
        }
    if role == "owner":
        base |= {"members.list", "members.update", "members.remove"}
    return sorted(base)


def import_metadata(item):
    return {
        "import_id": item["id"],
        "job_id": item["job_id"],
        "project_id": item["project_id"],
        "material_id": item["material_id"],
        "state": item["state"],
        "material_revision_id": (item.get("result") or {}).get("id"),
        "next_action": "materials.get"
        if item["state"] == "SUCCEEDED"
        else "imports.get",
    }


def material_metadata(item):
    return {
        "material_id": item["id"],
        "project_id": item["project_id"],
        "state": item["state"],
        "import_id": item["import_id"],
        "material_revision_id": (item.get("latest_revision") or {}).get("id"),
        "revisions": [
            {
                "material_revision_id": r["id"],
                "revision": r["revision"],
                "language": r["language"],
            }
            for r in item["revisions"]
        ],
        "next_action": "snapshots.create"
        if item["state"] == "READY"
        else "imports.get",
    }


def job_metadata(db, item, actor_id):
    if item["kind"] == "EXPORT":
        return {
            "job_id": item["job_id"],
            "export_id": item["job_id"],
            "project_id": item["project_id"],
            "kind": "EXPORT",
            "state": item["state"],
            "next_action": "exports.get",
        }
    if item["kind"] != "TXT_IMPORT":
        return item
    return {
        "job_id": item["job_id"],
        "import_id": item["job_id"],
        "project_id": item["project_id"],
        "kind": "TXT_IMPORT",
        "state": item["state"],
        "material_revision_id": (item.get("result") or {}).get("material_revision_id"),
        "next_action": "imports.get",
    }


def evidence_metadata(item):
    return {
        "evidence_id": item["id"],
        **{
            k: item[k]
            for k in (
                "project_id",
                "query_run_id",
                "result_set_id",
                "snapshot_id",
                "hit_ref",
            )
        },
        "next_action": "manual_evidence_view",
    }


def note_metadata(item):
    return {
        "note_id": item["id"],
        **{
            k: item[k]
            for k in (
                "project_id",
                "revision",
                "status",
                "evidence_ids",
                "query_run_ids",
                "authorization_evidence_ids",
                "authorization_query_run_ids",
            )
        },
        "next_action": "manual_note_view",
    }


def export_metadata(item):
    return {
        "export_id": item["id"],
        "job_id": item["job_id"],
        "project_id": item["project_id"],
        "state": item["state"],
        "next_action": "manual_download"
        if item["state"] == "SUCCEEDED"
        else "exports.get",
    }


def retained_export_decision(source, acquired, previous):
    if (
        previous
        and previous.source_identity_revision == source.identity_revision
        and acquired.source_identity == source_releases.identity(source)
        and previous.acquisition_manifest_sha256 == acquired.manifest_sha256
        and previous.license_sha256
        == source_releases.digest(acquired.manifest.get("license", {}))
    ):
        return previous.export_decision
    return "deny"


def dispatch(db, actor, scope, tool, raw_args, action_id):
    """Caller supplies a fenced, bound transaction; no URL or actor comes from args."""
    schema = SCHEMAS[tool]
    if scope["scope_kind"] == "platform" and tool.startswith("jobs."):
        if tool == "jobs.list":
            schema = IndexList if "task_kind" in raw_args else SyncList
        else:
            schema = IndexRef if "index_run_id" in raw_args else SyncRef
    if tool == "notes.accept":
        raise ApiError(
            403,
            "HUMAN_AUTHORIZATION_REQUIRED",
            "Only the signed-in human can accept a note revision",
        )
    if tool in {"evidence.get", "notes.get", "notes.create", "notes.update"}:
        raise ApiError(
            403,
            "MODEL_EGRESS_DENIED",
            "Material-bearing note/evidence tools require an approved material scope",
        )
    args = schema.model_validate(raw_args)
    key = str(action_id)
    if tool == "policies.get":
        return source_releases.get_policy(args.source_id, args.acquisition_id, actor)
    if tool == "policies.update":
        body = source_releases.PolicyInput.model_validate(
            args.model_dump(exclude={"policy_kind", "source_id", "acquisition_id"})
        )
        row = source_releases.source(db, args.source_id)
        acquired = source_releases.acquisition(db, args.source_id, args.acquisition_id)
        previous = source_releases.current_policy(db, acquired.id)
        body.export_decision = retained_export_decision(row, acquired, previous)
        return source_releases.update_policy(
            args.source_id, args.acquisition_id, body, actor, key
        )
    if tool == "releases.publish":
        body = source_releases.PublishInput.model_validate(
            args.model_dump(exclude={"source_id"})
        )
        return source_releases.publish(args.source_id, body, actor, key)
    if tool == "releases.get":
        return source_releases.get_release(args.source_id, args.release_id, actor)
    if tool == "indexes.build":
        return index_builds.start(
            args.source_id,
            index_builds.BuildInput(acquisition_id=args.acquisition_id),
            actor,
            key,
        )
    if tool == "indexes.report":
        return index_builds.report(args.index_run_id, actor)
    if tool == "sync.start":
        return source_sync.start(args.source_id, jobs.EmptyBody(), actor, key)
    if tool == "sync.report":
        return source_sync.report(args.sync_run_id, actor)
    if scope["scope_kind"] == "platform" and tool.startswith("jobs."):
        if isinstance(args, IndexList):
            return index_builds.list_runs(
                args.source_id, actor, args.cursor, args.page_size
            )
        if isinstance(args, IndexRef):
            if tool == "jobs.get":
                return index_builds.report(args.index_run_id, actor)
            handler = (
                index_builds.cancel if tool == "jobs.cancel" else index_builds.retry
            )
            return handler(args.index_run_id, jobs.EmptyBody(), actor, key)
        if tool == "jobs.list":
            return source_sync.list_runs(
                args.source_id, actor, args.cursor, args.page_size
            )
        if tool == "jobs.get":
            return source_sync.report(args.sync_run_id, actor)
        handler = source_sync.cancel if tool == "jobs.cancel" else source_sync.retry
        return handler(args.sync_run_id, jobs.EmptyBody(), actor, key)
    project_id = UUID(scope["project_id"]) if scope["scope_kind"] == "project" else None
    if tool in {"corpus.search", "results.context"}:
        raise ApiError(
            403,
            "MODEL_EGRESS_DENIED"
            if tool == "results.context"
            else "SNAPSHOT_SCOPE_UNAVAILABLE",
            "材料范围和模型外发尚未获准。",
        )
    if tool == "imports.start":
        value = materials.start_import(project_id, args, actor, key)
        return {"action_id": value["action_id"], **import_metadata(value["run"])}
    if tool == "imports.get":
        return import_metadata(materials.get_import(project_id, args.import_id, actor))
    if tool == "materials.list":
        value = materials.list_materials(project_id, actor, args.page_size, args.cursor)
        return {
            "items": [material_metadata(item) for item in value["items"]],
            "next_cursor": value["next_cursor"],
        }
    if tool == "materials.get":
        return material_metadata(
            materials.get_material(project_id, args.material_id, actor)
        )
    if tool == "snapshots.create":
        value = research.create_snapshot(project_id, args, actor, key)
        item = value["snapshot"]
        return {
            "action_id": value["action_id"],
            "job_id": value["job_id"],
            "snapshot_id": item["id"],
            "project_id": str(project_id),
            "state": item["state"],
            "next_action": "snapshots.get",
        }
    if tool in {"snapshots.get", "corpus.describe"}:
        research.resolve_snapshot(db, actor.id, project_id, args.snapshot_id)
        item = research.get_snapshot(project_id, args.snapshot_id, actor)
        return {
            "snapshot_id": item["id"],
            "project_id": str(project_id),
            "job_id": item["job_id"],
            "state": item["state"],
            "next_action": "manual_query" if item["available"] else "wait",
        }
    if tool == "results.get":
        item = research.get_result(project_id, args.result_set_id, actor)
        return {
            "id": item["id"],
            "project_id": str(project_id),
            "snapshot_id": item["snapshot_id"],
            "result_set_id": item["result_set_id"],
            "state": item["state"],
            "first_page_state": item["first_page_state"],
            "count_state": item["count_state"],
            "next_action": "manual_result_view",
        }
    if tool == "evidence.create":
        value = outcomes.create_evidence(project_id, args, actor, key)
        return {
            "action_id": value["action_id"],
            "existing": value["existing"],
            **evidence_metadata(value["evidence"]),
        }
    if tool in {"evidence.list", "notes.list", "exports.list"}:
        fn, projection = {
            "evidence.list": (outcomes.list_evidence, evidence_metadata),
            "notes.list": (outcomes.list_notes, note_metadata),
            "exports.list": (exports.list_exports, export_metadata),
        }[tool]
        value = fn(project_id, actor, args.cursor, args.page_size)
        return {
            "project_id": str(project_id),
            "items": [projection(x) for x in value["items"]],
            "total": value["total"],
            "next_cursor": value["next_cursor"],
        }
    if tool == "exports.create":
        value = exports.create_export(project_id, args, actor, key)
        return {"action_id": value["action_id"], **export_metadata(value["run"])}
    if tool == "exports.get":
        return export_metadata(exports.get_export(project_id, args.export_id, actor))
    if tool == "mounts.list":
        return source_mounts.list_mounts(project_id, actor, args.cursor, args.page_size)
    if tool == "mounts.create":
        return source_mounts.create(project_id, args, actor, key)
    if tool == "mounts.get":
        return source_mounts.get_mount(project_id, args.mount_id, actor)
    if tool == "mounts.manifest":
        return source_mounts.manifest(project_id, args.mount_id, actor)
    if tool == "mounts.remove":
        return source_mounts.remove(
            project_id, args.mount_id, jobs.EmptyBody(), actor, key
        )
    if isinstance(args, (UploadRef, JobRef)):
        row = db.get(
            Upload if isinstance(args, UploadRef) else Job,
            args.upload_id if isinstance(args, UploadRef) else args.job_id,
        )
        if row is None or row.project_id != project_id:
            raise ApiError(
                404, "SCOPE_RESOURCE_NOT_FOUND", "Resource is outside this session"
            )
    key = str(action_id)
    if tool == "account.get":
        return {
            "id": str(actor.id),
            "email": actor.email,
            "is_platform_admin": actor.is_platform_admin,
        }
    if tool == "projects.list":
        return projects.list_projects(actor)
    if tool == "projects.create":
        return projects.create_project(args, actor)
    if tool == "projects.get":
        return projects.get_project(project_id, actor)
    if tool == "members.list":
        return projects.list_members(project_id, actor)
    if tool == "members.update":
        return projects.set_member(
            project_id, args.user_id, projects.MemberInput(role=args.role), actor
        )
    if tool == "members.remove":
        projects.remove_member(project_id, args.user_id, actor)
        return {"user_id": str(args.user_id), "removed": True}
    if tool == "uploads.create":
        return uploads.create_upload(project_id, args, actor, key)
    if tool == "uploads.complete":
        return uploads.complete_upload(args.upload_id, jobs.EmptyBody(), actor, key)
    if tool == "jobs.list":
        value = jobs.list_jobs(project_id, actor, args.page_size, args.cursor)
        return {
            **value,
            "items": [job_metadata(db, x, actor.id) for x in value["items"]],
        }
    if tool == "jobs.get":
        return job_metadata(db, jobs.get_job(args.job_id, actor), actor.id)
    if tool == "jobs.cancel":
        return job_metadata(
            db, jobs.cancel(args.job_id, jobs.EmptyBody(), actor, key), actor.id
        )
    if tool == "jobs.retry":
        return job_metadata(
            db, jobs.retry(args.job_id, jobs.EmptyBody(), actor, key), actor.id
        )
    if tool == "sources.list":
        return catalog.list_sources(actor, **args.model_dump())
    if tool == "sources.get":
        return catalog.get_source(args.source_id, actor)
    if tool == "sources.versions":
        return catalog.source_versions(
            args.source_id, actor, args.cursor, args.page_size
        )
    if tool == "catalog.create":
        return catalog.create_catalog(args, actor, key)
    if tool == "catalog.update":
        body = catalog.CatalogUpdate.model_validate(
            args.model_dump(exclude={"source_id"})
        )
        return catalog.update_catalog(args.source_id, body, actor, key)
    raise ApiError(403, "TOOL_NOT_ALLOWED", "Tool is not available")


def revalidate_result(db, owner, actor, row):
    """Replayed ledger data does not bypass current source or project authorization."""
    data = row.response.get("data") or {}
    if not data:
        return
    if row.tool_name.startswith(("evidence.", "notes.", "exports.")) or data.get(
        "export_id"
    ):
        revalidate_outcomes(db, owner, actor, data)

    if row.tool_name in {
        "imports.start",
        "imports.get",
        "materials.list",
        "materials.get",
    } or data.get("import_id"):
        project_id = UUID(owner.scope["project_id"])
        source_mounts.project(
            db, actor.id, project_id, write=row.tool_name == "imports.start"
        )
        for item in data.get("items", [data]):
            for revision_id in [item.get("material_revision_id")] + [
                r["material_revision_id"] for r in item.get("revisions", [])
            ]:
                if revision_id:
                    materials.load_revision(db, project_id, UUID(revision_id))
    if row.tool_name in {
        "snapshots.create",
        "snapshots.get",
        "corpus.describe",
        "results.get",
    }:
        research.resolve_snapshot(
            db, actor.id, UUID(owner.scope["project_id"]), UUID(data["snapshot_id"])
        )
        if row.tool_name == "snapshots.create":
            source_mounts.project(
                db, actor.id, UUID(owner.scope["project_id"]), write=True
            )
    if row.tool_name in {"mounts.manifest", "mounts.create"}:
        ident = (
            data.get("mount_id")
            if row.tool_name == "mounts.manifest"
            else data["mount"]["id"]
        )
        project_id = UUID(owner.scope["project_id"])
        if row.tool_name == "mounts.create":
            source_mounts.project(db, actor.id, project_id, write=True)
        source_mounts.resolve_mount(db, actor.id, project_id, UUID(ident))
    elif row.tool_name == "releases.publish":
        catalog.require_admin(db, actor)
        release = db.get(
            source_releases.CatalogRelease, UUID(data["release"]["release_id"])
        )
        source_releases.require_available(db, release)
    elif row.tool_name == "policies.update":
        catalog.require_admin(db, actor)
        saved = data["policy"]
        source = source_releases.source(db, saved["source_id"])
        policy = source_releases.current_policy(db, UUID(saved["acquisition_id"]))
        if (
            not policy
            or str(policy.id) != saved["policy_id"]
            or policy.source_identity_revision != source.identity_revision
        ):
            raise ApiError(
                409, "POLICY_REPLAY_STALE", "Historical approval is no longer current"
            )


def outcome_refs(db, project_id, data):
    from services.api.outcome_models import Evidence, ExportRecord, NoteRevision

    evidence, queries = [], []
    for item in data.get("items", [data]):
        if item.get("evidence_id"):
            e = db.get(Evidence, UUID(item["evidence_id"]))
            if not e or e.project_id != project_id:
                raise ApiError(
                    403, "EVIDENCE_UNAVAILABLE", "Evidence reference is unavailable"
                )
            evidence.append(e.id)
            queries.append(e.query_run_id)
        if item.get("note_id"):
            r = db.get(NoteRevision, (UUID(item["note_id"]), item["revision"]))
            if not r or r.project_id != project_id:
                raise ApiError(403, "NOTE_UNAVAILABLE", "Note revision is unavailable")
            evidence.extend(r.authorization_evidence_ids)
            queries.extend(r.authorization_query_run_ids)
        if item.get("export_id"):
            r = db.get(ExportRecord, UUID(item["export_id"]))
            if not r or r.project_id != project_id:
                raise ApiError(
                    403, "EXPORT_UNAVAILABLE", "Export reference is unavailable"
                )
            evidence.extend(r.authorization_evidence_ids)
            queries.extend(r.authorization_query_run_ids)
    for eid in evidence:
        e = db.get(Evidence, UUID(str(eid)))
        if not e or e.project_id != project_id:
            raise ApiError(
                403, "EVIDENCE_UNAVAILABLE", "Evidence reference is unavailable"
            )
        queries.append(e.query_run_id)
    return outcomes.ids(evidence), outcomes.ids(queries)


def revalidate_outcomes(db, owner, actor, data):
    project_id = UUID(owner.scope["project_id"])
    evidence, queries = outcome_refs(db, project_id, data)
    outcomes.authorize_dependencies(db, actor.id, project_id, evidence, queries)
    for item in data.get("items", [data]):
        if item.get("export_id"):
            exports.load(db, actor.id, project_id, UUID(item["export_id"]))
