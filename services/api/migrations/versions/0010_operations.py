"""Operations (contracts/p9.md §一): llm_usage, audit_logs, feedback, projects.deleted_at."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None


def _user():
    return sa.Column(
        "user_id", UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL")
    )


def _project():
    return sa.Column(
        "project_id",
        UUID(as_uuid=True),
        sa.ForeignKey("projects.id", ondelete="SET NULL"),
    )


def _created(name="created_at", default="now"):
    return sa.Column(
        name,
        sa.DateTime(timezone=True),
        server_default=getattr(sa.func, default)(),
        nullable=False,
    )


def upgrade():
    op.add_column("projects", sa.Column("deleted_at", sa.DateTime(timezone=True)))
    op.create_table(
        "llm_usage",
        sa.Column("id", sa.BigInteger, sa.Identity(), primary_key=True),
        _created(),
        _user(),
        _project(),
        sa.Column("source", sa.Text, nullable=False),
        sa.Column("model", sa.Text),
        sa.Column("prompt_tokens", sa.Integer, nullable=False, server_default="0"),
        sa.Column("completion_tokens", sa.Integer, nullable=False, server_default="0"),
        sa.Column("total_tokens", sa.Integer, nullable=False, server_default="0"),
        sa.Column("job_id", UUID(as_uuid=True)),
        sa.Column("session_id", sa.Text),
    )
    op.create_index("ix_llm_usage_user_created", "llm_usage", ["user_id", "created_at"])
    op.create_index(
        "ix_llm_usage_project_created", "llm_usage", ["project_id", "created_at"]
    )
    op.create_table(
        "audit_logs",
        sa.Column("id", sa.BigInteger, sa.Identity(), primary_key=True),
        _created("at", "clock_timestamp"),
        sa.Column(
            "actor_id",
            UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
        ),
        sa.Column("actor_email", sa.Text),
        sa.Column("action", sa.Text, nullable=False),
        sa.Column("target_type", sa.Text),
        sa.Column("target_id", sa.Text),
        sa.Column("target_name", sa.Text),
        sa.Column(
            "project_id", UUID(as_uuid=True)
        ),  # no foreign key: kept after a purge
        sa.Column(
            "detail", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")
        ),
        sa.Column("ip", sa.Text),
    )
    op.create_index("ix_audit_logs_at", "audit_logs", ["at"])
    op.create_index("ix_audit_logs_project_at", "audit_logs", ["project_id", "at"])
    op.create_index("ix_audit_logs_actor_at", "audit_logs", ["actor_id", "at"])
    op.create_table(
        "feedback",
        sa.Column("id", sa.BigInteger, sa.Identity(), primary_key=True),
        _created(),
        _user(),
        _project(),
        sa.Column("page", sa.Text, nullable=False, server_default=""),
        sa.Column("app_version", sa.Text, nullable=False, server_default=""),
        sa.Column("text", sa.Text, nullable=False),
        sa.Column("status", sa.Text, nullable=False, server_default="open"),
        sa.Column("admin_note", sa.Text, nullable=False, server_default=""),
        sa.Column("handled_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint("status IN ('open', 'done')", name="ck_feedback_status"),
    )


def downgrade():
    op.drop_table("feedback")
    op.drop_table("audit_logs")
    op.drop_table("llm_usage")
    op.drop_column("projects", "deleted_at")
