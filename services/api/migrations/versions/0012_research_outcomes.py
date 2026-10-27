"""Fixed evidence, immutable note revisions and existing-ledger export jobs."""

from alembic import op

revision = "0012_research_outcomes"
down_revision = "0011_private_materials"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
    ALTER TABLE app.source_policies ADD COLUMN export_decision varchar(10) NOT NULL DEFAULT 'deny'
      CHECK(export_decision IN ('allow','deny'));
    ALTER TABLE app.jobs DROP CONSTRAINT jobs_kind_check;
    ALTER TABLE app.jobs ADD CHECK(kind IN ('UPLOAD_VALIDATE','TXT_IMPORT','EXPORT'));
    ALTER TABLE app.jobs ALTER COLUMN upload_id DROP NOT NULL;
    ALTER TABLE app.jobs ADD CHECK((kind='EXPORT' AND upload_id IS NULL AND input_sha256 IS NOT NULL)
       OR (kind IN ('UPLOAD_VALIDATE','TXT_IMPORT') AND upload_id IS NOT NULL));
    ALTER TABLE app.query_runs ADD CONSTRAINT query_run_project_unique UNIQUE(id,project_id);
    ALTER TABLE app.query_runs ADD CONSTRAINT query_fixed_identity_unique UNIQUE(id,result_set_id,snapshot_id,project_id);
    CREATE TABLE app.research_evidence (
      id uuid PRIMARY KEY, project_id uuid NOT NULL REFERENCES app.projects(id),
      created_by uuid NOT NULL REFERENCES app.users(id),
      query_run_id uuid NOT NULL, result_set_id uuid NOT NULL, snapshot_id uuid NOT NULL,
      ordinal bigint NOT NULL CHECK(ordinal>=0), coordinates jsonb NOT NULL,
      method jsonb NOT NULL, context_sha256 varchar(64) NOT NULL, created_at timestamptz NOT NULL,
      UNIQUE(id,project_id), UNIQUE(project_id,result_set_id,ordinal),
      FOREIGN KEY(query_run_id,result_set_id,snapshot_id,project_id)
        REFERENCES app.query_runs(id,result_set_id,snapshot_id,project_id)
    );
    CREATE TABLE app.research_notes (
      id uuid PRIMARY KEY, project_id uuid NOT NULL REFERENCES app.projects(id),
      created_by uuid NOT NULL REFERENCES app.users(id), current_revision integer NOT NULL CHECK(current_revision>0),
      created_at timestamptz NOT NULL, updated_at timestamptz NOT NULL, UNIQUE(id,project_id)
    );
    CREATE TABLE app.note_revisions (
      note_id uuid NOT NULL, revision integer NOT NULL CHECK(revision>0), project_id uuid NOT NULL,
      created_by uuid NOT NULL REFERENCES app.users(id), title varchar(200) NOT NULL, body varchar(200000) NOT NULL,
      evidence_ids jsonb NOT NULL, query_run_ids jsonb NOT NULL,
      authorization_evidence_ids jsonb NOT NULL, authorization_query_run_ids jsonb NOT NULL,
      created_at timestamptz NOT NULL, PRIMARY KEY(note_id,revision), UNIQUE(note_id,revision,project_id),
      FOREIGN KEY(note_id,project_id) REFERENCES app.research_notes(id,project_id),
      CHECK(jsonb_array_length(authorization_evidence_ids)+jsonb_array_length(authorization_query_run_ids)<=100)
    );
    ALTER TABLE app.research_notes ADD CONSTRAINT note_current_revision_fk
      FOREIGN KEY(id,current_revision,project_id) REFERENCES app.note_revisions(note_id,revision,project_id)
      DEFERRABLE INITIALLY DEFERRED;
    CREATE TABLE app.note_acceptances (
      note_id uuid NOT NULL, revision integer NOT NULL, project_id uuid NOT NULL,
      accepted_by uuid NOT NULL REFERENCES app.users(id), session_hash varchar(64) NOT NULL,
      accepted_at timestamptz NOT NULL, PRIMARY KEY(note_id,revision),
      FOREIGN KEY(note_id,revision,project_id) REFERENCES app.note_revisions(note_id,revision,project_id)
    );
    CREATE TABLE app.research_exports (
      id uuid PRIMARY KEY, project_id uuid NOT NULL, actor_id uuid NOT NULL REFERENCES app.users(id),
      target jsonb NOT NULL, format varchar(8) NOT NULL CHECK(format IN ('csv','json')),
      authorization_evidence_ids jsonb NOT NULL, authorization_query_run_ids jsonb NOT NULL,
      artifact jsonb, methods jsonb, created_at timestamptz NOT NULL,
      FOREIGN KEY(id,project_id) REFERENCES app.jobs(id,project_id),
      CHECK(jsonb_array_length(authorization_evidence_ids)+jsonb_array_length(authorization_query_run_ids)<=100)
    );
    CREATE FUNCTION app.outcome_dependencies_allowed(pid uuid, evidence_ids jsonb, query_ids jsonb)
      RETURNS boolean LANGUAGE sql STABLE SECURITY INVOKER SET search_path=pg_catalog,app AS $$
      SELECT app.project_role(pid) IS NOT NULL
        AND NOT EXISTS(SELECT 1 FROM jsonb_array_elements_text(evidence_ids) e(id)
          WHERE NOT EXISTS(SELECT 1 FROM app.research_evidence v WHERE v.id=e.id::uuid AND v.project_id=pid))
        AND NOT EXISTS(SELECT 1 FROM jsonb_array_elements_text(query_ids) q(id)
          WHERE NOT EXISTS(SELECT 1 FROM app.query_runs v WHERE v.id=q.id::uuid AND v.project_id=pid
           AND v.state='SUCCEEDED' AND v.counts IS NOT NULL AND app.research_snapshot_allowed(v.snapshot_id)))
    $$;
    REVOKE ALL ON FUNCTION app.outcome_dependencies_allowed(uuid,jsonb,jsonb) FROM PUBLIC;
    GRANT EXECUTE ON FUNCTION app.outcome_dependencies_allowed(uuid,jsonb,jsonb) TO corpus_app;
    """)
    for table in (
        "research_evidence",
        "research_notes",
        "note_revisions",
        "note_acceptances",
        "research_exports",
    ):
        op.execute(f"ALTER TABLE app.{table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE app.{table} FORCE ROW LEVEL SECURITY")
        op.execute(f"GRANT SELECT,INSERT ON app.{table} TO corpus_app")
        op.execute(f"GRANT SELECT ON app.{table} TO corpus_worker")
        op.execute(
            f"CREATE POLICY worker_read ON app.{table} FOR SELECT TO corpus_worker USING(true)"
        )
        readable = "app.project_role(project_id) IS NOT NULL"
        if table == "research_evidence":
            readable += " AND app.research_snapshot_allowed(snapshot_id)"
        if table in {"note_revisions", "research_exports"}:
            readable = "app.outcome_dependencies_allowed(project_id,authorization_evidence_ids,authorization_query_run_ids)"
        op.execute(
            f"CREATE POLICY outcome_read ON app.{table} FOR SELECT TO corpus_app USING({readable})"
        )
        writable = "app.project_role(project_id) IN ('owner','editor')"
        if table in {"research_evidence", "research_notes", "note_revisions"}:
            writable += " AND created_by=app.actor_id()"
        if table in {"research_evidence", "note_revisions"}:
            writable += " AND " + readable
        if table == "note_acceptances":
            writable += " AND accepted_by=app.actor_id()"
        if table == "research_exports":
            writable = readable + " AND actor_id=app.actor_id()"
        op.execute(
            f"CREATE POLICY outcome_add ON app.{table} FOR INSERT TO corpus_app WITH CHECK({writable})"
        )
    op.execute("""
    GRANT UPDATE(current_revision,updated_at) ON app.research_notes TO corpus_app;
    CREATE POLICY note_advance ON app.research_notes FOR UPDATE TO corpus_app
      USING(app.project_role(project_id) IN ('owner','editor')) WITH CHECK(app.project_role(project_id) IN ('owner','editor'));
    GRANT UPDATE(artifact,methods) ON app.research_exports TO corpus_worker;
    CREATE POLICY worker_publish ON app.research_exports FOR UPDATE TO corpus_worker USING(true) WITH CHECK(true);
    CREATE POLICY export_job_add ON app.jobs FOR INSERT TO corpus_app
      WITH CHECK(kind='EXPORT' AND actor_id=app.actor_id() AND app.project_role(project_id) IS NOT NULL);
    CREATE POLICY export_job_edit ON app.jobs FOR UPDATE TO corpus_app
      USING(kind='EXPORT' AND (actor_id=app.actor_id() OR app.project_role(project_id)='owner') AND app.project_role(project_id) IS NOT NULL)
      WITH CHECK(kind='EXPORT' AND (actor_id=app.actor_id() OR app.project_role(project_id)='owner') AND app.project_role(project_id) IS NOT NULL);
    CREATE POLICY export_action_add ON app.job_actions FOR INSERT TO corpus_app
      WITH CHECK(actor_id=app.actor_id() AND app.project_role(project_id) IS NOT NULL
        AND operation IN ('exports.create','jobs.cancel','jobs.retry'));
    CREATE POLICY export_action_edit ON app.job_actions FOR UPDATE TO corpus_app
      USING(actor_id=app.actor_id() AND app.project_role(project_id) IS NOT NULL
        AND operation IN ('exports.create','jobs.cancel','jobs.retry'));
    """)
    for table in ("job_attempts", "job_events", "job_outbox"):
        rule = f"EXISTS(SELECT 1 FROM app.jobs j WHERE j.id={table}.job_id AND j.project_id={table}.project_id AND j.kind='EXPORT' AND (j.actor_id=app.actor_id() OR app.project_role(j.project_id)='owner') AND app.project_role(j.project_id) IS NOT NULL)"
        op.execute(
            f"CREATE POLICY export_ledger_add ON app.{table} FOR INSERT TO corpus_app WITH CHECK({rule})"
        )
        op.execute(
            f"CREATE POLICY export_ledger_edit ON app.{table} FOR UPDATE TO corpus_app USING({rule}) WITH CHECK({rule})"
        )

    op.execute("""
    ALTER POLICY member_insert ON app.jobs WITH CHECK(kind<>'EXPORT' AND app.project_role(project_id) IN ('owner','editor'));
    ALTER POLICY member_update ON app.jobs USING(kind<>'EXPORT' AND app.project_role(project_id) IN ('owner','editor'))
      WITH CHECK(kind<>'EXPORT' AND app.project_role(project_id) IN ('owner','editor'));
    CREATE POLICY export_budget_owner_read ON app.research_exports FOR SELECT TO corpus_owner USING(true);
    CREATE POLICY export_budget_owner_read ON app.jobs FOR SELECT TO corpus_owner USING(true);
    CREATE POLICY export_budget_owner_read ON app.project_members FOR SELECT TO corpus_owner USING(true);
    CREATE FUNCTION app.export_project_bytes(pid uuid) RETURNS bigint LANGUAGE sql STABLE SECURITY DEFINER
      SET search_path=pg_catalog,app AS $$
      SELECT CASE WHEN EXISTS(SELECT 1 FROM app.project_members m JOIN app.users u ON u.id=m.user_id
        WHERE m.project_id=pid AND u.id=nullif(current_setting('app.actor_id',true),'')::uuid AND u.is_active)
      THEN (SELECT coalesce(sum((artifact->>'bytes')::bigint),0) FROM app.research_exports WHERE project_id=pid)
         + (SELECT coalesce(sum(reserved_bytes),0) FROM app.jobs WHERE project_id=pid AND kind='EXPORT')
      ELSE NULL END
    $$;
    REVOKE ALL ON FUNCTION app.export_project_bytes(uuid) FROM PUBLIC;
    GRANT EXECUTE ON FUNCTION app.export_project_bytes(uuid) TO corpus_app;
    """)
    for table in ("job_attempts", "job_events", "job_outbox"):
        rule = f"app.project_role(project_id) IN ('owner','editor') AND EXISTS(SELECT 1 FROM app.jobs j WHERE j.id={table}.job_id AND j.kind<>'EXPORT')"
        op.execute(f"ALTER POLICY member_insert ON app.{table} WITH CHECK({rule})")
        op.execute(
            f"ALTER POLICY member_update ON app.{table} USING({rule}) WITH CHECK({rule})"
        )


def downgrade():
    raise RuntimeError(
        "Immutable research outcomes require an explicit data-preserving downgrade"
    )
