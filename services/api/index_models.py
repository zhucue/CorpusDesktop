"""Platform index builds and immutable private index artifacts."""

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import BigInteger, DateTime, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from services.api.db import Base


class IndexRun(Base):
    __tablename__ = "index_build_runs"
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    source_id: Mapped[str] = mapped_column(ForeignKey("app.catalog_sources.source_id"))
    acquisition_id: Mapped[UUID] = mapped_column(
        ForeignKey("app.source_acquisitions.id")
    )
    actor_id: Mapped[UUID] = mapped_column(ForeignKey("app.users.id"))
    source_identity: Mapped[dict] = mapped_column(JSONB)
    recipe: Mapped[dict] = mapped_column(JSONB)
    recipe_sha256: Mapped[str] = mapped_column(String(64))
    state: Mapped[str] = mapped_column(String(20))
    stage: Mapped[str] = mapped_column(String(20))
    attempt: Mapped[int] = mapped_column(Integer)
    lease_epoch: Mapped[int] = mapped_column(Integer, default=0)
    lease_token: Mapped[UUID | None] = mapped_column()
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    reserved_bytes: Mapped[int] = mapped_column(BigInteger)
    progress: Mapped[dict] = mapped_column(JSONB)
    result: Mapped[dict | None] = mapped_column(JSONB(none_as_null=True))
    error: Mapped[dict | None] = mapped_column(JSONB(none_as_null=True))
    event_sequence: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class IndexAction(Base):
    __tablename__ = "index_build_actions"
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    actor_id: Mapped[UUID] = mapped_column(ForeignKey("app.users.id"))
    operation: Mapped[str] = mapped_column(String(30))
    idempotency_key: Mapped[str] = mapped_column(String(128))
    request_sha256: Mapped[str] = mapped_column(String(64))
    response: Mapped[dict] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class IndexAttempt(Base):
    __tablename__ = "index_build_attempts"
    run_id: Mapped[UUID] = mapped_column(
        ForeignKey("app.index_build_runs.id"), primary_key=True
    )
    number: Mapped[int] = mapped_column(Integer, primary_key=True)
    state: Mapped[str] = mapped_column(String(20))
    lease_epoch: Mapped[int] = mapped_column(Integer, default=0)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error: Mapped[dict | None] = mapped_column(JSONB(none_as_null=True))


class IndexEvent(Base):
    __tablename__ = "index_build_events"
    run_id: Mapped[UUID] = mapped_column(
        ForeignKey("app.index_build_runs.id"), primary_key=True
    )
    sequence: Mapped[int] = mapped_column(Integer, primary_key=True)
    event_type: Mapped[str] = mapped_column(String(50))
    data: Mapped[dict] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class IndexOutbox(Base):
    __tablename__ = "index_build_outbox"
    run_id: Mapped[UUID] = mapped_column(
        ForeignKey("app.index_build_runs.id"), primary_key=True
    )
    attempt: Mapped[int] = mapped_column(Integer, primary_key=True)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    failures: Mapped[int] = mapped_column(Integer, default=0)
    last_error: Mapped[str | None] = mapped_column(String(80))
    next_attempt_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class SourceIndex(Base):
    __tablename__ = "source_indexes"
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    run_id: Mapped[UUID] = mapped_column(
        ForeignKey("app.index_build_runs.id"), unique=True
    )
    acquisition_id: Mapped[UUID] = mapped_column(
        ForeignKey("app.source_acquisitions.id")
    )
    source_id: Mapped[str] = mapped_column(ForeignKey("app.catalog_sources.source_id"))
    recipe_sha256: Mapped[str] = mapped_column(String(64))
    identity_sha256: Mapped[str] = mapped_column(String(64))
    manifest_sha256: Mapped[str] = mapped_column(String(64))
    manifest: Mapped[dict] = mapped_column(JSONB)
    objects: Mapped[list] = mapped_column(JSONB)
    artifact_bytes: Mapped[int] = mapped_column(BigInteger)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
