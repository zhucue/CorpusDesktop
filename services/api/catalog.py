"""Authenticated source discovery and administrator metadata maintenance."""

import base64
import hashlib
import json
from datetime import UTC, datetime
from typing import Annotated
from uuid import uuid4

from fastapi import APIRouter, Header, Path, Query
from sqlalchemy import func, or_, select, text

from contracts.catalog import (
    SOURCE_ID_PATTERN,
    Capability,
    CatalogCreate,
    CatalogMetadata,
    CatalogUpdate,
    CatalogWriteView,
    IntegrationStatus,
    SourceList,
    SourceVersionList,
    SourceVersionView,
    SourceView,
)
from services.api.auth import CurrentActor
from services.api.catalog_models import CatalogAction, CatalogRelease, CatalogSource
from services.api.db import lock_actor, transaction
from services.api.errors import ApiError
from services.api.models import User

router = APIRouter(prefix="/api/v1", tags=["source catalog"])
SourceId = Annotated[str, Path(pattern=SOURCE_ID_PATTERN)]
IdempotencyKey = Annotated[
    str,
    Header(
        alias="Idempotency-Key",
        min_length=1,
        max_length=128,
        pattern=r"^[A-Za-z0-9._:-]+$",
    ),
]


def digest(value):
    return hashlib.sha256(
        json.dumps(
            value, sort_keys=True, ensure_ascii=False, separators=(",", ":")
        ).encode()
    ).hexdigest()


def make_cursor(last, filters):
    return base64.urlsafe_b64encode(
        json.dumps([last, digest(filters)]).encode()
    ).decode()


def read_cursor(value, filters):
    if value is None:
        return None
    try:
        last, signature = json.loads(
            base64.b64decode(value, altchars=b"-_", validate=True)
        )
        if not isinstance(last, str) or len(last) > 64 or signature != digest(filters):
            raise ValueError
        return last
    except (ValueError, TypeError, UnicodeError):
        raise ApiError(
            422, "INVALID_CURSOR", "Cursor does not match this listing"
        ) from None


def view_source(row):
    return SourceView(
        **row.metadata_json,
        source_id=row.source_id,
        integration_status=row.integration_status,
        evidence_refs=row.evidence_refs,
        revision=row.revision,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def get_row(session, source_id):
    row = session.get(CatalogSource, source_id)
    if row is None:
        raise ApiError(404, "SOURCE_NOT_FOUND", "Source not found")
    return row


@router.get("/sources", response_model=SourceList)
def list_sources(
    actor: CurrentActor,
    q: str | None = Query(None, max_length=160),
    language: str | None = Query(None, max_length=48),
    category: str | None = Query(None, max_length=48),
    status: IntegrationStatus | None = None,
    capability: Capability | None = None,
    cursor: str | None = Query(None, max_length=512),
    page_size: int = Query(50, ge=1, le=100),
):
    filters = {
        "q": q,
        "language": language,
        "category": category,
        "status": status,
        "capability": capability,
    }
    last = read_cursor(cursor, filters)
    clauses = []
    if q:
        clauses.append(
            or_(
                CatalogSource.source_id.icontains(q, autoescape=True),
                CatalogSource.metadata_json["name"].astext.icontains(
                    q, autoescape=True
                ),
                CatalogSource.metadata_json["publisher"].astext.icontains(
                    q, autoescape=True
                ),
            )
        )
    for field, value in (("languages", language), ("categories", category)):
        if value:
            clauses.append(CatalogSource.metadata_json[field].contains([value]))
    if status:
        clauses.append(CatalogSource.integration_status == status)
    # Production capabilities are unavailable; planned access routes are not permissions.
    if capability and capability != "discover":
        clauses.append(text("false"))
    with transaction(actor.id) as session:
        total = session.scalar(
            select(func.count()).select_from(CatalogSource).where(*clauses)
        )
        query = select(CatalogSource).where(*clauses)
        if last:
            query = query.where(CatalogSource.source_id > last)
        rows = list(
            session.scalars(
                query.order_by(CatalogSource.source_id).limit(page_size + 1)
            )
        )
        next_cursor = (
            make_cursor(rows[page_size - 1].source_id, filters)
            if len(rows) > page_size
            else None
        )
        return SourceList(
            items=[view_source(r) for r in rows[:page_size]],
            total=total,
            next_cursor=next_cursor,
        )


@router.get("/sources/{source_id}", response_model=SourceView)
def get_source(source_id: SourceId, actor: CurrentActor):
    with transaction(actor.id) as session:
        return view_source(get_row(session, source_id))


@router.get("/sources/{source_id}/versions", response_model=SourceVersionList)
def source_versions(
    source_id: SourceId,
    actor: CurrentActor,
    cursor: str | None = Query(None, max_length=512),
    page_size: int = Query(50, ge=1, le=100),
):
    from uuid import UUID

    last = read_cursor(cursor, {"source_id": source_id, "kind": "published_versions"})
    try:
        last_id = UUID(last) if last else None
    except ValueError:
        raise ApiError(422, "INVALID_CURSOR", "Invalid version cursor") from None
    with transaction(actor.id) as session:
        from services.api.source_releases import source, view_release

        source_row = source(session, source_id)
        clause = CatalogRelease.source_id == source_id
        total = session.scalar(
            select(func.count()).select_from(CatalogRelease).where(clause)
        )
        query = select(CatalogRelease).where(clause)
        if last_id:
            query = query.where(CatalogRelease.release_id > last_id)
        rows = list(
            session.scalars(
                query.order_by(CatalogRelease.release_id).limit(page_size + 1)
            )
        )
        next_cursor = (
            make_cursor(
                str(rows[page_size - 1].release_id),
                {"source_id": source_id, "kind": "published_versions"},
            )
            if len(rows) > page_size
            else None
        )
        return SourceVersionList(
            items=[
                SourceVersionView.model_validate(view_release(session, r, source_row))
                for r in rows[:page_size]
            ],
            total=total,
            next_cursor=next_cursor,
        )


def require_admin(session, actor):
    lock_actor(session, actor.id)
    user = session.scalar(
        select(User)
        .where(User.id == actor.id)
        .execution_options(populate_existing=True)
    )
    if not user or not user.is_active or not user.is_platform_admin:
        raise ApiError(
            403, "ADMIN_REQUIRED", "Current platform administrator role required"
        )


def write_catalog(actor, operation, source_id, body, key):
    request_hash = digest(
        {"source_id": source_id, "body": body.model_dump(mode="json")}
    )
    with transaction(actor.id) as session:
        require_admin(
            session, actor
        )  # Re-check before even returning an idempotent response.
        prior = session.scalar(
            select(CatalogAction).where(
                CatalogAction.actor_id == actor.id,
                CatalogAction.operation == operation,
                CatalogAction.idempotency_key == key,
            )
        )
        if prior:
            if prior.request_sha256 != request_hash:
                raise ApiError(
                    409,
                    "IDEMPOTENCY_CONFLICT",
                    "Idempotency key used with different input",
                )
            return CatalogWriteView.model_validate(prior.response)
        # Source lock serializes creation across administrators as well as revision checks.
        session.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:key,0))"),
            {"key": "catalog:" + source_id},
        )
        row = session.scalar(
            select(CatalogSource)
            .where(CatalogSource.source_id == source_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        now = datetime.now(UTC)
        metadata = CatalogMetadata.model_validate(
            body.model_dump(exclude={"source_id", "expected_revision"})
        ).model_dump()
        if operation == "catalog.create":
            if row:
                raise ApiError(
                    409, "SOURCE_EXISTS", "Source identifier already registered"
                )
            row = CatalogSource(
                source_id=source_id,
                metadata_json=metadata,
                revision=1,
                integration_status="catalog_only",
                evidence_refs=[],
                created_at=now,
                updated_at=now,
            )
            session.add(row)
        else:
            if row is None:
                raise ApiError(404, "SOURCE_NOT_FOUND", "Source not found")
            if row.revision != body.expected_revision:
                raise ApiError(
                    409, "REVISION_CONFLICT", "Source changed; reload before editing"
                )
            if any(
                row.metadata_json[field] != metadata[field]
                for field in ("name", "publisher", "official_url", "entry_kind")
            ):
                # Existing experiments belong to the old identity, never a renamed replacement.
                row.evidence_refs, row.integration_status = [], "catalog_only"
                row.identity_revision += 1
            row.metadata_json, row.revision, row.updated_at = (
                metadata,
                row.revision + 1,
                now,
            )
        action_id = uuid4()
        response = CatalogWriteView(
            **view_source(row).model_dump(), action_id=action_id
        )
        session.add(
            CatalogAction(
                id=action_id,
                actor_id=actor.id,
                operation=operation,
                idempotency_key=key,
                request_sha256=request_hash,
                response=response.model_dump(mode="json"),
                created_at=now,
            )
        )
        session.flush()
        return response


@router.post("/admin/catalog", response_model=CatalogWriteView, status_code=201)
def create_catalog(body: CatalogCreate, actor: CurrentActor, key: IdempotencyKey):
    return write_catalog(actor, "catalog.create", body.source_id, body, key)


@router.patch("/admin/catalog/{source_id}", response_model=CatalogWriteView)
def update_catalog(
    source_id: SourceId, body: CatalogUpdate, actor: CurrentActor, key: IdempotencyKey
):
    return write_catalog(actor, "catalog.update", source_id, body, key)
