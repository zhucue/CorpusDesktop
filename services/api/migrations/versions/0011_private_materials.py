"""Private TXT revisions and fixed mixed project indexes."""

from alembic import op

revision = "0011_private_materials"
down_revision = "0010_research_queries"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
    ALTER TABLE app.jobs DROP CONSTRAINT jobs_upload_id_key;
    ALTER TABLE app.jobs DROP CONSTRAINT jobs_kind_check;
    ALTER TABLE app.jobs ADD CHECK(kind IN ('UPLOAD_VALIDATE','TXT_IMPORT'));
    ALTER TABLE app.jobs ADD COLUMN input jsonb NOT NULL DEFAULT '{}';
    ALTER TABLE app.jobs ADD COLUMN input_sha256 varchar(64);
    ALTER TABLE app.jobs ADD COLUMN stage varchar(30);
    ALTER TABLE app.jobs ADD COLUMN progress jsonb;
    ALTER TABLE app.jobs ADD COLUMN reserved_bytes bigint NOT NULL DEFAULT 0 CHECK(reserved_bytes>=0);
    CREATE UNIQUE INDEX upload_validation_once ON app.jobs(upload_id) WHERE kind='UPLOAD_VALIDATE';
    CREATE UNIQUE INDEX txt_import_once ON app.jobs(upload_id,input_sha256) WHERE kind='TXT_IMPORT';
    ALTER TABLE app.jobs ADD CHECK(kind<>'TXT_IMPORT' OR input_sha256 IS NOT NULL);
    CREATE TABLE app.material_documents (
      id uuid PRIMARY KEY, project_id uuid NOT NULL REFERENCES app.projects(id),
      upload_id uuid NOT NULL, name varchar(255) NOT NULL, latest_revision_id uuid,
      import_id uuid NOT NULL, created_at timestamptz NOT NULL,
      UNIQUE(id,project_id), UNIQUE(upload_id,project_id),
      FOREIGN KEY(upload_id,project_id) REFERENCES app.upload_sessions(id,project_id),
      FOREIGN KEY(import_id,project_id) REFERENCES app.jobs(id,project_id)
    );
    CREATE TABLE app.material_revisions (
      id uuid PRIMARY KEY, project_id uuid NOT NULL, material_id uuid NOT NULL,
      upload_id uuid NOT NULL, import_id uuid NOT NULL UNIQUE,
      revision integer NOT NULL CHECK(revision>0), language varchar(3) NOT NULL CHECK(language IN ('cmn','eng')),
      manifest jsonb NOT NULL, manifest_sha256 varchar(64) NOT NULL,
      objects jsonb NOT NULL, created_at timestamptz NOT NULL,
      UNIQUE(id,project_id), UNIQUE(id,material_id,project_id), UNIQUE(material_id,revision),
      FOREIGN KEY(material_id,project_id) REFERENCES app.material_documents(id,project_id),
      FOREIGN KEY(upload_id,project_id) REFERENCES app.upload_sessions(id,project_id),
      FOREIGN KEY(import_id,project_id) REFERENCES app.jobs(id,project_id)
    );
    ALTER TABLE app.material_documents ADD CONSTRAINT material_latest_revision_fk
      FOREIGN KEY(latest_revision_id,id,project_id) REFERENCES app.material_revisions(id,material_id,project_id);
    ALTER TABLE app.research_snapshots ADD COLUMN index_result jsonb;
    ALTER TABLE app.research_snapshots ADD COLUMN reserved_bytes bigint NOT NULL DEFAULT 0 CHECK(reserved_bytes>=0);
    ALTER TABLE app.research_snapshot_members ALTER COLUMN mount_id DROP NOT NULL;
    ALTER TABLE app.research_snapshot_members DROP CONSTRAINT research_snapshot_members_kind_check;
    ALTER TABLE app.research_snapshot_members ADD COLUMN material_revision_id uuid;
    ALTER TABLE app.research_snapshot_members ADD FOREIGN KEY(material_revision_id,project_id)
      REFERENCES app.material_revisions(id,project_id);
    ALTER TABLE app.research_snapshot_members ADD CHECK(
      (kind='whole_source_mount' AND mount_id IS NOT NULL AND material_revision_id IS NULL)
      OR (kind='private_revision' AND mount_id IS NULL AND material_revision_id IS NOT NULL));
    CREATE OR REPLACE FUNCTION app.research_snapshot_allowed(sid uuid) RETURNS boolean LANGUAGE sql STABLE SECURITY INVOKER
      SET search_path=pg_catalog,app AS $$
      SELECT EXISTS(SELECT 1 FROM app.research_snapshot_members sm WHERE sm.snapshot_id=sid)
      AND NOT EXISTS(SELECT 1 FROM app.research_snapshot_members sm WHERE sm.snapshot_id=sid AND
        (app.project_role(sm.project_id) IS NULL OR CASE WHEN sm.kind='whole_source_mount' THEN
          NOT EXISTS(SELECT 1 FROM app.project_source_mounts m WHERE m.id=sm.mount_id AND m.project_id=sm.project_id
            AND m.removed_at IS NULL AND app.source_release_allowed(m.source_snapshot_id))
        ELSE NOT EXISTS(SELECT 1 FROM app.material_revisions r WHERE r.id=sm.material_revision_id AND r.project_id=sm.project_id) END))
    $$;
    """)
    for table in ("material_documents", "material_revisions"):
        op.execute(f"ALTER TABLE app.{table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE app.{table} FORCE ROW LEVEL SECURITY")
        op.execute(f"GRANT SELECT ON app.{table} TO corpus_app")
        op.execute(
            f"CREATE POLICY member_read ON app.{table} FOR SELECT TO corpus_app USING(app.project_role(project_id) IS NOT NULL)"
        )
        op.execute(f"GRANT SELECT,INSERT ON app.{table} TO corpus_worker")
        op.execute(
            f"CREATE POLICY worker_read ON app.{table} FOR SELECT TO corpus_worker USING(true)"
        )
        op.execute(
            f"CREATE POLICY worker_add ON app.{table} FOR INSERT TO corpus_worker WITH CHECK(true)"
        )
    op.execute("""
    GRANT INSERT,UPDATE ON app.material_documents TO corpus_app;
    GRANT UPDATE ON app.material_documents TO corpus_worker;
    CREATE POLICY member_add ON app.material_documents FOR INSERT TO corpus_app WITH CHECK(app.project_role(project_id) IN ('owner','editor'));
    CREATE POLICY member_edit ON app.material_documents FOR UPDATE TO corpus_app USING(app.project_role(project_id) IN ('owner','editor')) WITH CHECK(app.project_role(project_id) IN ('owner','editor'));
    CREATE POLICY worker_edit ON app.material_documents FOR UPDATE TO corpus_worker USING(true) WITH CHECK(true);
    """)


def downgrade():
    raise RuntimeError(
        "Private immutable materials require an explicit data-preserving downgrade"
    )
