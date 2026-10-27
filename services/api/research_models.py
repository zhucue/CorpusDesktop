"""Fixed research membership and bounded durable query control records."""

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import BigInteger, DateTime, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from services.api.db import Base


class Snapshot(Base):
    __tablename__ = "research_snapshots"
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    project_id: Mapped[UUID] = mapped_column(ForeignKey("app.projects.id"))
    created_by: Mapped[UUID] = mapped_column(ForeignKey("app.users.id"))
    name: Mapped[str] = mapped_column(String(160))
    state: Mapped[str] = mapped_column(String(20))
    index_result: Mapped[dict | None] = mapped_column(JSONB(none_as_null=True))
    reserved_bytes: Mapped[int] = mapped_column(BigInteger, default=0)
    manifest: Mapped[dict] = mapped_column(JSONB)
    manifest_sha256: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class SnapshotMember(Base):
    __tablename__ = "research_snapshot_members"
    snapshot_id: Mapped[UUID] = mapped_column(
        ForeignKey("app.research_snapshots.id"), primary_key=True
    )
    ordinal: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[UUID] = mapped_column(ForeignKey("app.projects.id"))
    kind: Mapped[str] = mapped_column(String(30))
    material_revision_id: Mapped[UUID | None] = mapped_column()
    mount_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("app.project_source_mounts.id")
    )
    descriptor: Mapped[dict] = mapped_column(JSONB)


class QueryRun(Base):
    __tablename__ = "query_runs"
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    project_id: Mapped[UUID] = mapped_column(ForeignKey("app.projects.id"))
    snapshot_id: Mapped[UUID] = mapped_column(ForeignKey("app.research_snapshots.id"))
    actor_id: Mapped[UUID] = mapped_column(ForeignKey("app.users.id"))
    result_set_id: Mapped[UUID] = mapped_column(unique=True)
    name: Mapped[str] = mapped_column(String(160))
    query: Mapped[dict] = mapped_column(JSONB)
    query_sha256: Mapped[str] = mapped_column(String(64))
    page_size: Mapped[int] = mapped_column(Integer)
    context_codepoints: Mapped[int] = mapped_column(Integer)
    state: Mapped[str] = mapped_column(String(20))
    attempt: Mapped[int] = mapped_column(Integer)
    first_page: Mapped[dict | None] = mapped_column(JSONB(none_as_null=True))
    counts: Mapped[dict | None] = mapped_column(JSONB(none_as_null=True))
    result_object: Mapped[dict | None] = mapped_column(JSONB(none_as_null=True))
    reserved_bytes: Mapped[int] = mapped_column(BigInteger)
    error: Mapped[dict | None] = mapped_column(JSONB(none_as_null=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class ResearchTask(Base):
    __tablename__ = "research_tasks"
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    project_id: Mapped[UUID] = mapped_column(ForeignKey("app.projects.id"))
    snapshot_id: Mapped[UUID] = mapped_column(ForeignKey("app.research_snapshots.id"))
    run_id: Mapped[UUID | None] = mapped_column(ForeignKey("app.query_runs.id"))
    actor_id: Mapped[UUID] = mapped_column(ForeignKey("app.users.id"))
    phase: Mapped[str] = mapped_column(String(20))
    state: Mapped[str] = mapped_column(String(20))
    attempt: Mapped[int] = mapped_column(Integer)
    lease_epoch: Mapped[int] = mapped_column(Integer)
    lease_token: Mapped[UUID | None] = mapped_column()
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    progress: Mapped[dict] = mapped_column(JSONB)
    error: Mapped[dict | None] = mapped_column(JSONB(none_as_null=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class ResearchOutbox(Base):
    __tablename__ = "research_outbox"
    task_id: Mapped[UUID] = mapped_column(
        ForeignKey("app.research_tasks.id"), primary_key=True
    )
    attempt: Mapped[int] = mapped_column(Integer, primary_key=True)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    failures: Mapped[int] = mapped_column(Integer, default=0)
    next_attempt_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class ResearchEvent(Base):
    __tablename__ = "research_events"
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    task_id: Mapped[UUID] = mapped_column(ForeignKey("app.research_tasks.id"))
    attempt: Mapped[int] = mapped_column(Integer)
    kind: Mapped[str] = mapped_column(String(40))
    data: Mapped[dict] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class ResearchAction(Base):
    __tablename__ = "research_actions"
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    project_id: Mapped[UUID] = mapped_column(ForeignKey("app.projects.id"))
    actor_id: Mapped[UUID] = mapped_column(ForeignKey("app.users.id"))
    operation: Mapped[str] = mapped_column(String(40))
    idempotency_key: Mapped[str] = mapped_column(String(128))
    request_sha256: Mapped[str] = mapped_column(String(64))
    response: Mapped[dict] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
