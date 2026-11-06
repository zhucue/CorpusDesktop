"""Semantic search and import dedup (contracts/p10.md §六, §七): sentence_embeddings, corpora.semantic,
documents.content_hash (backfilled from the stored document texts); job kind embed_corpus."""

import hashlib
import re
import unicodedata
from pathlib import Path

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None

DIM = 384  # engine.kb.embed.DIM
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
BATCH = 500


def _in(column, *values):
    return f"{column} IN (" + ", ".join(f"'{v}'" for v in values) + ")"


def content_hash(text: str) -> str:
    """Same rule as engine.parsers.content_hash: strip, collapse whitespace runs to one space, NFKC, sha256 hex.
    Inlined so the migration does not depend on runtime code."""
    norm = unicodedata.normalize("NFKC", re.sub(r"\s+", " ", text.strip()))
    return hashlib.sha256(norm.encode("utf-8")).hexdigest()


def _backfill(conn):
    """Hash every stored document text; a missing text file leaves the hash null."""
    rows = conn.execute(sa.text("SELECT id, text_path FROM documents")).all()
    pending = []
    for doc_id, path in rows:
        try:
            text = Path(path).read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        pending.append({"id": doc_id, "h": content_hash(text)})
        if len(pending) >= BATCH:
            conn.execute(
                sa.text("UPDATE documents SET content_hash = :h WHERE id = :id"),
                pending,
            )
            pending = []
    if pending:
        conn.execute(
            sa.text("UPDATE documents SET content_hash = :h WHERE id = :id"), pending
        )


def upgrade():
    op.drop_constraint("ck_job_kind", "jobs", type_="check")
    op.create_check_constraint(
        "ck_job_kind", "jobs", _in("kind", *JOB_KINDS, "embed_corpus")
    )
    op.create_table(
        "sentence_embeddings",
        sa.Column(
            "sentence_id",
            sa.BigInteger,
            sa.ForeignKey("sentences.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "corpus_id",
            UUID(as_uuid=True),
            sa.ForeignKey("corpora.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("embedding", Vector(DIM), nullable=False),
    )
    op.create_index(
        "ix_sentence_embeddings_corpus_id", "sentence_embeddings", ["corpus_id"]
    )
    op.create_index(
        "ix_sentence_embeddings_embedding",
        "sentence_embeddings",
        ["embedding"],
        postgresql_using="hnsw",
        postgresql_ops={"embedding": "vector_cosine_ops"},
    )
    op.add_column(
        "corpora",
        sa.Column("semantic", JSONB, nullable=False, server_default="{}"),
    )
    op.add_column("documents", sa.Column("content_hash", sa.Text))
    op.create_index(
        "ix_documents_content_hash", "documents", ["corpus_id", "content_hash"]
    )
    _backfill(op.get_bind())


def downgrade():
    op.drop_index("ix_documents_content_hash", "documents")
    op.drop_column("documents", "content_hash")
    op.drop_column("corpora", "semantic")
    op.drop_table("sentence_embeddings")
    op.execute("DELETE FROM jobs WHERE kind = 'embed_corpus'")
    op.drop_constraint("ck_job_kind", "jobs", type_="check")
    op.create_check_constraint("ck_job_kind", "jobs", _in("kind", *JOB_KINDS))
