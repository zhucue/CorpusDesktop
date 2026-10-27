"""Shared catalog persistence, isolated from private project materials."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from services.api.db import Base


class CatalogSource(Base):
    __tablename__ = "catalog_sources"
    source_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    metadata_json: Mapped[dict] = mapped_column(JSONB)
    integration_status: Mapped[str] = mapped_column(String(30))
    evidence_refs: Mapped[list] = mapped_column(JSONB)
    revision: Mapped[int] = mapped_column(Integer)
    identity_revision: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class CatalogAction(Base):
    __tablename__ = "catalog_actions"
    id: Mapped[UUID] = mapped_column(primary_key=True)
    actor_id: Mapped[UUID] = mapped_column(ForeignKey("app.users.id"))
    operation: Mapped[str] = mapped_column(String(30))
    idempotency_key: Mapped[str] = mapped_column(String(128))
    request_sha256: Mapped[str] = mapped_column(String(64))
    response: Mapped[dict] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class CatalogRelease(Base):
    __tablename__ = "catalog_releases"
    release_id: Mapped[UUID] = mapped_column(primary_key=True)
    source_id: Mapped[str] = mapped_column(ForeignKey("app.catalog_sources.source_id"))
    version: Mapped[str] = mapped_column(String(200))
    published_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    manifest_sha256: Mapped[str] = mapped_column(String(64))
    source_snapshot_id: Mapped[UUID] = mapped_column(unique=True)
    index_id: Mapped[UUID] = mapped_column(
        ForeignKey("app.source_indexes.id"), unique=True
    )
    acquisition_id: Mapped[UUID] = mapped_column(
        ForeignKey("app.source_acquisitions.id")
    )
    policy_id: Mapped[UUID] = mapped_column(ForeignKey("app.source_policies.id"))
    policy_revision: Mapped[int] = mapped_column(Integer)
    source_identity_revision: Mapped[int] = mapped_column(Integer)
    index_identity_sha256: Mapped[str] = mapped_column(String(64))
    recipe: Mapped[dict] = mapped_column(JSONB)
    counts: Mapped[dict] = mapped_column(JSONB)
    quality: Mapped[dict] = mapped_column(JSONB)
