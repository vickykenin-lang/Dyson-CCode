"""One PostgreSQL database for Layer A: one schema and one least-privilege app role per component.

`prepare` runs as an administrator: it creates the roles and the database, then each component's
own migration runs as the owner and grants only its own app role.
"""

from importlib.resources import files

import psycopg
from psycopg import sql
from psycopg.conninfo import make_conninfo
from psycopg.rows import dict_row

COMPONENTS = (
    "memory",
    "governance",
    "toolhub",
    "orchestrator",
    "assurance",
    "intelligence",
    "integration",
)
OWNER = "dyson_owner"
BACKUP = "dyson_backup"  # read-only, BYPASSRLS: pg_dump must see every Receptor's rows


def app_role(component: str) -> str:
    return f"dyson_{component}_app"


def prepare(admin_dsn: str, dbname: str, password: str) -> dict[str, str]:
    """Create roles, the database and every schema. Returns a DSN per role."""
    with psycopg.connect(admin_dsn, autocommit=True) as admin:
        for role in (OWNER, BACKUP, *(app_role(c) for c in COMPONENTS)):
            exists = admin.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", [role]).fetchone()
            verb = "ALTER" if exists else "CREATE"
            rls = "BYPASSRLS" if role == BACKUP else "NOBYPASSRLS"
            admin.execute(
                sql.SQL(f"{verb} ROLE {{}} LOGIN NOSUPERUSER {rls} PASSWORD {{}}").format(
                    sql.Identifier(role), sql.Literal(password)
                )
            )
        admin.execute(
            sql.SQL("CREATE DATABASE {} OWNER {}").format(
                sql.Identifier(dbname), sql.Identifier(OWNER)
            )
        )
        for role in (BACKUP, *(app_role(c) for c in COMPONENTS)):
            admin.execute(
                sql.SQL("GRANT CONNECT ON DATABASE {} TO {}").format(
                    sql.Identifier(dbname), sql.Identifier(role)
                )
            )
    dsns = {
        "admin": make_conninfo(admin_dsn, dbname=dbname),
        "owner": make_conninfo(admin_dsn, dbname=dbname, user=OWNER, password=password),
    }
    for c in COMPONENTS:
        dsns[c] = make_conninfo(admin_dsn, dbname=dbname, user=app_role(c), password=password)
    dsns["backup"] = make_conninfo(admin_dsn, dbname=dbname, user=BACKUP, password=password)
    migrate_all(dsns)
    return dsns


def migrate_all(dsns: dict[str, str]) -> None:
    from dyson_assurance.db import migrate as assurance
    from dyson_governance.store import migrate as governance
    from dyson_intelligence.db import migrate as intelligence
    from dyson_memory.db import connect as memory_connect
    from dyson_memory.db import migrate as memory
    from dyson_orchestrator.orchestrator import migrate as orchestrator
    from dyson_toolhub.store import migrate as toolhub

    owner = dsns["owner"]
    with memory_connect(owner) as c:
        memory(c, app_role("memory"), BACKUP)
    governance(owner, app_role("governance"))
    toolhub(owner, app_role("toolhub"))
    orchestrator(owner, app_role("orchestrator"))
    assurance(owner, app_role("assurance"))
    intelligence(owner, app_role("intelligence"))
    _migrate_integration(owner, app_role("integration"))


def _migrate_integration(dsn: str, role: str) -> None:
    with psycopg.connect(dsn, autocommit=True, row_factory=dict_row) as conn:
        exists = conn.execute("SELECT to_regclass('integration.schema_migrations') AS t").fetchone()
        if not exists["t"]:
            with conn.transaction():
                sql_text = files("dyson_integration").joinpath("migrations/001_integration.sql")
                conn.execute(sql_text.read_text("utf-8"))
        done = {
            r["version"] for r in conn.execute("SELECT version FROM integration.schema_migrations")
        }
        if 2 not in done:
            with conn.transaction():
                sql_text = files("dyson_integration").joinpath("migrations/002_thread_archive.sql")
                conn.execute(sql_text.read_text("utf-8"))
        r = sql.Identifier(role)
        conn.execute(sql.SQL("GRANT USAGE ON SCHEMA integration TO {}").format(r))
        for table in ("thread_tasks", "thread_archive"):
            t = sql.Identifier("integration", table)
            conn.execute(sql.SQL("GRANT SELECT, INSERT ON {} TO {}").format(t, r))
            seq = sql.Identifier("integration", f"{table}_seq_seq")
            conn.execute(sql.SQL("GRANT USAGE, SELECT ON SEQUENCE {} TO {}").format(seq, r))


def drop(admin_dsn: str, dbname: str) -> None:
    with psycopg.connect(admin_dsn, autocommit=True) as admin:
        admin.execute(
            sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(sql.Identifier(dbname))
        )
