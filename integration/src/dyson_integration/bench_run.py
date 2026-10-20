"""Run the Dyson engine side of the Milestone A benchmark on the real model (D-027).

Runs inside the Layer A container. It drives the Jarvis engine against C (the governed Model
Router) on the benchmark task set, with a sandbox Tool Hub that denies every real side effect, and
prints one JSON line per task so the host can stream a live scoreboard. It reaches a model only
through C, exactly like any other caller; it moves no money and changes nothing outside.

    docker exec dyson-layer-a-1 python -m dyson_integration.bench_run
"""

import json
import os
from time import monotonic
from uuid import uuid4

import httpx

from dyson_intelligence.benchmark import TASKS, _score_run
from dyson_intelligence.engine import JarvisEngine
from dyson_intelligence.models import ModelRequest, RoutedResponse

# Route under a class the real model is qualified for; C picks the model and enforces the budget.
TASK_CLASS = os.environ.get("DYSON_BENCH_TASK_CLASS", "conversation.interpret")
EDGE = os.environ.get("DYSON_ROUTER_URL", "http://127.0.0.1:8090/c")


def _token() -> str:
    path = os.environ.get("DYSON_HERMES_SECRETS", "/hermes/secrets.json")
    with open(path, encoding="utf-8") as f:
        return json.load(f)["hermes_router_token"]


class _Router:
    """The engine's RouterClient: complete(task_class, request) over C's edge."""

    def __init__(self, url: str, token: str):
        self._http = httpx.Client(base_url=url.rstrip("/"), timeout=60.0)
        self._token = token

    def complete(self, task_class: str, request: ModelRequest) -> RoutedResponse:
        r = self._http.post(
            "/v1/complete",
            json={"task_class": TASK_CLASS, "request": request.model_dump(mode="json")},
            headers={"Authorization": f"Bearer {self._token}"},
        )
        r.raise_for_status()
        return RoutedResponse.model_validate(r.json())


class _SandboxHub:
    """Every tool call is accepted in form but does nothing real (denied side effects)."""

    def __init__(self) -> None:
        self.calls: list = []

    def call(self, request) -> dict:
        self.calls.append(request.tool_id)
        return {"status": "ok", "note": "sandbox: no real side effect"}


def main() -> None:
    engine = JarvisEngine(_Router(EDGE, _token()), _SandboxHub())
    for task in TASKS:
        start = monotonic()
        try:
            run = engine.run(uuid4(), task.goal, task.tools)
            latency = int((monotonic() - start) * 1000)
            result = _score_run("dyson", task, run, latency)
            row = {
                "agent": "dyson",
                "task": result.task,
                "completed": result.completed,
                "governed": result.governed,
                "steps": result.steps,
                "latency_ms": result.latency_ms,
                "note": result.note,
            }
        except Exception as exc:  # report the failure plainly, never a guess
            row = {"agent": "dyson", "task": task.name, "completed": False, "governed": True,
                   "steps": 0, "latency_ms": int((monotonic() - start) * 1000),
                   "note": f"error: {type(exc).__name__}"}  # fmt: skip
        print("BENCH " + json.dumps(row), flush=True)


if __name__ == "__main__":
    main()
