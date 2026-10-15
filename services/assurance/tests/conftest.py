import os
from datetime import timedelta
from uuid import uuid4

import psycopg
import pytest
from assurance_testkit import NOW
from psycopg.conninfo import make_conninfo

from dyson_assurance.db import connect, migrate
from dyson_assurance.finance import FinancialController
from dyson_assurance.monitoring import Monitor
from dyson_assurance.qa import QAController

ADMIN = os.environ.get("DYSON_TEST_PG_ADMIN", "postgresql://postgres@127.0.0.1:5433/postgres")
OWNER, APP = "dyson_assurance_owner", "dyson_assurance_app"


class Recorder(list):
    def record(self, evidence, receptor_id):
        self.append((evidence, receptor_id))

    def escalate(self, to, subject, message, task_id=None):
        self.append((to, subject, message, task_id))


class Probe:
    """F's independent observation of the real world; tests set what it sees."""

    def __init__(self):
        self.sees = {}
        self.unreachable = False

    def observe(self, task_id, receptor_id, standard_id):
        if self.unreachable:
            raise ConnectionError("cannot observe")
        return self.sees.get(task_id)


class Clock:
    def __init__(self):
        self.now = NOW

    def __call__(self):
        return self.now

    def advance(self, **kw):
        self.now += timedelta(**kw)


@pytest.fixture(scope="session")
def pg():
    try:
        admin = psycopg.connect(ADMIN, autocommit=True)
    except psycopg.OperationalError as exc:
        if os.environ.get("DYSON_TEST_REQUIRE_DB") == "1":
            raise
        pytest.skip(f"no test database: {exc}")
    name = f"dyson_assurance_test_{uuid4().hex[:8]}"
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
        c.execute("DROP SCHEMA IF EXISTS assurance CASCADE")
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
def evidence():
    return Recorder()


@pytest.fixture
def escalations():
    return Recorder()


@pytest.fixture
def probe():
    return Probe()


@pytest.fixture
def qa(conn, probe, evidence, escalations, clock):
    return QAController(conn, probe, evidence, escalations, clock)


@pytest.fixture
def monitor(conn, escalations, clock):
    # stale_after is a test value until the Founder sets it; the other two are D-010 and D-009.
    return Monitor(conn, escalations, stale_after=timedelta(minutes=10),
                   repeated_failure_threshold=3, reminder_interval=timedelta(hours=1),
                   clock=clock)  # fmt: skip


@pytest.fixture
def finance(conn, evidence, clock):
    return FinancialController(conn, evidence, clock)
