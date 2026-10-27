"""Authenticated shared discovery catalog; S0 samples are not releases."""

import hashlib
import json
from pathlib import Path

from alembic import op
from sqlalchemy import text

revision = "0004_source_catalog"
down_revision = "0003_upload_jobs"
branch_labels = None
depends_on = None


def decode_seed(raw):
    data = json.loads(raw)
    canonical = json.dumps(
        data, sort_keys=True, ensure_ascii=False, separators=(",", ":")
    ).encode()
    if (
        hashlib.sha256(canonical).hexdigest()
        != "d57088bcfbffa4c77a6dff9bbdfb0db7301febbdb42d894937ab50df2ab4b2d4"
    ):
        raise RuntimeError("Frozen 0004 catalog seed changed; use a new migration")
    return data


def upgrade():
    op.execute("""
    CREATE TABLE app.catalog_sources (
      source_id varchar(64) PRIMARY KEY CHECK(source_id ~ '^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$'),
      metadata_json jsonb NOT NULL CHECK(jsonb_typeof(metadata_json)='object'),
      integration_status varchar(30) NOT NULL CHECK(integration_status IN ('catalog_only','verification_pending','experimental_evidence')),
      evidence_refs jsonb NOT NULL CHECK(jsonb_typeof(evidence_refs)='array'),
      revision integer NOT NULL CHECK(revision>0),
      created_at timestamptz NOT NULL, updated_at timestamptz NOT NULL
    );
    CREATE TABLE app.catalog_actions (
      id uuid PRIMARY KEY, actor_id uuid NOT NULL REFERENCES app.users(id),
      operation varchar(30) NOT NULL CHECK(operation IN ('catalog.create','catalog.update')),
      idempotency_key varchar(128) NOT NULL,
      request_sha256 varchar(64) NOT NULL CHECK(request_sha256 ~ '^[0-9a-f]{64}$'),
      response jsonb NOT NULL, created_at timestamptz NOT NULL,
      UNIQUE(actor_id,operation,idempotency_key)
    );
    CREATE TABLE app.catalog_releases (
      release_id uuid PRIMARY KEY,
      source_id varchar(64) NOT NULL REFERENCES app.catalog_sources(source_id),
      version varchar(200) NOT NULL,
      published_at timestamptz NOT NULL,
      manifest_sha256 varchar(64) NOT NULL CHECK(manifest_sha256 ~ '^[0-9a-f]{64}$'),
      UNIQUE(source_id,version)
    );
    ALTER TABLE app.catalog_sources ENABLE ROW LEVEL SECURITY;
    ALTER TABLE app.catalog_sources FORCE ROW LEVEL SECURITY;
    ALTER TABLE app.catalog_actions ENABLE ROW LEVEL SECURITY;
    ALTER TABLE app.catalog_actions FORCE ROW LEVEL SECURITY;
    ALTER TABLE app.catalog_releases ENABLE ROW LEVEL SECURITY;
    ALTER TABLE app.catalog_releases FORCE ROW LEVEL SECURITY;
    CREATE POLICY catalog_read ON app.catalog_sources FOR SELECT TO corpus_app
      USING(app.actor_id() IS NOT NULL);
    CREATE POLICY catalog_add ON app.catalog_sources FOR INSERT TO corpus_app
      WITH CHECK(EXISTS(SELECT 1 FROM app.users WHERE id=app.actor_id() AND is_platform_admin));
    CREATE POLICY catalog_change ON app.catalog_sources FOR UPDATE TO corpus_app
      USING(EXISTS(SELECT 1 FROM app.users WHERE id=app.actor_id() AND is_platform_admin))
      WITH CHECK(EXISTS(SELECT 1 FROM app.users WHERE id=app.actor_id() AND is_platform_admin));
    CREATE POLICY catalog_action_read ON app.catalog_actions FOR SELECT TO corpus_app
      USING(actor_id=app.actor_id() AND EXISTS(SELECT 1 FROM app.users WHERE id=app.actor_id() AND is_platform_admin));
    CREATE POLICY catalog_action_add ON app.catalog_actions FOR INSERT TO corpus_app
      WITH CHECK(actor_id=app.actor_id() AND EXISTS(SELECT 1 FROM app.users WHERE id=app.actor_id() AND is_platform_admin));
    CREATE POLICY catalog_release_read ON app.catalog_releases FOR SELECT TO corpus_app
      USING(app.actor_id() IS NOT NULL);
    GRANT SELECT,INSERT,UPDATE ON app.catalog_sources TO corpus_app;
    GRANT SELECT,INSERT ON app.catalog_actions TO corpus_app;
    GRANT SELECT ON app.catalog_releases TO corpus_app;
    """)
    # Owner is subject to FORCE RLS. Seed via a transaction-local owner policy, removed immediately.
    op.execute(
        "CREATE POLICY catalog_seed ON app.catalog_sources FOR INSERT TO corpus_owner WITH CHECK(true)"
    )
    data = decode_seed((Path(__file__).parents[2] / "catalog_seed.json").read_bytes())
    connection = op.get_bind()
    for row in data["items"]:
        connection.execute(
            text("""
          INSERT INTO app.catalog_sources(source_id,metadata_json,integration_status,evidence_refs,revision,created_at,updated_at)
          VALUES(:id,CAST(:metadata AS jsonb),:status,CAST(:evidence AS jsonb),1,now(),now())
        """),
            {
                "id": row["source_id"],
                "metadata": json.dumps(row["metadata"], ensure_ascii=False),
                "status": row["integration_status"],
                "evidence": json.dumps(row["evidence_refs"]),
            },
        )
    op.execute("DROP POLICY catalog_seed ON app.catalog_sources")


def downgrade():
    op.execute(
        "DROP TABLE app.catalog_releases,app.catalog_actions,app.catalog_sources"
    )
