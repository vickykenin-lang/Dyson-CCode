"""D-019: the benchmarked Bedrock model goes behind C only with the Founder's three approvals,
for exactly the approved values, and then serves B; the stand-ins no longer pass the bar."""

import json
from uuid import UUID

import pytest
from integration_testkit import say

from dyson_integration import model_rollout
from dyson_intelligence.models import ModelResponse


class FakeBedrock:
    def __init__(self):
        self.calls = []

    def complete(self, request, model_id):
        self.calls.append(model_id)
        reply = {"language": "en", "kind": "answer", "text": "I can tally numbers on T0."}
        return ModelResponse(text=json.dumps(reply), input_tokens=900, output_tokens=40)


def test_rollout_needs_all_three_approvals_then_serves_b(layer, gateway, founder, tmp_path):
    bedrock = FakeBedrock()
    layer.router._adapters["bedrock"] = bedrock
    state = tmp_path / "rollout.json"
    pending = model_rollout.propose(layer, state)
    assert [p["op"] for p in pending] == ["register_model", "set_acceptance_bar", "set_budget"]

    with pytest.raises(SystemExit):  # nothing applies before the Founder decides
        model_rollout.apply(layer, state)
    device = layer.founder_device()
    waiting = {p["approval_id"]: p for p in device.pending()}
    for p in pending[:2]:
        w = waiting[p["approval_id"]]
        device.decide(UUID(p["approval_id"]), w["action_digest"], "approve")
    with pytest.raises(SystemExit):  # two of three is not enough
        model_rollout.apply(layer, state)
    w = waiting[pending[2]["approval_id"]]
    device.decide(UUID(pending[2]["approval_id"]), w["action_digest"], "approve")

    assert model_rollout.apply(layer, state) == ["deepseek.v3.2"]
    out = say(gateway, founder, "What can you do?")
    assert out["reply"]["text"] == "I can tally numbers on T0."
    assert bedrock.calls == ["deepseek.v3.2"]
