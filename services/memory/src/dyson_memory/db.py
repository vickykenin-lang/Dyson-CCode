"""Connections and migrations for the "memory" schema.

Two database roles:
- the owner role runs migrations and owns the schema;
- the app role is what the running service uses. It can only SELECT and INSERT, and
  row-level security plus append-only triggers apply to it.
"""

from importlib.resources import files

import psycopg
from psycopg import sql
from psycopg.rows import dict_row

MIGRATIONS = sorted(
    (p for p in files("dyson_memory").joinpath("migrations").iterdir() if p.name.endswith(".sql")),
    key=lambda p: p.name,
)


def connect(dsn: str) -> psycopg.Connection:
    """An autocommit connection; MemoryStore opens an explicit transaction per operation."""
    return psycopg.connect(dsn, autocommit=True, row_factory=dict_row)


def applied_versions(conn: psycopg.Connection) -> set[int]:
    row = conn.execute("SELECT to_regclass('memory.schema_migrations') AS t").fetchone()
    if row["t"] is None:
        return set()
    return {r["version"] for r in conn.execute("SELECT version FROM memory.schema_migrations")}


def migrate(conn: psycopg.Connection, app_role: str, backup_role: str | None = None) -> list[int]:
    """Apply pending migrations as the owner role and grant the app role its narrow rights.

    backup_role, if given, gets read-only access for pg_dump. It must be a BYPASSRLS role,
    because a dump has to see every Receptor's rows.
    """
    done = applied_versions(conn)
    applied = []
    for path in MIGRATIONS:
        version = int(path.name.split("_", 1)[0])
        if version in done:
            continue
        with conn.transaction():
            conn.execute(path.read_text("utf-8"))
        applied.append(version)
    role = sql.Identifier(app_role)
    with conn.transaction():
        conn.execute(sql.SQL("GRANT USAGE ON SCHEMA memory TO {}").format(role))
        conn.execute(
            sql.SQL("GRANT SELECT, INSERT ON ALL TABLES IN SCHEMA memory TO {}").format(role)
        )
        conn.execute(
            sql.SQL("GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA memory TO {}").format(role)
        )
        conn.execute(sql.SQL("REVOKE INSERT ON memory.schema_migrations FROM {}").format(role))
        if backup_role:
            b = sql.Identifier(backup_role)
            conn.execute(sql.SQL("GRANT USAGE ON SCHEMA memory TO {}").format(b))
            conn.execute(sql.SQL("GRANT SELECT ON ALL TABLES IN SCHEMA memory TO {}").format(b))
            conn.execute(sql.SQL("GRANT SELECT ON ALL SEQUENCES IN SCHEMA memory TO {}").format(b))
    return applied
