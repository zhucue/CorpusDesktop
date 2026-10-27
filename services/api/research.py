"""Project research snapshots, durable queries and read-only result pages."""

import os
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID, uuid4

from fastapi import APIRouter, Header, Query, Response
from sqlalchemy import func, select, text

from contracts.research import (
    ContextView,
    HitPage,
    QueryAction,
    QueryInput,
    QueryList,
    QueryRunView,
    SnapshotAction,
    SnapshotInput,
    SnapshotList,
    SnapshotView,
)
from services.api import materials, source_mounts, source_releases
from services.api.auth import CurrentActor
from services.api.catalog import digest, make_cursor, read_cursor
from services.api.db import transaction
from services.api.errors import ApiError
from services.api.index_models import SourceIndex
from services.api.jobs import EmptyBody, fail, now
from services.api.material_models import Material
from services.api.projects import project_role
from services.api.research_models import (
    QueryRun,
    ResearchAction,
    ResearchEvent,
    ResearchOutbox,
    ResearchTask,
    Snapshot,
    SnapshotMember,
)
from services.api.source_sync import EMPTY_PROGRESS

router = APIRouter(prefix="/api/v1/projects/{project_id}")
TERMINAL = {"SUCCEEDED", "FAILED", "CANCELLED"}
SORT = ["document_ordinal", "start", "end"]
CAPABILITIES = {
    "character": True,
    "token_form": True,
    "lemma": False,
    "upos": False,
    "regex": False,
    "within": ["sentence"],
    "context_unit": "codepoint",
}


def validate_query(query):
    from pipelines.query.source_results import validate_query as validate

    try:
        validate(query)
    except ValueError:
        fail("QUERY_UNSUPPORTED", "查询超出当前固定索引支持的句内语法或资源上限。", 422)


def cache_root():
    return Path(
        os.environ.get(
            "RESEARCH_CACHE_DIR",
            str(Path(__file__).resolve().parents[2] / "tmp/research-cache"),
        )
    )


def result_path(run):
    return (
        cache_root()
        / "results"
        / str(run.result_set_id)
        / (run.result_object["sha256"] + ".spans")
    )


def emit(db, task, kind, data=None):
    task.updated_at = now()
    db.add(
        ResearchEvent(
            id=uuid4(),
            task_id=task.id,
            attempt=task.attempt,
            kind=kind,
            data=data or {},
            created_at=now(),
        )
    )


def enqueue(db, task):
    db.add(
        ResearchOutbox(
            task_id=task.id, attempt=task.attempt, next_attempt_at=now(), failures=0
        )
    )
    emit(db, task, "research.queued")


def new_task(db, snapshot, actor_id, phase, run=None):
    task = ResearchTask(
        id=uuid4(),
        project_id=snapshot.project_id,
        snapshot_id=snapshot.id,
        run_id=run.id if run else None,
        actor_id=actor_id,
        phase=phase,
        state="QUEUED",
        attempt=1,
        lease_epoch=0,
        progress=dict(EMPTY_PROGRESS),
        created_at=now(),
        updated_at=now(),
    )
    db.add(task)
    db.flush()
    enqueue(db, task)
    return task


def task_for(db, snapshot_id, run_id=None, phase="SNAPSHOT"):
    return db.scalar(
        select(ResearchTask).where(
            ResearchTask.snapshot_id == snapshot_id,
            ResearchTask.run_id == run_id,
            ResearchTask.phase == phase,
        )
    )


def load_snapshot(db, project_id, ident):
    item = db.scalar(
        select(Snapshot).where(Snapshot.id == ident, Snapshot.project_id == project_id)
    )
    if not item:
        fail("SNAPSHOT_NOT_FOUND", "研究快照不存在或不可访问。", 404)
    return item


def project_recipe():
    from pipelines.query.project_recipe import RECIPE_ID, RECIPE_SHA256

    return {"id": RECIPE_ID, "sha256": RECIPE_SHA256}


def is_project(snapshot):
    members = snapshot.manifest["members"]
    return len(members) != 1 or members[0]["kind"] != "whole_source_mount"


def snapshot_inputs(db, snapshot):
    inputs = []
    for member in snapshot.manifest["members"]:
        if member["kind"] == "whole_source_mount":
            index = db.get(SourceIndex, UUID(member["index_id"]))
            inputs.append(
                {
                    "kind": "source",
                    "source_id": member["source_id"],
                    "identity_sha256": index.identity_sha256,
                    "manifest_sha256": index.manifest_sha256,
                    "manifest": index.manifest,
                    "objects": index.objects,
                }
            )
        else:
            row = materials.load_revision(
                db, snapshot.project_id, UUID(member["material_revision_id"])
            )
            inputs.append(
                {
                    "kind": "private",
                    "manifest_sha256": row.manifest_sha256,
                    "manifest": row.manifest,
                    "objects": row.objects,
                }
            )
    return inputs


def resolve_snapshot(db, actor_id, project_id, ident, *, ready=False):
    project = source_mounts.project(db, actor_id, project_id)
    snapshot = load_snapshot(db, project_id, ident)
    members = list(
        db.scalars(
            select(SnapshotMember)
            .where(SnapshotMember.snapshot_id == ident)
            .order_by(SnapshotMember.ordinal)
        )
    )
    if (
        not members
        or digest(snapshot.manifest) != snapshot.manifest_sha256
        or [m.descriptor for m in members] != snapshot.manifest["members"]
    ):
        fail("SNAPSHOT_INVALID", "固定研究快照不完整。", 409)
    for source_id in sorted(
        {m.descriptor["source_id"] for m in members if m.kind == "whole_source_mount"}
    ):
        source_releases.lock_source(db, source_id)
    source_index = None
    for member in members:
        frozen = member.descriptor
        if member.kind == "whole_source_mount":
            _, _, release, index = source_mounts.resolve_mount(
                db, actor_id, project_id, member.mount_id
            )
            if (
                frozen["release_id"] != str(release.release_id)
                or frozen["index_id"] != str(index.id)
                or frozen["index_identity_sha256"] != index.identity_sha256
                or release.recipe != source_releases.recipe()
            ):
                fail("SNAPSHOT_IDENTITY_CHANGED", "固定来源身份不一致。", 403)
            source_index = index
        else:
            row = materials.load_revision(db, project_id, member.material_revision_id)
            if frozen["manifest_sha256"] != row.manifest_sha256 or frozen[
                "material_id"
            ] != str(row.material_id):
                fail("SNAPSHOT_IDENTITY_CHANGED", "固定私有修订身份不一致。", 403)
    if ready and snapshot.state != "READY":
        fail("SNAPSHOT_NOT_READY", "研究快照尚未准备完成。", 409)
    if is_project(snapshot):
        receipt = snapshot.index_result or {}
        if snapshot.state == "READY" and not receipt:
            fail("SNAPSHOT_INVALID", "项目索引尚未可靠登记。", 409)
        index = SimpleNamespace(
            manifest=receipt.get("manifest", {}),
            manifest_sha256=receipt.get("manifest_sha256"),
            identity_sha256=receipt.get("identity_sha256"),
            objects=receipt.get("objects", []),
        )
    else:
        index = source_index
    return project, snapshot, index


def index_counts(index):
    if not index or not index.manifest:
        return None
    counts = index.manifest["counts"]
    fields = (
        "sentences",
        "cmn_sentences",
        "eng_sentences",
        "characters",
        "tokens",
        "direct_edges",
        "unknown_owner",
    )
    source = counts.get("source_documents", counts["sentences"])
    private = counts.get("private_documents", 0)
    return {
        **{k: counts[k] for k in fields},
        "documents": source + private,
        "document_units": {"source_records": source, "private_files": private},
    }


def query_counts(run, snapshot):
    source = any(
        m["kind"] == "whole_source_mount" for m in snapshot.manifest["members"]
    )
    private = any(m["kind"] == "private_revision" for m in snapshot.manifest["members"])
    unit = (
        "mixed_document_units"
        if source and private
        else "uploaded_file"
        if private
        else "imported_sentence_record"
    )
    values = {
        k: (run.counts or {}).get(k)
        for k in ("total_hits", "matched_segments", "matched_documents")
    }
    units = (
        None
        if run.counts is None
        else {
            "source_records": run.counts.get(
                "matched_source_documents",
                run.counts["matched_documents"] if source and not private else 0,
            ),
            "private_files": run.counts.get("matched_private_documents", 0),
        }
    )
    return {**values, "document_count_unit": unit, "matched_document_units": units}


def reserve_index(db, project_id):
    db.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended('project-index-budget',0))")
    )
    amount = int(os.environ.get("PROJECT_INDEX_BUILD_MAX_BYTES", str(4 * 1024**3)))
    used = local = 0
    for row in db.scalars(select(Snapshot)):
        size = (
            sum(x["bytes"] for x in (row.index_result or {}).get("objects", []))
            + row.reserved_bytes
        )
        used += size
        if row.project_id == project_id:
            local += size
    if (
        amount <= 0
        or amount > 4 * 1024**3
        or used + amount
        > int(os.environ.get("PROJECT_INDEX_STORAGE_MAX_BYTES", str(12 * 1024**3)))
        or local + amount
        > int(os.environ.get("PROJECT_INDEX_PROJECT_MAX_BYTES", str(8 * 1024**3)))
    ):
        fail("PROJECT_INDEX_QUOTA_EXCEEDED", "项目索引预算不足，包含待清理预留。")
    return amount


def action(db, actor_id, project_id, operation, key, payload):
    if (
        not isinstance(key, str)
        or not key
        or len(key) > 128
        or not key.isascii()
        or any(ord(c) < 33 for c in key)
    ):
        fail("IDEMPOTENCY_KEY_REQUIRED", "提供有效的 Idempotency-Key。", 422)
    old = db.scalar(
        select(ResearchAction).where(
            ResearchAction.actor_id == actor_id,
            ResearchAction.project_id == project_id,
            ResearchAction.operation == operation,
            ResearchAction.idempotency_key == key,
        )
    )
    fingerprint = digest(payload)
    if old:
        if old.request_sha256 != fingerprint:
            fail("IDEMPOTENCY_CONFLICT", "相同操作标识不能用于不同请求。")
        return old, True
    row = ResearchAction(
        id=uuid4(),
        project_id=project_id,
        actor_id=actor_id,
        operation=operation,
        idempotency_key=key,
        request_sha256=fingerprint,
        response={},
        created_at=now(),
    )
    db.add(row)
    return row, False


def snapshot_view(db, actor_id, snapshot):
    project = source_mounts.project(db, actor_id, snapshot.project_id)
    reason, index = None, None
    try:
        _, _, index = resolve_snapshot(db, actor_id, snapshot.project_id, snapshot.id)
    except ApiError as exc:
        if exc.status not in {403, 409}:
            raise
        reason = exc.code
    task = task_for(db, snapshot.id)
    return {
        "id": str(snapshot.id),
        "project_id": str(snapshot.project_id),
        "name": snapshot.name,
        "created_by": str(snapshot.created_by),
        "job_id": str(task.id),
        "created_at": snapshot.created_at.isoformat(),
        "updated_at": snapshot.updated_at.isoformat(),
        "state": snapshot.state,
        "available": reason is None and snapshot.state == "READY",
        "unavailable_reason": reason
        or ("SNAPSHOT_NOT_READY" if snapshot.state != "READY" else None),
        "manifest_sha256": snapshot.manifest_sha256,
        "members": snapshot.manifest["members"],
        "counts": index_counts(index) if reason is None else None,
        "index_kind": "project" if is_project(snapshot) else "source_reuse",
        "query_capabilities": CAPABILITIES,
        "progress": task.progress,
        "error": task.error,
        "allowed_actions": {
            "retry": reason is None
            and task.state == "FAILED"
            and task.attempt < 3
            and snapshot.reserved_bytes == 0
            and project_role(db, actor_id, project) in {"owner", "editor"}
        },
    }


def current_task(db, run):
    full = task_for(db, run.snapshot_id, run.id, "FULL_RESULT")
    return (
        full
        if full and full.state != "CANCELLED"
        else task_for(db, run.snapshot_id, run.id, "FIRST_PAGE")
    )


def query_view(db, actor_id, run):
    project, snapshot, _ = resolve_snapshot(
        db, actor_id, run.project_id, run.snapshot_id
    )
    task = current_task(db, run)
    prepare = task_for(db, run.snapshot_id, run.id, "PREPARE_CACHE")
    permitted = (
        actor_id == run.actor_id or project_role(db, actor_id, project) == "owner"
    )
    return {
        "id": str(run.id),
        "name": run.name,
        "project_id": str(run.project_id),
        "snapshot_id": str(run.snapshot_id),
        "result_set_id": str(run.result_set_id),
        "actor_id": str(run.actor_id),
        "query": run.query,
        "query_sha256": run.query_sha256,
        "recipe": project_recipe()
        if is_project(snapshot)
        else snapshot.manifest["members"][0]["recipe"],
        "sort": SORT,
        "page_size": run.page_size,
        "context_codepoints": run.context_codepoints,
        "state": run.state,
        "stage": "COMPLETE"
        if run.state == "SUCCEEDED"
        else run.state
        if run.state in TERMINAL
        else task.phase
        if task.state == "RUNNING"
        else "QUEUED",
        "attempt": run.attempt,
        "created_at": run.created_at.isoformat(),
        "updated_at": run.updated_at.isoformat(),
        "first_page_state": "ready"
        if run.first_page
        else "failed"
        if run.state in {"FAILED", "CANCELLED"}
        else "pending",
        "count_state": "complete"
        if run.counts is not None
        else "failed"
        if run.state in {"FAILED", "CANCELLED"}
        else "pending",
        **query_counts(run, snapshot),
        "progress": task.progress,
        "error": run.error,
        "prepare_state": (
            "pending"
            if prepare.state in {"QUEUED", "RUNNING"}
            else "ready"
            if prepare.state == "SUCCEEDED"
            else "failed"
        )
        if prepare
        else "idle",
        "allowed_actions": {
            "cancel": permitted and run.state not in TERMINAL,
            "retry": actor_id == run.actor_id
            and run.state == "FAILED"
            and run.attempt < 3
            and run.reserved_bytes == 0
            and bool((run.error or {}).get("retryable")),
            "prepare": run.state == "SUCCEEDED"
            and (not prepare or prepare.state in TERMINAL and prepare.attempt < 3),
        },
    }


def load_run(db, actor_id, project_id, ident, *, result=False):
    source_mounts.project(db, actor_id, project_id)
    row = db.scalar(
        select(QueryRun).where(
            QueryRun.project_id == project_id,
            (QueryRun.result_set_id if result else QueryRun.id) == ident,
        )
    )
    if not row:
        fail("QUERY_NOT_FOUND", "查询不存在或不可访问。", 404)
    resolve_snapshot(db, actor_id, project_id, row.snapshot_id)
    return row


def reserve(db, project_id):
    db.execute(
        text(
            "SELECT pg_advisory_xact_lock(hashtextextended('research-result-budget',0))"
        )
    )
    amount = int(os.environ.get("QUERY_RESULT_MAX_BYTES", str(512 * 1024**2)))
    used = db.scalar(select(func.coalesce(func.sum(QueryRun.reserved_bytes), 0)))
    size = db.scalar(
        select(func.coalesce(func.sum(QueryRun.result_object["bytes"].as_integer()), 0))
    )
    # App RLS sees its project set; cross-project physical admission is checked again by worker.
    project_reserved = db.scalar(
        select(func.coalesce(func.sum(QueryRun.reserved_bytes), 0)).where(
            QueryRun.project_id == project_id
        )
    )
    project_size = db.scalar(
        select(
            func.coalesce(func.sum(QueryRun.result_object["bytes"].as_integer()), 0)
        ).where(QueryRun.project_id == project_id)
    )
    active = db.scalar(
        select(func.count())
        .select_from(QueryRun)
        .where(
            QueryRun.project_id == project_id, QueryRun.state.in_(["QUEUED", "RUNNING"])
        )
    )
    if (
        amount <= 0
        or amount > 512 * 1024**2
        or used + size + amount
        > int(os.environ.get("QUERY_STORAGE_MAX_BYTES", str(2 * 1024**3)))
        or project_reserved + project_size + amount
        > int(os.environ.get("QUERY_PROJECT_MAX_BYTES", str(1024**3)))
        or active >= 2
    ):
        fail(
            "QUERY_QUOTA_EXCEEDED",
            "查询预算不足，包含已登记结果、活动任务和待清理预留。",
            409,
        )
    return amount


@router.post("/snapshots", status_code=202, response_model=SnapshotAction)
def create_snapshot(
    project_id: UUID,
    body: SnapshotInput,
    actor: CurrentActor,
    idempotency_key: str = Header(),
):
    with transaction(actor.id) as db:
        source_mounts.project(db, actor.id, project_id, write=True)
        source_ids = set()
        for ident in body.mount_ids:
            mount = source_mounts.load(db, project_id, ident)
            source_ids.add(
                source_mounts.release_for(db, mount.source_snapshot_id).source_id
            )
        for source_id in sorted(source_ids):
            source_releases.lock_source(db, source_id)
        descriptors = []
        for ident in body.mount_ids:
            _, mount, release, index = source_mounts.resolve_mount(
                db, actor.id, project_id, ident
            )
            descriptors.append(
                {
                    "kind": "whole_source_mount",
                    "mount_id": str(mount.id),
                    "source_id": release.source_id,
                    "source_snapshot_id": str(release.source_snapshot_id),
                    "release_id": str(release.release_id),
                    "index_id": str(index.id),
                    "index_identity_sha256": index.identity_sha256,
                    "ordered_members_sha256": index.manifest["identity"][
                        "ordered_members_sha256"
                    ],
                    "recipe": release.recipe,
                }
            )
        documents = set()
        for ident in body.material_revision_ids:
            row = materials.load_revision(db, project_id, ident)
            if row.material_id in documents:
                fail(
                    "MATERIAL_REVISION_CONFLICT", "同一快照不能选择同一文档的多个修订。"
                )
            documents.add(row.material_id)
            value = materials.revision_view(row)
            descriptors.append(
                {
                    "kind": "private_revision",
                    "material_id": str(row.material_id),
                    "material_revision_id": str(row.id),
                    **{
                        k: value[k]
                        for k in (
                            "revision",
                            "language",
                            "manifest_sha256",
                            "canonical_sha256",
                            "recipe",
                        )
                    },
                }
            )
        ledger, old = action(
            db,
            actor.id,
            project_id,
            "snapshots.create",
            idempotency_key,
            body.model_dump(mode="json"),
        )
        if old:
            snapshot = load_snapshot(
                db, project_id, UUID(ledger.response["snapshot_id"])
            )
            resolve_snapshot(db, actor.id, project_id, snapshot.id)
        else:
            manifest = {
                "format": "research-snapshot/v2",
                "project_id": str(project_id),
                "members": descriptors,
                "member_order": "mount input order, then private input order",
                "index_order": "source namespace/revision then private document/revision; contiguous segments",
            }
            mixed = (
                len(descriptors) != 1 or descriptors[0]["kind"] != "whole_source_mount"
            )
            snapshot = Snapshot(
                id=uuid4(),
                project_id=project_id,
                created_by=actor.id,
                name="研究快照 " + now().strftime("%Y-%m-%d %H:%M"),
                state="PREPARING",
                manifest=manifest,
                manifest_sha256=digest(manifest),
                reserved_bytes=reserve_index(db, project_id) if mixed else 0,
                created_at=now(),
                updated_at=now(),
            )
            db.add(snapshot)
            db.flush()
            for ordinal, descriptor in enumerate(descriptors):
                db.add(
                    SnapshotMember(
                        snapshot_id=snapshot.id,
                        ordinal=ordinal,
                        project_id=project_id,
                        kind=descriptor["kind"],
                        mount_id=UUID(descriptor["mount_id"])
                        if descriptor["kind"] == "whole_source_mount"
                        else None,
                        material_revision_id=UUID(descriptor["material_revision_id"])
                        if descriptor["kind"] == "private_revision"
                        else None,
                        descriptor=descriptor,
                    )
                )
            db.flush()
            new_task(db, snapshot, actor.id, "SNAPSHOT")
            ledger.response = {"snapshot_id": str(snapshot.id)}
        value = snapshot_view(db, actor.id, snapshot)
        return {
            "action_id": str(ledger.id),
            "existing": old,
            "job_id": value["job_id"],
            "snapshot": value,
        }


@router.get("/snapshots/{snapshot_id}", response_model=SnapshotView)
def get_snapshot(project_id: UUID, snapshot_id: UUID, actor: CurrentActor):
    with transaction(actor.id) as db:
        source_mounts.project(db, actor.id, project_id)
        return snapshot_view(db, actor.id, load_snapshot(db, project_id, snapshot_id))


def listing(db, model, project_id, cursor, page_size, kind):
    filters = {"project_id": str(project_id), "kind": kind}
    last = read_cursor(cursor, filters)
    stmt = select(model).where(model.project_id == project_id)
    if last:
        try:
            stmt = stmt.where(model.id > UUID(last))
        except ValueError:
            fail("INVALID_CURSOR", "分页游标无效。", 422)
    rows = list(db.scalars(stmt.order_by(model.id).limit(page_size + 1)))
    return rows[:page_size], {
        "total": db.scalar(
            select(func.count())
            .select_from(model)
            .where(model.project_id == project_id)
        ),
        "next_cursor": make_cursor(str(rows[page_size - 1].id), filters)
        if len(rows) > page_size
        else None,
    }


@router.get("/snapshots", response_model=SnapshotList)
def list_snapshots(
    project_id: UUID,
    actor: CurrentActor,
    cursor: str | None = Query(None, max_length=512),
    page_size: int = Query(50, ge=1, le=100),
):
    with transaction(actor.id) as db:
        project = source_mounts.project(db, actor.id, project_id)
        rows, extra = listing(db, Snapshot, project_id, cursor, page_size, "snapshots")
        for sid in sorted(
            {
                m["source_id"]
                for row in rows
                for m in row.manifest["members"]
                if m["kind"] == "whole_source_mount"
            }
        ):
            source_releases.source(db, sid)
        return {
            "items": [snapshot_view(db, actor.id, row) for row in rows],
            **extra,
            "allowed_actions": {
                "create": project_role(db, actor.id, project) in {"owner", "editor"}
            },
        }


def reset_task(db, task):
    if task.attempt >= 3:
        fail("ATTEMPT_LIMIT", "人工尝试次数已达上限。", 409)
    task.attempt += 1
    task.lease_epoch += 1
    task.lease_token = task.lease_expires_at = None
    task.state, task.error, task.progress = "QUEUED", None, dict(EMPTY_PROGRESS)
    enqueue(db, task)


@router.post(
    "/snapshots/{snapshot_id}/retry", status_code=202, response_model=SnapshotAction
)
def retry_snapshot(
    project_id: UUID,
    snapshot_id: UUID,
    body: EmptyBody,
    actor: CurrentActor,
    idempotency_key: str = Header(),
):
    with transaction(actor.id) as db:
        source_mounts.project(db, actor.id, project_id, write=True)
        _, snapshot, _ = resolve_snapshot(db, actor.id, project_id, snapshot_id)
        ledger, old = action(
            db,
            actor.id,
            project_id,
            "snapshots.retry",
            idempotency_key,
            {"snapshot_id": str(snapshot_id)},
        )
        task = task_for(db, snapshot_id)
        if not old:
            if task.state != "FAILED":
                fail("RETRY_NOT_ALLOWED", "仅失败的快照准备可重试。")
            if snapshot.reserved_bytes:
                fail(
                    "PROJECT_INDEX_CLEANUP_REQUIRED", "私有对象尚未确认清理，不能重试。"
                )
            if is_project(snapshot):
                snapshot.reserved_bytes = reserve_index(db, project_id)
            task.actor_id = actor.id
            reset_task(db, task)
            snapshot.state, snapshot.updated_at = "PREPARING", now()
            ledger.response = {"snapshot_id": str(snapshot.id)}
        return {
            "action_id": str(ledger.id),
            "existing": old,
            "job_id": str(task.id),
            "snapshot": snapshot_view(db, actor.id, snapshot),
        }


def query_action(db, ledger, actor_id, run, task=None):
    ledger.response = {"query_run_id": str(run.id)}
    task = task or current_task(db, run)
    return {
        "action_id": str(ledger.id),
        "job_id": str(task.id),
        "query_run_id": str(run.id),
        "result_set_id": str(run.result_set_id),
        "state": run.state,
        "run": query_view(db, actor_id, run),
    }


@router.post("/queries", status_code=202, response_model=QueryAction)
def start_query(
    project_id: UUID,
    body: QueryInput,
    actor: CurrentActor,
    idempotency_key: str = Header(),
):
    query = body.model_dump(mode="json")["query"]
    validate_query(query)
    with transaction(actor.id) as db:
        _, snapshot, _ = resolve_snapshot(
            db, actor.id, project_id, body.snapshot_id, ready=True
        )
        ledger, old = action(
            db,
            actor.id,
            project_id,
            "corpus.search",
            idempotency_key,
            body.model_dump(mode="json"),
        )
        if old:
            return query_action(
                db,
                ledger,
                actor.id,
                load_run(
                    db, actor.id, project_id, UUID(ledger.response["query_run_id"])
                ),
            )
        reservation = reserve(db, project_id)
        run = QueryRun(
            id=uuid4(),
            project_id=project_id,
            snapshot_id=snapshot.id,
            actor_id=actor.id,
            result_set_id=uuid4(),
            name=("字符查询" if query["unit"] == "character" else "词形查询")
            + " "
            + now().strftime("%m-%d %H:%M"),
            query=query,
            query_sha256=digest(query),
            page_size=body.page_size,
            context_codepoints=body.context_codepoints,
            state="QUEUED",
            attempt=1,
            reserved_bytes=reservation,
            created_at=now(),
            updated_at=now(),
        )
        db.add(run)
        db.flush()
        new_task(db, snapshot, actor.id, "FIRST_PAGE", run)
        return query_action(db, ledger, actor.id, run)


@router.get("/queries/{query_run_id}", response_model=QueryRunView)
def get_query(project_id: UUID, query_run_id: UUID, actor: CurrentActor):
    with transaction(actor.id) as db:
        return query_view(
            db, actor.id, load_run(db, actor.id, project_id, query_run_id)
        )


@router.get("/result-sets/{result_set_id}", response_model=QueryRunView)
def get_result(project_id: UUID, result_set_id: UUID, actor: CurrentActor):
    with transaction(actor.id) as db:
        return query_view(
            db, actor.id, load_run(db, actor.id, project_id, result_set_id, result=True)
        )


@router.get("/queries", response_model=QueryList)
def list_queries(
    project_id: UUID,
    actor: CurrentActor,
    cursor: str | None = Query(None, max_length=512),
    page_size: int = Query(50, ge=1, le=100),
):
    with transaction(actor.id) as db:
        source_mounts.project(db, actor.id, project_id)
        rows, extra = listing(db, QueryRun, project_id, cursor, page_size, "queries")
        snapshots = [load_snapshot(db, project_id, row.snapshot_id) for row in rows]
        for sid in sorted(
            {
                m["source_id"]
                for s in snapshots
                for m in s.manifest["members"]
                if m["kind"] == "whole_source_mount"
            }
        ):
            source_releases.source(db, sid)
        return {"items": [query_view(db, actor.id, row) for row in rows], **extra}


def finish_failure(db, task, code, message, retryable=False):
    task.state, task.error = (
        "FAILED",
        {"code": code, "message": message, "retryable": retryable},
    )
    task.lease_epoch += 1
    task.lease_token = task.lease_expires_at = None
    if task.phase == "SNAPSHOT":
        snapshot = db.get(Snapshot, task.snapshot_id)
        snapshot.state, snapshot.updated_at = "FAILED", now()
    elif task.phase != "PREPARE_CACHE":
        run = db.get(QueryRun, task.run_id)
        if run.state not in TERMINAL:
            run.state, run.error, run.updated_at = "FAILED", task.error, now()
    emit(db, task, "research.failed", task.error)


def mutate_query(project_id, query_run_id, actor, key, operation):
    with transaction(actor.id) as db:
        run = load_run(db, actor.id, project_id, query_run_id)
        project = source_mounts.project(db, actor.id, project_id)
        if actor.id != run.actor_id and (
            operation != "cancel" or project_role(db, actor.id, project) != "owner"
        ):
            fail(
                "QUERY_CONTROL_DENIED",
                "只能管理本人查询，项目负责人可取消项目查询。",
                403,
            )
        ledger, old = action(
            db,
            actor.id,
            project_id,
            "queries." + operation,
            key,
            {"query_run_id": str(run.id)},
        )
        if old or operation == "cancel" and run.state in TERMINAL:
            return query_action(db, ledger, actor.id, run)
        tasks = list(
            db.scalars(select(ResearchTask).where(ResearchTask.run_id == run.id))
        )
        if operation == "cancel":
            # Only an executing full-result phase can have an unconfirmed S3 PUT.
            claimed = any(
                t.phase == "FULL_RESULT" and t.state == "RUNNING" for t in tasks
            )
            for task in tasks:
                if task.state not in TERMINAL:
                    task.state, task.lease_epoch = "CANCELLED", task.lease_epoch + 1
                    task.lease_token = task.lease_expires_at = None
                    emit(db, task, "research.cancelled")
            run.state, run.updated_at = "CANCELLED", now()
            if not claimed:
                run.reserved_bytes = 0
        else:
            if (
                run.state != "FAILED"
                or run.attempt >= 3
                or run.reserved_bytes
                or not (run.error or {}).get("retryable")
            ):
                fail("RETRY_NOT_ALLOWED", "任务尚不可重试，可能有待清理预留。")
            run.reserved_bytes = reserve(db, project_id)
            run.attempt += 1
            run.state, run.error, run.first_page, run.counts = (
                "QUEUED",
                None,
                None,
                None,
            )
            # Restart only the first page; old full-result delivery is fenced by state/attempt.
            for task in tasks:
                task.lease_epoch += 1
                task.lease_token = task.lease_expires_at = None
                if task.phase == "FIRST_PAGE":
                    reset_task(db, task)
                elif task.phase == "FULL_RESULT":
                    task.state = "CANCELLED"
            run.updated_at = now()
        return query_action(db, ledger, actor.id, run)


@router.post(
    "/queries/{query_run_id}/cancel", status_code=202, response_model=QueryAction
)
def cancel_query(
    project_id: UUID,
    query_run_id: UUID,
    body: EmptyBody,
    actor: CurrentActor,
    idempotency_key: str = Header(),
):
    return mutate_query(project_id, query_run_id, actor, idempotency_key, "cancel")


@router.post(
    "/queries/{query_run_id}/retry", status_code=202, response_model=QueryAction
)
def retry_query(
    project_id: UUID,
    query_run_id: UUID,
    body: EmptyBody,
    actor: CurrentActor,
    idempotency_key: str = Header(),
):
    return mutate_query(project_id, query_run_id, actor, idempotency_key, "retry")


@router.post(
    "/result-sets/{result_set_id}/prepare", status_code=202, response_model=QueryAction
)
def prepare_result(
    project_id: UUID,
    result_set_id: UUID,
    body: EmptyBody,
    actor: CurrentActor,
    idempotency_key: str = Header(),
):
    with transaction(actor.id) as db:
        run = load_run(db, actor.id, project_id, result_set_id, result=True)
        if run.state != "SUCCEEDED":
            fail("RESULT_NOT_COMPLETE", "只能恢复完整结果的固定缓存。")
        ledger, old = action(
            db,
            actor.id,
            project_id,
            "results.prepare",
            idempotency_key,
            {"result_set_id": str(result_set_id)},
        )
        task = task_for(db, run.snapshot_id, run.id, "PREPARE_CACHE")
        if not old:
            if not task:
                task = new_task(
                    db,
                    db.get(Snapshot, run.snapshot_id),
                    actor.id,
                    "PREPARE_CACHE",
                    run,
                )
            elif task.state in TERMINAL:
                task.actor_id = actor.id
                reset_task(db, task)
        return query_action(db, ledger, actor.id, run, task)


def format_hit(run, hit, ordinal, db=None):
    source_id = hit.get("source_id")
    if hit.get("origin_kind", "source") == "source" and source_id is None and db:
        snapshot = db.get(Snapshot, run.snapshot_id)
        sources = [
            m for m in snapshot.manifest["members"] if m["kind"] == "whole_source_mount"
        ]
        if len(sources) != 1:
            fail("SNAPSHOT_IDENTITY_CHANGED", "来源命中缺少固定namespace。", 409)
        source_id = sources[0]["source_id"]
    return {
        "hit_ref": {"result_set_id": str(run.result_set_id), "ordinal": ordinal},
        **{
            key: hit[key]
            for key in (
                "revision_id",
                "segment_id",
                "start_cp",
                "end_cp",
                "token_start",
                "token_end",
                "global_token_start",
                "global_token_end",
                "left",
                "match",
                "right",
                "source_url",
            )
        },
        "source_sentence_id": str(hit["source_sentence_id"])
        if hit["source_sentence_id"] is not None
        else None,
        "origin_kind": hit.get("origin_kind", "source"),
        "document_id": hit.get("document_id", hit["revision_id"]),
        "document_name": (
            db.get(Material, UUID(hit["document_id"])).name
            if db and hit.get("origin_kind") == "private"
            else str(hit.get("source_sentence_id") or hit.get("document_id", ""))
        ),
        "material_id": hit["document_id"]
        if hit.get("origin_kind") == "private"
        else None,
        "material_revision_id": hit["revision_id"]
        if hit.get("origin_kind") == "private"
        else None,
        "source_id": hit.get("source_id")
        if hit.get("origin_kind") == "private"
        else source_id,
        "context_start_cp": hit.get("context_start_cp", 0),
        "evidence_id": None,
    }


def read_cached(run, index, offset, limit):
    from pipelines.query.source_cache import open_cached
    from pipelines.query.source_results import read_page

    try:
        with open_cached(
            cache_root() / "indexes",
            index.manifest["package"]["sha256"],
            index.identity_sha256,
        ) as reader:
            return read_page(
                reader,
                result_path(run),
                offset,
                limit=limit,
                context_codepoints=run.context_codepoints,
                expected_sha256=run.result_object["sha256"],
                expected_records=run.counts["total_hits"],
            )
    except (OSError, ValueError):
        fail("CACHE_NOT_READY", "固定结果缓存不可用，请执行准备后重试。", 503)


def page_data(db, actor_id, run, cursor, page_size):
    _, snapshot, index = resolve_snapshot(
        db, actor_id, run.project_id, run.snapshot_id, ready=True
    )
    size = run.page_size if page_size is None else page_size
    if run.state in {"FAILED", "CANCELLED"} and run.first_page is None:
        fail(
            "QUERY_" + run.state, (run.error or {}).get("message", "查询已取消。"), 409
        )
    if size != run.page_size:
        fail("INVALID_CURSOR", "分页大小须与该次查询保持一致。", 422)
    filters = {
        "result": str(run.result_set_id),
        "query": run.query_sha256,
        "snapshot": snapshot.manifest_sha256,
        "page_size": size,
        "sort": SORT,
        "attempt": run.attempt,
    }
    last = read_cursor(cursor, filters)
    try:
        offset = int(last) if last is not None else 0
        if offset < 0 or offset % size or offset > 16_777_216:
            raise ValueError
    except ValueError:
        fail("INVALID_CURSOR", "分页位置无效。", 422)
    ready = run.counts is not None or offset == 0 and run.first_page is not None
    page = (
        read_cached(run, index, offset, size)
        if run.counts is not None
        else run.first_page
        if ready
        else {"hits": [], "has_more": False}
    )
    return {
        "project_id": str(run.project_id),
        "snapshot_id": str(run.snapshot_id),
        "result_set_id": str(run.result_set_id),
        "query_run_id": str(run.id),
        "hits": [
            format_hit(run, h, offset + i, db) for i, h in enumerate(page["hits"])
        ],
        "has_more": page["has_more"],
        "next_cursor": make_cursor(str(offset + size), filters)
        if run.counts is not None and page["has_more"]
        else None,
        "page_state": "ready" if ready else "pending",
        "count_state": "complete"
        if run.counts is not None
        else "failed"
        if run.state in {"FAILED", "CANCELLED"}
        else "pending",
        **query_counts(run, snapshot),
        "completeness": "complete" if run.counts is not None else "preview",
        "sort": SORT,
        "context": {
            "unit": "codepoint",
            "before": run.context_codepoints,
            "after": run.context_codepoints,
        },
    }


@router.get("/result-sets/{result_set_id}/hits", response_model=HitPage)
def hits(
    project_id: UUID,
    result_set_id: UUID,
    response: Response,
    actor: CurrentActor,
    cursor: str | None = Query(None, max_length=512),
    page_size: int | None = Query(None, ge=1, le=50),
):
    with transaction(actor.id) as db:
        run = load_run(db, actor.id, project_id, result_set_id, result=True)
        result = page_data(db, actor.id, run, cursor, page_size)
        response.status_code = 202 if result["page_state"] == "pending" else 200
        return result


@router.get(
    "/result-sets/{result_set_id}/hits/{ordinal}/context", response_model=ContextView
)
def context(project_id: UUID, result_set_id: UUID, ordinal: int, actor: CurrentActor):
    with transaction(actor.id) as db:
        run = load_run(db, actor.id, project_id, result_set_id, result=True)
        _, _, index = resolve_snapshot(
            db, actor.id, project_id, run.snapshot_id, ready=True
        )
        if ordinal < 0 or ordinal > 16_777_216:
            fail("HIT_NOT_FOUND", "命中引用不存在。", 404)
        if run.counts is None:
            fail("RESULT_NOT_COMPLETE", "完整结果尚未完成。", 409)
        page = read_cached(run, index, ordinal, 1)
        if not page["hits"]:
            fail("HIT_NOT_FOUND", "命中引用不存在。", 404)
        hit = page["hits"][0]
        from pipelines.query.source_cache import open_cached

        try:
            with open_cached(
                cache_root() / "indexes",
                index.manifest["package"]["sha256"],
                index.identity_sha256,
            ) as reader:
                full_text = reader.text(hit["sentence_ordinal"])
        except (OSError, ValueError):
            fail("CACHE_NOT_READY", "固定结果缓存不可用。", 503)
        value = format_hit(run, hit, ordinal, db)
        for key in ("left", "match", "right"):
            value.pop(key)
        return {
            **value,
            "project_id": str(project_id),
            "snapshot_id": str(run.snapshot_id),
            "result_set_id": str(result_set_id),
            "text": full_text,
        }
