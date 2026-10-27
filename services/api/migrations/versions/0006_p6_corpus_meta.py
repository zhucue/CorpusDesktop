"""P6: corpora.metadata (JSONB) for source, license and attribution of built-in corpora:
{license, attribution, source_url, version}; empty object for corpora without such data."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "corpora",
        sa.Column("metadata", JSONB, nullable=False, server_default="{}"),
    )


def downgrade():
    op.drop_column("corpora", "metadata")
