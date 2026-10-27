"""Deployment-only PostgreSQL role bootstrap. Never expose this service to the API."""

import os

import psycopg
from psycopg import sql


def main():
    url = os.environ["ADMIN_DATABASE_URL"].replace(
        "postgresql+psycopg://", "postgresql://", 1
    )
    with psycopg.connect(url, autocommit=True) as connection:
        for role, variable in (
            ("corpus_owner", "CORPUS_OWNER_DB_PASSWORD"),
            ("corpus_app", "CORPUS_APP_DB_PASSWORD"),
            ("corpus_worker", "CORPUS_WORKER_DB_PASSWORD"),
        ):
            if not connection.execute(
                "SELECT 1 FROM pg_roles WHERE rolname=%s", (role,)
            ).fetchone():
                connection.execute(
                    sql.SQL(
                        "CREATE ROLE {} LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOBYPASSRLS"
                    ).format(sql.Identifier(role))
                )
            connection.execute(
                sql.SQL(
                    "ALTER ROLE {} WITH LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOBYPASSRLS PASSWORD {}"
                ).format(sql.Identifier(role), sql.Literal(os.environ[variable]))
            )
        database = connection.execute("SELECT current_database()").fetchone()[0]
        connection.execute(
            sql.SQL(
                "GRANT CONNECT ON DATABASE {} TO corpus_owner,corpus_app,corpus_worker"
            ).format(sql.Identifier(database))
        )
        connection.execute("CREATE SCHEMA IF NOT EXISTS app AUTHORIZATION corpus_owner")
        connection.execute("REVOKE CREATE ON SCHEMA public FROM PUBLIC")
        connection.execute("GRANT USAGE,CREATE ON SCHEMA public TO corpus_owner")
        connection.execute("GRANT USAGE ON SCHEMA app TO corpus_app,corpus_worker")
        if connection.execute(
            "SELECT to_regclass('public.alembic_version')"
        ).fetchone()[0]:
            connection.execute(
                "ALTER TABLE public.alembic_version OWNER TO corpus_owner"
            )
    print(
        "Database roles prepared; runtime roles have no ownership or administrator privileges"
    )


if __name__ == "__main__":
    main()
