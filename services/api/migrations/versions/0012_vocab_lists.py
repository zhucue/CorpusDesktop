"""Vocabulary level lists (contracts/p10.md §二): vocab_lists, vocab_entries. The built-in NGSL 1.2 list is
inserted on first use by services/api/vocab.py (fixed id), so a truncated test database gets it back too."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "vocab_lists",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "project_id",
            UUID(as_uuid=True),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
        ),
        sa.Column("name", sa.Text, nullable=False),
        sa.Column("language", sa.Text, nullable=False),
        sa.Column("levels", JSONB, nullable=False),
        sa.Column("source", sa.Text, nullable=False, server_default=""),
        sa.Column("license", sa.Text, nullable=False, server_default=""),
        sa.Column(
            "created_by",
            UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index("ix_vocab_lists_project_id", "vocab_lists", ["project_id"])
    op.create_table(
        "vocab_entries",
        sa.Column(
            "list_id",
            UUID(as_uuid=True),
            sa.ForeignKey("vocab_lists.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("form", sa.Text, primary_key=True),
        sa.Column("level", sa.Text, nullable=False),
    )


def downgrade():
    op.drop_table("vocab_entries")
    op.drop_table("vocab_lists")
