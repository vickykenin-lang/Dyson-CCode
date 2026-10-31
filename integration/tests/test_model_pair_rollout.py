"""Offline migration gates and sensitive-route fallback; no provider calls."""

import json
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4

import pytest

from dyson_contracts.common import Component
from dyson_integration import model_pair_rollout as rollout
from dyson_intelligence.models import (
    ChatMessage,
    ModelBudget,
    ModelRequest,
    ModelResponse,
    ModelSpec,
)
from dyson_intelligence.router import TRUSTED_PROVIDERS, ModelRouter


def test_migration_values_preserve_primary_and_retire_only_bedrock():
    assert rollout.PRIMARY == "gemini-3-flash-preview"
    assert rollout.SPEC.provider == "claudeapi"
    assert rollout.SPEC.input_price_per_mtok == Decimal("3")
    assert rollout.SPEC.output_price_per_mtok == Decimal("15")
    assert set(rollout.RETIRE) == {"amazon.nova-micro-v1:0", "deepseek.v3.2"}
    assert len(rollout.steps()) == 5
    assert all(op != "set_budget" for _, p, _ in rollout.steps() for op in [p["op"]])


def test_apply_without_dfc_approval_never_registers_or_retires(tmp_path):
    state = tmp_path / "state.json"
    state.write_text(
        json.dumps([{"step": name, "approval_id": str(uuid4())} for name, _, _ in rollout.steps()])
    )
    layer = SimpleNamespace(core=Mock(), router=Mock())
    layer.core.approval_status.return_value = None
    with pytest.raises(RuntimeError, match="requires the matching DFC approval"):
        rollout.apply(layer, state)
    layer.router.register_model.assert_not_called()
    layer.router.retire_model.assert_not_called()
    layer.core.consume_approval.assert_not_called()


class Harness(ModelRouter):
    def __init__(self, adapters):
        self._adapters = adapters
        self._personal = tuple
        self.selected = []
        self.specs = {
            rollout.PRIMARY: ModelSpec(
                model_id=rollout.PRIMARY,
                provider="gemini",
                currency="USD",
                input_price_per_mtok=0,
                output_price_per_mtok=0,
            ),
            rollout.SPEC.model_id: rollout.SPEC,
        }

    def _budget(self, task):
        return ModelBudget(
            task_class=task,
            currency="USD",
            max_cost_per_day=Decimal("0.50"),
            max_output_tokens_per_call=4000,
        )

    def route(self, task):
        return [rollout.PRIMARY, rollout.SPEC.model_id]

    def _models(self):
        return self.specs

    def _reserve(self, *args):
        self.selected.append(args[5].provider)

    def _settle(self, *args):
        pass


def request():
    return ModelRequest(
        system="Synthetic context",
        messages=(ChatMessage(role="user", content="hi"),),
        max_output_tokens=128,
        sensitive=True,
    )


def test_grounded_requests_can_use_direct_gemini():
    gemini, claude = Mock(), Mock()
    gemini.complete.return_value = ModelResponse(text="hello", input_tokens=5, output_tokens=1)
    result = Harness({"gemini": gemini, "claudeapi": claude}).complete(
        Component.CONVERSATION_ENGINE, rollout.TASK, request()
    )
    assert result.model_id == rollout.PRIMARY
    claude.complete.assert_not_called()


def test_grounded_request_falls_back_to_sonnet_when_gemini_fails():
    gemini, claude = Mock(), Mock()
    gemini.complete.side_effect = RuntimeError("synthetic primary failure")
    claude.complete.return_value = ModelResponse(text="hello", input_tokens=5, output_tokens=1)
    result = Harness({"gemini": gemini, "claudeapi": claude}).complete(
        Component.CONVERSATION_ENGINE, rollout.TASK, request()
    )
    assert result.model_id == rollout.SPEC.model_id
    assert not result.attempts[0].ok and result.attempts[1].ok
    assert result.cost > 0


def test_relays_remain_excluded_from_private_context():
    assert {"gemini", "claudeapi"}.issubset(TRUSTED_PROVIDERS)
    assert "apinex" not in TRUSTED_PROVIDERS and "groq" not in TRUSTED_PROVIDERS


def test_all_approval_payloads_are_native_json_values():
    from pydantic import JsonValue, TypeAdapter

    for _, payload, _ in rollout.steps():
        TypeAdapter(JsonValue).validate_python(payload)


def test_apply_consumes_native_approval_with_required_actor(tmp_path, monkeypatch):
    from datetime import UTC, datetime

    from dyson_intelligence.models import Qualification

    state = tmp_path / "state.json"
    state.write_text(
        json.dumps([{"step": n, "approval_id": str(uuid4())} for n, _, _ in rollout.steps()])
    )
    actors = []

    def consume(approval_id, digest, category, by):
        actors.append(by)

    core = SimpleNamespace(
        approval_status=lambda aid: SimpleNamespace(value="approved"),
        consume_approval=consume,
        external_action_digest=lambda payload: "digest",
    )
    router = Mock()
    router.route.return_value = [rollout.PRIMARY, rollout.SPEC.model_id]
    q = Qualification(
        model_id=rollout.SPEC.model_id,
        task_class=rollout.TASK,
        tasks_run=3,
        tasks_passed=3,
        p95_latency_ms=1,
        cost_per_task=Decimal("0.001"),
        currency="USD",
        evidence_ref="synthetic-test",
        run_at=datetime.now(UTC),
    )
    monkeypatch.setattr(rollout, "qualify", lambda layer: q)
    result = rollout.apply(SimpleNamespace(core=core, router=router), state)
    assert actors == [Component.CORE_RD, Component.CORE_RD]
    assert result["route"] == [rollout.PRIMARY, rollout.SPEC.model_id]
