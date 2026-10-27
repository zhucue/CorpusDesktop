"""S1 accounts and project RLS, run only as the dedicated corpus_owner role."""

from alembic import op

revision = "0002_auth_projects"
down_revision = "0001_engineering_baseline"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
    CREATE TABLE app.users (
      id uuid PRIMARY KEY, email varchar(254) UNIQUE NOT NULL,
      password_hash varchar(512) NOT NULL,
      is_active boolean NOT NULL DEFAULT true,
      is_platform_admin boolean NOT NULL DEFAULT false,
      created_at timestamptz NOT NULL DEFAULT now()
    );
    CREATE TABLE app.login_sessions (
      token_hash varchar(64) PRIMARY KEY, user_id uuid NOT NULL REFERENCES app.users(id) ON DELETE CASCADE,
      csrf_hash varchar(64) NOT NULL, expires_at timestamptz NOT NULL,
      created_at timestamptz NOT NULL DEFAULT now()
    );
    CREATE INDEX ON app.login_sessions(user_id);
    CREATE INDEX ON app.login_sessions(expires_at);
    CREATE TABLE app.projects (
      id uuid PRIMARY KEY, owner_id uuid NOT NULL REFERENCES app.users(id),
      name varchar(160) NOT NULL, created_at timestamptz NOT NULL DEFAULT now(),
      UNIQUE (id,owner_id)
    );
    CREATE TABLE app.project_members (
      project_id uuid NOT NULL, user_id uuid NOT NULL REFERENCES app.users(id),
      owner_id uuid NOT NULL REFERENCES app.users(id), role varchar(10) NOT NULL,
      PRIMARY KEY(project_id,user_id),
      FOREIGN KEY(project_id,owner_id) REFERENCES app.projects(id,owner_id) ON DELETE CASCADE,
      CONSTRAINT member_role CHECK(role IN ('owner','editor','viewer')),
      CONSTRAINT owner_role_identity CHECK((role='owner')=(user_id=owner_id))
    );
    CREATE INDEX ON app.project_members(user_id,project_id);
    CREATE FUNCTION app.actor_id() RETURNS uuid LANGUAGE sql STABLE SECURITY INVOKER
      SET search_path=pg_catalog,app AS $$
      SELECT id FROM app.users WHERE id=nullif(current_setting('app.actor_id',true),'')::uuid AND is_active
    $$;
    REVOKE ALL ON FUNCTION app.actor_id() FROM PUBLIC;
    GRANT EXECUTE ON FUNCTION app.actor_id() TO corpus_app,corpus_worker;
    ALTER TABLE app.projects ENABLE ROW LEVEL SECURITY;
    ALTER TABLE app.projects FORCE ROW LEVEL SECURITY;
    ALTER TABLE app.project_members ENABLE ROW LEVEL SECURITY;
    ALTER TABLE app.project_members FORCE ROW LEVEL SECURITY;
    CREATE POLICY member_read ON app.project_members FOR SELECT TO corpus_app
      USING(user_id=app.actor_id() OR owner_id=app.actor_id());
    CREATE POLICY member_add ON app.project_members FOR INSERT TO corpus_app
      WITH CHECK(owner_id=app.actor_id());
    CREATE POLICY member_change ON app.project_members FOR UPDATE TO corpus_app
      USING(owner_id=app.actor_id() AND role<>'owner')
      WITH CHECK(owner_id=app.actor_id() AND role<>'owner');
    CREATE POLICY member_remove ON app.project_members FOR DELETE TO corpus_app
      USING(owner_id=app.actor_id() AND role<>'owner');
    CREATE POLICY project_read ON app.projects FOR SELECT TO corpus_app
      USING(owner_id=app.actor_id() OR EXISTS(
        SELECT 1 FROM app.project_members m WHERE m.project_id=id AND m.user_id=app.actor_id()));
    CREATE POLICY project_add ON app.projects FOR INSERT TO corpus_app
      WITH CHECK(owner_id=app.actor_id());
    CREATE POLICY project_change ON app.projects FOR UPDATE TO corpus_app
      USING(owner_id=app.actor_id() OR EXISTS(
        SELECT 1 FROM app.project_members m WHERE m.project_id=id AND m.user_id=app.actor_id() AND m.role='editor'))
      WITH CHECK(owner_id=app.actor_id() OR EXISTS(
        SELECT 1 FROM app.project_members m WHERE m.project_id=id AND m.user_id=app.actor_id() AND m.role='editor'));
    CREATE FUNCTION app.project_role(project uuid) RETURNS text LANGUAGE sql STABLE SECURITY INVOKER
      SET search_path=pg_catalog,app AS $$
      SELECT CASE WHEN p.owner_id=app.actor_id() THEN 'owner' ELSE m.role END
      FROM app.projects p LEFT JOIN app.project_members m ON m.project_id=p.id AND m.user_id=app.actor_id()
      WHERE p.id=project
    $$;
    REVOKE ALL ON FUNCTION app.project_role(uuid) FROM PUBLIC;
    GRANT EXECUTE ON FUNCTION app.project_role(uuid) TO corpus_app,corpus_worker;
    GRANT USAGE ON SCHEMA app TO corpus_app,corpus_worker;
    GRANT SELECT ON app.users TO corpus_app;
    GRANT UPDATE(password_hash) ON app.users TO corpus_app;
    GRANT SELECT,INSERT,DELETE ON app.login_sessions TO corpus_app;
    GRANT SELECT,INSERT ON app.projects TO corpus_app;
    GRANT UPDATE(name) ON app.projects TO corpus_app;
    GRANT SELECT,INSERT,DELETE ON app.project_members TO corpus_app;
    GRANT UPDATE(role) ON app.project_members TO corpus_app;
    """)


def downgrade():
    op.execute("""
    DROP FUNCTION app.project_role(uuid);
    DROP TABLE app.project_members;
    DROP TABLE app.projects;
    DROP FUNCTION app.actor_id();
    DROP TABLE app.login_sessions;
    DROP TABLE app.users;
    """)
