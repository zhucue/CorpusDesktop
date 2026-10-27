import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Identity,
    Index,
    Integer,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

ROLES = ("owner", "editor", "annotator", "viewer")
CORPUS_STATUSES = ("empty", "importing", "indexing", "ready", "stale", "failed")
JOB_KINDS = ("import", "index", "export")
JOB_STATES = ("queued", "running", "succeeded", "failed", "cancelled")


def _in(column, values):
    return f"{column} IN ({', '.join(repr(v) for v in values)})"


class Base(DeclarativeBase):
    pass


def _id():
    return mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)


def _created():
    return mapped_column(DateTime(timezone=True), server_default=func.now())


class User(Base):
    __tablename__ = "users"
    id: Mapped[uuid.UUID] = _id()
    email: Mapped[str] = mapped_column(Text, unique=True)
    display_name: Mapped[str] = mapped_column(Text)
    password_hash: Mapped[str] = mapped_column(Text)
    is_admin: Mapped[bool] = mapped_column(Boolean, server_default="false")
    created_at: Mapped[datetime] = _created()


class LoginSession(Base):
    __tablename__ = "login_sessions"
    token_hash: Mapped[str] = mapped_column(Text, primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    created_at: Mapped[datetime] = _created()
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class Project(Base):
    __tablename__ = "projects"
    id: Mapped[uuid.UUID] = _id()
    name: Mapped[str] = mapped_column(Text)
    created_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = _created()


class ProjectMember(Base):
    __tablename__ = "project_members"
    __table_args__ = (CheckConstraint(_in("role", ROLES), name="ck_member_role"),)
    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), primary_key=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True, index=True
    )
    role: Mapped[str] = mapped_column(Text)


class Corpus(Base):
    __tablename__ = "corpora"
    __table_args__ = (
        CheckConstraint(_in("status", CORPUS_STATUSES), name="ck_corpus_status"),
    )
    id: Mapped[uuid.UUID] = _id()
    project_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(Text)
    language: Mapped[str] = mapped_column(Text)
    description: Mapped[str] = mapped_column(Text, server_default="")
    parallel: Mapped[bool] = mapped_column(Boolean, server_default="false")
    status: Mapped[str] = mapped_column(Text, server_default="empty")
    error: Mapped[str | None] = mapped_column(Text)
    stats: Mapped[dict] = mapped_column(
        JSONB, server_default='{"documents": 0, "sentences": 0, "tokens": 0}'
    )
    index_version: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = _created()


class Document(Base):
    __tablename__ = "documents"
    id: Mapped[uuid.UUID] = _id()
    corpus_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("corpora.id", ondelete="CASCADE"), index=True
    )
    title: Mapped[str] = mapped_column(Text)
    language: Mapped[str] = mapped_column(Text)
    meta: Mapped[dict] = mapped_column("metadata", JSONB, server_default="{}")
    external_id: Mapped[str | None] = mapped_column(Text)
    text_path: Mapped[str] = mapped_column(Text)
    char_count: Mapped[int] = mapped_column(Integer)
    sentence_count: Mapped[int] = mapped_column(Integer)
    token_count: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = _created()


class Sentence(Base):
    __tablename__ = "sentences"
    __table_args__ = (UniqueConstraint("document_id", "idx"),)
    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    document_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE")
    )
    idx: Mapped[int] = mapped_column(Integer)
    start_cp: Mapped[int] = mapped_column(Integer)
    end_cp: Mapped[int] = mapped_column(Integer)
    text: Mapped[str] = mapped_column(Text)


class Token(Base):
    __tablename__ = "tokens"
    __table_args__ = (UniqueConstraint("sentence_id", "idx"),)
    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    sentence_id: Mapped[int] = mapped_column(
        ForeignKey("sentences.id", ondelete="CASCADE")
    )
    idx: Mapped[int] = mapped_column(Integer)
    start_cp: Mapped[int] = mapped_column(Integer)
    end_cp: Mapped[int] = mapped_column(Integer)
    form: Mapped[str] = mapped_column(Text)
    pos: Mapped[str | None] = mapped_column(Text)
    lemma: Mapped[str | None] = mapped_column(Text)
    head: Mapped[int | None] = mapped_column(Integer)
    deprel: Mapped[str | None] = mapped_column(Text)


class SentenceAlignment(Base):
    __tablename__ = "sentence_alignments"
    src_sentence_id: Mapped[int] = mapped_column(
        ForeignKey("sentences.id", ondelete="CASCADE"), primary_key=True
    )
    tgt_sentence_id: Mapped[int] = mapped_column(
        ForeignKey("sentences.id", ondelete="CASCADE"), primary_key=True, index=True
    )


class Subcorpus(Base):
    __tablename__ = "subcorpora"
    id: Mapped[uuid.UUID] = _id()
    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    corpus_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("corpora.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(Text)
    filter: Mapped[dict] = mapped_column(JSONB)
    created_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = _created()


class SavedQuery(Base):
    __tablename__ = "saved_queries"
    id: Mapped[uuid.UUID] = _id()
    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(Text)
    query: Mapped[str] = mapped_column(Text)
    scope: Mapped[dict] = mapped_column(JSONB)
    created_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = _created()


class Job(Base):
    __tablename__ = "jobs"
    __table_args__ = (
        CheckConstraint(_in("kind", JOB_KINDS), name="ck_job_kind"),
        CheckConstraint(_in("state", JOB_STATES), name="ck_job_state"),
        Index("ix_jobs_state_created", "state", "created_at"),
    )
    id: Mapped[uuid.UUID] = _id()
    project_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    owner_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE")
    )
    kind: Mapped[str] = mapped_column(Text)
    params: Mapped[dict] = mapped_column(JSONB)
    state: Mapped[str] = mapped_column(Text, server_default="queued")
    progress: Mapped[dict] = mapped_column(
        JSONB, server_default='{"done": 0, "total": null, "message": ""}'
    )
    result: Mapped[dict | None] = mapped_column(JSONB)
    error: Mapped[dict | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.clock_timestamp()
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
