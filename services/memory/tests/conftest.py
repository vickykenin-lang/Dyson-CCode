"""Test database setup.

DYSON_TEST_PG_ADMIN is a superuser DSN (default: local cluster on port 5433). Each test session
creates its own database and two roles: an owner that runs migrations and an app role that the
store uses, so row-level security and grants are really exercised. Set DYSON_TEST_REQUIRE_DB=1
(CI does) to fail instead of skip when the database is unreachable.
"""

import json
import os
from uuid import uuid4

import psycopg
import pytest
from memory_testkit import CANARY
from psycopg.conninfo import make_conninfo

from dyson_memory.db import connect, migrate
from dyson_memory.secrets import LocalSecretStore, SecretGuard
from dyson_memory.store import MemoryStore

ADMIN = os.environ.get("DYSON_TEST_PG_ADMIN", "postgresql://postgres@127.0.0.1:5433/postgres")
OWNER, APP, BACKUP = "dyson_memory_owner", "dyson_memory_app", "dyson_memory_backup"


@pytest.fixture(scope="session")
def database():
    try:
        admin = psycopg.connect(ADMIN, autocommit=True)
    except psycopg.OperationalError as exc:
        if os.environ.get("DYSON_TEST_REQUIRE_DB") == "1":
            raise
        pytest.skip(f"no test database: {exc}")
    name = f"dyson_memory_test_{uuid4().hex[:8]}"
    for role, pw, rls in (
        (OWNER, "owner-pw", "NOBYPASSRLS"),
        (APP, "app-pw", "NOBYPASSRLS"),
        (BACKUP, "backup-pw", "BYPASSRLS"),
    ):
        exists = admin.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", [role]).fetchone()
        verb = "ALTER" if exists else "CREATE"
        admin.execute(f"{verb} ROLE {role} LOGIN NOSUPERUSER {rls} PASSWORD '{pw}'")
    admin.execute(f"CREATE DATABASE {name} OWNER {OWNER}")
    admin.execute(f"GRANT CONNECT ON DATABASE {name} TO {APP}, {BACKUP}")
    dsns = {
        "admin": make_conninfo(ADMIN, dbname=name),
        "owner": make_conninfo(ADMIN, dbname=name, user=OWNER, password="owner-pw"),
        "app": make_conninfo(ADMIN, dbname=name, user=APP, password="app-pw"),
        "backup": make_conninfo(ADMIN, dbname=name, user=BACKUP, password="backup-pw"),
    }
    admin.close()
    yield dsns
    # Reconnect: a test may have restarted the server and killed older connections.
    with psycopg.connect(ADMIN, autocommit=True) as admin:
        admin.execute(f"DROP DATABASE {name} WITH (FORCE)")


@pytest.fixture
def db(database):
    """A freshly migrated memory schema for each test."""
    with psycopg.connect(database["admin"], autocommit=True) as c:
        c.execute("DROP SCHEMA IF EXISTS memory CASCADE")
    with connect(database["owner"]) as c:
        migrate(c, APP, BACKUP)
    return database


@pytest.fixture
def secret_file(tmp_path):
    path = tmp_path / "secrets.json"
    path.write_text(
        json.dumps({"core": {"model_api_key": CANARY}, "T0": {"t0_token": "t0-secret-value"}})
    )
    path.chmod(0o600)
    return path


@pytest.fixture
def guard(secret_file):
    return SecretGuard(LocalSecretStore(secret_file))


@pytest.fixture
def store_for(db, guard):
    conns = []

    def make(scope: str) -> MemoryStore:
        conn = connect(db["app"])
        conns.append(conn)
        return MemoryStore(conn, scope, guard)

    yield make
    for c in conns:
        if not c.closed:
            c.close()


@pytest.fixture
def admin(db):
    with psycopg.connect(db["admin"], autocommit=True) as c:
        yield c
