"""Project snapshots and background first-page/full-span research queries."""

from alembic import op

revision = "0010_research_queries"
down_revision = "0009_source_release_mounts"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
    CREATE TABLE app.research_snapshots (
      id uuid PRIMARY KEY, project_id uuid NOT NULL REFERENCES app.projects(id),
      created_by uuid NOT NULL REFERENCES app.users(id), name varchar(160) NOT NULL,
      state varchar(20) NOT NULL CHECK(state IN ('PREPARING','READY','FAILED')),
      manifest jsonb NOT NULL, manifest_sha256 varchar(64) NOT NULL,
      created_at timestamptz NOT NULL, updated_at timestamptz NOT NULL,
      UNIQUE(id,project_id)
    );
    CREATE TABLE app.research_snapshot_members (
      snapshot_id uuid NOT NULL, ordinal integer NOT NULL CHECK(ordinal>=0),
      project_id uuid NOT NULL, kind varchar(30) NOT NULL CHECK(kind='whole_source_mount'),
      mount_id uuid NOT NULL, descriptor jsonb NOT NULL, PRIMARY KEY(snapshot_id,ordinal),
      FOREIGN KEY(snapshot_id,project_id) REFERENCES app.research_snapshots(id,project_id),
      FOREIGN KEY(mount_id,project_id) REFERENCES app.project_source_mounts(id,project_id)
    );
    CREATE TABLE app.query_runs (
      id uuid PRIMARY KEY, project_id uuid NOT NULL, snapshot_id uuid NOT NULL,
      actor_id uuid NOT NULL REFERENCES app.users(id), result_set_id uuid NOT NULL UNIQUE,
      name varchar(160) NOT NULL, query jsonb NOT NULL, query_sha256 varchar(64) NOT NULL,
      page_size integer NOT NULL CHECK(page_size BETWEEN 1 AND 50),
      context_codepoints integer NOT NULL CHECK(context_codepoints BETWEEN 0 AND 200),
      state varchar(20) NOT NULL CHECK(state IN ('QUEUED','RUNNING','SUCCEEDED','FAILED','CANCELLED')),
      attempt integer NOT NULL CHECK(attempt BETWEEN 1 AND 3), first_page jsonb, counts jsonb,
      result_object jsonb, reserved_bytes bigint NOT NULL CHECK(reserved_bytes>=0), error jsonb,
      created_at timestamptz NOT NULL, updated_at timestamptz NOT NULL,
      FOREIGN KEY(snapshot_id,project_id) REFERENCES app.research_snapshots(id,project_id),
      UNIQUE(id,snapshot_id,project_id),
      CHECK((state='SUCCEEDED') = (result_object IS NOT NULL AND counts IS NOT NULL))
    );
    CREATE TABLE app.research_tasks (
      id uuid PRIMARY KEY, project_id uuid NOT NULL, snapshot_id uuid NOT NULL, run_id uuid,
      actor_id uuid NOT NULL REFERENCES app.users(id),
      phase varchar(20) NOT NULL CHECK(phase IN ('SNAPSHOT','FIRST_PAGE','FULL_RESULT','PREPARE_CACHE')),
      state varchar(20) NOT NULL CHECK(state IN ('QUEUED','RUNNING','SUCCEEDED','FAILED','CANCELLED')),
      attempt integer NOT NULL CHECK(attempt BETWEEN 1 AND 3), lease_epoch integer NOT NULL,
      lease_token uuid, lease_expires_at timestamptz, progress jsonb NOT NULL, error jsonb,
      created_at timestamptz NOT NULL, updated_at timestamptz NOT NULL,
      FOREIGN KEY(snapshot_id,project_id) REFERENCES app.research_snapshots(id,project_id),
      FOREIGN KEY(run_id,snapshot_id,project_id) REFERENCES app.query_runs(id,snapshot_id,project_id),
      CHECK((phase='SNAPSHOT') = (run_id IS NULL))
    );
    CREATE UNIQUE INDEX research_one_snapshot_task ON app.research_tasks(snapshot_id) WHERE phase='SNAPSHOT';
    CREATE UNIQUE INDEX research_one_run_phase ON app.research_tasks(run_id,phase) WHERE run_id IS NOT NULL;
    CREATE TABLE app.research_outbox (
      task_id uuid NOT NULL REFERENCES app.research_tasks(id), attempt integer NOT NULL,
      published_at timestamptz, failures integer NOT NULL DEFAULT 0,
      next_attempt_at timestamptz NOT NULL, PRIMARY KEY(task_id,attempt)
    );
    CREATE TABLE app.research_events (
      id uuid PRIMARY KEY, task_id uuid NOT NULL REFERENCES app.research_tasks(id),
      attempt integer NOT NULL, kind varchar(40) NOT NULL, data jsonb NOT NULL, created_at timestamptz NOT NULL
    );
    CREATE TABLE app.research_actions (
      id uuid PRIMARY KEY, project_id uuid NOT NULL REFERENCES app.projects(id),
      actor_id uuid NOT NULL REFERENCES app.users(id), operation varchar(40) NOT NULL,
      idempotency_key varchar(128) NOT NULL, request_sha256 varchar(64) NOT NULL,
      response jsonb NOT NULL, created_at timestamptz NOT NULL,
      UNIQUE(project_id,actor_id,operation,idempotency_key)
    );
    CREATE FUNCTION app.research_snapshot_allowed(sid uuid) RETURNS boolean LANGUAGE sql STABLE SECURITY INVOKER
      SET search_path=pg_catalog,app AS $$
      SELECT EXISTS(SELECT 1 FROM app.research_snapshot_members sm
        JOIN app.project_source_mounts m ON m.id=sm.mount_id AND m.project_id=sm.project_id
        WHERE sm.snapshot_id=sid AND app.project_role(sm.project_id) IS NOT NULL
        AND m.removed_at IS NULL AND app.source_release_allowed(m.source_snapshot_id))
    $$;
    REVOKE ALL ON FUNCTION app.research_snapshot_allowed(uuid) FROM PUBLIC;
    GRANT EXECUTE ON FUNCTION app.research_snapshot_allowed(uuid) TO corpus_app;
    """)
    for table in (
        "research_snapshots",
        "research_snapshot_members",
        "query_runs",
        "research_tasks",
        "research_outbox",
        "research_events",
        "research_actions",
    ):
        op.execute(f"ALTER TABLE app.{table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE app.{table} FORCE ROW LEVEL SECURITY")
        op.execute(
            f"CREATE POLICY worker_all ON app.{table} TO corpus_worker USING(true) WITH CHECK(true)"
        )
        op.execute(f"GRANT SELECT,INSERT,UPDATE ON app.{table} TO corpus_worker")
        if table in {"research_outbox", "research_events"}:
            read = "EXISTS(SELECT 1 FROM app.research_tasks t WHERE t.id=task_id)"
            write = read
        else:
            read = "app.project_role(project_id) IS NOT NULL"
            write = read
        if table == "query_runs":
            read += " AND app.research_snapshot_allowed(snapshot_id)"
            write = read + " AND actor_id=app.actor_id()"
        elif table == "research_tasks":
            write += " AND actor_id=app.actor_id() AND (phase<>'SNAPSHOT' OR app.project_role(project_id) IN ('owner','editor'))"
        elif table in {"research_snapshots", "research_snapshot_members"}:
            write = "app.project_role(project_id) IN ('owner','editor')"
        elif table == "research_actions":
            read += " AND actor_id=app.actor_id()"
            write = (
                read
                + " AND (operation NOT LIKE 'snapshots.%' OR app.project_role(project_id) IN ('owner','editor'))"
            )
        op.execute(
            f"CREATE POLICY member_read ON app.{table} FOR SELECT TO corpus_app USING({read})"
        )
        op.execute(
            f"CREATE POLICY member_add ON app.{table} FOR INSERT TO corpus_app WITH CHECK({write})"
        )
        if table not in {"research_snapshot_members", "research_events"}:
            update = write
            if table in {"query_runs", "research_tasks"}:
                update = "app.project_role(project_id) IS NOT NULL AND (actor_id=app.actor_id() OR app.project_role(project_id)='owner')"
            if table == "research_tasks":
                update = "app.project_role(project_id) IS NOT NULL AND (phase='PREPARE_CACHE' OR actor_id=app.actor_id() OR app.project_role(project_id)='owner')"
            op.execute(
                f"CREATE POLICY member_change ON app.{table} FOR UPDATE TO corpus_app USING({update}) WITH CHECK({update})"
            )
            op.execute(f"GRANT UPDATE ON app.{table} TO corpus_app")
        op.execute(f"GRANT SELECT,INSERT ON app.{table} TO corpus_app")
    # Worker authorization uses the initiating actor in Python under the same actor/project/source locks.
    for table in (
        "project_source_mounts",
        "source_policies",
        "source_policy_heads",
        "catalog_releases",
    ):
        op.execute(
            f"CREATE POLICY research_worker_read ON app.{table} FOR SELECT TO corpus_worker USING(true)"
        )
        op.execute(f"GRANT SELECT ON app.{table} TO corpus_worker")


def downgrade():
    for table in (
        "project_source_mounts",
        "source_policies",
        "source_policy_heads",
        "catalog_releases",
    ):
        op.execute(f"DROP POLICY research_worker_read ON app.{table}")
    op.execute(
        "DROP TABLE app.research_actions,app.research_events,app.research_outbox,app.research_tasks,app.query_runs"
    )
    op.execute("DROP FUNCTION app.research_snapshot_allowed(uuid)")
    op.execute("DROP TABLE app.research_snapshot_members,app.research_snapshots")
