"""Separate platform synchronization and immutable, unpublished acquisitions."""

from alembic import op

revision = "0007_source_sync"
down_revision = "0006_agent_checkpoints"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
    CREATE TABLE app.source_sync_actions (
      id uuid PRIMARY KEY, actor_id uuid NOT NULL REFERENCES app.users(id),
      operation varchar(30) NOT NULL CHECK(operation IN ('sync.start','sync.cancel','sync.retry')),
      idempotency_key varchar(128) NOT NULL, request_sha256 varchar(64) NOT NULL,
      response jsonb NOT NULL, created_at timestamptz NOT NULL,
      UNIQUE(actor_id,operation,idempotency_key)
    );
    CREATE TABLE app.source_sync_runs (
      id uuid PRIMARY KEY, source_id varchar(64) NOT NULL REFERENCES app.catalog_sources(source_id),
      actor_id uuid NOT NULL REFERENCES app.users(id), connector_id varchar(80) NOT NULL,
      source_revision integer NOT NULL, source_identity jsonb NOT NULL,
      previous_acquisition_id uuid,
      state varchar(20) NOT NULL CHECK(state IN ('QUEUED','RUNNING','SUCCEEDED','FAILED','CANCELLED')),
      stage varchar(20) NOT NULL CHECK(stage IN ('QUEUED','ACQUIRING','PARSING','STORING','VALIDATED','FAILED','CANCELLED')),
      attempt integer NOT NULL CHECK(attempt BETWEEN 1 AND 3),
      lease_epoch integer NOT NULL DEFAULT 0, lease_token uuid, lease_expires_at timestamptz,
      progress jsonb NOT NULL, expected_inputs jsonb, result jsonb, error jsonb,
      event_sequence integer NOT NULL DEFAULT 0, created_at timestamptz NOT NULL, updated_at timestamptz NOT NULL,
      UNIQUE(id,source_id,connector_id)
    );
    CREATE UNIQUE INDEX source_sync_one_active ON app.source_sync_runs(source_id)
      WHERE state IN ('QUEUED','RUNNING');
    CREATE TABLE app.source_sync_attempts (
      run_id uuid NOT NULL REFERENCES app.source_sync_runs(id), number integer NOT NULL,
      state varchar(20) NOT NULL, lease_epoch integer NOT NULL DEFAULT 0,
      started_at timestamptz, finished_at timestamptz, error jsonb, PRIMARY KEY(run_id,number)
    );
    CREATE TABLE app.source_sync_events (
      run_id uuid NOT NULL REFERENCES app.source_sync_runs(id), sequence integer NOT NULL,
      event_type varchar(50) NOT NULL, data jsonb NOT NULL, created_at timestamptz NOT NULL,
      PRIMARY KEY(run_id,sequence)
    );
    CREATE TABLE app.source_sync_outbox (
      run_id uuid NOT NULL REFERENCES app.source_sync_runs(id), attempt integer NOT NULL,
      published_at timestamptz, failures integer NOT NULL DEFAULT 0, last_error varchar(80),
      next_attempt_at timestamptz NOT NULL, PRIMARY KEY(run_id,attempt),
      FOREIGN KEY(run_id,attempt) REFERENCES app.source_sync_attempts(run_id,number)
    );
    CREATE TABLE app.source_acquisitions (
      id uuid PRIMARY KEY, run_id uuid NOT NULL UNIQUE,
      source_id varchar(64) NOT NULL, connector_id varchar(80) NOT NULL,
      source_identity jsonb NOT NULL, manifest_sha256 varchar(64) NOT NULL,
      manifest jsonb NOT NULL, objects jsonb NOT NULL, created_at timestamptz NOT NULL,
      FOREIGN KEY(run_id,source_id,connector_id) REFERENCES app.source_sync_runs(id,source_id,connector_id),
      UNIQUE(id,source_id,connector_id)
    );
    ALTER TABLE app.source_sync_runs ADD CONSTRAINT source_sync_previous_acquisition_fk FOREIGN KEY(previous_acquisition_id,source_id,connector_id)
      REFERENCES app.source_acquisitions(id,source_id,connector_id);
    CREATE POLICY source_worker_read ON app.catalog_sources FOR SELECT TO corpus_worker USING(true);
    GRANT SELECT ON app.catalog_sources TO corpus_worker;
    """)
    for table in (
        "source_sync_runs",
        "source_sync_actions",
        "source_sync_attempts",
        "source_sync_events",
        "source_sync_outbox",
        "source_acquisitions",
    ):
        op.execute(f"ALTER TABLE app.{table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE app.{table} FORCE ROW LEVEL SECURITY")
        admin = "EXISTS(SELECT 1 FROM app.users WHERE id=app.actor_id() AND is_active AND is_platform_admin)"
        op.execute(
            f"CREATE POLICY admin_read ON app.{table} FOR SELECT TO corpus_app USING({admin})"
        )
        op.execute(f"GRANT SELECT ON app.{table} TO corpus_app")
        if table != "source_acquisitions":
            op.execute(
                f"CREATE POLICY admin_add ON app.{table} FOR INSERT TO corpus_app WITH CHECK({admin})"
            )
            op.execute(f"GRANT INSERT ON app.{table} TO corpus_app")
        if table in {"source_sync_runs", "source_sync_attempts", "source_sync_actions"}:
            op.execute(
                f"CREATE POLICY admin_change ON app.{table} FOR UPDATE TO corpus_app USING({admin}) WITH CHECK({admin})"
            )
            op.execute(f"GRANT UPDATE ON app.{table} TO corpus_app")
        if table != "source_sync_actions":
            op.execute(
                f"CREATE POLICY worker_read ON app.{table} FOR SELECT TO corpus_worker USING(true)"
            )
            op.execute(f"GRANT SELECT ON app.{table} TO corpus_worker")
            if table in {"source_acquisitions", "source_sync_events"}:
                op.execute(
                    f"CREATE POLICY worker_add ON app.{table} FOR INSERT TO corpus_worker WITH CHECK(true)"
                )
                op.execute(f"GRANT INSERT ON app.{table} TO corpus_worker")
            if table in {
                "source_sync_runs",
                "source_sync_attempts",
                "source_sync_outbox",
            }:
                op.execute(
                    f"CREATE POLICY worker_change ON app.{table} FOR UPDATE TO corpus_worker USING(true) WITH CHECK(true)"
                )
                op.execute(f"GRANT UPDATE ON app.{table} TO corpus_worker")


def downgrade():
    op.execute(
        "ALTER TABLE app.source_sync_runs DROP CONSTRAINT source_sync_previous_acquisition_fk"
    )
    op.execute(
        "DROP TABLE app.source_acquisitions,app.source_sync_outbox,app.source_sync_events,app.source_sync_attempts,app.source_sync_runs,app.source_sync_actions"
    )
    op.execute("DROP POLICY source_worker_read ON app.catalog_sources")
