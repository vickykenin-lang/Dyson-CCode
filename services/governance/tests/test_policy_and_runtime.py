"""Policy engine, the no-LLM guarantee, durability in PostgreSQL, and the HTTP API."""

import ast
import shutil
from datetime import date
from pathlib import Path
from uuid import uuid4

import psycopg
import pytest
from fastapi.testclient import TestClient

from dyson_contracts.common import Component
from dyson_contracts.control import ControlCommand, ControlCommandType, ControlMode, ControlScope
from dyson_governance.api import create_app
from dyson_governance.core import GovernanceCore
from dyson_governance.policy import PolicyEngine, PolicyIntegrityError
from dyson_governance.store import PgEventStore

PACKAGE = Path(__file__).resolve().parents[1] / "src" / "dyson_governance"
POLICY_DIR = Path(__file__).resolve().parents[3] / "policy"


# Policy engine --------------------------------------------------------------------------
def test_every_rule_has_version_and_effective_date(policy):
    for i in range(1, 15):
        rule = policy.rule(f"AMD-{i}")
        assert rule.version and rule.effective_from == date(2026, 10, 10)
    assert policy.control("AMD-3", "qa_consecutive_failure_limit") == 3
    with pytest.raises(LookupError):
        policy.control("AMD-3", "qa_consecutive_failure_limit", on=date(2026, 10, 9))


def test_tampered_register_is_refused(tmp_path):
    shutil.copytree(POLICY_DIR, tmp_path / "policy")
    reg = tmp_path / "policy" / "amd_register.yaml"
    reg.write_text(
        reg.read_text().replace(
            "qa_consecutive_failure_limit: 3", "qa_consecutive_failure_limit: 9"
        )
    )
    with pytest.raises(PolicyIntegrityError):
        PolicyEngine.load(tmp_path / "policy")


# No LLM in the control path -------------------------------------------------------------
ALLOWED_IMPORTS = {
    "collections", "contextlib", "dataclasses", "datetime", "decimal", "enum", "hashlib", "hmac",
    "importlib", "json", "pathlib", "threading", "typing", "uuid",
    "fastapi", "psycopg", "pydantic", "yaml", "dyson_contracts", "dyson_governance",
}  # fmt: skip


def test_governance_imports_no_model_or_network_client():
    for path in PACKAGE.glob("*.py"):
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.level == 0:
                names = [node.module]
            else:
                continue
            for name in names:
                assert name.split(".")[0] in ALLOWED_IMPORTS, f"{path.name} imports {name}"


# Durability -----------------------------------------------------------------------------
def _stop(by=Component.GOVERNANCE_CORE, clock=None):
    return ControlCommand(
        command_id=uuid4(),
        command=ControlCommandType.STOP,
        scope=ControlScope.MASTER,
        issued_by=by,
        issued_at=clock(),
    )


def test_stop_survives_a_restart(pg, policy, channel, clock):
    store = PgEventStore(pg["app"])
    GovernanceCore(store, policy, channel, clock=clock).control(_stop(clock=clock))
    store.close()
    fresh = PgEventStore(pg["app"])  # a new process rebuilds state from the log
    try:
        assert (
            GovernanceCore(fresh, policy, channel, clock=clock).effective_mode("R11")
            is ControlMode.STOPPED
        )
    finally:
        fresh.close()


def test_event_log_is_append_only(pg, policy, channel, clock):
    store = PgEventStore(pg["app"])
    GovernanceCore(store, policy, channel, clock=clock).control(_stop(clock=clock))
    store.close()
    for dsn in (pg["app"], pg["admin"]):
        with psycopg.connect(dsn, autocommit=True) as c:
            for stmt in (
                "UPDATE governance.events SET type = 'x'",
                "DELETE FROM governance.events",
            ):
                with pytest.raises(psycopg.errors.InsufficientPrivilege):
                    c.execute(stmt)


def test_two_instances_see_each_others_stop(pg, policy, channel, clock):
    a, b = PgEventStore(pg["app"]), PgEventStore(pg["app"])
    try:
        core_a = GovernanceCore(a, policy, channel, clock=clock)
        core_b = GovernanceCore(b, policy, channel, clock=clock)
        core_a.control(
            ControlCommand(
                command_id=uuid4(),
                command=ControlCommandType.PAUSE,
                scope=ControlScope.RECEPTOR,
                receptor_id="R77",
                issued_by=Component.GOVERNANCE_CORE,
                issued_at=clock(),
            )
        )
        # The test database is shared, so check R77's own state, not the master override.
        assert core_b.control_state(ControlScope.RECEPTOR, "R77").mode is ControlMode.PAUSED
    finally:
        a.close()
        b.close()


# HTTP API -------------------------------------------------------------------------------
def test_api_stop_requires_founder_proof(core, founder):
    client = TestClient(create_app(core))
    cmd = _stop(by=Component.FOUNDER, clock=founder.clock)
    body = cmd.model_dump(mode="json")
    assert client.post("/control", json=body).status_code == 422  # header missing
    assert client.post("/control", json=body, headers={"X-Founder-Proof": "bad"}).status_code == 409
    ok = client.post("/control", json=body, headers={"X-Founder-Proof": founder.channel.sign(cmd)})
    assert ok.status_code == 200 and ok.json()["mode"] == "stopped"
    assert client.get("/control/effective", params={"receptor_id": "R11"}).json() == {
        "mode": "stopped"
    }


def test_api_refuses_component_commands_and_founder_proposals(core, founder):
    client = TestClient(create_app(core))
    cmd = _stop(clock=founder.clock)
    assert (
        client.post(
            "/control", json=cmd.model_dump(mode="json"), headers={"X-Founder-Proof": "x"}
        ).status_code
        == 403
    )
    proposal = {"kind": "set_parameter", "payload": {}, "summary": "x", "requested_by": "founder"}
    assert client.post("/proposals", json=proposal).status_code == 422


def test_api_decision_flow(core, founder):
    client = TestClient(create_app(core))
    r = client.post(
        "/proposals",
        json={
            "kind": "set_parameter",
            "payload": {"name": "recovery_attempt_limit", "value": 2},
            "summary": "Set recovery_attempt_limit to 2",
            "requested_by": "E",
        },
    )
    assert r.status_code == 201
    from dyson_contracts.approvals import ApprovalRequest

    req = ApprovalRequest.model_validate(r.json())
    d, proof = founder.decision(req)
    out = client.post(
        "/decisions", json=d.model_dump(mode="json"), headers={"X-Founder-Proof": proof}
    )
    assert out.json() == {"status": "executed"}
    assert client.get(f"/approvals/{req.approval_id}").json() == {"status": "executed"}
    assert core.sync().parameters["recovery_attempt_limit"] == 2
