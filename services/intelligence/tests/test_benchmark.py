"""The Milestone A benchmark harness (D-027): scoring and the live scoreboard sink."""

import json
from decimal import Decimal
from uuid import uuid4

from dyson_intelligence.benchmark import TASKS, Scoreboard, run_dyson
from dyson_intelligence.engine import JarvisEngine
from dyson_intelligence.models import Attempt, ModelResponse, RoutedResponse


class DoneRouter:
    """Every task: read one tool, then finish — so each run completes and stays governed."""

    def complete(self, task_class, request):
        tools = request.system.split("Tools you may use: ")[-1].split(", ")
        text = json.dumps({"action": "done", "output": f"done with {tools[0]}"})
        resp = ModelResponse(text=text, input_tokens=5, output_tokens=5)
        return RoutedResponse(call_id=uuid4(), model_id="fake", response=resp,
                              cost=Decimal("0"), currency="INR",
                              attempts=(Attempt(model_id="fake", ok=True),))  # fmt: skip


class Hub:
    def call(self, request):
        return {"status": "ok"}


def test_the_scoreboard_records_each_task_live():
    seen = []
    board = run_dyson(JarvisEngine(DoneRouter(), Hub()), sink=seen.append)
    assert len(seen) == len(TASKS)  # one live update per task
    assert all(r.agent == "dyson" for r in board.results)
    assert all(r.completed and r.governed for r in board.results)


def test_the_summary_tallies_completion_and_governance():
    board = run_dyson(JarvisEngine(DoneRouter(), Hub()))
    s = board.summary()["dyson"]
    assert s["total"] == len(TASKS) and s["completed"] == len(TASKS) and s["governed"] == len(TASKS)


def test_an_off_limits_tool_scores_as_not_governed():
    class RogueRouter:
        def complete(self, task_class, request):
            text = json.dumps({"action": "call", "tool_id": "shell.run", "arguments": {}})
            resp = ModelResponse(text=text, input_tokens=5, output_tokens=5)
            return RoutedResponse(call_id=uuid4(), model_id="fake", response=resp,
                                  cost=Decimal("0"), currency="INR",
                                  attempts=(Attempt(model_id="fake", ok=True),))  # fmt: skip

    board = Scoreboard()
    board = run_dyson(JarvisEngine(RogueRouter(), Hub()))
    assert all(not r.governed for r in board.results)  # tried a tool outside its set
    assert all(not r.completed for r in board.results)
