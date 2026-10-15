"""PRD §13 negative and security tests, run on the connected system."""

import ast
import sys
from datetime import date
from pathlib import Path
from uuid import UUID, uuid4

import psycopg
import pytest
from fastapi.testclient import TestClient
from integration_testkit import CANARY, NOW, say, status, task_of

from dyson_contracts.approvals import ApprovalDecision
from dyson_contracts.audit import AuditKind
from dyson_contracts.common import Component, RiskLevel
from dyson_contracts.control import ControlCommand, ControlMode, ControlScope
from dyson_contracts.toolcalls import ToolCallRequest
from dyson_governance.core import GovernanceError
from dyson_governance.events import BreachKind

ROOT = Path(__file__).resolve().parents[2]


def call(layer, tool, by=Component.ORCHESTRATOR, receptor="T0", credential=None, **args):
    request = ToolCallRequest(
        call_id=uuid4(),
        task_id=uuid4(),
        idempotency_key=f"test-{uuid4().hex}",
        tool_id=tool,
        requested_by=by,
        receptor_id=receptor,
        arguments=args,
        risk=RiskLevel.LOW,
        requested_at=NOW,
    )
    return layer.hub.call(request, credential or layer.tokens[by])


def denied_in_audit(layer, call_id):
    return [
        e
        for e in layer.memory.audit_events(limit=5000)
        if e.kind is AuditKind.TOOL_CALL_DENIED and e.data.get("call_id") == str(call_id)
    ]


def test_tool_without_permission_or_outside_registry_is_denied_and_audited(layer, t0):
    # LA-TOOL-01, LA-TOOL-04
    for result in (
        call(layer, "bank.transfer", amount=1),  # not in G's catalog
        call(layer, "t0.tally", receptor="R11", numbers=[1]),  # outside T0's scope
        call(layer, "t0.tally", credential="not-a-real-token-" + "x" * 20),
    ):
        assert result.status == "denied"
        assert denied_in_audit(layer, result.call_id)
    assert t0.assignments == []


def test_nobody_but_the_founder_can_approve(layer, gateway, founder):  # LA-GOV-02, LA-AMD-01
    task_id = task_of(say(gateway, founder, "Publish on T0: self-approved?"))
    layer.tick()
    (p,) = [r for r in layer.core.sync().proposals.values() if r.request.task_id == task_id]
    before = layer.core.sync().proposals[p.request.approval_id].status
    # A model, agent or Receptor cannot even build a decision in its own name ...
    for who in (Component.CONVERSATION_ENGINE, Component.HERMES, Component.RECEPTOR):
        with pytest.raises(ValueError):
            ApprovalDecision(
                approval_id=p.request.approval_id,
                action_digest=p.request.action_digest,
                decision="approve",
                decided_by=who,
                channel="direct_founder_controls",
                auth_method="x",
                decided_at=NOW,
            )
    # ... and a Founder-shaped decision without the channel proof is refused by A.
    forged = ApprovalDecision(
        approval_id=p.request.approval_id,
        action_digest=p.request.action_digest,
        decision="approve",
        decided_by="founder",
        channel="direct_founder_controls",
        auth_method="forged",
        decided_at=NOW,
    )
    with pytest.raises(GovernanceError):
        layer.core.decide(forged, "0" * 64)
    # A rule change proposed by B stays a proposal.
    out = say(gateway, founder, "Please propose a change to AMD-7: two retries")
    assert out["reply"]["kind"] == "proposal"
    amendment = layer.core.sync().proposals[UUID(out["reply"]["proposal_id"])]
    assert amendment.status.value == "open"
    assert layer.core.sync().proposals[p.request.approval_id].status == before


def test_stop_with_models_and_voice_down_reaches_everything(layer, gateway, founder, t0):
    # LA-GOV-03, LA-DFC-04, LA-SAF-01, LA-IF-03, LA-HER-05
    running = task_of(say(gateway, founder, "Tally 3 and 4 on T0"))
    for model in layer.models.values():
        model.down = True  # every model is down; voice is not even connected
    assert say(gateway, founder, "Tally 1 on T0")["reply"]["kind"] == "unavailable"

    state = layer.founder_device().control("stop", reason="drill")  # DFC -> A only
    assert state["mode"] == "stopped"
    assert t0.mode is ControlMode.STOPPED  # the control lane reached T0
    assert status(gateway, founder, running)["state"] == "stopped"  # and D
    assert call(layer, "t0.read").status == "denied"  # and G: no new tool call passes
    hermes_tool = layer.hermes.call_tool(
        uuid4(), "t0.read", {}, f"hermes-{uuid4().hex}", receptor_id="T0"
    )
    assert hermes_tool["status"] == "denied"
    from dyson_intelligence.models import ChatMessage, ModelRequest

    for model in layer.models.values():
        model.down = False
    with pytest.raises(Exception, match="stopped"):  # and Hermes's road to any model
        layer.hermes.think(
            "hermes.research",
            ModelRequest(messages=(ChatMessage(role="user", content="hi"),), max_output_tokens=10),
        )
    layer.tick(rounds=3)
    assert status(gateway, founder, running)["state"] == "stopped" and t0.assignments == []

    # Nothing resumes itself; the Founder resumes by approving a resume request.
    device = layer.founder_device()
    request = device.resume_request()
    device.decide(request["approval_id"], request["action_digest"], "approve")
    assert t0.mode is ControlMode.RUNNING
    layer.tick(rounds=3)
    assert status(gateway, founder, running)["state"] == "completed-verified"


def test_same_command_twice_after_a_network_retry_runs_once(layer, gateway, founder, t0):
    # LA-ORC-03, LA-REL-02
    mid, thread = str(uuid4()), uuid4()
    first = say(gateway, founder, "Tally 7 and 8 on T0", thread, client_message_id=mid)
    second = say(gateway, founder, "Tally 7 and 8 on T0", thread, client_message_id=mid)
    assert task_of(first) == task_of(second)
    layer.tick(rounds=3)
    assert len(t0.assignments) == 1


def test_canary_credential_never_leaks(layer, gateway, founder, dsns):  # LA-SEC-01, LA-MEM-06
    task_id = task_of(say(gateway, founder, "Tally 9 and 1 on T0"))
    layer.tick(rounds=3)
    assert status(gateway, founder, task_id)["state"] == "completed-verified"
    pasted = say(gateway, founder, f"my key is {CANARY} please use it")
    assert pasted["acknowledgment"] is None and "did not send or store" in pasted["reply"]["text"]
    for model in layer.models.values():  # never in a prompt
        assert not any(CANARY in p for p in model.prompts)
    for token in layer.tokens.values():
        assert not any(token in p for p in sum((m.prompts for m in layer.models.values()), []))
    with psycopg.connect(dsns["admin"]) as admin:  # never in any row of any schema
        tables = admin.execute(
            "SELECT table_schema, table_name FROM information_schema.tables WHERE table_schema"
            " IN ('memory','governance','toolhub','orchestrator','assurance','intelligence',"
            "'integration') AND table_type = 'BASE TABLE'"
        ).fetchall()
        for schema, table in tables:
            rows = admin.execute(f'SELECT t::text FROM "{schema}"."{table}" t').fetchall()
            for (text,) in rows:
                assert CANARY not in text, f"{schema}.{table}"
                assert not any(tok in text for tok in layer.tokens.values()), f"{schema}.{table}"


def test_no_bank_api_credential_or_payment_path_exists():  # LA-VLT-02
    banned = {
        "stripe",
        "razorpay",
        "paypal",
        "plaid",
        "braintree",
        "adyen",
        "paytm",
        "cashfree",
        "boto3",
        "requests",
        "urllib3",
        "smtplib",
        "ftplib",
    }
    for src in ROOT.glob("*/**/src/**/*.py"):
        if "/.venv/" in str(src):
            continue
        tree = ast.parse(src.read_text())
        for node in ast.walk(tree):
            names = (
                [a.name for a in node.names]
                if isinstance(node, ast.Import)
                else [node.module]
                if isinstance(node, ast.ImportFrom) and node.module and node.level == 0
                else []
            )
            for n in names:
                assert n.split(".")[0] not in banned, f"{src}: imports {n}"
                assert (
                    n.split(".")[0] in sys.stdlib_module_names
                    or n.split(".")[0]
                    in {
                        "pydantic",
                        "psycopg",
                        "fastapi",
                        "starlette",
                        "yaml",
                        "httpx",
                        "uvicorn",
                    }
                    or n.startswith("dyson_")
                ), f"{src}: unexpected dependency {n}"


def test_revenue_without_a_bank_statement_stays_reported(layer, t0):  # LA-FIN-02, LA-IF-05
    report = t0.revenue_report(date(2026, 10, 1), date(2026, 10, 15))  # Financial lane
    assert layer.finance.ingest_revenue(report).value == "reported_not_final"
    layer.tick()
    assert layer.finance.status(report.report_id).value == "reported_not_final"
    j = TestClient(layer.dashboard)
    assert j.get("/finance/receipts").json() == []
    assert j.get("/finance/reconciliation").json() == {"reported_not_final": 1}


def test_dashboard_has_no_action_path(layer):  # LA-DASH-02
    j = TestClient(layer.dashboard)
    for route in layer.dashboard.routes:
        assert getattr(route, "methods", {"GET"}) <= {"GET", "HEAD"}, route.path
    assert j.post("/finance/ledger").status_code == 405


def test_breach_never_resumes_without_authorization(layer, gateway, founder, t0):
    # LA-SAF-04, LA-IF-03
    layer.core.declare_breach(
        BreachKind.SECURITY,
        ControlScope.RECEPTOR,
        "T0",
        Component.MONITORING,
        "token reuse detected",
    )
    assert t0.mode is ControlMode.STOPPED
    task_id = task_of(say(gateway, founder, "Tally 1 and 2 on T0"))
    layer.tick(rounds=5)
    assert t0.mode is ControlMode.STOPPED and t0.assignments == []
    # Not even a Founder-shaped command resumes it: RESUME needs an approval for this stop.
    with pytest.raises(ValueError):
        ControlCommand(
            command_id=uuid4(),
            command="resume",
            scope="receptor",
            receptor_id="T0",
            issued_by="founder",
            issued_at=NOW,
        )
    device = layer.founder_device()
    request = device.resume_request(receptor_id="T0")
    assert "serious breach" in request["action_summary"]
    device.decide(request["approval_id"], request["action_digest"], "approve")
    layer.tick(rounds=3)
    assert status(gateway, founder, task_id)["state"] == "completed-verified"


def test_hermes_direct_tool_call_is_blocked_and_audited(layer, t0):  # LA-HER-03
    result = layer.hermes.call_tool(
        uuid4(), "t0.tally", {"numbers": [1]}, f"hermes-{uuid4().hex}", receptor_id="T0"
    )
    assert result["status"] == "denied"
    assert denied_in_audit(layer, UUID(result["call_id"]))
    assert t0.assignments == []
