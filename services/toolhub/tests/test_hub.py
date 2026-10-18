"""Every tool call is authorized individually, denied and audited when any check fails."""

import ast
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

import psycopg
import pytest
from fastapi.testclient import TestClient
from toolhub_testkit import NOW, TOKENS

from dyson_contracts.approvals import ApprovalCategory
from dyson_contracts.audit import AuditKind
from dyson_contracts.common import Component, Money, RiskLevel
from dyson_contracts.control import ControlMode
from dyson_contracts.integrations import IntegrationStatus
from dyson_contracts.toolcalls import CheckName, ToolCallRequest
from dyson_toolhub.api import create_app
from dyson_toolhub.hub import ToolHub
from dyson_toolhub.ports import StaticTokens, action_digest, revive_digest
from dyson_toolhub.store import PgToolStore

ORCH = Component.ORCHESTRATOR


def _tokens():
    return TOKENS


def req(
    tool="core.lookup",
    receptor=None,
    by=ORCH,
    spend=None,
    approval=None,
    risk=RiskLevel.LOW,
    key=None,
    **args,
):
    return ToolCallRequest(
        call_id=uuid4(),
        task_id=uuid4(),
        idempotency_key=key or f"task-{uuid4().hex}",
        tool_id=tool,
        requested_by=by,
        receptor_id=receptor,
        arguments=args,
        risk=risk,
        estimated_spend=Money(amount=Decimal(spend), currency="INR") if spend else None,
        approval_id=approval,
        requested_at=NOW,
    )


def failed(result):
    return {c.check for c in result.decision.checks if not c.passed}


# First milestone: unauthorized tool execution is denied and audited ------------------
def test_unauthorized_call_is_denied_and_audited(hub, ran, audit):
    r = hub.call(req(), credential="not-a-credential")
    assert r.status == "denied" and failed(r) == {CheckName.IDENTITY_PERMISSION}
    assert ran == []
    assert audit[-1].kind is AuditKind.TOOL_CALL_DENIED
    assert "identity_permission" in audit[-1].summary
    assert hub._store.decisions()[-1]["allowed"] is False


def test_all_six_checks_are_evaluated_every_time(hub):
    r = hub.call(req(), credential="nope")
    assert [c.check for c in r.decision.checks] == list(CheckName)


def test_credential_must_match_the_claimed_caller(hub):
    tokens = _tokens()
    r = hub.call(req(by=ORCH), credential=tokens[Component.HERMES])
    assert CheckName.IDENTITY_PERMISSION in failed(r)


def test_caller_must_be_allowed_for_the_tool(hub):
    tokens = _tokens()
    r = hub.call(req("t0.inspect", receptor="T0", by=Component.HERMES), tokens[Component.HERMES])
    assert CheckName.IDENTITY_PERMISSION in failed(r)
    ok = hub.call(req("core.lookup", by=Component.HERMES), tokens[Component.HERMES])
    assert ok.status == "executed"


def test_allowed_call_runs_and_is_audited(hub, ran, audit):
    r = hub.call(req("t0.inspect", receptor="T0", target="R3"), _tokens()[ORCH])
    assert r.status == "executed" and r.result == {"ok": True, "tool": "t0.inspect"}
    assert ran == [("t0.inspect", {"target": "R3"})]
    assert audit[-1].kind is AuditKind.TOOL_CALL


# Registry and kill switches -------------------------------------------------------------
def test_unknown_or_unadmitted_tools_are_not_callable(hub, gov):
    t = _tokens()[ORCH]
    assert CheckName.REGISTRY in failed(hub.call(req("shell.exec"), t))
    gov.admit("core.lookup", IntegrationStatus.ISOLATED)
    assert CheckName.REGISTRY in failed(hub.call(req("core.lookup"), t))


def test_kill_switches_and_revival(hub, gov):
    t = _tokens()[ORCH]
    hub.kill("tool", "t0.inspect", "suspect behaviour")
    assert CheckName.REGISTRY in failed(hub.call(req("t0.inspect", receptor="T0"), t))
    hub.kill("connector", "internal", "connector compromised")
    assert CheckName.REGISTRY in failed(hub.call(req("core.lookup"), t))
    with pytest.raises(PermissionError):
        hub.revive("tool", "t0.inspect", uuid4())
    aid = gov.approve(revive_digest("tool", "t0.inspect"), ApprovalCategory.INTEGRATION)
    hub.revive("tool", "t0.inspect", aid)
    assert hub.call(req("t0.inspect", receptor="T0"), t).status == "executed"
    assert CheckName.REGISTRY in failed(hub.call(req("core.lookup"), t))  # connector still off


# Receptor scope, including Receptor-to-Receptor support ---------------------------------
def test_scope_rules(hub):
    t = _tokens()[ORCH]
    assert CheckName.RECEPTOR_SCOPE in failed(hub.call(req("core.lookup", receptor="T0"), t))
    assert CheckName.RECEPTOR_SCOPE in failed(hub.call(req("t0.inspect"), t))
    assert CheckName.RECEPTOR_SCOPE in failed(hub.call(req("ads.topup", receptor="T0"), t))


def test_receptor_support_is_limited_and_governed(hub):
    t = _tokens()[ORCH]
    assert CheckName.RECEPTOR_SCOPE in failed(
        hub.call(req("support.r12", receptor="R11", operation="read_ledger"), t)
    )
    assert CheckName.RECEPTOR_SCOPE in failed(
        hub.call(req("support.r12", receptor="R12", operation="share_inventory"), t)
    )
    assert CheckName.RECEPTOR_SCOPE in failed(
        hub.call(req("support.r12", receptor="T0", operation="share_inventory"), t)
    )
    ok = hub.call(req("support.r12", receptor="R11", operation="share_inventory"), t)
    assert ok.status == "executed"


# Risk, spend and approvals --------------------------------------------------------------
def test_money_needs_an_approval_for_the_exact_action_used_once(hub, gov, ran):
    t = _tokens()[ORCH]
    first = req("ads.topup", receptor="R11", spend="200")
    assert failed(hub.call(first, t)) == {CheckName.APPROVAL_STATUS}
    wrong = gov.approve(
        action_digest(req("ads.topup", receptor="R11", spend="900")), ApprovalCategory.FINANCIAL
    )
    assert CheckName.APPROVAL_STATUS in failed(
        hub.call(req("ads.topup", receptor="R11", spend="200", approval=wrong), t)
    )
    probe = req("ads.topup", receptor="R11", spend="200")
    aid = gov.approve(action_digest(probe), ApprovalCategory.FINANCIAL)
    good = probe.model_copy(update={"approval_id": aid})
    assert hub.call(good, t).status == "executed"
    assert gov.consumed == [aid]
    again = good.model_copy(update={"call_id": uuid4(), "idempotency_key": f"task-{uuid4().hex}"})
    assert CheckName.APPROVAL_STATUS in failed(hub.call(again, t))  # single use
    assert [n for n, _ in ran] == ["ads.topup"]


def _approved(gov, **kw):
    probe = req(**kw)
    return probe.model_copy(
        update={"approval_id": gov.approve(action_digest(probe), ApprovalCategory.FINANCIAL)}
    )


def test_spend_limits_use_g_own_spend_record(hub, gov):
    t = _tokens()[ORCH]
    assert CheckName.RISK_SPEND_LIMITS in failed(
        hub.call(_approved(gov, tool="ads.topup", receptor="R11", spend="600"), t)
    )
    assert (
        hub.call(_approved(gov, tool="ads.topup", receptor="R11", spend="500"), t).status
        == "executed"
    )
    assert (
        hub.call(_approved(gov, tool="ads.topup", receptor="R11", spend="450"), t).status
        == "executed"
    )
    over = hub.call(_approved(gov, tool="ads.topup", receptor="R11", spend="100"), t)
    assert failed(over) == {CheckName.RISK_SPEND_LIMITS}  # 950 used this month, cap 1000


def test_failed_execution_does_not_count_as_spend(hub, gov):
    t = _tokens()[ORCH]
    boom = hub.call(_approved(gov, tool="ads.topup", receptor="R11", spend="500", explode=True), t)
    assert boom.status == "failed" and "tool crashed" in boom.error
    assert (
        hub.call(_approved(gov, tool="ads.topup", receptor="R11", spend="500"), t).status
        == "executed"
    )
    assert (
        hub.call(_approved(gov, tool="ads.topup", receptor="R11", spend="500"), t).status
        == "executed"
    )


def test_callers_cannot_declare_a_risky_tool_safe(hub, gov):
    t = _tokens()[ORCH]
    r = hub.call(req("infra.deploy", risk=RiskLevel.LOW), t)
    assert failed(r) == {CheckName.APPROVAL_STATUS}
    probe = req("infra.deploy")
    aid = gov.approve(action_digest(probe), ApprovalCategory.OTHER)
    assert hub.call(probe.model_copy(update={"approval_id": aid}), t).status == "executed"


# STOP state -----------------------------------------------------------------------------
def test_stop_state_is_checked_on_every_call(hub, gov, ran):
    t = _tokens()[ORCH]
    assert hub.call(req("t0.inspect", receptor="T0"), t).status == "executed"
    gov.modes["T0"] = ControlMode.PAUSED
    assert failed(hub.call(req("t0.inspect", receptor="T0"), t)) == {CheckName.STOP_STATE}
    assert hub.call(req("core.lookup"), t).status == "executed"
    gov.modes[None] = ControlMode.STOPPED
    assert failed(hub.call(req("core.lookup"), t)) == {CheckName.STOP_STATE}
    assert len(ran) == 2


def test_governance_unreachable_means_deny(hub, gov):
    gov.down = True
    r = hub.call(req("t0.inspect", receptor="T0"), _tokens()[ORCH])
    assert r.status == "denied"
    assert all("unavailable" in c.detail for c in r.decision.checks if not c.passed)


# Idempotency and failures ---------------------------------------------------------------
def test_retry_with_same_key_never_runs_twice(hub, ran):
    t = _tokens()[ORCH]
    a = req("t0.inspect", receptor="T0", key="task-0001-attempt-x")
    b = a.model_copy(update={"call_id": uuid4()})
    assert hub.call(a, t).status == "executed"
    second = hub.call(b, t)
    assert second.status == "duplicate" and second.result == {"ok": True, "tool": "t0.inspect"}
    assert len(ran) == 1


def test_audit_outage_keeps_decision_durable(catalog, gov):
    from dyson_toolhub.store import InMemoryToolStore

    def broken(_):
        raise ConnectionError("I is down")

    gov.admit("core.lookup")
    store = InMemoryToolStore()
    hub = ToolHub(catalog, gov, StaticTokens(_tokens()), store, broken)
    hub.call(req(), "nope")
    assert len(hub.audit_backlog) == 1 and store.decisions()[-1]["allowed"] is False


# No LLM in the decision path ------------------------------------------------------------
ALLOWED = {
    "collections", "contextlib", "dataclasses", "datetime", "decimal", "enum", "hashlib",
    "importlib", "json", "threading", "typing", "uuid",
    "fastapi", "psycopg", "pydantic", "dyson_contracts", "dyson_toolhub",
}  # fmt: skip


def test_toolhub_imports_no_model_or_network_client():
    pkg = Path(__file__).resolve().parents[1] / "src" / "dyson_toolhub"
    for path in pkg.glob("*.py"):
        for node in ast.walk(ast.parse(path.read_text())):
            names = (
                [a.name for a in node.names] if isinstance(node, ast.Import)
                else [node.module] if isinstance(node, ast.ImportFrom) and node.level == 0
                else []
            )  # fmt: skip
            for name in names:
                assert name.split(".")[0] in ALLOWED, f"{path.name} imports {name}"


# PostgreSQL -----------------------------------------------------------------------------
def test_durable_idempotency_spend_and_append_only(pg, catalog, gov, ran):
    for t_ in ("ads.topup", "t0.inspect"):
        gov.admit(t_)
    gov.permits = {"R11": {"ads.topup"}, "T0": {"t0.inspect"}}
    t = _tokens()[ORCH]
    s1 = PgToolStore(pg["app"])
    hub1 = ToolHub(catalog, gov, StaticTokens(_tokens()), s1)
    first = req("t0.inspect", receptor="T0", key=f"task-pg-{uuid4().hex}")
    assert hub1.call(first, t).status == "executed"
    for _ in range(2):  # 900 of the 1000 monthly cap, spent before the restart
        spent = hub1.call(_approved(gov, tool="ads.topup", receptor="R11", spend="450"), t)
        assert spent.status == "executed"
    s1.close()
    s2 = PgToolStore(pg["app"])  # a restarted G
    hub2 = ToolHub(catalog, gov, StaticTokens(_tokens()), s2)
    assert hub2.call(first.model_copy(update={"call_id": uuid4()}), t).status == "duplicate"
    over = hub2.call(_approved(gov, tool="ads.topup", receptor="R11", spend="200"), t)
    assert failed(over) == {CheckName.RISK_SPEND_LIMITS}
    s2.close()
    assert len([n for n, _ in ran if n == "t0.inspect"]) == 1
    for dsn in (pg["app"], pg["admin"]):
        with psycopg.connect(dsn, autocommit=True) as c:
            for stmt in (
                "UPDATE toolhub.decisions SET allowed = true",
                "DELETE FROM toolhub.executions",
            ):
                with pytest.raises(psycopg.errors.InsufficientPrivilege):
                    c.execute(stmt)


# HTTP API -------------------------------------------------------------------------------
def test_api(hub, catalog):
    tokens = _tokens()
    client = TestClient(create_app(hub, StaticTokens(tokens), catalog.specs()))
    body = req("core.lookup").model_dump(mode="json")
    assert (
        client.post("/calls", json=body, headers={"X-Caller-Credential": "x"}).json()["status"]
        == "denied"
    )
    body = req("core.lookup").model_dump(mode="json")
    ok = client.post("/calls", json=body, headers={"X-Caller-Credential": tokens[ORCH]})
    assert ok.json()["status"] == "executed"
    kill = {"target_kind": "tool", "target_id": "core.lookup", "reason": "test"}
    assert (
        client.post("/kill", json=kill, headers={"X-Caller-Credential": tokens[ORCH]}).status_code
        == 403
    )
    assert (
        client.post(
            "/kill", json=kill, headers={"X-Caller-Credential": tokens[Component.GOVERNANCE_CORE]}
        ).status_code
        == 204
    )
    body = req("core.lookup").model_dump(mode="json")
    assert (
        client.post("/calls", json=body, headers={"X-Caller-Credential": tokens[ORCH]}).json()[
            "status"
        ]
        == "denied"
    )


def test_lane_adapter_receives_task_id_and_idempotency_key(hub, catalog, gov):  # LA-IF-02
    from dyson_toolhub.catalog import LaneAdapter, ToolScope, ToolSpec

    delivered = []
    catalog.register(
        ToolSpec(tool_id="t0.lane", connector_id="t0", allowed_callers=frozenset({ORCH}),
                 scope=ToolScope.RECEPTOR),
        LaneAdapter(lambda r: delivered.append(r) or {"receipt": "r-1"}),
    )  # fmt: skip
    gov.admit("t0.lane")
    gov.permits.setdefault("T0", set()).add("t0.lane")
    request = req("t0.lane", receptor="T0", key="task-lane-key-0001")
    result = hub.call(request, TOKENS[ORCH])
    assert result.status == "executed" and result.result == {"receipt": "r-1"}
    (got,) = delivered
    assert got.task_id == request.task_id and got.idempotency_key == "task-lane-key-0001"
    assert hub.call(request, TOKENS[ORCH]).status == "duplicate" and len(delivered) == 1


def test_survival_mode_holds_money_and_high_risk_but_not_low_risk_work(hub, gov, ran):
    # AMD-12 v1.1: even an approved money action waits for the Founder; ordinary work goes on.
    t = _tokens()[ORCH]
    gov.survival = True
    paid = _approved(gov, tool="ads.topup", receptor="R11", spend="200")
    out = hub.call(paid, t)
    assert failed(out) == {CheckName.APPROVAL_STATUS} and gov.consumed == []
    assert "Survival Mode" in next(c.detail for c in out.decision.checks if not c.passed)
    gov.survival = False
    assert hub.call(paid.model_copy(update={"call_id": uuid4()}), t).status == "executed"
