import os
from decimal import Decimal
from uuid import uuid4

import psycopg
import pytest
from psycopg.conninfo import make_conninfo
from toolhub_testkit import NOW, TOKENS

from dyson_contracts.common import Component, Money, RiskLevel
from dyson_contracts.control import ControlMode
from dyson_contracts.integrations import IntegrationKind, IntegrationRecord, IntegrationStatus
from dyson_toolhub.catalog import Catalog, ToolScope, ToolSpec
from dyson_toolhub.hub import ToolHub
from dyson_toolhub.ports import StaticTokens
from dyson_toolhub.store import InMemoryToolStore, migrate

ADMIN = os.environ.get("DYSON_TEST_PG_ADMIN", "postgresql://postgres@127.0.0.1:5433/postgres")
OWNER, APP = "dyson_toolhub_owner", "dyson_toolhub_app"


class FakeGovernance:
    """Stands in for the Governance Core (A) until Step 9 connects the real one."""

    def __init__(self):
        self.modes: dict[str | None, ControlMode] = {}
        self.records: dict[str, IntegrationRecord] = {}
        self.permits: dict[str, set[str]] = {}
        self.month_cap = Money(amount=Decimal("1000"), currency="INR")
        self.action_cap = Money(amount=Decimal("500"), currency="INR")
        self.approvals: dict = {}  # id -> [digest, category, consumed]
        self.consumed: list = []
        self.down = False

    def _up(self):
        if self.down:
            raise ConnectionError("Governance Core unreachable")

    survival = False

    def survival_mode(self):
        self._up()
        return self.survival

    def effective_mode(self, receptor_id):
        self._up()
        master = self.modes.get(None, ControlMode.RUNNING)
        own = (
            self.modes.get(receptor_id, ControlMode.RUNNING) if receptor_id else ControlMode.RUNNING
        )
        for m in (ControlMode.STOPPED, ControlMode.PAUSED):
            if m in (master, own):
                return m
        return ControlMode.RUNNING

    def registry(self):
        self._up()
        return dict(self.records)

    def receptor_permits(self, receptor_id, tool_id):
        self._up()
        return tool_id in self.permits.get(receptor_id, set())

    def spend_allowed(self, receptor_id, tool_id, amount, month_to_date):
        self._up()
        if amount.amount > self.action_cap.amount:
            return False, "over the per-action limit"
        if amount.amount + month_to_date.amount > self.month_cap.amount:
            return False, "over the monthly limit"
        return True, "within limits"

    def check_approval(self, approval_id, digest, category):
        self._up()
        a = self.approvals.get(approval_id)
        return bool(a and a[0] == digest and a[1] is category and not a[2])

    def consume_approval(self, approval_id, digest, category, by):
        if not self.check_approval(approval_id, digest, category):
            raise PermissionError("no approval to consume")
        self.approvals[approval_id][2] = True
        self.consumed.append(approval_id)

    # helpers for tests
    def admit(self, tool_id, status=IntegrationStatus.ADMITTED):
        self.records[tool_id] = IntegrationRecord(
            integration_id=tool_id, kind=IntegrationKind.API, name=tool_id, version="1.0",
            risk=RiskLevel.LOW, status=status, security_checked=True, change_record_ref="CR-1",
            updated_at=NOW,
        )  # fmt: skip

    def approve(self, digest, category):
        aid = uuid4()
        self.approvals[aid] = [digest, category, False]
        return aid


@pytest.fixture
def gov():
    return FakeGovernance()


@pytest.fixture
def ran():
    return []


@pytest.fixture
def catalog(ran):
    cat = Catalog()

    def adapter(name):
        def run(args):
            ran.append((name, args))
            if args.get("explode"):
                raise RuntimeError("tool crashed")
            return {"ok": True, "tool": name}

        return run

    orch = frozenset({Component.ORCHESTRATOR})
    both = frozenset({Component.ORCHESTRATOR, Component.HERMES})
    cat.register(ToolSpec(tool_id="core.lookup", connector_id="internal", allowed_callers=both,
                          scope=ToolScope.CORE), adapter("core.lookup"))  # fmt: skip
    cat.register(ToolSpec(tool_id="t0.inspect", connector_id="t0", allowed_callers=orch,
                          scope=ToolScope.RECEPTOR), adapter("t0.inspect"))  # fmt: skip
    cat.register(ToolSpec(tool_id="ads.topup", connector_id="adsnet", allowed_callers=orch,
                          scope=ToolScope.RECEPTOR, min_risk=RiskLevel.MEDIUM),
                 adapter("ads.topup"))  # fmt: skip
    cat.register(ToolSpec(tool_id="infra.deploy", connector_id="aws", allowed_callers=orch,
                          scope=ToolScope.CORE, min_risk=RiskLevel.HIGH),
                 adapter("infra.deploy"))  # fmt: skip
    cat.register(ToolSpec(tool_id="support.r12", connector_id="receptor-lane", allowed_callers=orch,
                          scope=ToolScope.RECEPTOR_SUPPORT, target_receptor="R12",
                          allowed_operations=frozenset({"share_inventory"})),
                 adapter("support.r12"))  # fmt: skip
    return cat


@pytest.fixture
def audit():
    return []


@pytest.fixture
def hub(catalog, gov, audit):
    for t in ("core.lookup", "t0.inspect", "ads.topup", "infra.deploy", "support.r12"):
        gov.admit(t)
    gov.permits = {"T0": {"t0.inspect"}, "R11": {"ads.topup", "t0.inspect", "support.r12"}}
    return ToolHub(
        catalog, gov, StaticTokens(TOKENS), InMemoryToolStore(), audit.append, lambda: NOW
    )


@pytest.fixture(scope="session")
def pg():
    try:
        admin = psycopg.connect(ADMIN, autocommit=True)
    except psycopg.OperationalError as exc:
        if os.environ.get("DYSON_TEST_REQUIRE_DB") == "1":
            raise
        pytest.skip(f"no test database: {exc}")
    name = f"dyson_toolhub_test_{uuid4().hex[:8]}"
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
    migrate(dsns["owner"], APP)
    yield dsns
    with psycopg.connect(ADMIN, autocommit=True) as admin:
        admin.execute(f"DROP DATABASE {name} WITH (FORCE)")
