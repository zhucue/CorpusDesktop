"""Export jobs begin before their actual output byte size is known."""

from alembic import op

revision = "0013_export_unknown_size"
down_revision = "0012_research_outcomes"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
    ALTER TABLE app.jobs DROP CONSTRAINT jobs_total_bytes_check;
    ALTER TABLE app.jobs ADD CONSTRAINT jobs_total_bytes_by_kind_check
      CHECK((kind='EXPORT' AND total_bytes>=0) OR (kind<>'EXPORT' AND total_bytes>0));
    """)


def downgrade():
    raise RuntimeError("Export rows require the kind-specific byte-size constraint")
