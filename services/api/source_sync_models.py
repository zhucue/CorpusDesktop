"""Platform acquisition ledger; deliberately independent of project jobs."""

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import DateTime, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from services.api.db import Base


class SyncRun(Base):
    __tablename__ = "source_sync_runs"
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    source_id: Mapped[str] = mapped_column(ForeignKey("app.catalog_sources.source_id"))
    actor_id: Mapped[UUID] = mapped_column(ForeignKey("app.users.id"))
    connector_id: Mapped[str] = mapped_column(String(80))
    source_revision: Mapped[int] = mapped_column(Integer)
    source_identity: Mapped[dict] = mapped_column(JSONB)
    previous_acquisition_id: Mapped[UUID | None] = mapped_column()
    state: Mapped[str] = mapped_column(String(20))
    stage: Mapped[str] = mapped_column(String(20))
    attempt: Mapped[int] = mapped_column(Integer)
    lease_epoch: Mapped[int] = mapped_column(Integer, default=0)
    lease_token: Mapped[UUID | None] = mapped_column()
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    progress: Mapped[dict] = mapped_column(JSONB)
    expected_inputs: Mapped[dict | None] = mapped_column(JSONB(none_as_null=True))
    result: Mapped[dict | None] = mapped_column(JSONB(none_as_null=True))
    error: Mapped[dict | None] = mapped_column(JSONB(none_as_null=True))
    event_sequence: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class SyncAction(Base):
    __tablename__ = "source_sync_actions"
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    actor_id: Mapped[UUID] = mapped_column(ForeignKey("app.users.id"))
    operation: Mapped[str] = mapped_column(String(30))
    idempotency_key: Mapped[str] = mapped_column(String(128))
    request_sha256: Mapped[str] = mapped_column(String(64))
    response: Mapped[dict] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class SyncAttempt(Base):
    __tablename__ = "source_sync_attempts"
    run_id: Mapped[UUID] = mapped_column(
        ForeignKey("app.source_sync_runs.id"), primary_key=True
    )
    number: Mapped[int] = mapped_column(Integer, primary_key=True)
    state: Mapped[str] = mapped_column(String(20))
    lease_epoch: Mapped[int] = mapped_column(Integer, default=0)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error: Mapped[dict | None] = mapped_column(JSONB(none_as_null=True))


class SyncEvent(Base):
    __tablename__ = "source_sync_events"
    run_id: Mapped[UUID] = mapped_column(
        ForeignKey("app.source_sync_runs.id"), primary_key=True
    )
    sequence: Mapped[int] = mapped_column(Integer, primary_key=True)
    event_type: Mapped[str] = mapped_column(String(50))
    data: Mapped[dict] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class SyncOutbox(Base):
    __tablename__ = "source_sync_outbox"
    run_id: Mapped[UUID] = mapped_column(
        ForeignKey("app.source_sync_runs.id"), primary_key=True
    )
    attempt: Mapped[int] = mapped_column(Integer, primary_key=True)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    failures: Mapped[int] = mapped_column(Integer, default=0)
    last_error: Mapped[str | None] = mapped_column(String(80))
    next_attempt_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class Acquisition(Base):
    __tablename__ = "source_acquisitions"
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    run_id: Mapped[UUID] = mapped_column(
        ForeignKey("app.source_sync_runs.id"), unique=True
    )
    source_id: Mapped[str] = mapped_column(ForeignKey("app.catalog_sources.source_id"))
    connector_id: Mapped[str] = mapped_column(String(80))
    source_identity: Mapped[dict] = mapped_column(JSONB)
    manifest_sha256: Mapped[str] = mapped_column(String(64))
    manifest: Mapped[dict] = mapped_column(JSONB)
    objects: Mapped[list] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
