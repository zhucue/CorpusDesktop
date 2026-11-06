"""Account lifecycle (contracts/p7.md §五): users.disabled_at, must_change_password, last_login_at."""

import sqlalchemy as sa
from alembic import op

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("users", sa.Column("disabled_at", sa.DateTime(timezone=True)))
    op.add_column(
        "users",
        sa.Column(
            "must_change_password",
            sa.Boolean,
            nullable=False,
            server_default=sa.false(),
        ),
    )
    op.add_column("users", sa.Column("last_login_at", sa.DateTime(timezone=True)))


def downgrade():
    op.drop_column("users", "last_login_at")
    op.drop_column("users", "must_change_password")
    op.drop_column("users", "disabled_at")
