"""Annotation layer meta (contracts/p8.md §五): annotation_layers.meta, e.g. the sampling record of a sample layer."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "annotation_layers",
        sa.Column("meta", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
    )


def downgrade():
    op.drop_column("annotation_layers", "meta")
