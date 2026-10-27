"""Private versioned upload sessions, durable actions/jobs/outbox and RLS."""

from alembic import op

revision = "0003_upload_jobs"
down_revision = "0002_auth_projects"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
    CREATE TABLE app.upload_sessions (
      id uuid PRIMARY KEY, project_id uuid NOT NULL REFERENCES app.projects(id),
      actor_id uuid NOT NULL REFERENCES app.users(id), filename varchar(255) NOT NULL,
      media_type varchar(100) NOT NULL, expected_size bigint NOT NULL CHECK(expected_size>0),
      expected_sha256 varchar(64) NOT NULL CHECK(expected_sha256 ~ '^[0-9a-f]{64}$'),
      object_key varchar(255) NOT NULL UNIQUE, version_id varchar(255), etag varchar(255),
      state varchar(30) NOT NULL CHECK(state IN ('CREATED','UPLOADING','UPLOADED','VALIDATING','VALIDATED','VALIDATION_FAILED','FAILED','CANCELLED')),
      error_code varchar(80), created_at timestamptz NOT NULL, expires_at timestamptz NOT NULL,
      UNIQUE(id,project_id), CHECK(expires_at>created_at),
      CHECK(state NOT IN ('UPLOADED','VALIDATING','VALIDATED','VALIDATION_FAILED','CANCELLED') OR (version_id IS NOT NULL AND etag IS NOT NULL))
    );
    CREATE INDEX ON app.upload_sessions(project_id,state);
    CREATE TABLE app.job_actions (
      id uuid PRIMARY KEY, project_id uuid NOT NULL REFERENCES app.projects(id),
      actor_id uuid NOT NULL REFERENCES app.users(id), operation varchar(60) NOT NULL,
      idempotency_key varchar(128) NOT NULL, request_sha256 varchar(64) NOT NULL,
      response jsonb NOT NULL, created_at timestamptz NOT NULL,
      UNIQUE(project_id,actor_id,operation,idempotency_key), UNIQUE(id,project_id)
    );
    CREATE TABLE app.jobs (
      id uuid PRIMARY KEY, project_id uuid NOT NULL REFERENCES app.projects(id),
      actor_id uuid NOT NULL REFERENCES app.users(id), action_id uuid NOT NULL,
      upload_id uuid NOT NULL UNIQUE, kind varchar(40) NOT NULL CHECK(kind='UPLOAD_VALIDATE'),
      state varchar(30) NOT NULL CHECK(state IN ('QUEUED','RUNNING','SUCCEEDED','FAILED','CANCELLED')),
      attempt integer NOT NULL CHECK(attempt BETWEEN 1 AND 3),
      lease_epoch integer NOT NULL CHECK(lease_epoch>=0), lease_token uuid, lease_expires_at timestamptz,
      processed_bytes bigint NOT NULL CHECK(processed_bytes>=0), total_bytes bigint NOT NULL CHECK(total_bytes>0),
      error jsonb, result jsonb, event_sequence integer NOT NULL CHECK(event_sequence>=0),
      created_at timestamptz NOT NULL, updated_at timestamptz NOT NULL,
      UNIQUE(id,project_id),
      FOREIGN KEY(upload_id,project_id) REFERENCES app.upload_sessions(id,project_id),
      FOREIGN KEY(action_id,project_id) REFERENCES app.job_actions(id,project_id),
      CHECK((state='RUNNING')=(lease_token IS NOT NULL AND lease_expires_at IS NOT NULL)),
      CHECK((state='SUCCEEDED')=(result IS NOT NULL)),
      CHECK((state='FAILED')=(error IS NOT NULL))
    );
    CREATE INDEX ON app.jobs(project_id,created_at,id);
    CREATE INDEX ON app.jobs(state,lease_expires_at);
    CREATE TABLE app.job_attempts (
      job_id uuid NOT NULL, project_id uuid NOT NULL, number integer NOT NULL CHECK(number BETWEEN 1 AND 3),
      state varchar(30) NOT NULL CHECK(state IN ('QUEUED','RUNNING','SUCCEEDED','FAILED','CANCELLED')),
      lease_epoch integer NOT NULL CHECK(lease_epoch>=0), started_at timestamptz, finished_at timestamptz,
      error jsonb, PRIMARY KEY(job_id,number),
      FOREIGN KEY(job_id,project_id) REFERENCES app.jobs(id,project_id)
    );
    CREATE TABLE app.job_events (
      id uuid PRIMARY KEY, project_id uuid NOT NULL, job_id uuid NOT NULL,
      sequence integer NOT NULL CHECK(sequence>0), kind varchar(50) NOT NULL, state varchar(30) NOT NULL,
      attempt integer NOT NULL, payload jsonb NOT NULL, created_at timestamptz NOT NULL,
      UNIQUE(job_id,sequence), FOREIGN KEY(job_id,project_id) REFERENCES app.jobs(id,project_id)
    );
    CREATE TABLE app.job_outbox (
      id uuid PRIMARY KEY, project_id uuid NOT NULL, job_id uuid NOT NULL, attempt integer NOT NULL,
      published_at timestamptz, failures integer NOT NULL CHECK(failures>=0), last_error varchar(80),
      next_attempt_at timestamptz NOT NULL, UNIQUE(job_id,attempt),
      FOREIGN KEY(job_id,project_id) REFERENCES app.jobs(id,project_id)
    );
    CREATE INDEX ON app.job_outbox(next_attempt_at) WHERE published_at IS NULL;
    GRANT SELECT ON app.users,app.projects,app.project_members TO corpus_worker;
    CREATE POLICY worker_project_read ON app.projects FOR SELECT TO corpus_worker USING(true);
    CREATE POLICY worker_member_read ON app.project_members FOR SELECT TO corpus_worker USING(true);
    """)
    for table in ("upload_sessions", "jobs", "job_attempts", "job_events", "job_actions", "job_outbox"):
        op.execute(f"ALTER TABLE app.{table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE app.{table} FORCE ROW LEVEL SECURITY")
        op.execute(f"GRANT SELECT,INSERT,UPDATE ON app.{table} TO corpus_app,corpus_worker")
        op.execute(f"CREATE POLICY worker_access ON app.{table} TO corpus_worker USING(true) WITH CHECK(true)")
        read = "actor_id=app.actor_id() AND app.project_role(project_id) IS NOT NULL" if table == "job_actions" else "app.project_role(project_id) IS NOT NULL"
        write = "app.project_role(project_id) IN ('owner','editor')"
        if table in {"upload_sessions", "job_actions"}:
            write += " AND actor_id=app.actor_id()"
        op.execute(f"CREATE POLICY member_read ON app.{table} FOR SELECT TO corpus_app USING({read})")
        op.execute(f"CREATE POLICY member_insert ON app.{table} FOR INSERT TO corpus_app WITH CHECK({write})")
        if table == "upload_sessions":
            write = "app.project_role(project_id) IN ('owner','editor') AND (actor_id=app.actor_id() OR app.project_role(project_id)='owner')"
        op.execute(f"CREATE POLICY member_update ON app.{table} FOR UPDATE TO corpus_app USING({write}) WITH CHECK({write})")


def downgrade():
    for table in ("job_outbox", "job_events", "job_attempts", "jobs", "job_actions", "upload_sessions"):
        op.execute(f"DROP TABLE app.{table}")
    op.execute("DROP POLICY worker_project_read ON app.projects")
    op.execute("DROP POLICY worker_member_read ON app.project_members")
    op.execute("REVOKE SELECT ON app.users,app.projects,app.project_members FROM corpus_worker")
