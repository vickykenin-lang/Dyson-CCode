import os
from uuid import uuid4

import psycopg
import pytest
from intelligence_testkit import Clock, FakeGovernance, FakeModel
from psycopg.conninfo import make_conninfo

from dyson_intelligence.db import connect, migrate
from dyson_intelligence.router import ModelRouter

ADMIN = os.environ.get("DYSON_TEST_PG_ADMIN", "postgresql://postgres@127.0.0.1:5433/postgres")
OWNER, APP = "dyson_intelligence_owner", "dyson_intelligence_app"


@pytest.fixture(scope="session")
def pg():
    try:
        admin = psycopg.connect(ADMIN, autocommit=True)
    except psycopg.OperationalError as exc:
        if os.environ.get("DYSON_TEST_REQUIRE_DB") == "1":
            raise
        pytest.skip(f"no test database: {exc}")
    name = f"dyson_intelligence_test_{uuid4().hex[:8]}"
    for role, pw in ((OWNER, "owner-pw"), (APP, "app-pw")):
        exists = admin.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", [role]).fetchone()
        admin.execute(
            f"{'ALTER' if exists else 'CREATE'} ROLE {role} LOGIN NOSUPERUSER PASSWORD '{pw}'"
        )
    admin.execute(f"CREATE DATABASE {name} OWNER {OWNER}")
    admin.execute(f"GRANT CONNECT ON DATABASE {name} TO {APP}")
    admin.close()
    yield {
        "admin": make_conninfo(ADMIN, dbname=name),
        "owner": make_conninfo(ADMIN, dbname=name, user=OWNER, password="owner-pw"),
        "app": make_conninfo(ADMIN, dbname=name, user=APP, password="app-pw"),
    }
    with psycopg.connect(ADMIN, autocommit=True) as admin:
        admin.execute(f"DROP DATABASE {name} WITH (FORCE)")


@pytest.fixture
def db(pg):
    with psycopg.connect(pg["admin"], autocommit=True) as c:
        c.execute("DROP SCHEMA IF EXISTS intelligence CASCADE")
    migrate(pg["owner"], APP)
    return pg


@pytest.fixture
def conn(db):
    c = connect(db["app"])
    yield c
    c.close()


@pytest.fixture
def clock():
    return Clock()


@pytest.fixture
def gov():
    return FakeGovernance()


@pytest.fixture
def providers():
    """Two independent providers, so losing one can be tested."""
    return {"alpha": FakeModel('{"ok": true}'), "beta": FakeModel('{"ok": true}')}


@pytest.fixture
def router(conn, gov, providers, clock):
    return ModelRouter(conn, gov, providers, clock)
