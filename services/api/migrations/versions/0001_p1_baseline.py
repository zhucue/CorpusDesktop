"""P1 baseline: accounts, projects, corpora, search data, jobs"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def _id():
    return sa.Column("id", UUID(as_uuid=True), primary_key=True)


def _created():
    return sa.Column(
        "created_at",
        sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.func.now(),
    )


def _fk(name, target, nullable=False, ondelete="CASCADE"):
    return sa.Column(
        name,
        sa.ForeignKey(target, ondelete=ondelete),
        nullable=nullable,
        type_=UUID(as_uuid=True),
    )


def upgrade():
    op.create_table(
        "users",
        _id(),
        sa.Column("email", sa.Text, nullable=False, unique=True),
        sa.Column("display_name", sa.Text, nullable=False),
        sa.Column("password_hash", sa.Text, nullable=False),
        sa.Column("is_admin", sa.Boolean, nullable=False, server_default="false"),
        _created(),
    )
    op.create_table(
        "login_sessions",
        sa.Column("token_hash", sa.Text, primary_key=True),
        _fk("user_id", "users.id"),
        _created(),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_login_sessions_user_id", "login_sessions", ["user_id"])
    op.create_table(
        "projects",
        _id(),
        sa.Column("name", sa.Text, nullable=False),
        _fk("created_by", "users.id", ondelete=None),
        _created(),
    )
    op.create_table(
        "project_members",
        sa.Column(
            "project_id",
            UUID(as_uuid=True),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "user_id",
            UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("role", sa.Text, nullable=False),
        sa.CheckConstraint(
            "role IN ('owner', 'editor', 'annotator', 'viewer')",
            name="ck_member_role",
        ),
    )
    op.create_index("ix_project_members_user_id", "project_members", ["user_id"])
    op.create_table(
        "corpora",
        _id(),
        _fk("project_id", "projects.id", nullable=True),
        sa.Column("name", sa.Text, nullable=False),
        sa.Column("language", sa.Text, nullable=False),
        sa.Column("description", sa.Text, nullable=False, server_default=""),
        sa.Column("parallel", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("status", sa.Text, nullable=False, server_default="empty"),
        sa.Column("error", sa.Text),
        sa.Column(
            "stats",
            JSONB,
            nullable=False,
            server_default='{"documents": 0, "sentences": 0, "tokens": 0}',
        ),
        sa.Column("index_version", sa.Text),
        _created(),
        sa.CheckConstraint(
            "status IN ('empty', 'importing', 'indexing', 'ready', 'stale', 'failed')",
            name="ck_corpus_status",
        ),
    )
    op.create_index("ix_corpora_project_id", "corpora", ["project_id"])
    op.create_table(
        "documents",
        _id(),
        _fk("corpus_id", "corpora.id"),
        sa.Column("title", sa.Text, nullable=False),
        sa.Column("language", sa.Text, nullable=False),
        sa.Column("metadata", JSONB, nullable=False, server_default="{}"),
        sa.Column("external_id", sa.Text),
        sa.Column("text_path", sa.Text, nullable=False),
        sa.Column("char_count", sa.Integer, nullable=False),
        sa.Column("sentence_count", sa.Integer, nullable=False),
        sa.Column("token_count", sa.Integer, nullable=False),
        _created(),
    )
    op.create_index("ix_documents_corpus_id", "documents", ["corpus_id"])
    op.create_table(
        "sentences",
        sa.Column("id", sa.BigInteger, sa.Identity(), primary_key=True),
        _fk("document_id", "documents.id"),
        sa.Column("idx", sa.Integer, nullable=False),
        sa.Column("start_cp", sa.Integer, nullable=False),
        sa.Column("end_cp", sa.Integer, nullable=False),
        sa.Column("text", sa.Text, nullable=False),
        sa.UniqueConstraint("document_id", "idx"),
    )
    op.create_table(
        "tokens",
        sa.Column("id", sa.BigInteger, sa.Identity(), primary_key=True),
        sa.Column(
            "sentence_id",
            sa.BigInteger,
            sa.ForeignKey("sentences.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("idx", sa.Integer, nullable=False),
        sa.Column("start_cp", sa.Integer, nullable=False),
        sa.Column("end_cp", sa.Integer, nullable=False),
        sa.Column("form", sa.Text, nullable=False),
        sa.Column("pos", sa.Text),
        sa.Column("lemma", sa.Text),
        sa.Column("head", sa.Integer),
        sa.Column("deprel", sa.Text),
        sa.UniqueConstraint("sentence_id", "idx"),
    )
    op.create_table(
        "sentence_alignments",
        sa.Column(
            "src_sentence_id",
            sa.BigInteger,
            sa.ForeignKey("sentences.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "tgt_sentence_id",
            sa.BigInteger,
            sa.ForeignKey("sentences.id", ondelete="CASCADE"),
            primary_key=True,
        ),
    )
    op.create_index(
        "ix_sentence_alignments_tgt_sentence_id",
        "sentence_alignments",
        ["tgt_sentence_id"],
    )
    op.create_table(
        "subcorpora",
        _id(),
        _fk("project_id", "projects.id"),
        _fk("corpus_id", "corpora.id"),
        sa.Column("name", sa.Text, nullable=False),
        sa.Column("filter", JSONB, nullable=False),
        _fk("created_by", "users.id", ondelete=None),
        _created(),
    )
    op.create_index("ix_subcorpora_project_id", "subcorpora", ["project_id"])
    op.create_index("ix_subcorpora_corpus_id", "subcorpora", ["corpus_id"])
    op.create_table(
        "saved_queries",
        _id(),
        _fk("project_id", "projects.id"),
        sa.Column("name", sa.Text, nullable=False),
        sa.Column("query", sa.Text, nullable=False),
        sa.Column("scope", JSONB, nullable=False),
        _fk("created_by", "users.id", ondelete=None),
        _created(),
    )
    op.create_index("ix_saved_queries_project_id", "saved_queries", ["project_id"])
    op.create_table(
        "jobs",
        _id(),
        _fk("project_id", "projects.id", nullable=True),
        _fk("owner_id", "users.id"),
        sa.Column("kind", sa.Text, nullable=False),
        sa.Column("params", JSONB, nullable=False),
        sa.Column("state", sa.Text, nullable=False, server_default="queued"),
        sa.Column(
            "progress",
            JSONB,
            nullable=False,
            server_default='{"done": 0, "total": null, "message": ""}',
        ),
        sa.Column("result", JSONB),
        sa.Column("error", JSONB),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.clock_timestamp(),
        ),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint("kind IN ('import', 'index', 'export')", name="ck_job_kind"),
        sa.CheckConstraint(
            "state IN ('queued', 'running', 'succeeded', 'failed', 'cancelled')",
            name="ck_job_state",
        ),
    )
    op.create_index("ix_jobs_project_id", "jobs", ["project_id"])
    op.create_index("ix_jobs_state_created", "jobs", ["state", "created_at"])


def downgrade():
    for table in (
        "jobs",
        "saved_queries",
        "subcorpora",
        "sentence_alignments",
        "tokens",
        "sentences",
        "documents",
        "corpora",
        "project_members",
        "projects",
        "login_sessions",
        "users",
    ):
        op.drop_table(table)
