"""P5: span / relation / alignment layers, multiple annotators, adjudication, sentence reviews

annotation_layers: kind span | relation | alignment, mode single | multi, annotators, base_layer_id (relation),
tgt_corpus_id and level (alignment; corpus_id is the source corpus), guideline_document_id; label_set_id is
null for alignment layers. annotations.annotator_id (backfilled with the layer creator) joins the unique key.
Built-in label sets learner-errors, translation-strategies and error-correction are seeded at api startup.
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None

STATUSES = "status IN ('suggested', 'confirmed', 'modified', 'rejected')"


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


def _review_columns():
    return [
        sa.Column("source", sa.Text, nullable=False),
        sa.Column("status", sa.Text, nullable=False, server_default="suggested"),
        sa.Column("revision", sa.Integer, nullable=False, server_default="0"),
        _fk("updated_by", "users.id", nullable=True, ondelete="SET NULL"),
        _ts("updated_at"),
    ]


def upgrade():
    op.drop_constraint("ck_layer_kind", "annotation_layers", type_="check")
    op.create_check_constraint(
        "ck_layer_kind",
        "annotation_layers",
        "kind IN ('pos', 'dep', 'span', 'relation', 'alignment')",
    )
    op.alter_column("annotation_layers", "label_set_id", nullable=True)
    op.add_column(
        "annotation_layers",
        sa.Column("mode", sa.Text, nullable=False, server_default="single"),
    )
    op.add_column(
        "annotation_layers", sa.Column("annotators", ARRAY(UUID(as_uuid=True)))
    )
    op.execute("UPDATE annotation_layers SET annotators = ARRAY[created_by]")
    op.alter_column("annotation_layers", "annotators", nullable=False)
    op.add_column(
        "annotation_layers",
        _fk("base_layer_id", "annotation_layers.id", nullable=True),
    )
    op.add_column(
        "annotation_layers", _fk("tgt_corpus_id", "corpora.id", nullable=True)
    )
    op.add_column("annotation_layers", sa.Column("level", sa.Text))
    op.add_column(
        "annotation_layers",
        _fk(
            "guideline_document_id",
            "kb_documents.id",
            nullable=True,
            ondelete="SET NULL",
        ),
    )
    op.create_check_constraint(
        "ck_layer_mode", "annotation_layers", "mode IN ('single', 'multi')"
    )
    op.create_check_constraint(
        "ck_layer_level",
        "annotation_layers",
        "level IS NULL OR level IN ('sentence', 'word')",
    )

    op.add_column("annotations", _fk("annotator_id", "users.id", nullable=True))
    op.execute(
        "UPDATE annotations a SET annotator_id = l.created_by"
        " FROM annotation_layers l WHERE l.id = a.layer_id"
    )
    op.alter_column("annotations", "annotator_id", nullable=False)
    op.drop_constraint("uq_annotations_token", "annotations", type_="unique")
    op.create_unique_constraint(
        "uq_annotations_token",
        "annotations",
        ["layer_id", "document_id", "sentence_index", "token_index", "annotator_id"],
    )

    op.create_table(
        "span_annotations",
        sa.Column("id", sa.BigInteger, sa.Identity(), primary_key=True),
        _fk("layer_id", "annotation_layers.id"),
        _fk("annotator_id", "users.id"),
        _fk("document_id", "documents.id"),
        sa.Column("sentence_index", sa.Integer),
        sa.Column("start_cp", sa.Integer, nullable=False),
        sa.Column("end_cp", sa.Integer, nullable=False),
        sa.Column("label", sa.Text, nullable=False),
        sa.Column("attrs", JSONB, nullable=False, server_default="{}"),
        sa.Column("model_label", sa.Text),
        sa.Column("model_attrs", JSONB),
        *_review_columns(),
        sa.CheckConstraint(STATUSES, name="ck_span_status"),
        sa.CheckConstraint("start_cp >= 0 AND end_cp > start_cp", name="ck_span_range"),
    )
    op.create_index(
        "ix_span_annotations_position",
        "span_annotations",
        ["layer_id", "document_id", "start_cp"],
    )
    op.create_index("ix_span_annotations_document", "span_annotations", ["document_id"])

    op.create_table(
        "relation_annotations",
        sa.Column("id", sa.BigInteger, sa.Identity(), primary_key=True),
        _fk("layer_id", "annotation_layers.id"),
        _fk("annotator_id", "users.id"),
        sa.Column(
            "from_span_id",
            sa.BigInteger,
            sa.ForeignKey("span_annotations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "to_span_id",
            sa.BigInteger,
            sa.ForeignKey("span_annotations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("label", sa.Text, nullable=False),
        sa.Column("model_label", sa.Text),
        *_review_columns(),
        sa.CheckConstraint(STATUSES, name="ck_relation_status"),
    )
    op.create_index(
        "ix_relation_annotations_layer", "relation_annotations", ["layer_id"]
    )
    op.create_index(
        "ix_relation_annotations_from", "relation_annotations", ["from_span_id"]
    )
    op.create_index(
        "ix_relation_annotations_to", "relation_annotations", ["to_span_id"]
    )

    op.create_table(
        "alignment_annotations",
        sa.Column("id", sa.BigInteger, sa.Identity(), primary_key=True),
        _fk("layer_id", "annotation_layers.id"),
        _fk("annotator_id", "users.id"),
        _fk("src_document_id", "documents.id"),
        sa.Column("src_sentence_index", sa.Integer, nullable=False),
        _fk("tgt_document_id", "documents.id"),
        sa.Column("tgt_sentence_index", sa.Integer, nullable=False),
        sa.Column("src_tokens", ARRAY(sa.Integer), nullable=False, server_default="{}"),
        sa.Column("tgt_tokens", ARRAY(sa.Integer), nullable=False, server_default="{}"),
        sa.Column("score", sa.Float),
        *_review_columns(),
        sa.CheckConstraint(STATUSES, name="ck_alignment_status"),
    )
    op.create_index(
        "ix_alignment_annotations_src",
        "alignment_annotations",
        ["layer_id", "src_document_id", "src_sentence_index"],
    )
    op.create_index(
        "ix_alignment_annotations_tgt", "alignment_annotations", ["tgt_document_id"]
    )

    op.create_table(
        "adjudications",
        sa.Column("id", sa.BigInteger, sa.Identity(), primary_key=True),
        _fk("layer_id", "annotation_layers.id"),
        sa.Column("target_kind", sa.Text, nullable=False),
        sa.Column("target_key", sa.Text, nullable=False),
        sa.Column("final", JSONB, nullable=False),
        _fk("decided_by", "users.id", nullable=True, ondelete="SET NULL"),
        _ts("decided_at"),
        sa.CheckConstraint(
            "target_kind IN ('token', 'span', 'relation', 'alignment')",
            name="ck_adjudication_kind",
        ),
        sa.UniqueConstraint(
            "layer_id", "target_kind", "target_key", name="uq_adjudications_target"
        ),
    )

    op.create_table(
        "sentence_reviews",
        _fk("layer_id", "annotation_layers.id"),
        _fk("annotator_id", "users.id"),
        _fk("document_id", "documents.id"),
        sa.Column("sentence_index", sa.Integer, nullable=False),
        _ts("reviewed_at"),
        sa.PrimaryKeyConstraint(
            "layer_id", "annotator_id", "document_id", "sentence_index"
        ),
    )


def downgrade():
    for table in (
        "sentence_reviews",
        "adjudications",
        "alignment_annotations",
        "relation_annotations",
        "span_annotations",
    ):
        op.drop_table(table)
    op.execute(
        "DELETE FROM annotation_layers WHERE kind IN ('span', 'relation', 'alignment')"
    )
    op.execute(
        "DELETE FROM annotations a USING annotation_layers l"
        " WHERE l.id = a.layer_id AND a.annotator_id <> l.created_by"
    )
    op.drop_constraint("uq_annotations_token", "annotations", type_="unique")
    op.create_unique_constraint(
        "uq_annotations_token",
        "annotations",
        ["layer_id", "document_id", "sentence_index", "token_index"],
    )
    op.drop_column("annotations", "annotator_id")
    op.drop_constraint("ck_layer_level", "annotation_layers", type_="check")
    op.drop_constraint("ck_layer_mode", "annotation_layers", type_="check")
    for col in (
        "guideline_document_id",
        "level",
        "tgt_corpus_id",
        "base_layer_id",
        "annotators",
        "mode",
    ):
        op.drop_column("annotation_layers", col)
    op.alter_column("annotation_layers", "label_set_id", nullable=False)
    op.drop_constraint("ck_layer_kind", "annotation_layers", type_="check")
    op.create_check_constraint(
        "ck_layer_kind", "annotation_layers", "kind IN ('pos', 'dep')"
    )
