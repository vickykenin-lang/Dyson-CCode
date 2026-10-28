"""Make a strong free model (Gemini 3 Flash) the conversation engine's primary.

C currently routes conversation.interpret to amazon.nova-micro-v1:0 (cheapest qualified, but too
weak). gemini-3-flash-preview (direct Google AI Studio, free, via the Founder's DFC-saved key)
benchmarks at 8/8 valid engine decisions, p95 ~2s (see docs/benchmarks/).
Priced at 0 it wins C's cheapest-first routing while clearing the quality bar; Bedrock stays the
trusted fallback for when Gemini errors or is slow. Three Founder approvals, exactly as the earlier
model rollouts (D-019, D-027).

    python -m dyson_integration.gemini_rollout propose   # A admits the model; three approvals
                                                          # wait on Direct Founder Controls
    python -m dyson_integration.gemini_rollout apply      # after the Founder approved all three
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

PROVIDER = "gemini"  # the OpenAI-compatible provider wired in serve.py::OAI_PROVIDERS
TASK = "conversation.interpret"
EVIDENCE = "docs/benchmarks/2026-10-26-gemini-conversation.md"
RUN_AT = datetime(2026, 10, 26, 0, 0, 0, tzinfo=UTC)

SPEC = ModelSpec(model_id="gemini-3-flash-preview", provider=PROVIDER,
                 input_price_per_mtok=Decimal(0), output_price_per_mtok=Decimal(0),
                 currency="USD")  # free tier  # fmt: skip
# Generous latency ceiling: Gemini benched p95 ~2s, but the free tier spikes; headroom keeps a
# future re-benchmark from dropping it, and the router falls back to Bedrock on a slow/failed call.
BAR = AcceptanceBar(task_class=TASK, min_quality=0.90, max_latency_ms=8000)
# The budget is per task-class and shared with the paid fallbacks (Nova/DeepSeek); keep it positive
# so the fallback still works when Gemini is down. Gemini itself is free, so it never consumes it.
BUDGET = ModelBudget(task_class=TASK, max_cost_per_day=Decimal("0.50"), currency="USD",
                     max_output_tokens_per_call=4000)  # fmt: skip
# Live measurement on B's real INTERPRETATION_SCHEMA (EVIDENCE): 8/8 valid decisions, p95 1999 ms.
QUALIFICATION = Qualification(model_id=SPEC.model_id, task_class=TASK, tasks_run=8,
                              tasks_passed=8, p95_latency_ms=1999,
                              cost_per_task=Decimal(0), currency="USD",
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
                                 "gemini-ai-studio", RiskLevel.MEDIUM, "D-028")  # fmt: skip
        core.record_security_check(
            SPEC.model_id, True, "Google AI Studio direct; key in secret store, read-only chat"
        )
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
    return router.route(TASK)


def _label(value) -> str:
    return getattr(value, "model_id", "") or f"{value.task_class}"


def main() -> None:
    from .serve import build_from_env

    layer = build_from_env()
    state = Path("/data/gemini_rollout.json")
    if sys.argv[1:] == ["propose"]:
        for p in propose(layer, state):
            print(f"{p['op']}: waiting for the Founder ({p['approval_id']})")
    elif sys.argv[1:] == ["apply"]:
        print("route for", TASK, "=", apply(layer, state))
    else:
        raise SystemExit("usage: gemini_rollout propose|apply")


if __name__ == "__main__":
    main()
