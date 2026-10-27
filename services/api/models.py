import uuid
from datetime import datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Identity,
    Index,
    Integer,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, TSVECTOR, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

ROLES = ("owner", "editor", "annotator", "viewer")
CORPUS_STATUSES = ("empty", "importing", "indexing", "ready", "stale", "failed")
JOB_KINDS = (
    "import",
    "index",
    "export",
    "stats",
    "preannotate",
    "kb_import",
    "kb_summarize",
    "kb_extract",
)
LABEL_SET_KINDS = ("pos", "dep", "span", "relation")
LAYER_KINDS = ("pos", "dep", "span", "relation", "alignment")
TOKEN_KINDS = ("pos", "dep")
LAYER_MODES = ("single", "multi")
TARGET_KINDS = ("token", "span", "relation", "alignment")
LAYER_STATUSES = ("created", "preannotating", "ready", "failed")
ANNOTATION_STATUSES = ("suggested", "confirmed", "modified", "rejected")
EVIDENCE_KINDS = ("hit", "stat_row", "text")
AGENT_STATES = ("idle", "running")
AGENT_ROLES = ("user", "assistant")
JOB_STATES = ("queued", "running", "succeeded", "failed", "cancelled")
KB_KINDS = ("literature", "guideline", "note", "url")
KB_STATUSES = ("queued", "parsing", "embedding", "ready", "failed")
TERM_SOURCES = ("manual", "corpus", "literature", "model")
TERM_STATUSES = ("draft", "confirmed")
NOTE_REF_KINDS = ("search", "stat", "evidence", "chunk", "term")
EMBED_DIM = 384  # engine.kb.embed.DIM


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


class StatResult(Base):
    __tablename__ = "stat_results"
    id: Mapped[uuid.UUID] = _id()
    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    method: Mapped[str] = mapped_column(Text)
    params: Mapped[dict] = mapped_column(JSONB)
    scope: Mapped[dict] = mapped_column(JSONB)
    index_version: Mapped[str | None] = mapped_column(Text)
    totals: Mapped[dict] = mapped_column(JSONB)
    columns: Mapped[list] = mapped_column(JSONB)
    rows_path: Mapped[str] = mapped_column(Text)
    row_count: Mapped[int] = mapped_column(Integer)
    created_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = _created()


class Evidence(Base):
    __tablename__ = "evidence"
    __table_args__ = (
        CheckConstraint(_in("kind", EVIDENCE_KINDS), name="ck_evidence_kind"),
    )
    id: Mapped[uuid.UUID] = _id()
    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    kind: Mapped[str] = mapped_column(Text)
    ref: Mapped[dict] = mapped_column(JSONB)
    text: Mapped[str] = mapped_column(Text)
    source: Mapped[str] = mapped_column(Text)
    note: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = _created()


def _server_id():
    return mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=func.gen_random_uuid(),
    )


# agent_sessions / agent_messages are written directly by the Node agent service (services/agent).
class AgentSession(Base):
    __tablename__ = "agent_sessions"
    __table_args__ = (
        CheckConstraint(_in("state", AGENT_STATES), name="ck_agent_session_state"),
    )
    id: Mapped[uuid.UUID] = _server_id()
    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    owner_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    title: Mapped[str] = mapped_column(Text, server_default="")
    scope: Mapped[dict | None] = mapped_column(JSONB)
    state: Mapped[str] = mapped_column(Text, server_default="idle")
    pi_session_path: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = _created()
    updated_at: Mapped[datetime] = _created()


class AgentMessage(Base):
    __tablename__ = "agent_messages"
    __table_args__ = (
        CheckConstraint(_in("role", AGENT_ROLES), name="ck_agent_message_role"),
        Index("ix_agent_messages_session_created", "session_id", "created_at"),
    )
    id: Mapped[uuid.UUID] = _server_id()
    session_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("agent_sessions.id", ondelete="CASCADE")
    )
    role: Mapped[str] = mapped_column(Text)
    content: Mapped[str] = mapped_column(Text, server_default="")
    parts: Mapped[list] = mapped_column(JSONB, server_default="[]")
    tool_calls: Mapped[list] = mapped_column(JSONB, server_default="[]")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.clock_timestamp()
    )
    duration_ms: Mapped[int | None] = mapped_column(Integer)


class AgentToken(Base):
    __tablename__ = "agent_tokens"
    token_hash: Mapped[str] = mapped_column(Text, primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE")
    )
    created_at: Mapped[datetime] = _created()
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class LabelSet(Base):
    """Built-in sets have project_id null and a unique name (services.api.label_sets.BUILTIN)."""

    __tablename__ = "label_sets"
    __table_args__ = (
        CheckConstraint(_in("kind", LABEL_SET_KINDS), name="ck_label_set_kind"),
        Index(
            "uq_label_sets_builtin_name",
            "name",
            unique=True,
            postgresql_where=text("project_id IS NULL"),
        ),
    )
    id: Mapped[uuid.UUID] = _id()
    project_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(Text)
    kind: Mapped[str] = mapped_column(Text)
    language: Mapped[str | None] = mapped_column(Text)
    labels: Mapped[list] = mapped_column(JSONB)
    created_at: Mapped[datetime] = _created()


class AnnotationLayer(Base):
    __tablename__ = "annotation_layers"
    __table_args__ = (
        CheckConstraint(_in("kind", LAYER_KINDS), name="ck_layer_kind"),
        CheckConstraint(_in("status", LAYER_STATUSES), name="ck_layer_status"),
        CheckConstraint(_in("mode", LAYER_MODES), name="ck_layer_mode"),
        CheckConstraint(
            "level IS NULL OR level IN ('sentence', 'word')", name="ck_layer_level"
        ),
    )
    id: Mapped[uuid.UUID] = _id()
    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    corpus_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("corpora.id", ondelete="CASCADE"), index=True
    )
    kind: Mapped[str] = mapped_column(Text)
    name: Mapped[str] = mapped_column(Text)
    label_set_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("label_sets.id", ondelete="RESTRICT"), index=True
    )  # null for alignment layers
    source_model: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, server_default="created")
    progress: Mapped[dict] = mapped_column(JSONB)
    document_ids: Mapped[list | None] = mapped_column(JSONB)  # null = whole corpus
    job_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("jobs.id", ondelete="SET NULL")
    )
    error: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = _created()
    updated_at: Mapped[datetime] = _created()
    # P5: single = one shared set of annotations (annotator_id = created_by); multi = one set per annotator
    mode: Mapped[str] = mapped_column(Text, server_default="single")
    annotators: Mapped[list] = mapped_column(ARRAY(UUID(as_uuid=True)))
    base_layer_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("annotation_layers.id", ondelete="CASCADE")
    )  # relation layers: the span layer whose spans they connect
    tgt_corpus_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("corpora.id", ondelete="CASCADE")
    )  # alignment layers; corpus_id is the source corpus
    level: Mapped[str | None] = mapped_column(Text)  # alignment: sentence | word
    guideline_document_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("kb_documents.id", ondelete="SET NULL")
    )


class Annotation(Base):
    """One token of a layer. token_index and head are 1-based (CoNLL-U; head 0 = root), i.e. tokens.idx + 1."""

    __tablename__ = "annotations"
    __table_args__ = (
        CheckConstraint(
            _in("status", ANNOTATION_STATUSES), name="ck_annotation_status"
        ),
        UniqueConstraint(
            "layer_id",
            "document_id",
            "sentence_index",
            "token_index",
            "annotator_id",
            name="uq_annotations_token",
        ),
        Index("ix_annotations_document", "document_id"),
    )
    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    layer_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("annotation_layers.id", ondelete="CASCADE")
    )
    document_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE")
    )
    sentence_index: Mapped[int] = mapped_column(Integer)
    token_index: Mapped[int] = mapped_column(Integer)
    annotator_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE")
    )
    label: Mapped[str | None] = mapped_column(Text)
    head: Mapped[int | None] = mapped_column(Integer)
    source: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, server_default="suggested")
    model_label: Mapped[str | None] = mapped_column(Text)
    model_head: Mapped[int | None] = mapped_column(Integer)
    revision: Mapped[int] = mapped_column(Integer, server_default="0")
    updated_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class KbDocument(Base):
    """Literature (file), url, guideline or note; note / guideline Markdown lives in body."""

    __tablename__ = "kb_documents"
    __table_args__ = (
        CheckConstraint(_in("kind", KB_KINDS), name="ck_kb_document_kind"),
        CheckConstraint(_in("status", KB_STATUSES), name="ck_kb_document_status"),
    )
    id: Mapped[uuid.UUID] = _id()
    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    kind: Mapped[str] = mapped_column(Text)
    title: Mapped[str] = mapped_column(Text)
    source: Mapped[str] = mapped_column(Text, server_default="")
    file_path: Mapped[str | None] = mapped_column(Text)
    text_path: Mapped[str | None] = mapped_column(Text)
    body: Mapped[str | None] = mapped_column(Text)
    meta: Mapped[dict] = mapped_column(JSONB, server_default="{}")
    status: Mapped[str] = mapped_column(Text, server_default="queued")
    error: Mapped[str | None] = mapped_column(Text)
    chunk_count: Mapped[int] = mapped_column(Integer, server_default="0")
    created_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = _created()
    updated_at: Mapped[datetime] = _created()


class KbChunk(Base):
    __tablename__ = "kb_chunks"
    __table_args__ = (
        UniqueConstraint("document_id", "ordinal", name="uq_kb_chunks_ordinal"),
        Index("ix_kb_chunks_tsv", "tsv", postgresql_using="gin"),
        Index(
            "ix_kb_chunks_embedding",
            "embedding",
            postgresql_using="hnsw",
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
    )
    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    document_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("kb_documents.id", ondelete="CASCADE")
    )
    ordinal: Mapped[int] = mapped_column(Integer)
    text: Mapped[str] = mapped_column(Text)
    locator: Mapped[dict] = mapped_column(JSONB, server_default="{}")
    embedding = mapped_column(Vector(EMBED_DIM), nullable=True)
    embed_model: Mapped[str | None] = mapped_column(Text)
    tsv = mapped_column(TSVECTOR, nullable=False)


class KbTerm(Base):
    __tablename__ = "kb_terms"
    __table_args__ = (
        UniqueConstraint("project_id", "term", "language", name="uq_kb_terms_term"),
        CheckConstraint(_in("source", TERM_SOURCES), name="ck_kb_term_source"),
        CheckConstraint(_in("status", TERM_STATUSES), name="ck_kb_term_status"),
    )
    id: Mapped[uuid.UUID] = _id()
    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE")
    )
    term: Mapped[str] = mapped_column(Text)
    language: Mapped[str] = mapped_column(Text)
    translations: Mapped[list] = mapped_column(JSONB, server_default="[]")
    definition: Mapped[str | None] = mapped_column(Text)
    domain: Mapped[str | None] = mapped_column(Text)
    examples: Mapped[list] = mapped_column(JSONB, server_default="[]")
    source: Mapped[str] = mapped_column(Text, server_default="manual")
    status: Mapped[str] = mapped_column(Text, server_default="draft")
    created_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    confirmed_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = _created()
    updated_at: Mapped[datetime] = _created()


class NoteRef(Base):
    __tablename__ = "note_refs"
    __table_args__ = (
        CheckConstraint(_in("kind", NOTE_REF_KINDS), name="ck_note_ref_kind"),
    )
    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    note_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("kb_documents.id", ondelete="CASCADE"), index=True
    )
    kind: Mapped[str] = mapped_column(Text)
    ref: Mapped[dict] = mapped_column(JSONB)
    created_at: Mapped[datetime] = _created()


def _status_check(name):
    return CheckConstraint(_in("status", ANNOTATION_STATUSES), name=name)


def _layer_fk():
    return mapped_column(ForeignKey("annotation_layers.id", ondelete="CASCADE"))


def _user_fk():
    return mapped_column(ForeignKey("users.id", ondelete="CASCADE"))


class _Reviewed:
    source: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, server_default="suggested")
    revision: Mapped[int] = mapped_column(Integer, server_default="0")
    updated_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class SpanAnnotation(_Reviewed, Base):
    """A labelled text span; start_cp / end_cp are document code points, sentence_index null when the span
    crosses sentences."""

    __tablename__ = "span_annotations"
    __table_args__ = (
        _status_check("ck_span_status"),
        CheckConstraint("start_cp >= 0 AND end_cp > start_cp", name="ck_span_range"),
        Index("ix_span_annotations_position", "layer_id", "document_id", "start_cp"),
        Index("ix_span_annotations_document", "document_id"),
    )
    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    layer_id: Mapped[uuid.UUID] = _layer_fk()
    annotator_id: Mapped[uuid.UUID] = _user_fk()
    document_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE")
    )
    sentence_index: Mapped[int | None] = mapped_column(Integer)
    start_cp: Mapped[int] = mapped_column(Integer)
    end_cp: Mapped[int] = mapped_column(Integer)
    label: Mapped[str] = mapped_column(Text)
    attrs: Mapped[dict] = mapped_column(JSONB, server_default="{}")
    model_label: Mapped[str | None] = mapped_column(Text)
    model_attrs: Mapped[dict | None] = mapped_column(JSONB)


class RelationAnnotation(_Reviewed, Base):
    __tablename__ = "relation_annotations"
    __table_args__ = (
        _status_check("ck_relation_status"),
        Index("ix_relation_annotations_layer", "layer_id"),
        Index("ix_relation_annotations_from", "from_span_id"),
        Index("ix_relation_annotations_to", "to_span_id"),
    )
    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    layer_id: Mapped[uuid.UUID] = _layer_fk()
    annotator_id: Mapped[uuid.UUID] = _user_fk()
    from_span_id: Mapped[int] = mapped_column(
        ForeignKey("span_annotations.id", ondelete="CASCADE")
    )
    to_span_id: Mapped[int] = mapped_column(
        ForeignKey("span_annotations.id", ondelete="CASCADE")
    )
    label: Mapped[str] = mapped_column(Text)
    model_label: Mapped[str | None] = mapped_column(Text)


class AlignmentAnnotation(_Reviewed, Base):
    """A sentence pair (src_tokens = tgt_tokens = []) or, in word layers, one link between 1-based tokens."""

    __tablename__ = "alignment_annotations"
    __table_args__ = (
        _status_check("ck_alignment_status"),
        Index(
            "ix_alignment_annotations_src",
            "layer_id",
            "src_document_id",
            "src_sentence_index",
        ),
        Index("ix_alignment_annotations_tgt", "tgt_document_id"),
    )
    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    layer_id: Mapped[uuid.UUID] = _layer_fk()
    annotator_id: Mapped[uuid.UUID] = _user_fk()
    src_document_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE")
    )
    src_sentence_index: Mapped[int] = mapped_column(Integer)
    tgt_document_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE")
    )
    tgt_sentence_index: Mapped[int] = mapped_column(Integer)
    src_tokens: Mapped[list] = mapped_column(ARRAY(Integer), server_default="{}")
    tgt_tokens: Mapped[list] = mapped_column(ARRAY(Integer), server_default="{}")
    score: Mapped[float | None] = mapped_column(Float)


class Adjudication(Base):
    """Final value of a disputed target in a multi-annotator layer; it is the effective annotation."""

    __tablename__ = "adjudications"
    __table_args__ = (
        CheckConstraint(_in("target_kind", TARGET_KINDS), name="ck_adjudication_kind"),
        UniqueConstraint(
            "layer_id", "target_kind", "target_key", name="uq_adjudications_target"
        ),
    )
    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    layer_id: Mapped[uuid.UUID] = _layer_fk()
    target_kind: Mapped[str] = mapped_column(Text)
    target_key: Mapped[str] = mapped_column(Text)
    final: Mapped[dict] = mapped_column(JSONB)
    decided_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    decided_at: Mapped[datetime] = _created()


class SentenceReview(Base):
    """An annotator finished a sentence (span / relation layers) or a source sentence (alignment layers)."""

    __tablename__ = "sentence_reviews"
    layer_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("annotation_layers.id", ondelete="CASCADE"), primary_key=True
    )
    annotator_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    document_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), primary_key=True
    )
    sentence_index: Mapped[int] = mapped_column(Integer, primary_key=True)
    reviewed_at: Mapped[datetime] = _created()
