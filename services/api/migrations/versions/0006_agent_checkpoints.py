"""Immutable private Pi checkpoints and conditionally published session pointers."""

from alembic import op

revision = "0006_agent_checkpoints"
down_revision = "0005_agent_runs"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
    ALTER TABLE app.agent_runs DROP CONSTRAINT agent_runs_state_check;
    ALTER TABLE app.agent_runs ADD CHECK(state IN ('QUEUED','RUNNING','WAITING_REVIEW','CANCELLED','SUCCEEDED'));
    ALTER TABLE app.agent_sessions ADD COLUMN latest_checkpoint_id uuid;
    ALTER TABLE app.agent_runs ADD COLUMN base_checkpoint_id uuid;
    ALTER TABLE app.agent_runs ADD COLUMN final_checkpoint_id uuid;
    ALTER TABLE app.agent_runs ADD UNIQUE(id,session_id,actor_id);
    CREATE TABLE app.agent_checkpoints (
      id uuid PRIMARY KEY, session_id uuid NOT NULL, run_id uuid NOT NULL,
      actor_id uuid NOT NULL, request_key uuid NOT NULL, base_checkpoint_id uuid,
      lease_epoch integer NOT NULL, event_sequence bigint NOT NULL,
      object_key varchar(255) NOT NULL UNIQUE, version_id varchar(255) NOT NULL,
      etag varchar(255) NOT NULL, sha256 varchar(64) NOT NULL,
      byte_size bigint NOT NULL CHECK(byte_size>0 AND byte_size<=8388608),
      sdk_session_id uuid NOT NULL, leaf_id varchar(160) NOT NULL,
      runtime_manifest jsonb NOT NULL, dependencies jsonb NOT NULL,
      created_at timestamptz NOT NULL,
      FOREIGN KEY(session_id,actor_id) REFERENCES app.agent_sessions(id,actor_id),
      FOREIGN KEY(run_id,session_id,actor_id) REFERENCES app.agent_runs(id,session_id,actor_id),
      UNIQUE(run_id,request_key), UNIQUE(id,session_id,actor_id),
      FOREIGN KEY(base_checkpoint_id,session_id,actor_id)
        REFERENCES app.agent_checkpoints(id,session_id,actor_id)
    );
    ALTER TABLE app.agent_sessions ADD FOREIGN KEY(latest_checkpoint_id,id,actor_id)
      REFERENCES app.agent_checkpoints(id,session_id,actor_id);
    ALTER TABLE app.agent_runs ADD FOREIGN KEY(base_checkpoint_id,session_id,actor_id)
      REFERENCES app.agent_checkpoints(id,session_id,actor_id);
    ALTER TABLE app.agent_runs ADD FOREIGN KEY(final_checkpoint_id,session_id,actor_id)
      REFERENCES app.agent_checkpoints(id,session_id,actor_id);
    ALTER TABLE app.agent_checkpoints ENABLE ROW LEVEL SECURITY;
    ALTER TABLE app.agent_checkpoints FORCE ROW LEVEL SECURITY;
    GRANT SELECT,INSERT ON app.agent_checkpoints TO corpus_app;
    CREATE POLICY actor_access ON app.agent_checkpoints TO corpus_app
      USING(actor_id=app.actor_id() AND EXISTS(SELECT 1 FROM app.agent_sessions s WHERE s.id=session_id))
      WITH CHECK(actor_id=app.actor_id() AND EXISTS(SELECT 1 FROM app.agent_sessions s WHERE s.id=session_id));
    """)


def downgrade():
    op.execute("""
    ALTER TABLE app.agent_runs DROP COLUMN final_checkpoint_id;
    ALTER TABLE app.agent_runs DROP COLUMN base_checkpoint_id;
    ALTER TABLE app.agent_sessions DROP COLUMN latest_checkpoint_id;
    DROP TABLE app.agent_checkpoints;
    ALTER TABLE app.agent_runs DROP CONSTRAINT agent_runs_id_session_id_actor_id_key;
    ALTER TABLE app.agent_runs DROP CONSTRAINT agent_runs_state_check;
    ALTER TABLE app.agent_runs ADD CHECK(state IN ('QUEUED','RUNNING','WAITING_REVIEW','CANCELLED'));
    """)
