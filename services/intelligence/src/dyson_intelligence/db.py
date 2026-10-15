"""Connection and migration for the "intelligence" schema. The app role may only read and insert."""

from importlib.resources import files

import psycopg
from psycopg import sql
from psycopg.rows import dict_row


def connect(dsn: str) -> psycopg.Connection:
    return psycopg.connect(dsn, autocommit=True, row_factory=dict_row)


def migrate(dsn: str, app_role: str) -> None:
    with connect(dsn) as conn:
        exists = conn.execute(
            "SELECT to_regclass('intelligence.schema_migrations') AS t"
        ).fetchone()
        done = (
            {
                r["version"]
                for r in conn.execute("SELECT version FROM intelligence.schema_migrations")
            }
            if exists["t"]
            else set()
        )
        mig = files("dyson_intelligence").joinpath("migrations")
        for path in sorted(
            (p for p in mig.iterdir() if p.name.endswith(".sql")), key=lambda p: p.name
        ):
            if int(path.name.split("_", 1)[0]) not in done:
                with conn.transaction():
                    conn.execute(path.read_text("utf-8"))
        role = sql.Identifier(app_role)
        with conn.transaction():
            for stmt in (
                "GRANT USAGE ON SCHEMA intelligence TO {}",
                "GRANT SELECT, INSERT ON ALL TABLES IN SCHEMA intelligence TO {}",
                "GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA intelligence TO {}",
                "REVOKE INSERT ON intelligence.schema_migrations FROM {}",
            ):
                conn.execute(sql.SQL(stmt).format(role))
