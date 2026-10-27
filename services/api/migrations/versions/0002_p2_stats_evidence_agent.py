"""P2: stat results, evidence, agent sessions / messages / tokens; job kind stats"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def _id(server=False):
    return sa.Column(
        "id",
        UUID(as_uuid=True),
        primary_key=True,
        server_default=sa.text("gen_random_uuid()") if server else None,
    )


def _ts(name="created_at", default=None):
    return sa.Column(
        name,
        sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.func.now() if default is None else default,
    )


def _fk(name, target, ondelete="CASCADE"):
    return sa.Column(
        name,
        sa.ForeignKey(target, ondelete=ondelete),
        nullable=False,
        type_=UUID(as_uuid=True),
    )


def upgrade():
    op.drop_constraint("ck_job_kind", "jobs", type_="check")
    op.create_check_constraint(
        "ck_job_kind", "jobs", "kind IN ('import', 'index', 'export', 'stats')"
    )
    op.create_table(
        "stat_results",
        _id(),
        _fk("project_id", "projects.id"),
        sa.Column("method", sa.Text, nullable=False),
        sa.Column("params", JSONB, nullable=False),
        sa.Column("scope", JSONB, nullable=False),
        sa.Column("index_version", sa.Text),
        sa.Column("totals", JSONB, nullable=False),
        sa.Column("columns", JSONB, nullable=False),
        sa.Column("rows_path", sa.Text, nullable=False),
        sa.Column("row_count", sa.Integer, nullable=False),
        _fk("created_by", "users.id", ondelete=None),
        _ts(),
    )
    op.create_index("ix_stat_results_project_id", "stat_results", ["project_id"])
    op.create_table(
        "evidence",
        _id(),
        _fk("project_id", "projects.id"),
        sa.Column("kind", sa.Text, nullable=False),
        sa.Column("ref", JSONB, nullable=False),
        sa.Column("text", sa.Text, nullable=False),
        sa.Column("source", sa.Text, nullable=False),
        sa.Column("note", sa.Text),
        _fk("created_by", "users.id", ondelete=None),
        _ts(),
        sa.CheckConstraint(
            "kind IN ('hit', 'stat_row', 'text')", name="ck_evidence_kind"
        ),
    )
    op.create_index("ix_evidence_project_id", "evidence", ["project_id"])
    op.create_table(
        "agent_sessions",
        _id(server=True),
        _fk("project_id", "projects.id"),
        _fk("owner_id", "users.id"),
        sa.Column("title", sa.Text, nullable=False, server_default=""),
        sa.Column("scope", JSONB),
        sa.Column("state", sa.Text, nullable=False, server_default="idle"),
        sa.Column("pi_session_path", sa.Text),
        _ts(),
        _ts("updated_at"),
        sa.CheckConstraint(
            "state IN ('idle', 'running')", name="ck_agent_session_state"
        ),
    )
    op.create_index("ix_agent_sessions_project_id", "agent_sessions", ["project_id"])
    op.create_index("ix_agent_sessions_owner_id", "agent_sessions", ["owner_id"])
    op.create_table(
        "agent_messages",
        _id(server=True),
        _fk("session_id", "agent_sessions.id"),
        sa.Column("role", sa.Text, nullable=False),
        sa.Column("content", sa.Text, nullable=False, server_default=""),
        sa.Column("parts", JSONB, nullable=False, server_default="[]"),
        sa.Column("tool_calls", JSONB, nullable=False, server_default="[]"),
        _ts(default=sa.func.clock_timestamp()),
        sa.Column("duration_ms", sa.Integer),
        sa.CheckConstraint(
            "role IN ('user', 'assistant')", name="ck_agent_message_role"
        ),
    )
    op.create_index(
        "ix_agent_messages_session_created",
        "agent_messages",
        ["session_id", "created_at"],
    )
    op.create_table(
        "agent_tokens",
        sa.Column("token_hash", sa.Text, primary_key=True),
        _fk("user_id", "users.id"),
        _fk("project_id", "projects.id"),
        _ts(),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_agent_tokens_user_id", "agent_tokens", ["user_id"])


def downgrade():
    for table in (
        "agent_tokens",
        "agent_messages",
        "agent_sessions",
        "evidence",
        "stat_results",
    ):
        op.drop_table(table)
    op.execute("DELETE FROM jobs WHERE kind = 'stats'")
    op.drop_constraint("ck_job_kind", "jobs", type_="check")
    op.create_check_constraint(
        "ck_job_kind", "jobs", "kind IN ('import', 'index', 'export')"
    )
