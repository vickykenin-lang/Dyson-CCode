"""Switch C to a working model (Nova micro) for the benchmark (D-027).

Finding 1 showed deepseek.v3.2 is non-functional on Bedrock; Nova micro answers in 0.4 s and
produces valid engine decisions (6/6). This registers it behind C, priced below deepseek, so C
routes to it. Three Founder approvals, exactly as the first model rollout (D-019).

    python -m dyson_integration.nova_rollout propose   # A admits the model; three approvals
                                                        # wait on Direct Founder Controls
    python -m dyson_integration.nova_rollout apply      # after the Founder approved all three
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
EVIDENCE = "docs/benchmarks/2026-10-20-milestone-a-findings.md"
RUN_AT = datetime(2026, 10, 20, 12, 0, 0, tzinfo=UTC)

SPEC = ModelSpec(model_id="amazon.nova-micro-v1:0", provider=BEDROCK,
                 input_price_per_mtok=Decimal("0.035"), output_price_per_mtok=Decimal("0.14"),
                 currency="USD")  # fmt: skip
BAR = AcceptanceBar(task_class=TASK, min_quality=0.90, max_latency_ms=5000)
# A small daily cap for the benchmark; Nova micro is cheap, so cents is plenty.
BUDGET = ModelBudget(task_class=TASK, max_cost_per_day=Decimal("0.50"), currency="USD",
                     max_output_tokens_per_call=4000)  # fmt: skip
# Real measurement on 6 engine-decision prompts (findings doc): 6/6 valid, p95 386 ms, Nova 0.4s.
QUALIFICATION = Qualification(model_id=SPEC.model_id, task_class=TASK, tasks_run=6,
                              tasks_passed=6, p95_latency_ms=386,
                              cost_per_task=Decimal("0.0000200"), currency="USD",
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
                                 "bedrock-ap-southeast-2", RiskLevel.MEDIUM, "D-027")  # fmt: skip
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
    state = Path("/data/nova_rollout.json")
    if sys.argv[1:] == ["propose"]:
        for p in propose(layer, state):
            print(f"{p['op']}: waiting for the Founder ({p['approval_id']})")
    elif sys.argv[1:] == ["apply"]:
        print("route for", TASK, "=", apply(layer, state))
    else:
        raise SystemExit("usage: nova_rollout propose|apply")


if __name__ == "__main__":
    main()
