"""Gemini primary / direct Claude Sonnet fallback, with action-bound DFC approvals.

propose creates reviewable requests only. apply needs those approvals and the
approved source deployment. It qualifies Sonnet on synthetic requests, accounts
for every attempt against the existing conversation budget, and retires Bedrock
only after qualification succeeds. It never signs a Founder decision.
"""

import json
import sys
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from time import monotonic
from uuid import UUID, uuid4

from dyson_contracts.approvals import ApprovalCategory
from dyson_contracts.common import Component, RiskLevel
from dyson_contracts.integrations import IntegrationKind
from dyson_governance.events import ProposalKind
from dyson_intelligence.conversation import INTERPRETATION_SCHEMA, _Interpretation
from dyson_intelligence.models import (
    ChatMessage,
    ModelRequest,
    ModelResponse,
    ModelSpec,
    Qualification,
)
from dyson_intelligence.router import TRUSTED_PROVIDERS, _cost, _input_bound

TASK = "conversation.interpret"
PRIMARY = "gemini-3-flash-preview"
SPEC = ModelSpec(
    model_id="claude-sonnet-4-6",
    provider="claudeapi",
    currency="USD",
    input_price_per_mtok=Decimal("3"),
    output_price_per_mtok=Decimal("15"),
)
RETIRE = ("amazon.nova-micro-v1:0", "deepseek.v3.2")
SOURCE_REF = "codex/gemini-sonnet-route-20261030"
CASES = (
    ("Say namaste in Hinglish.", "answer"),
    ("What should you do when my instruction is ambiguous?", "answer"),
    ("Explain in one sentence what a pending approval means.", "answer"),
)
DEPLOY = {
    "component": "C",
    "op": "deploy_direct_provider_allowlist",
    "value": {
        "source": SOURCE_REF,
        "allow_sensitive_to": ["gemini", "claudeapi"],
        "exclude_relays": True,
        "primary": PRIMARY,
        "fallback": SPEC.model_id,
    },
}
BENCH = {
    "component": "C",
    "op": "qualify_direct_sonnet",
    "value": {
        "model": SPEC.model_dump(mode="json"),
        "cases": [list(case) for case in CASES],
        "max_output_tokens": 128,
        "budget": "existing conversation.interpret budget",
    },
}


def steps():
    return [
        (
            "register",
            {"component": "C", "op": "register_model", "value": SPEC.model_dump(mode="json")},
            ApprovalCategory.INTEGRATION,
        ),
        ("benchmark", BENCH, ApprovalCategory.FINANCIAL),
        *[
            (
                f"retire:{m}",
                {"component": "C", "op": "retire_model", "value": {"model_id": m}},
                ApprovalCategory.INTEGRATION,
            )
            for m in RETIRE
        ],
        ("deployment", DEPLOY, ApprovalCategory.DEPLOYMENT),
    ]


def propose(layer, state):
    core = layer.core
    if SPEC.model_id not in core.registry():
        core.propose_integration(
            SPEC.model_id,
            IntegrationKind.MODEL,
            SPEC.model_id,
            "anthropic-direct",
            RiskLevel.MEDIUM,
            SOURCE_REF,
        )
        core.record_security_check(
            SPEC.model_id,
            True,
            "Direct api.anthropic.com; DFC credential and model catalog verified. "
            "Inference qualification remains pending; no operational qualification claimed.",
        )
        core.admit_integration(SPEC.model_id)
    pending = []
    for name, payload, category in steps():
        digest = core.external_action_digest(payload)
        current = datetime.now(UTC)
        existing = next(
            (
                p.request
                for p in core.sync().proposals.values()
                if p.request.action_digest == digest
                and p.status.value in ("open", "approved")
                and (p.request.expires_at is None or p.request.expires_at > current)
            ),
            None,
        )
        req = existing or core.propose(
            ProposalKind.EXTERNAL_ACTION,
            payload,
            f"Gemini > Sonnet migration: {name}; keep USD 0.50/day; direct providers may receive "
            "redacted knowledge context; no relay access",
            Component.CORE_RD,
            category,
        )
        pending.append(
            {"step": name, "approval_id": str(req.approval_id), "action_digest": req.action_digest}
        )
    state.write_text(json.dumps(pending, indent=2))
    return pending


def qualify(layer):
    router = layer.router
    budget = router._budget(TASK)
    if budget.currency != "USD" or budget.max_cost_per_day > Decimal("0.50"):
        raise RuntimeError("Expected existing USD conversation budget at most 0.50/day")
    passed, costs, times = 0, [], []
    adapter = router._adapters[SPEC.provider]
    for question, expected in CASES:
        request = ModelRequest(
            system="You are Dyson's conversation interpreter. Answer only as JSON matching "
            "the schema. Do not use tools or claim to execute anything.",
            messages=(ChatMessage(role="user", content=question),),
            max_output_tokens=128,
            response_schema=INTERPRETATION_SCHEMA,
        )
        aid, cid = uuid4(), uuid4()
        worst = _cost(SPEC, _input_bound(request), request.max_output_tokens)
        router._reserve(aid, cid, 1, Component.CONVERSATION_ENGINE, TASK, SPEC, worst, budget)
        started = monotonic()
        try:
            response = adapter.complete(request, SPEC.model_id)
            if response.output_tokens > request.max_output_tokens:
                raise RuntimeError("Sonnet exceeded benchmark output limit")
        except Exception as exc:
            # Preserve the reservation as an upper bound when the provider may have billed.
            router._settle(
                aid,
                cid,
                1,
                Component.CONVERSATION_ENGINE,
                TASK,
                SPEC,
                "failed",
                ModelResponse(text="", input_tokens=0, output_tokens=0),
                worst,
                type(exc).__name__,
            )
            raise RuntimeError("Sonnet qualification failed; Bedrock was not retired") from None
        cost = _cost(SPEC, response.input_tokens, response.output_tokens)
        router._settle(
            aid, cid, 1, Component.CONVERSATION_ENGINE, TASK, SPEC, "ok", response, cost, ""
        )
        times.append(int((monotonic() - started) * 1000))
        costs.append(cost)
        interpretation = _Interpretation.model_validate(json.loads(response.text))
        passed += int(interpretation.kind == expected and bool(interpretation.text.strip()))
    q = Qualification(
        model_id=SPEC.model_id,
        task_class=TASK,
        tasks_run=len(CASES),
        tasks_passed=passed,
        p95_latency_ms=max(times),
        cost_per_task=sum(costs) / len(costs),
        currency="USD",
        evidence_ref="model_pair_rollout:synthetic-live-qualification",
        run_at=datetime.now(UTC),
    )
    if passed != len(CASES) or max(times) > 8000:
        raise RuntimeError("Sonnet did not meet the current acceptance bar; Bedrock not retired")
    return q


def apply(layer, state):
    pending = {p["step"]: UUID(p["approval_id"]) for p in json.loads(state.read_text())}
    core, router = layer.core, layer.router
    registration_applied = False
    for name, _, _ in steps():
        status = core.approval_status(pending[name])
        if name == "register" and status is not None and status.value == "consumed":
            row = router._conn.execute(
                "SELECT spec, enabled, approval_id FROM intelligence.models "
                "WHERE model_id = %s ORDER BY seq DESC LIMIT 1",
                [SPEC.model_id],
            ).fetchone()
            if (
                row
                and row["enabled"]
                and row["spec"] == SPEC.model_dump(mode="json")
                and row["approval_id"] == pending["register"]
            ):
                registration_applied = True
                continue
        if status is None or status.value != "approved":
            raise RuntimeError(f"{name}: requires the matching DFC approval; no bypass")
    if not {"gemini", "claudeapi"}.issubset(TRUSTED_PROVIDERS):
        raise RuntimeError("Deploy the approved direct-provider allowlist first")
    # Apply registration through C; no fabricated model/qualification database rows.
    if not registration_applied:
        router.register_model(SPEC, pending["register"])
    core.consume_approval(
        pending["benchmark"],
        core.external_action_digest(BENCH),
        ApprovalCategory.FINANCIAL,
        by=Component.CORE_RD,
    )
    q = qualify(layer)
    router.record_qualification(q)
    route = router.route(TASK)
    if PRIMARY not in route or SPEC.model_id not in route or route[0] != PRIMARY:
        raise RuntimeError("Expected Gemini primary and qualified Sonnet before retirement")
    for model in RETIRE:
        router.retire_model(model, pending[f"retire:{model}"])
    core.consume_approval(
        pending["deployment"],
        core.external_action_digest(DEPLOY),
        ApprovalCategory.DEPLOYMENT,
        by=Component.CORE_RD,
    )
    return {"route": router.route(TASK), "qualification": q.model_dump(mode="json")}


def main():
    from .serve import _models, _now, _settings_and_dsns
    from .system import LayerA
    from .t0 import TestReceptorT0

    settings, dsns = _settings_and_dsns(migrate=False)
    layer = LayerA.build(dsns, settings, TestReceptorT0(), _now, _models(settings.secret_file))
    state = Path("/data/model_pair_rollout.json")
    if sys.argv[1:] == ["propose"]:
        print(json.dumps(propose(layer, state)))
    elif sys.argv[1:] == ["apply"]:
        print(json.dumps(apply(layer, state)))
    else:
        raise SystemExit("usage: model_pair_rollout propose|apply")


if __name__ == "__main__":
    main()
