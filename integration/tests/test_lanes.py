"""The five lanes, Test T0, bounded repair, H to J through I, and G's routing."""

import ast
import hashlib
from datetime import date
from decimal import Decimal
from pathlib import Path
from uuid import UUID, uuid4

from fastapi.testclient import TestClient
from integration_testkit import NOW, say, status, task_of

from dyson_assurance.finance import FinancialController
from dyson_contracts.common import Component, Money, RiskLevel
from dyson_contracts.finance import BankStatementUpload, PaymentMethod, RevenueReport
from dyson_contracts.toolcalls import ToolCallRequest
from dyson_integration import t0 as t0_module

SRC = Path(__file__).resolve().parents[1] / "src" / "dyson_integration"
LANES = {"assign", "health_report", "revenue_report", "on_control", "published"}


def test_layer_a_reaches_t0_only_through_the_five_lanes():  # LA-IF-01
    """Outside t0.py, the only T0 attributes Layer A touches are its lane entry points (and,
    for tests and repairs, the T0Verifier reads `published`: the real output, never a claim)."""
    for path in SRC.glob("*.py"):
        if path.name == "t0.py":
            continue
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
                if node.value.id == "t0":
                    assert node.attr in LANES | {"on_control"}, f"{path.name}: t0.{node.attr}"
            if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Attribute):
                if getattr(node.value, "attr", "") == "t0":
                    assert node.attr in LANES, f"{path.name}: .t0.{node.attr}"


def test_t0_is_synthetic_with_no_money(layer):  # LA-IF-12
    manifest = t0_module.MANIFEST
    assert manifest.synthetic is True and manifest.handles_money is False
    limits = layer.core.limits("T0")
    assert limits.max_spend_per_action.amount == 0 and limits.max_spend_per_month.amount == 0
    assert layer.core.sync().receptors["T0"].status.value == "active"


def test_every_task_to_t0_goes_through_g_with_id_and_key(layer, gateway, founder, t0):
    # LA-IF-02
    for text in ("Tally 1 and 2 on T0", "Tally 3 and 4 on T0"):
        say(gateway, founder, text)
    layer.tick(rounds=3)
    executed = [d for d in layer.hub._store.decisions() if d["allowed"]]
    assert len(t0.assignments) == len(executed) == 2
    for a in t0.assignments:
        assert a.idempotency_key.startswith(f"{a.task_id}:a")


def test_inspect_repair_and_return_evidence(layer, t0):
    # PRD §13 stream D milestone; LA-G-05, LA-SAF-05
    layer.tick()
    t0.broken = True  # T0's worker starts failing
    layer.tick()
    (attempts,) = layer.repairs.incidents.values()
    assert attempts[-1]["status"] == "executed" and attempts[-1]["verified"] is True
    assert t0.restarts == 1 and t0.health_report().status.value == "healthy"
    assert attempts[-1]["evidence_ids"]  # F checked the repair independently
    layer.tick(rounds=3)
    assert t0.restarts == 1  # healthy again: no more repairs


def test_repairs_stop_at_the_founder_set_limit(layer, t0):  # LA-SAF-05, D-008
    layer.tick()
    t0.hard_broken = True  # a restart cannot fix this
    layer.tick(rounds=6)
    assert t0.restarts == 3  # recovery_attempt_limit
    told = [m for m in layer.inbox.messages if m[2].startswith("Repair limit")]
    assert len(told) == 1 and told[0][0] == "founder"


def test_finance_reaches_j_only_through_verified_records_in_i(layer):  # LA-FIN-05, LA-DASH-04
    report = RevenueReport(
        report_id=uuid4(),
        receptor_id="R11",
        period_start=date(2026, 10, 1),
        period_end=date(2026, 10, 15),
        amount=Money(amount=Decimal("1500.00"), currency="INR"),
        payment_method=PaymentMethod.UPI,
        reference="ORDER-77",
        reported_at=NOW,
    )
    layer.finance.ingest_revenue(report)
    csv = b"date,direction,amount,currency,reference\n2026-10-10,credit,1500.00,INR,ORDER-77\n"
    upload = BankStatementUpload(
        upload_id=uuid4(),
        uploaded_by="founder",
        file_sha256=hashlib.sha256(csv).hexdigest(),
        filename="oct.csv",
        period_start=date(2026, 10, 1),
        period_end=date(2026, 10, 31),
        uploaded_at=NOW,
    )
    layer.finance.upload_statement(upload, csv)
    layer.tick()
    j = TestClient(layer.dashboard)
    (receipt,) = j.get("/finance/receipts").json()
    assert receipt["report_id"] == str(report.report_id)

    # A receipt H holds but whose evidence never reached I is not shown as verified.
    class Lost:
        def record(self, evidence, receptor_id):
            pass

    stray = FinancialController(layer.finance._c, Lost(), layer.clock)
    other = report.model_copy(update={"report_id": uuid4(), "reference": "ORDER-78"})
    stray.ingest_revenue(other)
    csv2 = b"date,direction,amount,currency,reference\n2026-10-11,credit,1500.00,INR,ORDER-78\n"
    stray.upload_statement(
        upload.model_copy(
            update={"upload_id": uuid4(), "file_sha256": hashlib.sha256(csv2).hexdigest()}
        ),
        csv2,
    )
    stray.reconcile()
    assert len(layer.finance.receipts()) == 2  # H has both
    assert [r["report_id"] for r in j.get("/finance/receipts").json()] == [str(report.report_id)]
    (line,) = [x for x in j.get("/finance/ledger").json() if x["receptor_id"] == "R11"]
    assert Decimal(line["verified_revenue"]) == Decimal("1500.00")


def _core_call(layer, tool, by=Component.ORCHESTRATOR, **args):
    request = ToolCallRequest(
        call_id=uuid4(),
        task_id=uuid4(),
        idempotency_key=f"route-{uuid4().hex}",
        tool_id=tool,
        requested_by=by,
        arguments=args,
        risk=RiskLevel.LOW,
        requested_at=NOW,
    )
    return layer.hub.call(request, layer.tokens[by])


def test_g_routes_to_hermes_qa_and_finance_within_scope(layer, gateway, founder):  # LA-TOOL-05
    hermes = _core_call(layer, "hermes.research", question="What sells best in October?")
    assert hermes.status == "executed"
    assert hermes.result["verified"] is False and hermes.result["produced_by"] == "hermes"
    assert _core_call(layer, "finance.reconcile").status == "executed"
    task_id = task_of(say(gateway, founder, "Tally 2 and 5 on T0"))
    layer.tick(rounds=3)
    audit = _core_call(layer, "qa.audit", task_id=str(task_id))
    assert audit.status == "executed" and audit.result == {"verdicts": 1}
    # Out of scope: Hermes may not route work to Hermes, F or H.
    for tool in ("hermes.research", "finance.reconcile", "qa.audit"):
        assert _core_call(layer, tool, by=Component.HERMES).status == "denied"


def test_core_rd_proposals_enter_the_amendment_workflow(layer):  # LA-RD-04
    request = layer.core.propose_amendment(
        "AMD-7", "- 3 retries\n+ 2 retries", "Retries past 2 never succeed", Component.CORE_RD
    )
    device = layer.founder_device()
    pending = {p["approval_id"]: p for p in device.pending()}
    assert str(request.approval_id) in pending
    assert pending[str(request.approval_id)]["category"] == "rule_change"
    before = layer.memory.register_view("AMD-7")
    device.decide(request.approval_id, request.action_digest, "approve")
    assert layer.core.approval_status(request.approval_id).value == "approved"
    assert layer.memory.register_view("AMD-7") == before  # never applied at runtime


def test_controls_stay_effective_while_an_amendment_is_in_flight(layer, gateway, founder, t0):
    # LA-AMD-03
    request = layer.core.propose_amendment(
        "AMD-5", "change STOP wording", "clarity", Component.CORE_RD
    )
    for stage in ("proposed", "approved"):
        if stage == "approved":
            layer.approve(request)
        # financial / high-risk approval is still required
        task_id = task_of(say(gateway, founder, f"Publish on T0: during {stage}"))
        layer.tick()
        assert status(gateway, founder, task_id)["state"] == "approval-needed"
        # per-Receptor scope is still enforced
        out = _core_call(layer, "t0.tally", numbers=[1])
        assert out.status == "denied"
        # STOP still works, and audit logging continues
        before = len(layer.memory.audit_events(limit=5000))
        layer.founder_device().control("pause", receptor_id="T0")
        assert t0.mode.value == "paused"
        assert len(layer.memory.audit_events(limit=5000)) > before
        req = layer.founder_device().resume_request(receptor_id="T0")
        layer.founder_device().decide(UUID(req["approval_id"]), req["action_digest"], "approve")
        assert t0.mode.value == "running"
    # and the QA/QC hold still applies
    held = task_of(say(gateway, founder, "Tally 1, 2, 3, 4, 5, 6 on T0"))
    layer.tick(rounds=12)
    assert status(gateway, founder, held)["state"] == "held"
