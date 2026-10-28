"""Connections and migrations for the "knowledge" schema.

Unlike the append-only memory schema, knowledge is mutable: a re-ingested file replaces its chunks
and a deleted file is tombstoned, so the app role gets SELECT/INSERT/UPDATE/DELETE. Migrations run
as the owner; the first one creates the schema and records its own version.
"""

from importlib.resources import files

import psycopg
from psycopg import sql
from psycopg.rows import dict_row

_MIG = files("dyson_knowledge").joinpath("migrations")
MIGRATIONS = sorted((p for p in _MIG.iterdir() if p.name.endswith(".sql")), key=lambda p: p.name)


def connect(dsn: str) -> psycopg.Connection:
    """An autocommit connection; PgStore opens an explicit transaction per write."""
    return psycopg.connect(dsn, autocommit=True, row_factory=dict_row)


def applied_versions(conn: psycopg.Connection) -> set[int]:
    row = conn.execute("SELECT to_regclass('knowledge.schema_migrations') AS t").fetchone()
    if row["t"] is None:
        return set()
    return {r["version"] for r in conn.execute("SELECT version FROM knowledge.schema_migrations")}


def migrate(conn: psycopg.Connection, app_role: str | None = None) -> list[int]:
    """Apply pending migrations; if given, grant the app role read/write rights on the schema."""
    done = applied_versions(conn)
    applied = []
    for path in MIGRATIONS:
        version = int(path.name.split("_", 1)[0])
        if version in done:
            continue
        with conn.transaction():
            conn.execute(path.read_text("utf-8"))
        applied.append(version)
    if app_role:
        role = sql.Identifier(app_role)
        with conn.transaction():
            conn.execute(sql.SQL("GRANT USAGE ON SCHEMA knowledge TO {}").format(role))
            conn.execute(
                sql.SQL(
                    "GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA knowledge TO {}"
                ).format(role)  # fmt: skip
            )
            conn.execute(sql.SQL("REVOKE INSERT, UPDATE, DELETE ON knowledge.schema_migrations "
                                 "FROM {}").format(role))  # fmt: skip
    return applied
