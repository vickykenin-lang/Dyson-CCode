import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import psycopg
import pytest
from psycopg.conninfo import make_conninfo

from dyson_contracts.approvals import ApprovalDecision, ApprovalDecisionKind
from dyson_contracts.common import Component
from dyson_governance.channel import HmacChannel
from dyson_governance.core import GovernanceCore
from dyson_governance.policy import PolicyEngine
from dyson_governance.store import InMemoryEventStore, migrate

POLICY_DIR = Path(__file__).resolve().parents[3] / "policy"
ADMIN = os.environ.get("DYSON_TEST_PG_ADMIN", "postgresql://postgres@127.0.0.1:5433/postgres")
OWNER, APP = "dyson_governance_owner", "dyson_governance_app"


class Clock:
    def __init__(self):
        self.now = datetime(2026, 10, 15, 12, 0, tzinfo=UTC)

    def __call__(self):
        return self.now

    def advance(self, **kw):
        self.now += timedelta(**kw)


class Founder:
    """Plays Direct Founder Controls: signs what the Founder confirmed."""

    def __init__(self, channel: HmacChannel, clock: Clock):
        self.channel, self.clock = channel, clock

    def decision(self, request, approve=True, **override):
        fields = dict(
            approval_id=request.approval_id,
            action_digest=request.action_digest,
            decision=ApprovalDecisionKind.APPROVE if approve else ApprovalDecisionKind.REJECT,
            decided_by=Component.FOUNDER,
            channel=Component.DIRECT_FOUNDER_CONTROLS,
            auth_method="test-passkey",
            decided_at=self.clock(),
        )
        d = ApprovalDecision(**(fields | override))
        return d, self.channel.sign(d)

    def decide(self, core, request, approve=True):
        d, proof = self.decision(request, approve)
        return core.decide(d, proof)


@pytest.fixture
def policy():
    return PolicyEngine.load(POLICY_DIR)


@pytest.fixture
def clock():
    return Clock()


@pytest.fixture
def channel():
    return HmacChannel(b"k" * 32)


@pytest.fixture
def founder(channel, clock):
    return Founder(channel, clock)


@pytest.fixture
def audit():
    return []


@pytest.fixture
def heard():
    return []


@pytest.fixture
def core(policy, channel, clock, audit, heard):
    def listener(cmd, state):
        heard.append((cmd, state))

    return GovernanceCore(
        InMemoryEventStore(),
        policy,
        channel,
        audit_sink=audit.append,
        control_listeners=[listener],
        clock=clock,
    )


@pytest.fixture(scope="session")
def pg():
    try:
        admin = psycopg.connect(ADMIN, autocommit=True)
    except psycopg.OperationalError as exc:
        if os.environ.get("DYSON_TEST_REQUIRE_DB") == "1":
            raise
        pytest.skip(f"no test database: {exc}")
    name = f"dyson_governance_test_{uuid4().hex[:8]}"
    for role, pw in ((OWNER, "owner-pw"), (APP, "app-pw")):
        exists = admin.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", [role]).fetchone()
        verb = "ALTER" if exists else "CREATE"
        admin.execute(f"{verb} ROLE {role} LOGIN NOSUPERUSER PASSWORD '{pw}'")
    admin.execute(f"CREATE DATABASE {name} OWNER {OWNER}")
    admin.execute(f"GRANT CONNECT ON DATABASE {name} TO {APP}")
    admin.close()
    dsns = {
        "admin": make_conninfo(ADMIN, dbname=name),
        "owner": make_conninfo(ADMIN, dbname=name, user=OWNER, password="owner-pw"),
        "app": make_conninfo(ADMIN, dbname=name, user=APP, password="app-pw"),
    }
    migrate(dsns["owner"], APP)
    yield dsns
    with psycopg.connect(ADMIN, autocommit=True) as admin:
        admin.execute(f"DROP DATABASE {name} WITH (FORCE)")
