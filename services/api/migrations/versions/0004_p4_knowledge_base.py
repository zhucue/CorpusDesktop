"""P4: knowledge base documents, chunks (pgvector + full text), terms, note refs; job kinds kb_*"""

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects.postgresql import JSONB, TSVECTOR, UUID

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None

JOB_KINDS = ("import", "index", "export", "stats", "preannotate")
KB_JOB_KINDS = ("kb_import", "kb_summarize", "kb_extract")


def _ts(name):
    return sa.Column(
        name, sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
    )


def _fk(name, target, nullable=False, ondelete="CASCADE"):
    return sa.Column(
        name,
        sa.ForeignKey(target, ondelete=ondelete),
        nullable=nullable,
        type_=UUID(as_uuid=True),
    )


def _in(column, *values):
    return f"{column} IN (" + ", ".join(f"'{v}'" for v in values) + ")"


def upgrade():
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.drop_constraint("ck_job_kind", "jobs", type_="check")
    op.create_check_constraint(
        "ck_job_kind", "jobs", _in("kind", *JOB_KINDS, *KB_JOB_KINDS)
    )
    op.create_table(
        "kb_documents",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        _fk("project_id", "projects.id"),
        sa.Column("kind", sa.Text, nullable=False),
        sa.Column("title", sa.Text, nullable=False),
        sa.Column("source", sa.Text, nullable=False, server_default=""),
        sa.Column("file_path", sa.Text),
        sa.Column("text_path", sa.Text),
        sa.Column("body", sa.Text),
        sa.Column("meta", JSONB, nullable=False, server_default="{}"),
        sa.Column("status", sa.Text, nullable=False, server_default="queued"),
        sa.Column("error", sa.Text),
        sa.Column("chunk_count", sa.Integer, nullable=False, server_default="0"),
        _fk("created_by", "users.id", ondelete=None),
        _ts("created_at"),
        _ts("updated_at"),
        sa.CheckConstraint(
            _in("kind", "literature", "guideline", "note", "url"),
            name="ck_kb_document_kind",
        ),
        sa.CheckConstraint(
            _in("status", "queued", "parsing", "embedding", "ready", "failed"),
            name="ck_kb_document_status",
        ),
    )
    op.create_index("ix_kb_documents_project_id", "kb_documents", ["project_id"])
    op.create_table(
        "kb_chunks",
        sa.Column("id", sa.BigInteger, sa.Identity(), primary_key=True),
        _fk("document_id", "kb_documents.id"),
        sa.Column("ordinal", sa.Integer, nullable=False),
        sa.Column("text", sa.Text, nullable=False),
        sa.Column("locator", JSONB, nullable=False, server_default="{}"),
        sa.Column("embedding", Vector(384)),
        sa.Column("embed_model", sa.Text),
        sa.Column("tsv", TSVECTOR, nullable=False),
        sa.UniqueConstraint("document_id", "ordinal", name="uq_kb_chunks_ordinal"),
    )
    op.create_index("ix_kb_chunks_tsv", "kb_chunks", ["tsv"], postgresql_using="gin")
    op.create_index(
        "ix_kb_chunks_embedding",
        "kb_chunks",
        ["embedding"],
        postgresql_using="hnsw",
        postgresql_ops={"embedding": "vector_cosine_ops"},
    )
    op.create_table(
        "kb_terms",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        _fk("project_id", "projects.id"),
        sa.Column("term", sa.Text, nullable=False),
        sa.Column("language", sa.Text, nullable=False),
        sa.Column("translations", JSONB, nullable=False, server_default="[]"),
        sa.Column("definition", sa.Text),
        sa.Column("domain", sa.Text),
        sa.Column("examples", JSONB, nullable=False, server_default="[]"),
        sa.Column("source", sa.Text, nullable=False, server_default="manual"),
        sa.Column("status", sa.Text, nullable=False, server_default="draft"),
        _fk("created_by", "users.id", ondelete=None),
        _fk("confirmed_by", "users.id", nullable=True, ondelete="SET NULL"),
        _ts("created_at"),
        _ts("updated_at"),
        sa.UniqueConstraint("project_id", "term", "language", name="uq_kb_terms_term"),
        sa.CheckConstraint(
            _in("source", "manual", "corpus", "literature", "model"),
            name="ck_kb_term_source",
        ),
        sa.CheckConstraint(
            _in("status", "draft", "confirmed"), name="ck_kb_term_status"
        ),
    )
    op.create_table(
        "note_refs",
        sa.Column("id", sa.BigInteger, sa.Identity(), primary_key=True),
        _fk("note_id", "kb_documents.id"),
        sa.Column("kind", sa.Text, nullable=False),
        sa.Column("ref", JSONB, nullable=False),
        _ts("created_at"),
        sa.CheckConstraint(
            _in("kind", "search", "stat", "evidence", "chunk", "term"),
            name="ck_note_ref_kind",
        ),
    )
    op.create_index("ix_note_refs_note_id", "note_refs", ["note_id"])


def downgrade():
    op.execute("DELETE FROM jobs WHERE " + _in("kind", *KB_JOB_KINDS))
    for table in ("note_refs", "kb_terms", "kb_chunks", "kb_documents"):
        op.drop_table(table)
    op.drop_constraint("ck_job_kind", "jobs", type_="check")
    op.create_check_constraint("ck_job_kind", "jobs", _in("kind", *JOB_KINDS))
