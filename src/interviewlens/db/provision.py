"""Provision non-superuser application/migration roles using bootstrap access.

Credentials come only from the private environment. Never put them in argv.
Re-runnable after restoring a new target database; no business rows are changed.
"""
import os
from urllib.parse import urlsplit

import psycopg
from psycopg import sql


def provision(dsn: str, app_password: str, migration_password: str):
    for password in (app_password, migration_password):
        if len(password) < 32 or "REPLACE" in password:
            raise ValueError("Strong role credentials required")
    with psycopg.connect(dsn, autocommit=True) as conn:
        database = conn.execute("SELECT current_database()").fetchone()[0]
        conn.execute("SELECT pg_advisory_lock(479830715)")
        try:
            with conn.transaction():
                for name, password in (("il_app", app_password), ("il_migrate", migration_password)):
                    if not conn.execute("SELECT 1 FROM pg_roles WHERE rolname=%s", (name,)).fetchone():
                        conn.execute(sql.SQL("CREATE ROLE {} LOGIN").format(sql.Identifier(name)))
                    conn.execute(sql.SQL("ALTER ROLE {} NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS PASSWORD {}").format(sql.Identifier(name), sql.Literal(password)))
                conn.execute("CREATE EXTENSION IF NOT EXISTS vector")
                conn.execute(sql.SQL("ALTER DATABASE {} OWNER TO il_migrate").format(sql.Identifier(database)))
                conn.execute(sql.SQL("REVOKE ALL ON DATABASE {} FROM PUBLIC").format(sql.Identifier(database)))
                conn.execute(sql.SQL("GRANT CONNECT ON DATABASE {} TO il_app,il_migrate").format(sql.Identifier(database)))
                conn.execute("ALTER SCHEMA public OWNER TO il_migrate")
                conn.execute("REVOKE CREATE ON SCHEMA public FROM PUBLIC,il_app")
                conn.execute("GRANT USAGE ON SCHEMA public TO il_app")
                # Restores with --no-owner are initially bootstrap-owned. Adopt
                # business relations so subsequent migrations remain possible.
                relations = conn.execute("""SELECT c.relname,c.relkind FROM pg_class c
                    JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname='public'
                    AND c.relkind IN ('r','p','v','m','S') ORDER BY c.relkind='S'""").fetchall()
                for name, kind in relations:
                    command = {'v': 'VIEW', 'm': 'MATERIALIZED VIEW', 'S': 'SEQUENCE'}.get(kind, 'TABLE')
                    conn.execute(sql.SQL("ALTER " + command + " public.{} OWNER TO il_migrate").format(sql.Identifier(name)))
                functions = conn.execute("""SELECT p.oid::regprocedure::text FROM pg_proc p
                    JOIN pg_namespace n ON n.oid=p.pronamespace WHERE n.nspname='public'
                    AND NOT EXISTS(SELECT 1 FROM pg_depend d WHERE d.classid='pg_proc'::regclass AND d.objid=p.oid AND d.deptype='e')""").fetchall()
                for (signature,) in functions:
                    # regprocedure text is server-generated, not user input.
                    conn.execute(sql.SQL("ALTER FUNCTION " + signature + " OWNER TO il_migrate"))
                conn.execute("GRANT SELECT,INSERT,UPDATE,DELETE ON ALL TABLES IN SCHEMA public TO il_app")
                conn.execute("GRANT USAGE,SELECT ON ALL SEQUENCES IN SCHEMA public TO il_app")
                conn.execute("ALTER DEFAULT PRIVILEGES FOR ROLE il_migrate IN SCHEMA public GRANT SELECT,INSERT,UPDATE,DELETE ON TABLES TO il_app")
                conn.execute("ALTER DEFAULT PRIVILEGES FOR ROLE il_migrate IN SCHEMA public GRANT USAGE,SELECT ON SEQUENCES TO il_app")
                protect_metadata(conn)
        finally:
            conn.execute("SELECT pg_advisory_unlock(479830715)")


def protect_metadata(conn):
    for table in ("il_schema_migrations", "il_read_revision"):
        if conn.execute("SELECT to_regclass(%s)", (f"public.{table}",)).fetchone()[0]:
            conn.execute(sql.SQL("REVOKE INSERT,UPDATE,DELETE ON public.{} FROM il_app").format(sql.Identifier(table)))


if __name__ == "__main__":
    try:
        dsn = os.environ["BOOTSTRAP_DATABASE_URL"]
        if urlsplit(dsn).scheme != "postgresql":
            raise ValueError("PostgreSQL bootstrap URL required")
        provision(dsn, os.environ["APP_DB_PASSWORD"], os.environ["MIGRATION_DB_PASSWORD"])
        print("Provisioned limited database roles; credentials withheld.")
    except Exception as error:
        print(f"Provisioning stopped ({type(error).__name__}); credentials withheld.")
        raise SystemExit(1) from None
