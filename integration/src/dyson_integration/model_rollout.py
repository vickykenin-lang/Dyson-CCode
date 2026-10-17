"""Put a benchmarked Bedrock model behind C for conversation.interpret (AMD-4, D-019).

Two steps, run inside the Layer A container on the server:

    python -m dyson_integration.model_rollout propose   # A admits the model; three approvals
                                                         # wait on Direct Founder Controls
    python -m dyson_integration.model_rollout apply     # after the Founder approved all three

The approvals are for exactly these values: registering the model with its prices, the
acceptance bar, and the daily model budget. C checks each approval against the value's digest,
so nothing else can be applied with them. The stand-in models get their real benchmark result
recorded, so they no longer pass the bar on a made-up score.
"""

import json
import sys
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from dyson_contracts.approvals import ApprovalCategory
from dyson_contracts.common import Component, RiskLevel
from dyson_contracts.integrations import IntegrationKind
from dyson_governance.events import ProposalKind
from dyson_intelligence.models import AcceptanceBar, ModelBudget, ModelSpec, Qualification

from .bedrock_model import PROVIDER as BEDROCK

TASK = "conversation.interpret"
EVIDENCE = "docs/benchmarks/2026-10-17-conversation-interpret.md"
RUN_AT = datetime(2026, 10, 17, 14, 4, 1, tzinfo=UTC)

SPEC = ModelSpec(model_id="deepseek.v3.2", provider=BEDROCK,
                 input_price_per_mtok=Decimal("0.64"), output_price_per_mtok=Decimal("1.91"),
                 currency="USD")  # fmt: skip
BAR = AcceptanceBar(task_class=TASK, min_quality=0.90, max_latency_ms=5000)  # D-019
# D-013: model calls at most 30 USD in total, about 0.16 USD a day.
BUDGET = ModelBudget(task_class=TASK, max_cost_per_day=Decimal("0.16"), currency="USD",
                     max_output_tokens_per_call=4000)  # fmt: skip
QUALIFICATION = Qualification(model_id=SPEC.model_id, task_class=TASK, tasks_run=26,
                              tasks_passed=25, p95_latency_ms=3423,
                              cost_per_task=Decimal("0.0007419"), currency="USD",
                              evidence_ref=EVIDENCE, run_at=RUN_AT)  # fmt: skip
STEPS = (
    ("register_model", SPEC, ApprovalCategory.INTEGRATION),
    ("set_acceptance_bar", BAR, ApprovalCategory.RULE_CHANGE),
    ("set_budget", BUDGET, ApprovalCategory.FINANCIAL),
)


def propose(layer, state: Path) -> list[dict]:
    core = layer.core
    if core.sync().integrations.get(SPEC.model_id) is None:
        core.propose_integration(SPEC.model_id, IntegrationKind.MODEL, SPEC.model_id,
                                 "bedrock-ap-southeast-2", RiskLevel.MEDIUM, "D-019")  # fmt: skip
        core.record_security_check(SPEC.model_id, True, "AWS Bedrock in ap-southeast-2 (D-013)")
        core.admit_integration(SPEC.model_id)
    pending = []
    for op, value, category in STEPS:
        payload = {"component": "C", "op": op, "value": value.model_dump(mode="json")}
        request = core.propose(ProposalKind.EXTERNAL_ACTION, payload,
                               f"Model Router: {op} {_label(value)}", Component.CORE_RD,
                               category)  # fmt: skip
        pending.append({"op": op, "approval_id": str(request.approval_id)})
    state.write_text(json.dumps(pending))
    return pending


def apply(layer, state: Path) -> list[str]:
    from uuid import UUID

    ids = {p["op"]: UUID(p["approval_id"]) for p in json.loads(state.read_text())}
    for op, _, _ in STEPS:
        status = layer.core.approval_status(ids[op])
        if status is None or status.value != "approved":
            raise SystemExit(f"{op}: approval {ids[op]} is {status and status.value}; not applied")
    router = layer.router
    router.register_model(SPEC, ids["register_model"])
    router.set_acceptance_bar(BAR, ids["set_acceptance_bar"])
    router.set_budget(BUDGET, ids["set_budget"])
    router.record_qualification(QUALIFICATION)
    from .rules_model import MODEL_ID
    from .system import BACKUP_MODEL_ID

    for model_id in (MODEL_ID, BACKUP_MODEL_ID):  # their real result on the same benchmark
        router.record_qualification(Qualification(
            model_id=model_id, task_class=TASK, tasks_run=26, tasks_passed=STAND_IN_PASSED,
            p95_latency_ms=5, cost_per_task=Decimal(0), currency="INR",
            evidence_ref=EVIDENCE, run_at=RUN_AT))  # fmt: skip
    return router.route(TASK)


STAND_IN_PASSED = 18  # the stand-in on the same 26 commands (EVIDENCE): 69%, under the bar


def _label(value) -> str:
    return getattr(value, "model_id", "") or f"{value.task_class}"


def main() -> None:
    from .serve import build_from_env

    layer = build_from_env()
    state = Path("/data/model_rollout.json")
    if sys.argv[1:] == ["propose"]:
        for p in propose(layer, state):
            print(f"{p['op']}: waiting for the Founder ({p['approval_id']})")
    elif sys.argv[1:] == ["apply"]:
        print("route for", TASK, "=", apply(layer, state))
    else:
        raise SystemExit("usage: model_rollout propose|apply")


if __name__ == "__main__":
    main()
