"""Private indexed artifacts; no policy approval, public release or mount."""

from alembic import op

revision = "0008_index_builds"
down_revision = "0007_source_sync"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
    ALTER TABLE app.source_acquisitions ADD CONSTRAINT acquisition_source_unique UNIQUE(id,source_id);
    CREATE TABLE app.index_build_actions (
      id uuid PRIMARY KEY, actor_id uuid NOT NULL REFERENCES app.users(id),
      operation varchar(30) NOT NULL CHECK(operation IN ('indexes.build','indexes.cancel','indexes.retry')),
      idempotency_key varchar(128) NOT NULL, request_sha256 varchar(64) NOT NULL,
      response jsonb NOT NULL, created_at timestamptz NOT NULL,
      UNIQUE(actor_id,operation,idempotency_key)
    );
    CREATE TABLE app.index_build_runs (
      id uuid PRIMARY KEY, source_id varchar(64) NOT NULL,
      acquisition_id uuid NOT NULL, actor_id uuid NOT NULL REFERENCES app.users(id),
      source_identity jsonb NOT NULL, recipe jsonb NOT NULL, recipe_sha256 varchar(64) NOT NULL,
      state varchar(20) NOT NULL CHECK(state IN ('QUEUED','RUNNING','SUCCEEDED','FAILED','CANCELLED')),
      stage varchar(20) NOT NULL CHECK(stage IN ('QUEUED','FETCHING','INDEXING','VERIFYING','STORING','INDEXED','FAILED','CANCELLED')),
      attempt integer NOT NULL CHECK(attempt BETWEEN 1 AND 3),
      lease_epoch integer NOT NULL DEFAULT 0, lease_token uuid, lease_expires_at timestamptz,
      reserved_bytes bigint NOT NULL CHECK(reserved_bytes>=0), progress jsonb NOT NULL,
      result jsonb, error jsonb, event_sequence integer NOT NULL DEFAULT 0,
      created_at timestamptz NOT NULL, updated_at timestamptz NOT NULL,
      FOREIGN KEY(acquisition_id,source_id) REFERENCES app.source_acquisitions(id,source_id),
      UNIQUE(id,acquisition_id,source_id,recipe_sha256)
    );
    CREATE UNIQUE INDEX index_build_one_active ON app.index_build_runs(source_id)
      WHERE state IN ('QUEUED','RUNNING');
    CREATE TABLE app.index_build_attempts (
      run_id uuid NOT NULL REFERENCES app.index_build_runs(id), number integer NOT NULL,
      state varchar(20) NOT NULL, lease_epoch integer NOT NULL DEFAULT 0,
      started_at timestamptz, finished_at timestamptz, error jsonb, PRIMARY KEY(run_id,number)
    );
    CREATE TABLE app.index_build_events (
      run_id uuid NOT NULL REFERENCES app.index_build_runs(id), sequence integer NOT NULL,
      event_type varchar(50) NOT NULL, data jsonb NOT NULL, created_at timestamptz NOT NULL,
      PRIMARY KEY(run_id,sequence)
    );
    CREATE TABLE app.index_build_outbox (
      run_id uuid NOT NULL REFERENCES app.index_build_runs(id), attempt integer NOT NULL,
      published_at timestamptz, failures integer NOT NULL DEFAULT 0, last_error varchar(80),
      next_attempt_at timestamptz NOT NULL, PRIMARY KEY(run_id,attempt),
      FOREIGN KEY(run_id,attempt) REFERENCES app.index_build_attempts(run_id,number)
    );
    CREATE TABLE app.source_indexes (
      id uuid PRIMARY KEY, run_id uuid NOT NULL UNIQUE, acquisition_id uuid NOT NULL,
      source_id varchar(64) NOT NULL, recipe_sha256 varchar(64) NOT NULL,
      identity_sha256 varchar(64) NOT NULL, manifest_sha256 varchar(64) NOT NULL,
      manifest jsonb NOT NULL, objects jsonb NOT NULL, artifact_bytes bigint NOT NULL CHECK(artifact_bytes>=0),
      created_at timestamptz NOT NULL,
      FOREIGN KEY(run_id,acquisition_id,source_id,recipe_sha256)
        REFERENCES app.index_build_runs(id,acquisition_id,source_id,recipe_sha256),
      UNIQUE(acquisition_id,recipe_sha256)
    );
    """)
    for table in (
        "index_build_runs",
        "index_build_actions",
        "index_build_attempts",
        "index_build_events",
        "index_build_outbox",
        "source_indexes",
    ):
        op.execute(f"ALTER TABLE app.{table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE app.{table} FORCE ROW LEVEL SECURITY")
        admin = "EXISTS(SELECT 1 FROM app.users WHERE id=app.actor_id() AND is_active AND is_platform_admin)"
        op.execute(
            f"CREATE POLICY admin_read ON app.{table} FOR SELECT TO corpus_app USING({admin})"
        )
        op.execute(f"GRANT SELECT ON app.{table} TO corpus_app")
        if table != "source_indexes":
            op.execute(
                f"CREATE POLICY admin_add ON app.{table} FOR INSERT TO corpus_app WITH CHECK({admin})"
            )
            op.execute(f"GRANT INSERT ON app.{table} TO corpus_app")
        if table in {"index_build_runs", "index_build_attempts", "index_build_actions"}:
            op.execute(
                f"CREATE POLICY admin_change ON app.{table} FOR UPDATE TO corpus_app USING({admin}) WITH CHECK({admin})"
            )
            op.execute(f"GRANT UPDATE ON app.{table} TO corpus_app")
        if table != "index_build_actions":
            op.execute(
                f"CREATE POLICY worker_read ON app.{table} FOR SELECT TO corpus_worker USING(true)"
            )
            op.execute(f"GRANT SELECT ON app.{table} TO corpus_worker")
            if table in {"source_indexes", "index_build_events"}:
                op.execute(
                    f"CREATE POLICY worker_add ON app.{table} FOR INSERT TO corpus_worker WITH CHECK(true)"
                )
                op.execute(f"GRANT INSERT ON app.{table} TO corpus_worker")
            if table in {
                "index_build_runs",
                "index_build_attempts",
                "index_build_outbox",
            }:
                op.execute(
                    f"CREATE POLICY worker_change ON app.{table} FOR UPDATE TO corpus_worker USING(true) WITH CHECK(true)"
                )
                op.execute(f"GRANT UPDATE ON app.{table} TO corpus_worker")


def downgrade():
    op.execute(
        "DROP TABLE app.source_indexes,app.index_build_outbox,app.index_build_events,app.index_build_attempts,app.index_build_runs,app.index_build_actions"
    )
    op.execute(
        "ALTER TABLE app.source_acquisitions DROP CONSTRAINT acquisition_source_unique"
    )
