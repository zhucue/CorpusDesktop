"""Evidence basket: one item per pinned hit and per stat row in a project (contracts/p11.md §二.6).

Existing duplicates are merged first: the earliest item (created_at, id) stays and takes the group's
non-empty notes (oldest first, one per line), note refs pointing at a removed duplicate (note_refs.ref.evidence_id) point at the kept item, then the duplicates are deleted. The unique
indexes make concurrent pins of the same hit keep one row (services/api/evidence.py inserts ON CONFLICT DO
NOTHING and returns the existing item)."""

from alembic import op

revision = "0013"
down_revision = "0012"
branch_labels = None
depends_on = None

# (index name, kind, key expressions): the keys services/api/evidence.py matches pins on
KEYS = (
    (
        "uq_evidence_hit",
        "hit",
        ["(ref ->> 'document_id')", "(ref ->> 'start_cp')", "(ref ->> 'end_cp')"],
    ),
    (
        "uq_evidence_stat_row",
        "stat_row",
        ["(ref ->> 'stat_id')", "md5(ref ->> 'row_key')"],
    ),
)

# Duplicates: same project and key, every key part present (a null part is never a duplicate in the index).
RANKED = """
WITH ranked AS (
    SELECT id,
           first_value(id) OVER w AS keep,
           row_number() OVER w AS n
    FROM evidence
    WHERE kind = '{kind}' AND {present}
    WINDOW w AS (PARTITION BY project_id, {keys} ORDER BY created_at, id)
)
"""


def upgrade():
    for name, kind, keys in KEYS:
        ranked = RANKED.format(
            kind=kind,
            keys=", ".join(keys),
            present=" AND ".join(f"{k} IS NOT NULL" for k in keys),
        )
        op.execute(
            ranked
            + """
UPDATE note_refs nr
SET ref = jsonb_set(nr.ref, '{evidence_id}', to_jsonb(r.keep::text))
FROM ranked r
WHERE r.n > 1 AND nr.kind = 'evidence' AND nr.ref ->> 'evidence_id' = r.id::text
"""
        )
        op.execute(
            ranked
            + r"""
UPDATE evidence e SET note = m.note
FROM (
    SELECT r.keep,
           max(r.n) AS size,
           string_agg(x.note, E'\n' ORDER BY x.created_at, x.id)
               FILTER (WHERE x.note IS NOT NULL AND x.note <> '') AS note
    FROM ranked r JOIN evidence x ON x.id = r.id
    GROUP BY r.keep
) m
WHERE e.id = m.keep AND m.size > 1 AND m.note IS NOT NULL
"""
        )
        op.execute(
            ranked
            + "DELETE FROM evidence e USING ranked r WHERE e.id = r.id AND r.n > 1"
        )
        op.execute(
            f"CREATE UNIQUE INDEX {name} ON evidence (project_id, {', '.join(keys)})"
            f" WHERE kind = '{kind}'"
        )


def downgrade():
    for name, _, _ in KEYS:
        op.execute(f"DROP INDEX IF EXISTS {name}")
