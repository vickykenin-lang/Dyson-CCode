import os
from collections import defaultdict
from uuid import uuid4

import psycopg
import pytest
from orchestrator_testkit import NOW
from psycopg.conninfo import make_conninfo

from dyson_contracts.common import Component
from dyson_contracts.control import ControlMode
from dyson_contracts.lanes import VerificationVerdict
from dyson_orchestrator.orchestrator import Orchestrator, migrate
from dyson_orchestrator.ports import ToolRun

ADMIN = os.environ.get("DYSON_TEST_PG_ADMIN", "postgresql://postgres@127.0.0.1:5433/postgres")
OWNER, APP = "dyson_orchestrator_owner", "dyson_orchestrator_app"


class FakeHub:
    """Behaves like G: one execution per idempotency key, whatever the number of calls."""

    def __init__(self):
        self.calls = []
        self.executed = defaultdict(int)
        self.results = {}
        self.unreachable = 0  # how many upcoming calls fail with a network error
        self.deny = False
        self.crash = False

    def call(self, request):
        self.calls.append(request)
        if self.unreachable:
            self.unreachable -= 1
            raise ConnectionError("network")
        if self.deny:
            return ToolRun(status="denied", denied_checks=("approval_status",))
        key = request.idempotency_key
        if key in self.results:
            return ToolRun(status="duplicate", result=self.results[key])
        self.executed[key] += 1
        if self.crash:
            return ToolRun(status="failed", error="RuntimeError: tool crashed")
        self.results[key] = {"ok": True, "key": key}
        return ToolRun(status="executed", result=self.results[key])


class FakeGovernance:
    def __init__(self):
        self.modes = {}
        self.proposals = {}  # approval_id -> (payload, category)
        self.status = {}
        self.down = False

    def effective_mode(self, receptor_id):
        if self.down:
            raise ConnectionError("A unreachable")
        master = self.modes.get(None, ControlMode.RUNNING)
        own = self.modes.get(receptor_id, ControlMode.RUNNING)
        for m in (ControlMode.STOPPED, ControlMode.PAUSED):
            if m in (master, own):
                return m
        return ControlMode.RUNNING

    def propose_external_action(self, payload, category, summary, task_id):
        aid = uuid4()
        self.proposals[aid] = (payload, category)
        self.status[aid] = "open"
        return aid

    def approval_status(self, approval_id):
        return self.status[approval_id]


class FakeQA:
    """Plays the independent QA/QC Controller (F)."""

    def __init__(self):
        self.verdicts = []  # queue of (technical_success, fit_for_purpose); default pass
        self.unreachable = False
        self.seen = []

    def verify(self, task_id, plan, run):
        if self.unreachable:
            raise ConnectionError("F unreachable")
        self.seen.append((task_id, run))
        tech, fit = self.verdicts.pop(0) if self.verdicts else (True, True)
        return VerificationVerdict(
            task_id=task_id, technical_success=tech, fit_for_purpose=fit,
            evidence_ids=(uuid4(),), verified_by=Component.QA_QC, verified_at=NOW,
        )  # fmt: skip


class Escalations(list):
    def escalate(self, task_id, reason):
        self.append((task_id, reason))


class Events(list):
    def record(self, transition):
        self.append(transition)


@pytest.fixture(scope="session")
def pg():
    try:
        admin = psycopg.connect(ADMIN, autocommit=True)
    except psycopg.OperationalError as exc:
        if os.environ.get("DYSON_TEST_REQUIRE_DB") == "1":
            raise
        pytest.skip(f"no test database: {exc}")
    name = f"dyson_orchestrator_test_{uuid4().hex[:8]}"
    for role, pw in ((OWNER, "owner-pw"), (APP, "app-pw")):
        exists = admin.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", [role]).fetchone()
        admin.execute(
            f"{'ALTER' if exists else 'CREATE'} ROLE {role} LOGIN NOSUPERUSER PASSWORD '{pw}'"
        )
    admin.execute(f"CREATE DATABASE {name} OWNER {OWNER}")
    admin.execute(f"GRANT CONNECT ON DATABASE {name} TO {APP}")
    admin.close()
    dsns = {
        "admin": make_conninfo(ADMIN, dbname=name),
        "owner": make_conninfo(ADMIN, dbname=name, user=OWNER, password="owner-pw"),
        "app": make_conninfo(ADMIN, dbname=name, user=APP, password="app-pw"),
    }
    yield dsns
    with psycopg.connect(ADMIN, autocommit=True) as admin:
        admin.execute(f"DROP DATABASE {name} WITH (FORCE)")


@pytest.fixture
def db(pg):
    """A fresh orchestrator schema for every test: no task leaks between tests."""
    with psycopg.connect(pg["admin"], autocommit=True) as c:
        c.execute("DROP SCHEMA IF EXISTS orchestrator CASCADE")
    migrate(pg["owner"], APP)
    return pg


@pytest.fixture
def parts():
    return {
        "hub": FakeHub(),
        "gov": FakeGovernance(),
        "qa": FakeQA(),
        "esc": Escalations(),
        "events": Events(),
    }


@pytest.fixture
def make(db, parts):
    made = []

    def build():
        o = Orchestrator(db["app"], parts["hub"], parts["gov"], parts["qa"], parts["esc"],
                         parts["events"], clock=lambda: NOW)  # fmt: skip
        made.append(o)
        return o

    yield build
    for o in made:
        o.close_connection()


@pytest.fixture
def orch(make):
    return make()
