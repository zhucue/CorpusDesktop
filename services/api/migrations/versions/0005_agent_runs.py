"""Fenced Pi host control and atomic invocation ledger; no model execution grant."""

from alembic import op

revision = "0005_agent_runs"
down_revision = "0004_source_catalog"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
    CREATE TABLE app.agent_sessions (
      id uuid PRIMARY KEY, actor_id uuid NOT NULL REFERENCES app.users(id),
      scope jsonb NOT NULL, scope_digest varchar(64) NOT NULL,
      active_run_id uuid, lease_epoch integer NOT NULL CHECK(lease_epoch>=0),
      created_at timestamptz NOT NULL, UNIQUE(id,actor_id)
    );
    CREATE TABLE app.agent_runs (
      id uuid PRIMARY KEY, session_id uuid NOT NULL, actor_id uuid NOT NULL,
      request_key uuid NOT NULL, scope_digest varchar(64) NOT NULL,
      state varchar(30) NOT NULL CHECK(state IN ('QUEUED','RUNNING','WAITING_REVIEW','CANCELLED')),
      reason varchar(80), allowed_tools jsonb NOT NULL,
      lease_epoch integer NOT NULL CHECK(lease_epoch>=0),
      lease_expires_at timestamptz, host_id uuid,
      event_sequence bigint NOT NULL CHECK(event_sequence>=0),
      created_at timestamptz NOT NULL, updated_at timestamptz NOT NULL,
      FOREIGN KEY(session_id,actor_id) REFERENCES app.agent_sessions(id,actor_id),
      UNIQUE(id,actor_id), UNIQUE(session_id,request_key),
      CHECK((state='RUNNING')=(lease_expires_at IS NOT NULL AND host_id IS NOT NULL))
    );
    ALTER TABLE app.agent_sessions ADD FOREIGN KEY(active_run_id,actor_id)
      REFERENCES app.agent_runs(id,actor_id);
    CREATE UNIQUE INDEX agent_one_active_run ON app.agent_runs(session_id)
      WHERE state IN ('QUEUED','RUNNING','WAITING_REVIEW');
    CREATE INDEX ON app.agent_runs(state,created_at);
    CREATE TABLE app.agent_credentials (
      token_hash varchar(64) PRIMARY KEY, run_id uuid NOT NULL, actor_id uuid NOT NULL,
      session_id uuid NOT NULL, scope_digest varchar(64) NOT NULL,
      lease_epoch integer NOT NULL, expires_at timestamptz NOT NULL,
      FOREIGN KEY(run_id,actor_id) REFERENCES app.agent_runs(id,actor_id),
      FOREIGN KEY(session_id,actor_id) REFERENCES app.agent_sessions(id,actor_id)
    );
    CREATE TABLE app.agent_invocations (
      id uuid PRIMARY KEY, run_id uuid NOT NULL, actor_id uuid NOT NULL,
      request_key uuid NOT NULL, tool_call_id varchar(160) NOT NULL,
      tool_name varchar(80) NOT NULL, arguments_digest varchar(64) NOT NULL,
      action_id uuid UNIQUE, response jsonb NOT NULL, created_at timestamptz NOT NULL,
      FOREIGN KEY(run_id,actor_id) REFERENCES app.agent_runs(id,actor_id),
      UNIQUE(run_id,request_key)
    );
    CREATE TABLE app.agent_events (
      id uuid PRIMARY KEY, run_id uuid NOT NULL, actor_id uuid NOT NULL,
      sequence bigint NOT NULL CHECK(sequence>0), kind varchar(60) NOT NULL,
      payload jsonb NOT NULL, created_at timestamptz NOT NULL,
      FOREIGN KEY(run_id,actor_id) REFERENCES app.agent_runs(id,actor_id),
      UNIQUE(run_id,sequence)
    );
    """)
    for table in (
        "agent_sessions",
        "agent_runs",
        "agent_credentials",
        "agent_invocations",
        "agent_events",
    ):
        op.execute(f"ALTER TABLE app.{table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE app.{table} FORCE ROW LEVEL SECURITY")
        op.execute(f"GRANT SELECT,INSERT,UPDATE ON app.{table} TO corpus_app")
        if table == "agent_sessions":
            visible = """actor_id=app.actor_id() AND (
              scope->>'scope_kind'='account'
              OR (scope->>'scope_kind'='platform' AND EXISTS(
                SELECT 1 FROM app.users WHERE id=app.actor_id() AND is_platform_admin))
              OR (scope->>'scope_kind'='project' AND app.project_role((scope->>'project_id')::uuid) IS NOT NULL))"""
        elif table in {"agent_runs", "agent_credentials"}:
            visible = "actor_id=app.actor_id() AND EXISTS(SELECT 1 FROM app.agent_sessions s WHERE s.id=session_id)"
        else:
            visible = "actor_id=app.actor_id() AND EXISTS(SELECT 1 FROM app.agent_runs r WHERE r.id=run_id)"
        op.execute(
            f"CREATE POLICY actor_access ON app.{table} TO corpus_app USING({visible}) WITH CHECK({visible})"
        )
    # Only dedicated internal handlers set this after checking the host secret.
    op.execute("""
    CREATE POLICY host_lookup ON app.agent_runs FOR SELECT TO corpus_app
      USING(current_setting('app.agent_host',true)='true');
    CREATE POLICY credential_lookup ON app.agent_credentials FOR SELECT TO corpus_app
      USING(token_hash=current_setting('app.agent_token_hash',true));
    """)


def downgrade():
    op.execute(
        "ALTER TABLE app.agent_sessions DROP CONSTRAINT agent_sessions_active_run_id_actor_id_fkey"
    )
    for table in (
        "agent_events",
        "agent_invocations",
        "agent_credentials",
        "agent_runs",
        "agent_sessions",
    ):
        op.execute(f"DROP TABLE app.{table}")
