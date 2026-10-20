"""The Jarvis engine (phase 5): the agent loop, subagents, STOP, and skill gating."""

import json
from decimal import Decimal
from uuid import uuid4

import pytest

from dyson_contracts.capability import (
    Budget,
    CapabilityKind,
    CapabilityManifest,
    IsolationTier,
    Operation,
    Provenance,
)
from dyson_contracts.common import Component, RiskLevel
from dyson_intelligence.engine import JarvisEngine, StopReason
from dyson_intelligence.models import Attempt, ModelResponse, RoutedResponse

TOOLS = frozenset({"calendar.list", "mail.send"})


class ScriptRouter:
    """Returns decisions from a script, one per step."""

    def __init__(self, *decisions):
        self.decisions = [d if isinstance(d, str) else json.dumps(d) for d in decisions]
        self.i = 0

    def complete(self, task_class, request):
        text = self.decisions[min(self.i, len(self.decisions) - 1)]
        self.i += 1
        resp = ModelResponse(text=text, input_tokens=5, output_tokens=5)
        return RoutedResponse(call_id=uuid4(), model_id="fake", response=resp,
                              cost=Decimal("0"), currency="INR",
                              attempts=(Attempt(model_id="fake", ok=True),))  # fmt: skip


class Hub:
    """Records tool calls; returns a scripted status per call_id order."""

    def __init__(self, *results):
        self.results = list(results) or [{"status": "ok", "value": "done"}]
        self.calls = []

    def call(self, request):
        self.calls.append(request)
        return self.results[min(len(self.calls) - 1, len(self.results) - 1)]


def _skill():
    return CapabilityManifest(
        id="dyson.skill.summarise",
        version="0.1.0",
        kind=CapabilityKind.SKILL,
        contract_version="1.0.0",
        publisher="Dyson",
        license="MIT",
        summary="summarise a thread",
        provenance=Provenance(source_url="dyson://skills/s", artifact_digest="a" * 64),
        operations=(Operation(name="run", summary="summarise", risk=RiskLevel.LOW),),
        budget=Budget(cpus=Decimal("0.25"), memory_mb=128, timeout_s=30, calls_per_minute=10),
        isolation=IsolationTier.GVISOR,
        risk=RiskLevel.LOW,
    )


def test_a_tool_step_then_done():
    router = ScriptRouter(
        {"action": "call", "tool_id": "calendar.list", "arguments": {}},
        {"action": "done", "output": "you have 2 meetings"},
    )
    hub = Hub({"status": "ok", "events": 2})
    run = JarvisEngine(router, hub).run(uuid4(), "what's on today?", TOOLS)
    assert run.stop_reason is StopReason.DONE
    assert run.output == "you have 2 meetings" and run.unverified
    assert [c.tool_id for c in hub.calls] == ["calendar.list"]


def test_a_tool_outside_the_allowed_set_is_refused_locally():
    # The model keeps asking for a tool it was never given. Each attempt is refused locally and
    # fed back as a correction; it never reaches G, and after MAX_STRIKES the engine gives up.
    router = ScriptRouter({"action": "call", "tool_id": "shell.run", "arguments": {}})
    hub = Hub()
    run = JarvisEngine(router, hub).run(uuid4(), "do something", TOOLS)
    assert run.stop_reason is StopReason.ERROR and hub.calls == []  # never reached G
    assert sum(1 for s in run.steps if s.result == "not allowed") == 3  # tried, then gave up


def test_the_engine_recovers_after_an_off_limits_tool():
    # First the model reaches for a tool it does not have; the engine refuses locally and re-plans.
    # On the next turn it picks an allowed tool and finishes — no stop, no wasted run.
    router = ScriptRouter(
        {"action": "call", "tool_id": "shell.run", "arguments": {}},
        {"action": "call", "tool_id": "calendar.list", "arguments": {}},
        {"action": "done", "output": "clear"},
    )
    hub = Hub({"status": "ok", "events": 0})
    run = JarvisEngine(router, hub).run(uuid4(), "what's on today?", TOOLS)
    assert run.stop_reason is StopReason.DONE and run.output == "clear"
    assert [c.tool_id for c in hub.calls] == ["calendar.list"]  # shell.run never reached G
    assert any(s.result == "not allowed" for s in run.steps)  # the refusal is on the record


def test_the_engine_recovers_after_a_malformed_decision():
    router = ScriptRouter("not json", {"action": "done", "output": "ok"})
    run = JarvisEngine(router, Hub()).run(uuid4(), "x", TOOLS)
    assert run.stop_reason is StopReason.DONE and run.output == "ok"


def test_a_latency_budget_stops_a_slow_run():
    # A fake monotonic clock jumps 7s per reading; with a 10s budget the run times out after the
    # first completed step instead of grinding through the whole step budget.
    from itertools import count

    ticks = count(0, 7)
    router = ScriptRouter({"action": "call", "tool_id": "calendar.list", "arguments": {}})
    hub = Hub({"status": "ok"})
    engine = JarvisEngine(router, hub, monotonic=lambda: next(ticks))
    run = engine.run(uuid4(), "loop", TOOLS, max_steps=10, max_seconds=10)
    assert run.stop_reason is StopReason.TIMEOUT
    assert len(hub.calls) == 1  # one step done, then the budget cut it off


def test_stop_ends_the_loop_at_once():
    router = ScriptRouter({"action": "call", "tool_id": "mail.send", "arguments": {}},
                          {"action": "done", "output": "sent"})  # fmt: skip
    hub = Hub({"status": "stopped"})
    run = JarvisEngine(router, hub).run(uuid4(), "send mail", TOOLS)
    assert run.stop_reason is StopReason.STOPPED
    assert run.output is None and len(hub.calls) == 1  # stopped before a second step


def test_a_denied_tool_ends_the_run():
    router = ScriptRouter({"action": "call", "tool_id": "mail.send", "arguments": {}})
    hub = Hub({"status": "denied", "denied_checks": ["approval"]})
    run = JarvisEngine(router, hub).run(uuid4(), "send mail", TOOLS)
    assert run.stop_reason is StopReason.DENIED


def test_relentlessly_malformed_decisions_give_up_as_error():
    # The model never returns valid JSON. The engine re-plans, then gives up after MAX_STRIKES.
    run = JarvisEngine(ScriptRouter("not json"), Hub()).run(uuid4(), "x", TOOLS)
    assert run.stop_reason is StopReason.ERROR


def test_the_step_budget_is_bounded():
    # Always asks to call; never says done. The loop must stop at max_steps.
    router = ScriptRouter({"action": "call", "tool_id": "calendar.list", "arguments": {}})
    hub = Hub({"status": "ok"})
    run = JarvisEngine(router, hub).run(uuid4(), "loop", TOOLS, max_steps=3)
    assert run.stop_reason is StopReason.EXHAUSTED and len(hub.calls) == 3


def test_a_subagent_uses_only_a_subset_of_tools():
    router = ScriptRouter(
        {"action": "delegate", "subgoal": "check calendar", "tools": ["calendar.list"]},
        # the subagent's turns:
        {"action": "call", "tool_id": "calendar.list", "arguments": {}},
        {"action": "done", "output": "clear"},
        # back in the parent:
        {"action": "done", "output": "all set"},
    )
    hub = Hub({"status": "ok", "events": 0})
    run = JarvisEngine(router, hub).run(uuid4(), "plan my day", TOOLS)
    assert run.stop_reason is StopReason.DONE and run.output == "all set"
    assert any(s.action == "delegate" for s in run.steps)


def test_the_engine_can_propose_a_skill_but_not_enable_it():
    engine = JarvisEngine(ScriptRouter(), Hub())
    proposed = engine.propose_skill(_skill())
    assert proposed.kind is CapabilityKind.SKILL  # returned as a manifest for the Gate
    bad = _skill().model_copy(update={"kind": CapabilityKind.AGENT})
    with pytest.raises(ValueError):
        engine.propose_skill(bad)


def test_output_is_always_unverified():
    router = ScriptRouter({"action": "done", "output": "x"})
    run = JarvisEngine(router, Hub()).run(uuid4(), "x", TOOLS)
    assert run.unverified and run.produced_by is Component.HERMES
