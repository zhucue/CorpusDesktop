"""Whole immutable-source mounts; authorization is checked on each actual read."""

from uuid import UUID, uuid4

from fastapi import APIRouter, Header, Query
from pydantic import BaseModel, ConfigDict
from sqlalchemy import func, select

from contracts.releases import MountAction as MountActionView
from contracts.releases import MountList, MountManifest, MountView
from services.api import source_releases as releases
from services.api.auth import CurrentActor
from services.api.catalog import digest, make_cursor, read_cursor
from services.api.catalog_models import CatalogRelease
from services.api.db import lock_actor, lock_project, transaction
from services.api.index_models import SourceIndex
from services.api.jobs import EmptyBody, fail, now
from services.api.projects import project_role, require_project
from services.api.release_models import MountAction, SourceMount

router = APIRouter(prefix="/api/v1/projects/{project_id}/mounts")


class MountInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source_snapshot_id: UUID


def project(db, actor_id, project_id, *, write=False):
    lock_actor(db, actor_id)
    lock_project(db, project_id)
    return require_project(db, actor_id, project_id, write=write)


def load(db, project_id, mount_id):
    mount = db.scalar(
        select(SourceMount)
        .where(SourceMount.id == mount_id, SourceMount.project_id == project_id)
        .execution_options(populate_existing=True)
    )
    if not mount:
        fail("MOUNT_NOT_FOUND", "项目挂载不存在。", 404)
    return mount


def release_for(db, snapshot_id):
    row = db.scalar(
        select(CatalogRelease).where(CatalogRelease.source_snapshot_id == snapshot_id)
    )
    if not row:
        fail("RELEASE_NOT_FOUND", "固定来源发布版本不存在。", 404)
    return row


def view(db, actor_id, project_row, mount):
    release = releases.view_release(db, release_for(db, mount.source_snapshot_id))
    write = project_role(db, actor_id, project_row) in {"owner", "editor"}
    return {
        "id": str(mount.id),
        "project_id": str(mount.project_id),
        "created_at": mount.created_at.isoformat(),
        "removed_at": mount.removed_at.isoformat() if mount.removed_at else None,
        "state": "REMOVED" if mount.removed_at else "ACTIVE",
        "release": release,
        "allowed_actions": {
            "read_manifest": mount.removed_at is None and release["available"],
            "remove": write and mount.removed_at is None,
        },
    }


def resolve_mount(db, actor_id, project_id, mount_id):
    """Server-only fixed index handle. Call in transaction; never return objects to clients."""
    project_row = project(db, actor_id, project_id)
    mount = load(db, project_id, mount_id)
    if mount.removed_at:
        fail("MOUNT_REMOVED", "该挂载已移除。", 403)
    release = release_for(db, mount.source_snapshot_id)
    releases.require_available(db, release)
    index = db.get(SourceIndex, release.index_id)
    if (
        not index
        or index.identity_sha256 != release.index_identity_sha256
        or index.manifest_sha256 != release.manifest_sha256
    ):
        fail("INDEX_NOT_AVAILABLE", "固定索引不可访问。", 403)
    return project_row, mount, release, index


def action(db, actor_id, project_id, operation, key, payload):
    if (
        not isinstance(key, str)
        or not key
        or len(key) > 128
        or not key.isascii()
        or any(ord(c) < 33 for c in key)
    ):
        fail("IDEMPOTENCY_KEY_REQUIRED", "提供有效的 Idempotency-Key。", 422)
    fingerprint = digest(payload)
    old = db.scalar(
        select(MountAction).where(
            MountAction.actor_id == actor_id,
            MountAction.project_id == project_id,
            MountAction.operation == operation,
            MountAction.idempotency_key == key,
        )
    )
    if old:
        if old.request_sha256 != fingerprint:
            fail("IDEMPOTENCY_CONFLICT", "相同操作标识不能用于不同请求。")
        return old, True
    row = MountAction(
        id=uuid4(),
        actor_id=actor_id,
        project_id=project_id,
        operation=operation,
        idempotency_key=key,
        request_sha256=fingerprint,
        response={},
        created_at=now(),
    )
    db.add(row)
    return row, False


@router.get("", response_model=MountList)
def list_mounts(
    project_id: UUID,
    actor: CurrentActor,
    cursor: str | None = Query(None, max_length=512),
    page_size: int = Query(50, ge=1, le=100),
):
    with transaction(actor.id) as db:
        project_row = project(db, actor.id, project_id)
        filters = {"project_id": str(project_id), "kind": "mounts"}
        cursor_id = read_cursor(cursor, filters)
        query = select(SourceMount).where(SourceMount.project_id == project_id)
        if cursor_id:
            try:
                query = query.where(SourceMount.id > UUID(cursor_id))
            except ValueError:
                fail("INVALID_CURSOR", "分页游标无效。", 422)
        rows = list(db.scalars(query.order_by(SourceMount.id).limit(page_size + 1)))
        # Stable source lock order avoids two projects listing multiple sources in reverse order.
        source_ids = sorted(
            {
                release_for(db, row.source_snapshot_id).source_id
                for row in rows[:page_size]
            }
        )
        for source_id in source_ids:
            releases.source(db, source_id)
        return {
            "items": [view(db, actor.id, project_row, row) for row in rows[:page_size]],
            "total": db.scalar(
                select(func.count())
                .select_from(SourceMount)
                .where(SourceMount.project_id == project_id)
            ),
            "next_cursor": make_cursor(str(rows[page_size - 1].id), filters)
            if len(rows) > page_size
            else None,
            "allowed_actions": {
                "create": project_role(db, actor.id, project_row) in {"owner", "editor"}
            },
        }


@router.post("", status_code=201, response_model=MountActionView)
def create(
    project_id: UUID,
    body: MountInput,
    actor: CurrentActor,
    idempotency_key: str = Header(),
):
    with transaction(actor.id) as db:
        project_row = project(db, actor.id, project_id, write=True)
        release = release_for(db, body.source_snapshot_id)
        releases.require_available(db, release)
        ledger, old = action(
            db,
            actor.id,
            project_id,
            "mounts.create",
            idempotency_key,
            {"source_snapshot_id": str(body.source_snapshot_id)},
        )
        if old:
            mount = load(db, project_id, UUID(ledger.response["mount"]["id"]))
            if mount.removed_at:
                fail("MOUNT_REMOVED", "已移除的挂载不能通过重放恢复。", 403)
            return {**ledger.response, "mount": view(db, actor.id, project_row, mount)}
        mount = db.scalar(
            select(SourceMount).where(
                SourceMount.project_id == project_id,
                SourceMount.source_snapshot_id == body.source_snapshot_id,
                SourceMount.removed_at.is_(None),
            )
        )
        existing = mount is not None
        if not mount:
            mount = SourceMount(
                id=uuid4(),
                project_id=project_id,
                source_snapshot_id=body.source_snapshot_id,
                created_by=actor.id,
                created_at=now(),
            )
            db.add(mount)
            db.flush()
        ledger.response = {
            "action_id": str(ledger.id),
            "existing": existing,
            "mount": view(db, actor.id, project_row, mount),
        }
        return ledger.response


@router.get("/{mount_id}", response_model=MountView)
def get_mount(project_id: UUID, mount_id: UUID, actor: CurrentActor):
    with transaction(actor.id) as db:
        project_row = project(db, actor.id, project_id)
        return view(db, actor.id, project_row, load(db, project_id, mount_id))


@router.post("/{mount_id}/remove", response_model=MountActionView)
def remove(
    project_id: UUID,
    mount_id: UUID,
    body: EmptyBody,
    actor: CurrentActor,
    idempotency_key: str = Header(),
):
    with transaction(actor.id) as db:
        project_row = project(db, actor.id, project_id, write=True)
        mount = load(db, project_id, mount_id)
        ledger, old = action(
            db,
            actor.id,
            project_id,
            "mounts.remove",
            idempotency_key,
            {"mount_id": str(mount_id)},
        )
        if old:
            # Do not return a historical permitted read flag after later policy withdrawal.
            return {
                "action_id": str(ledger.id),
                "existing": False,
                "mount": view(db, actor.id, project_row, mount),
            }
        if not mount.removed_at:
            mount.removed_at = now()
        ledger.response = {
            "action_id": str(ledger.id),
            "existing": False,
            "mount": view(db, actor.id, project_row, mount),
        }
        return ledger.response


@router.get("/{mount_id}/manifest", response_model=MountManifest)
def manifest(project_id: UUID, mount_id: UUID, actor: CurrentActor):
    with transaction(actor.id) as db:
        _, mount, release, index = resolve_mount(db, actor.id, project_id, mount_id)
        parsed = releases.verified_manifest(index)
        return {
            "mount_id": str(mount.id),
            "source_snapshot_id": str(release.source_snapshot_id),
            "manifest_sha256": release.manifest_sha256,
            "manifest": parsed,
        }


def check_manifest_dependencies(db, actor_id, project_id, mount_ids):
    """Acquire the project's source locks in one stable order before context reuse."""
    project(db, actor_id, project_id)
    mounts = [load(db, project_id, UUID(ident)) for ident in sorted(set(mount_ids))]
    sources = {release_for(db, item.source_snapshot_id).source_id for item in mounts}
    for source_id in sorted(sources):
        releases.source(db, source_id)
    for mount in mounts:
        resolve_mount(db, actor_id, project_id, mount.id)
