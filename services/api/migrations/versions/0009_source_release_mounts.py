"""Explicit fixed-input policy, immutable source publication and project RLS mounts."""

from alembic import op

revision = "0009_source_release_mounts"
down_revision = "0008_index_builds"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
    ALTER TABLE app.catalog_sources ADD COLUMN identity_revision integer NOT NULL DEFAULT 1 CHECK(identity_revision>0);
    CREATE TABLE app.source_policies (
      id uuid PRIMARY KEY, source_id varchar(64) NOT NULL, acquisition_id uuid NOT NULL,
      revision integer NOT NULL CHECK(revision>0), source_identity_revision integer NOT NULL,
      source_identity jsonb NOT NULL, acquisition_manifest_sha256 varchar(64) NOT NULL,
      license_sha256 varchar(64) NOT NULL, decision varchar(10) NOT NULL CHECK(decision IN ('allow','deny')),
      review_note varchar(4000) NOT NULL, evidence_urls jsonb NOT NULL,
      reviewed_by uuid NOT NULL REFERENCES app.users(id), reviewed_at timestamptz NOT NULL,
      FOREIGN KEY(acquisition_id,source_id) REFERENCES app.source_acquisitions(id,source_id),
      UNIQUE(acquisition_id,revision), UNIQUE(id,acquisition_id,source_id,revision)
    );
    CREATE TABLE app.source_policy_heads (
      acquisition_id uuid PRIMARY KEY REFERENCES app.source_acquisitions(id),
      source_id varchar(64) NOT NULL REFERENCES app.catalog_sources(source_id),
      policy_id uuid NOT NULL, revision integer NOT NULL,
      FOREIGN KEY(policy_id,acquisition_id,source_id,revision) REFERENCES app.source_policies(id,acquisition_id,source_id,revision)
    );
    ALTER TABLE app.source_indexes ADD CONSTRAINT source_index_source_unique UNIQUE(id,acquisition_id,source_id);
    ALTER TABLE app.catalog_releases
      ADD COLUMN source_snapshot_id uuid NOT NULL UNIQUE,
      ADD COLUMN index_id uuid NOT NULL UNIQUE,
      ADD COLUMN acquisition_id uuid NOT NULL,
      ADD COLUMN policy_id uuid NOT NULL,
      ADD COLUMN policy_revision integer NOT NULL,
      ADD COLUMN source_identity_revision integer NOT NULL,
      ADD COLUMN index_identity_sha256 varchar(64) NOT NULL,
      ADD COLUMN recipe jsonb NOT NULL,
      ADD COLUMN counts jsonb NOT NULL,
      ADD COLUMN quality jsonb NOT NULL,
      ADD CONSTRAINT release_index_source_fk FOREIGN KEY(index_id,acquisition_id,source_id) REFERENCES app.source_indexes(id,acquisition_id,source_id),
      ADD CONSTRAINT release_policy_source_fk FOREIGN KEY(policy_id,acquisition_id,source_id,policy_revision) REFERENCES app.source_policies(id,acquisition_id,source_id,revision),
      ADD CONSTRAINT release_source_unique UNIQUE(release_id,source_id);
    CREATE TABLE app.source_release_heads (
      source_id varchar(64) PRIMARY KEY REFERENCES app.catalog_sources(source_id),
      release_id uuid NOT NULL,
      FOREIGN KEY(release_id,source_id) REFERENCES app.catalog_releases(release_id,source_id)
    );
    CREATE TABLE app.source_release_actions (
      id uuid PRIMARY KEY, actor_id uuid NOT NULL REFERENCES app.users(id),
      operation varchar(30) NOT NULL CHECK(operation IN ('policies.update','releases.publish')),
      idempotency_key varchar(128) NOT NULL, request_sha256 varchar(64) NOT NULL,
      response jsonb NOT NULL, created_at timestamptz NOT NULL,
      UNIQUE(actor_id,operation,idempotency_key)
    );
    CREATE TABLE app.project_source_mounts (
      id uuid PRIMARY KEY, project_id uuid NOT NULL REFERENCES app.projects(id),
      source_snapshot_id uuid NOT NULL REFERENCES app.catalog_releases(source_snapshot_id),
      created_by uuid NOT NULL REFERENCES app.users(id), created_at timestamptz NOT NULL,
      removed_at timestamptz, UNIQUE(id,project_id)
    );
    CREATE UNIQUE INDEX mount_one_active_snapshot ON app.project_source_mounts(project_id,source_snapshot_id) WHERE removed_at IS NULL;
    CREATE TABLE app.mount_actions (
      id uuid PRIMARY KEY, actor_id uuid NOT NULL REFERENCES app.users(id),
      project_id uuid NOT NULL REFERENCES app.projects(id),
      operation varchar(30) NOT NULL CHECK(operation IN ('mounts.create','mounts.remove')),
      idempotency_key varchar(128) NOT NULL, request_sha256 varchar(64) NOT NULL,
      response jsonb NOT NULL, created_at timestamptz NOT NULL,
      UNIQUE(project_id,actor_id,operation,idempotency_key)
    );
    """)
    admin = "EXISTS(SELECT 1 FROM app.users WHERE id=app.actor_id() AND is_active AND is_platform_admin)"
    for table in (
        "source_policies",
        "source_policy_heads",
        "source_release_heads",
        "source_release_actions",
    ):
        op.execute(f"ALTER TABLE app.{table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE app.{table} FORCE ROW LEVEL SECURITY")
        read = (
            "app.actor_id() IS NOT NULL" if table != "source_release_actions" else admin
        )
        op.execute(
            f"CREATE POLICY policy_read ON app.{table} FOR SELECT TO corpus_app USING({read})"
        )
        op.execute(
            f"CREATE POLICY policy_add ON app.{table} FOR INSERT TO corpus_app WITH CHECK({admin})"
        )
        op.execute(f"GRANT SELECT,INSERT ON app.{table} TO corpus_app")
        if table != "source_policies":
            op.execute(
                f"CREATE POLICY policy_change ON app.{table} FOR UPDATE TO corpus_app USING({admin}) WITH CHECK({admin})"
            )
            op.execute(f"GRANT UPDATE ON app.{table} TO corpus_app")
    op.execute(
        f"CREATE POLICY release_add ON app.catalog_releases FOR INSERT TO corpus_app WITH CHECK({admin})"
    )
    op.execute("GRANT INSERT ON app.catalog_releases TO corpus_app")
    op.execute("""
    CREATE FUNCTION app.source_release_allowed(snapshot uuid) RETURNS boolean LANGUAGE sql STABLE SECURITY INVOKER
      SET search_path=pg_catalog,app AS $$
      SELECT EXISTS(SELECT 1 FROM app.catalog_releases r
       JOIN app.catalog_sources s ON s.source_id=r.source_id
       JOIN app.source_policy_heads h ON h.acquisition_id=r.acquisition_id
       JOIN app.source_policies p ON p.id=h.policy_id
       WHERE r.source_snapshot_id=snapshot AND p.decision='allow'
        AND p.source_identity_revision=s.identity_revision
        AND app.actor_id() IS NOT NULL)
    $$;
    REVOKE ALL ON FUNCTION app.source_release_allowed(uuid) FROM PUBLIC;
    GRANT EXECUTE ON FUNCTION app.source_release_allowed(uuid) TO corpus_app;
    ALTER TABLE app.project_source_mounts ENABLE ROW LEVEL SECURITY;
    ALTER TABLE app.project_source_mounts FORCE ROW LEVEL SECURITY;
    CREATE POLICY mount_read ON app.project_source_mounts FOR SELECT TO corpus_app USING(app.project_role(project_id) IS NOT NULL);
    CREATE POLICY mount_add ON app.project_source_mounts FOR INSERT TO corpus_app
      WITH CHECK(app.project_role(project_id) IN ('owner','editor') AND created_by=app.actor_id() AND app.source_release_allowed(source_snapshot_id));
    CREATE POLICY mount_remove ON app.project_source_mounts FOR UPDATE TO corpus_app
      USING(app.project_role(project_id) IN ('owner','editor')) WITH CHECK(app.project_role(project_id) IN ('owner','editor'));
    GRANT SELECT,INSERT ON app.project_source_mounts TO corpus_app;
    GRANT UPDATE(removed_at) ON app.project_source_mounts TO corpus_app;
    ALTER TABLE app.mount_actions ENABLE ROW LEVEL SECURITY;
    ALTER TABLE app.mount_actions FORCE ROW LEVEL SECURITY;
    CREATE POLICY mount_action_read ON app.mount_actions FOR SELECT TO corpus_app USING(actor_id=app.actor_id() AND app.project_role(project_id) IS NOT NULL);
    CREATE POLICY mount_action_add ON app.mount_actions FOR INSERT TO corpus_app WITH CHECK(actor_id=app.actor_id() AND app.project_role(project_id) IN ('owner','editor'));
    CREATE POLICY mount_action_change ON app.mount_actions FOR UPDATE TO corpus_app USING(actor_id=app.actor_id() AND app.project_role(project_id) IN ('owner','editor'));
    GRANT SELECT,INSERT,UPDATE ON app.mount_actions TO corpus_app;
    CREATE POLICY mounted_index_read ON app.source_indexes FOR SELECT TO corpus_app USING(EXISTS(
      SELECT 1 FROM app.catalog_releases r JOIN app.project_source_mounts m ON m.source_snapshot_id=r.source_snapshot_id
      WHERE r.index_id=source_indexes.id AND m.removed_at IS NULL AND app.project_role(m.project_id) IS NOT NULL AND app.source_release_allowed(r.source_snapshot_id)));
    """)


def downgrade():
    op.execute("DROP POLICY mounted_index_read ON app.source_indexes")
    op.execute("DROP TABLE app.mount_actions,app.project_source_mounts")
    op.execute("DROP FUNCTION app.source_release_allowed(uuid)")
    op.execute("DROP TABLE app.source_release_actions,app.source_release_heads")
    op.execute("DROP POLICY release_add ON app.catalog_releases")
    op.execute("REVOKE INSERT ON app.catalog_releases FROM corpus_app")
    op.execute("""ALTER TABLE app.catalog_releases DROP CONSTRAINT release_index_source_fk,DROP CONSTRAINT release_policy_source_fk,DROP CONSTRAINT release_source_unique,
      DROP COLUMN source_snapshot_id,DROP COLUMN index_id,DROP COLUMN acquisition_id,DROP COLUMN policy_id,DROP COLUMN policy_revision,DROP COLUMN source_identity_revision,
      DROP COLUMN index_identity_sha256,DROP COLUMN recipe,DROP COLUMN counts,DROP COLUMN quality""")
    op.execute("DROP TABLE app.source_policy_heads,app.source_policies")
    op.execute(
        "ALTER TABLE app.source_indexes DROP CONSTRAINT source_index_source_unique"
    )
    op.execute("ALTER TABLE app.catalog_sources DROP COLUMN identity_revision")
