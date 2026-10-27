"""Isolated PostgreSQL RLS experiment, not a production schema or authentication layer.

Run against the S0 Compose API container via stdin; DATABASE_URL stays in the
container environment. Each run creates and removes its own schema and login.
"""

import json
import os
import secrets
from datetime import UTC, datetime
from uuid import uuid4

import psycopg
from psycopg import sql
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DBAPIError


def run_probe(database_url: str) -> dict:
    suffix = uuid4().hex
    schema = f"s0_rls_{suffix}"
    role = f"s0_rls_user_{suffix}"
    password = secrets.token_hex(24)
    admin_url = make_url(database_url)
    admin = psycopg.connect(
        host=admin_url.host, port=admin_url.port or 5432,
        dbname=admin_url.database, user=admin_url.username,
        password=admin_url.password, autocommit=True, connect_timeout=5,
    )
    engine = None
    checks = []
    created_role = False
    created_schema = False
    result = {
        "experiment": "S0 isolated PostgreSQL RLS",
        "executed_at": datetime.now(UTC).isoformat(),
        "production_schema": False,
        "checks": checks,
        "cleanup": False,
    }
    try:
        result["postgres_version"] = admin.execute("SHOW server_version").fetchone()[0]
        admin.execute(sql.SQL("CREATE ROLE {} LOGIN PASSWORD {} NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE NOINHERIT").format(sql.Identifier(role), sql.Literal(password)))
        created_role = True
        admin.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
        created_schema = True
        admin.execute(sql.SQL("SET search_path TO {}").format(sql.Identifier(schema)))
        admin.execute("""
            CREATE TABLE memberships (
              project_id text NOT NULL, actor_id text NOT NULL,
              role text NOT NULL CHECK (role IN ('owner', 'editor', 'viewer')),
              PRIMARY KEY (project_id, actor_id));
            CREATE TABLE documents (
              project_id text NOT NULL, document_id text NOT NULL, body text NOT NULL,
              PRIMARY KEY (project_id, document_id));
            INSERT INTO memberships VALUES
              ('project-a','owner-a','owner'), ('project-a','editor-a','editor'),
              ('project-a','viewer-a','viewer'), ('project-b','owner-b','owner');
            INSERT INTO documents VALUES ('project-a','a-1','private-a'), ('project-b','b-1','private-b');
            ALTER TABLE memberships ENABLE ROW LEVEL SECURITY;
            ALTER TABLE memberships FORCE ROW LEVEL SECURITY;
            ALTER TABLE documents ENABLE ROW LEVEL SECURITY;
            ALTER TABLE documents FORCE ROW LEVEL SECURITY;
            CREATE POLICY membership_read ON memberships FOR SELECT USING
              (actor_id = nullif(current_setting('corpus.actor_id', true), ''));
            CREATE POLICY document_read ON documents FOR SELECT USING
              (EXISTS (SELECT 1 FROM memberships m WHERE m.project_id=documents.project_id));
            CREATE POLICY document_insert ON documents FOR INSERT WITH CHECK
              (EXISTS (SELECT 1 FROM memberships m WHERE m.project_id=documents.project_id AND m.role IN ('owner','editor')));
            CREATE POLICY document_update ON documents FOR UPDATE USING
              (EXISTS (SELECT 1 FROM memberships m WHERE m.project_id=documents.project_id AND m.role IN ('owner','editor')))
              WITH CHECK (EXISTS (SELECT 1 FROM memberships m WHERE m.project_id=documents.project_id AND m.role IN ('owner','editor')));
            CREATE POLICY document_delete ON documents FOR DELETE USING
              (EXISTS (SELECT 1 FROM memberships m WHERE m.project_id=documents.project_id AND m.role IN ('owner','editor')));
        """)
        admin.execute(sql.SQL("GRANT USAGE ON SCHEMA {} TO {}").format(sql.Identifier(schema), sql.Identifier(role)))
        admin.execute(sql.SQL("GRANT SELECT ON memberships TO {}").format(sql.Identifier(role)))
        admin.execute(sql.SQL("GRANT SELECT, INSERT, UPDATE, DELETE ON documents TO {}").format(sql.Identifier(role)))
        runtime_url = admin_url.set(drivername="postgresql+psycopg", username=role, password=password)
        engine = create_engine(runtime_url, pool_size=1, max_overflow=0, connect_args={"connect_timeout": 5})
        table = f'"{schema}".documents'
        memberships = f'"{schema}".memberships'

        def bind(connection, actor):
            # The host supplies the authorized actor; never accept this value from model SQL.
            connection.execute(text("SELECT set_config('corpus.actor_id', :actor, true)"), {"actor": actor})

        def visible(actor):
            with engine.begin() as connection:
                bind(connection, actor)
                return connection.execute(text(f"SELECT body FROM {table} ORDER BY body")).scalars().all()

        def denied_insert(actor, project):
            try:
                with engine.begin() as connection:
                    bind(connection, actor)
                    connection.execute(text(f"INSERT INTO {table} VALUES (:project, 'forbidden', 'forbidden')"), {"project": project})
            except DBAPIError as error:
                assert error.orig.sqlstate == "42501"
                return
            raise AssertionError("RLS unexpectedly permitted insert")

        with engine.begin() as connection:
            identity = connection.execute(text("SELECT current_user, rolsuper, rolbypassrls FROM pg_roles WHERE rolname=current_user")).one()
            assert identity == (role, False, False)
            owner = connection.execute(text("SELECT tableowner FROM pg_tables WHERE schemaname=:schema AND tablename='documents'"), {"schema": schema}).scalar_one()
            assert owner != role
        checks.append("separate_login_is_non_superuser_non_owner_without_bypassrls")

        assert visible("owner-a") == ["private-a"]
        assert visible("editor-a") == ["private-a"]
        assert visible("viewer-a") == ["private-a"]
        assert visible("owner-b") == ["private-b"]
        assert visible("platform-admin-without-membership") == []
        assert visible("unknown-actor") == []
        checks.append("owner_editor_viewer_reads_are_project_scoped_and_platform_admin_has_no_private_access")

        for actor in ("owner-a", "editor-a"):
            with engine.begin() as connection:
                bind(connection, actor)
                connection.execute(text(f"INSERT INTO {table} VALUES ('project-a', :id, 'new')"), {"id": actor})
                assert connection.execute(text(f"UPDATE {table} SET body='updated' WHERE document_id=:id"), {"id": actor}).rowcount == 1
                assert connection.execute(text(f"DELETE FROM {table} WHERE document_id=:id"), {"id": actor}).rowcount == 1
        checks.append("owner_and_editor_can_insert_update_delete_in_own_project")

        denied_insert("viewer-a", "project-a")
        denied_insert("editor-a", "project-b")
        with engine.begin() as connection:
            bind(connection, "viewer-a")
            assert connection.execute(text(f"UPDATE {table} SET body='forbidden'")).rowcount == 0
            assert connection.execute(text(f"DELETE FROM {table}")).rowcount == 0
        with engine.begin() as connection:
            bind(connection, "editor-a")
            assert connection.execute(text(f"UPDATE {table} SET body='forbidden' WHERE project_id='project-b'")).rowcount == 0
            assert connection.execute(text(f"DELETE FROM {table} WHERE project_id='project-b'")).rowcount == 0
        checks.append("viewer_write_and_cross_project_read_write_are_denied")

        try:
            with engine.begin() as connection:
                bind(connection, "editor-a")
                connection.execute(text(f"UPDATE {table} SET project_id='project-b' WHERE project_id='project-a'"))
        except DBAPIError as error:
            assert error.orig.sqlstate == "42501"
        else:
            raise AssertionError("Project relocation bypassed WITH CHECK")
        checks.append("update_with_check_prevents_moving_rows_to_unauthorized_project")

        try:
            with engine.begin() as connection:
                bind(connection, "viewer-a")
                connection.execute(text(f"UPDATE {memberships} SET role='owner'"))
        except DBAPIError as error:
            assert error.orig.sqlstate == "42501"
        else:
            raise AssertionError("Runtime role unexpectedly changed membership")
        checks.append("runtime_cannot_self_grant_project_membership")

        pids = []
        for actor, expected in (("owner-a", ["private-a"]), (None, []), ("owner-b", ["private-b"]), (None, [])):
            with engine.begin() as connection:
                pids.append(connection.execute(text("SELECT pg_backend_pid()")).scalar_one())
                if actor:
                    bind(connection, actor)
                else:
                    assert not connection.execute(text("SELECT current_setting('corpus.actor_id', true)")).scalar_one()
                assert connection.execute(text(f"SELECT body FROM {table} ORDER BY body")).scalars().all() == expected
        assert len(set(pids)) == 1
        # Rollback after a failed RLS write must reset identity on the same pooled connection too.
        denied_insert("viewer-a", "project-a")
        with engine.begin() as connection:
            assert connection.execute(text("SELECT pg_backend_pid()")).scalar_one() == pids[0]
            assert not connection.execute(text("SELECT current_setting('corpus.actor_id', true)")).scalar_one()
            assert connection.execute(text(f"SELECT count(*) FROM {table}")).scalar_one() == 0
        checks.append("same_pooled_connection_resets_actor_after_commit_and_rollback")

        assert visible("owner-a") == ["private-a"]
        assert visible("owner-b") == ["private-b"]
        checks.append("rejected_writes_leave_original_private_rows_unchanged")
        result["status"] = "passed"
    finally:
        if engine is not None:
            engine.dispose()
        # Identifiers originate only from this function's UUID, never caller input.
        if created_schema:
            assert schema.startswith("s0_rls_") and schema[7:] == suffix
            admin.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema)))
        if created_role:
            admin.execute(sql.SQL("DROP ROLE {}").format(sql.Identifier(role)))
        assert admin.execute("SELECT count(*) FROM pg_namespace WHERE nspname=%s", (schema,)).fetchone()[0] == 0
        assert admin.execute("SELECT count(*) FROM pg_roles WHERE rolname=%s", (role,)).fetchone()[0] == 0
        admin.close()
        result["cleanup"] = True
    return result


if __name__ == "__main__":
    print(json.dumps(run_probe(os.environ["DATABASE_URL"]), ensure_ascii=False, indent=2))
