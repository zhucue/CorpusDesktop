"""Worker heartbeat: jobs.heartbeat_at (refreshed by the running worker) and jobs.worker_id,
so several workers can run and only jobs of a dead worker are failed."""

import sqlalchemy as sa
from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("jobs", sa.Column("heartbeat_at", sa.DateTime(timezone=True)))
    op.add_column("jobs", sa.Column("worker_id", sa.Text))


def downgrade():
    op.drop_column("jobs", "worker_id")
    op.drop_column("jobs", "heartbeat_at")
