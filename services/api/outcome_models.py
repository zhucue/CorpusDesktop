"""Immutable evidence and note revisions; exports use the existing job ledger."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import DateTime, Integer, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from services.api.db import Base


class Evidence(Base):
    __tablename__ = "research_evidence"
    id: Mapped[UUID] = mapped_column(primary_key=True)
    project_id: Mapped[UUID] = mapped_column()
    created_by: Mapped[UUID] = mapped_column()
    query_run_id: Mapped[UUID] = mapped_column()
    result_set_id: Mapped[UUID] = mapped_column()
    snapshot_id: Mapped[UUID] = mapped_column()
    ordinal: Mapped[int] = mapped_column(Integer)
    coordinates: Mapped[dict] = mapped_column(JSONB)
    method: Mapped[dict] = mapped_column(JSONB)
    context_sha256: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class Note(Base):
    __tablename__ = "research_notes"
    id: Mapped[UUID] = mapped_column(primary_key=True)
    project_id: Mapped[UUID] = mapped_column()
    created_by: Mapped[UUID] = mapped_column()
    current_revision: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class NoteRevision(Base):
    __tablename__ = "note_revisions"
    note_id: Mapped[UUID] = mapped_column(primary_key=True)
    revision: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[UUID] = mapped_column()
    created_by: Mapped[UUID] = mapped_column()
    title: Mapped[str] = mapped_column(String(200))
    body: Mapped[str] = mapped_column(String(200000))
    evidence_ids: Mapped[list] = mapped_column(JSONB)
    query_run_ids: Mapped[list] = mapped_column(JSONB)
    authorization_evidence_ids: Mapped[list] = mapped_column(JSONB)
    authorization_query_run_ids: Mapped[list] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class NoteAcceptance(Base):
    __tablename__ = "note_acceptances"
    note_id: Mapped[UUID] = mapped_column(primary_key=True)
    revision: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[UUID] = mapped_column()
    accepted_by: Mapped[UUID] = mapped_column()
    session_hash: Mapped[str] = mapped_column(String(64))
    accepted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class ExportRecord(Base):
    __tablename__ = "research_exports"
    id: Mapped[UUID] = mapped_column(primary_key=True)
    project_id: Mapped[UUID] = mapped_column()
    actor_id: Mapped[UUID] = mapped_column()
    target: Mapped[dict] = mapped_column(JSONB)
    format: Mapped[str] = mapped_column(String(8))
    authorization_evidence_ids: Mapped[list] = mapped_column(JSONB)
    authorization_query_run_ids: Mapped[list] = mapped_column(JSONB)
    artifact: Mapped[dict | None] = mapped_column(JSONB(none_as_null=True))
    methods: Mapped[dict | None] = mapped_column(JSONB(none_as_null=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
