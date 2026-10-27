"""Private upload and execution ledger. PostgreSQL is the state authority."""

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    BigInteger,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from services.api.db import Base


class Upload(Base):
    __tablename__ = "upload_sessions"
    __table_args__ = (UniqueConstraint("id", "project_id"),)
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    project_id: Mapped[UUID] = mapped_column(ForeignKey("app.projects.id"))
    actor_id: Mapped[UUID] = mapped_column(ForeignKey("app.users.id"))
    filename: Mapped[str] = mapped_column(String(255))
    media_type: Mapped[str] = mapped_column(String(100))
    expected_size: Mapped[int] = mapped_column(BigInteger)
    expected_sha256: Mapped[str] = mapped_column(String(64))
    object_key: Mapped[str] = mapped_column(String(255), unique=True)
    version_id: Mapped[str | None] = mapped_column(String(255))
    etag: Mapped[str | None] = mapped_column(String(255))
    state: Mapped[str] = mapped_column(String(30))
    error_code: Mapped[str | None] = mapped_column(String(80))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class Job(Base):
    __tablename__ = "jobs"
    __table_args__ = (
        UniqueConstraint("id", "project_id"),
        ForeignKeyConstraint(
            ["upload_id", "project_id"],
            ["app.upload_sessions.id", "app.upload_sessions.project_id"],
        ),
        ForeignKeyConstraint(
            ["action_id", "project_id"],
            ["app.job_actions.id", "app.job_actions.project_id"],
        ),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    project_id: Mapped[UUID] = mapped_column(ForeignKey("app.projects.id"))
    actor_id: Mapped[UUID] = mapped_column(ForeignKey("app.users.id"))
    action_id: Mapped[UUID] = mapped_column()
    upload_id: Mapped[UUID | None] = mapped_column()
    input: Mapped[dict] = mapped_column(JSONB, default=dict)
    input_sha256: Mapped[str | None] = mapped_column(String(64))
    stage: Mapped[str | None] = mapped_column(String(30))
    progress: Mapped[dict | None] = mapped_column(JSONB(none_as_null=True))
    reserved_bytes: Mapped[int] = mapped_column(BigInteger, default=0)
    kind: Mapped[str] = mapped_column(String(40), default="UPLOAD_VALIDATE")
    state: Mapped[str] = mapped_column(String(30))
    attempt: Mapped[int] = mapped_column(Integer)
    lease_epoch: Mapped[int] = mapped_column(Integer, default=0)
    lease_token: Mapped[UUID | None] = mapped_column()
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    processed_bytes: Mapped[int] = mapped_column(BigInteger, default=0)
    total_bytes: Mapped[int] = mapped_column(BigInteger)
    error: Mapped[dict | None] = mapped_column(JSONB(none_as_null=True))
    result: Mapped[dict | None] = mapped_column(JSONB(none_as_null=True))
    event_sequence: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class Attempt(Base):
    __tablename__ = "job_attempts"
    __table_args__ = (
        ForeignKeyConstraint(
            ["job_id", "project_id"], ["app.jobs.id", "app.jobs.project_id"]
        ),
    )
    job_id: Mapped[UUID] = mapped_column(primary_key=True)
    number: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[UUID] = mapped_column()
    state: Mapped[str] = mapped_column(String(30))
    lease_epoch: Mapped[int] = mapped_column(Integer, default=0)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error: Mapped[dict | None] = mapped_column(JSONB(none_as_null=True))


class JobEvent(Base):
    __tablename__ = "job_events"
    __table_args__ = (
        UniqueConstraint("job_id", "sequence"),
        ForeignKeyConstraint(
            ["job_id", "project_id"], ["app.jobs.id", "app.jobs.project_id"]
        ),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    project_id: Mapped[UUID] = mapped_column()
    job_id: Mapped[UUID] = mapped_column()
    sequence: Mapped[int] = mapped_column(Integer)
    kind: Mapped[str] = mapped_column(String(50))
    state: Mapped[str] = mapped_column(String(30))
    attempt: Mapped[int] = mapped_column(Integer)
    payload: Mapped[dict] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class Action(Base):
    __tablename__ = "job_actions"
    __table_args__ = (
        UniqueConstraint("project_id", "actor_id", "operation", "idempotency_key"),
        UniqueConstraint("id", "project_id"),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    actor_id: Mapped[UUID] = mapped_column(ForeignKey("app.users.id"))
    project_id: Mapped[UUID] = mapped_column(ForeignKey("app.projects.id"))
    idempotency_key: Mapped[str] = mapped_column(String(128))
    operation: Mapped[str] = mapped_column(String(60))
    request_sha256: Mapped[str] = mapped_column(String(64))
    response: Mapped[dict] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class Outbox(Base):
    __tablename__ = "job_outbox"
    __table_args__ = (
        UniqueConstraint("job_id", "attempt"),
        ForeignKeyConstraint(
            ["job_id", "project_id"], ["app.jobs.id", "app.jobs.project_id"]
        ),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    project_id: Mapped[UUID] = mapped_column()
    job_id: Mapped[UUID] = mapped_column()
    attempt: Mapped[int] = mapped_column(Integer)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    failures: Mapped[int] = mapped_column(Integer, default=0)
    last_error: Mapped[str | None] = mapped_column(String(80))
    next_attempt_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
