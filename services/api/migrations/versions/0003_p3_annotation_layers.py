"""P3: label sets, annotation layers, annotations; job kind preannotate

Built-in label sets are seeded idempotently at api startup (services.api.label_sets.seed_builtin).
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def _ts(name):
    return sa.Column(
        name, sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
    )


def _fk(name, target, nullable=False, ondelete="CASCADE"):
    return sa.Column(
        name,
        sa.ForeignKey(target, ondelete=ondelete),
        nullable=nullable,
        type_=UUID(as_uuid=True),
    )


def _kinds(*kinds):
    return "kind IN (" + ", ".join(f"'{k}'" for k in kinds) + ")"


def upgrade():
    op.drop_constraint("ck_job_kind", "jobs", type_="check")
    op.create_check_constraint(
        "ck_job_kind",
        "jobs",
        _kinds("import", "index", "export", "stats", "preannotate"),
    )
    op.create_table(
        "label_sets",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        _fk("project_id", "projects.id", nullable=True),
        sa.Column("name", sa.Text, nullable=False),
        sa.Column("kind", sa.Text, nullable=False),
        sa.Column("language", sa.Text),
        sa.Column("labels", JSONB, nullable=False),
        _ts("created_at"),
        sa.CheckConstraint(
            _kinds("pos", "dep", "span", "relation"), name="ck_label_set_kind"
        ),
    )
    op.create_index("ix_label_sets_project_id", "label_sets", ["project_id"])
    op.create_index(
        "uq_label_sets_builtin_name",
        "label_sets",
        ["name"],
        unique=True,
        postgresql_where=sa.text("project_id IS NULL"),
    )
    op.create_table(
        "annotation_layers",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        _fk("project_id", "projects.id"),
        _fk("corpus_id", "corpora.id"),
        sa.Column("kind", sa.Text, nullable=False),
        sa.Column("name", sa.Text, nullable=False),
        _fk("label_set_id", "label_sets.id", ondelete="RESTRICT"),
        sa.Column("source_model", sa.Text, nullable=False),
        sa.Column("status", sa.Text, nullable=False, server_default="created"),
        sa.Column("progress", JSONB, nullable=False),
        sa.Column("document_ids", JSONB),
        _fk("job_id", "jobs.id", nullable=True, ondelete="SET NULL"),
        sa.Column("error", sa.Text),
        _fk("created_by", "users.id", ondelete=None),
        _ts("created_at"),
        _ts("updated_at"),
        sa.CheckConstraint(_kinds("pos", "dep"), name="ck_layer_kind"),
        sa.CheckConstraint(
            "status IN ('created', 'preannotating', 'ready', 'failed')",
            name="ck_layer_status",
        ),
    )
    for col in ("project_id", "corpus_id", "label_set_id"):
        op.create_index(f"ix_annotation_layers_{col}", "annotation_layers", [col])
    op.create_table(
        "annotations",
        sa.Column("id", sa.BigInteger, sa.Identity(), primary_key=True),
        _fk("layer_id", "annotation_layers.id"),
        _fk("document_id", "documents.id"),
        sa.Column("sentence_index", sa.Integer, nullable=False),
        sa.Column("token_index", sa.Integer, nullable=False),
        sa.Column("label", sa.Text),
        sa.Column("head", sa.Integer),
        sa.Column("source", sa.Text, nullable=False),
        sa.Column("status", sa.Text, nullable=False, server_default="suggested"),
        sa.Column("model_label", sa.Text),
        sa.Column("model_head", sa.Integer),
        sa.Column("revision", sa.Integer, nullable=False, server_default="0"),
        _fk("updated_by", "users.id", nullable=True, ondelete="SET NULL"),
        _ts("updated_at"),
        sa.CheckConstraint(
            "status IN ('suggested', 'confirmed', 'modified', 'rejected')",
            name="ck_annotation_status",
        ),
        sa.UniqueConstraint(
            "layer_id",
            "document_id",
            "sentence_index",
            "token_index",
            name="uq_annotations_token",
        ),
    )
    op.create_index("ix_annotations_document", "annotations", ["document_id"])


def downgrade():
    for table in ("annotations", "annotation_layers", "label_sets"):
        op.drop_table(table)
    op.execute("DELETE FROM jobs WHERE kind = 'preannotate'")
    op.drop_constraint("ck_job_kind", "jobs", type_="check")
    op.create_check_constraint(
        "ck_job_kind", "jobs", _kinds("import", "index", "export", "stats")
    )
