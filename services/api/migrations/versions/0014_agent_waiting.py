"""Durable user messages and fenced same-run background-job continuation."""

from alembic import op

revision = "0014_agent_waiting"
down_revision = "0013_export_unknown_size"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
    ALTER TABLE app.agent_sessions ADD COLUMN config_id varchar(60) NOT NULL DEFAULT 'local-fixture-v1';
    ALTER TABLE app.agent_runs ADD COLUMN config_id varchar(60) NOT NULL DEFAULT 'local-fixture-v1';
    ALTER TABLE app.agent_runs ADD COLUMN user_message text NOT NULL DEFAULT '';
    ALTER TABLE app.agent_runs ADD COLUMN request_digest varchar(64) NOT NULL DEFAULT '';
    ALTER TABLE app.agent_runs ADD COLUMN resume_checkpoint_id uuid;
    ALTER TABLE app.agent_runs ADD COLUMN active_deadline_at timestamptz;
    ALTER TABLE app.agent_runs ADD COLUMN wait_deadline_at timestamptz;
    ALTER TABLE app.agent_runs ADD COLUMN waiting_jobs jsonb NOT NULL DEFAULT '[]'::jsonb;
    ALTER TABLE app.agent_runs ADD CHECK(length(user_message)<=8000);
    ALTER TABLE app.agent_runs ADD CHECK(jsonb_typeof(waiting_jobs)='array');
    ALTER TABLE app.agent_checkpoints ADD CONSTRAINT agent_checkpoint_run_identity UNIQUE(id,run_id,session_id,actor_id);
    ALTER TABLE app.agent_runs ADD CONSTRAINT agent_resume_checkpoint_fk
      FOREIGN KEY(resume_checkpoint_id,id,session_id,actor_id)
      REFERENCES app.agent_checkpoints(id,run_id,session_id,actor_id);
    ALTER TABLE app.agent_runs DROP CONSTRAINT agent_runs_state_check;
    ALTER TABLE app.agent_runs ADD CONSTRAINT agent_runs_state_check
      CHECK(state IN ('QUEUED','RUNNING','WAITING_JOB','WAITING_REVIEW','CANCELLED','SUCCEEDED','FAILED'));
    DROP INDEX app.agent_one_active_run;
    CREATE UNIQUE INDEX agent_one_active_run ON app.agent_runs(session_id)
      WHERE state IN ('QUEUED','RUNNING','WAITING_JOB','WAITING_REVIEW');
    """)


def downgrade():
    raise RuntimeError(
        "Retain durable user messages and waiting checkpoints; downgrade requires explicit migration planning"
    )
