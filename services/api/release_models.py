"""Fixed-acquisition permission decisions, immutable releases and project mounts."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from services.api.db import Base


class SourcePolicy(Base):
    __tablename__ = "source_policies"
    id: Mapped[UUID] = mapped_column(primary_key=True)
    source_id: Mapped[str] = mapped_column(ForeignKey("app.catalog_sources.source_id"))
    acquisition_id: Mapped[UUID] = mapped_column(
        ForeignKey("app.source_acquisitions.id")
    )
    revision: Mapped[int] = mapped_column(Integer)
    source_identity_revision: Mapped[int] = mapped_column(Integer)
    source_identity: Mapped[dict] = mapped_column(JSONB)
    acquisition_manifest_sha256: Mapped[str] = mapped_column(String(64))
    license_sha256: Mapped[str] = mapped_column(String(64))
    decision: Mapped[str] = mapped_column(String(10))
    export_decision: Mapped[str] = mapped_column(String(10), default="deny")
    review_note: Mapped[str] = mapped_column(String(4000))
    evidence_urls: Mapped[list] = mapped_column(JSONB)
    reviewed_by: Mapped[UUID] = mapped_column(ForeignKey("app.users.id"))
    reviewed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class PolicyHead(Base):
    __tablename__ = "source_policy_heads"
    acquisition_id: Mapped[UUID] = mapped_column(
        ForeignKey("app.source_acquisitions.id"), primary_key=True
    )
    source_id: Mapped[str] = mapped_column(ForeignKey("app.catalog_sources.source_id"))
    policy_id: Mapped[UUID] = mapped_column(ForeignKey("app.source_policies.id"))
    revision: Mapped[int] = mapped_column(Integer)


class ReleaseHead(Base):
    __tablename__ = "source_release_heads"
    source_id: Mapped[str] = mapped_column(
        ForeignKey("app.catalog_sources.source_id"), primary_key=True
    )
    release_id: Mapped[UUID] = mapped_column(
        ForeignKey("app.catalog_releases.release_id")
    )


class ReleaseAction(Base):
    __tablename__ = "source_release_actions"
    id: Mapped[UUID] = mapped_column(primary_key=True)
    actor_id: Mapped[UUID] = mapped_column(ForeignKey("app.users.id"))
    operation: Mapped[str] = mapped_column(String(30))
    idempotency_key: Mapped[str] = mapped_column(String(128))
    request_sha256: Mapped[str] = mapped_column(String(64))
    response: Mapped[dict] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class SourceMount(Base):
    __tablename__ = "project_source_mounts"
    id: Mapped[UUID] = mapped_column(primary_key=True)
    project_id: Mapped[UUID] = mapped_column(ForeignKey("app.projects.id"))
    source_snapshot_id: Mapped[UUID] = mapped_column(
        ForeignKey("app.catalog_releases.source_snapshot_id")
    )
    created_by: Mapped[UUID] = mapped_column(ForeignKey("app.users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    removed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class MountAction(Base):
    __tablename__ = "mount_actions"
    id: Mapped[UUID] = mapped_column(primary_key=True)
    project_id: Mapped[UUID] = mapped_column(ForeignKey("app.projects.id"))
    actor_id: Mapped[UUID] = mapped_column(ForeignKey("app.users.id"))
    operation: Mapped[str] = mapped_column(String(30))
    idempotency_key: Mapped[str] = mapped_column(String(128))
    request_sha256: Mapped[str] = mapped_column(String(64))
    response: Mapped[dict] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
