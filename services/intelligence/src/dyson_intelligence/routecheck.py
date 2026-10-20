"""A live route health probe (D-027 follow-up): prove the configured model actually answers.

The Milestone A benchmark caught a model that was qualified on paper but never functional at
runtime (the first model on C's route read-timed out on every real call). Recorded qualification
is not proof the live route works. This probe closes that gap: it sends one tiny request through C,
exactly like any other caller, and checks a real answer comes back inside a latency budget. Run it
after a deploy or a model switch; a route that fails the probe is dead to callers, whatever the
scoreboard said.

It reaches a model only through C, moves no money, and changes nothing. It never guesses: a refusal,
a timeout, or an empty answer is reported as a failure, not smoothed over.
"""

import time
from collections.abc import Callable

from dyson_contracts.common import Contract

from .models import ChatMessage, ModelRequest, RoutedResponse

RouterCall = Callable[[str, ModelRequest], RoutedResponse]

PROBE_PROMPT = "Reply with the single word: ok"
DEFAULT_BUDGET_MS = 8000  # a healthy route answers a trivial prompt well inside this


class RouteHealth(Contract):
    ok: bool
    task_class: str
    model_id: str | None = None
    latency_ms: int
    detail: str


def probe_route(
    router_call: RouterCall,
    task_class: str,
    budget_ms: int = DEFAULT_BUDGET_MS,
    monotonic: Callable[[], float] = time.monotonic,
) -> RouteHealth:
    """Send one trivial request through C and report whether the live route answers in budget."""
    request = ModelRequest(
        system="You are a health probe. Answer in one short word.",
        messages=(ChatMessage(role="user", content=PROBE_PROMPT),),
        max_output_tokens=16,
    )
    start = monotonic()
    try:
        routed = router_call(task_class, request)
    except Exception as exc:  # a refusal, STOP, timeout, or unreachable C: the route is not healthy
        latency_ms = int((monotonic() - start) * 1000)
        return RouteHealth(
            ok=False, task_class=task_class, latency_ms=latency_ms,
            detail=f"router error: {type(exc).__name__}",
        )  # fmt: skip
    latency_ms = int((monotonic() - start) * 1000)
    answer = (routed.response.text or "").strip()
    if not answer:
        return RouteHealth(
            ok=False, task_class=task_class, model_id=routed.model_id, latency_ms=latency_ms,
            detail="empty answer",
        )  # fmt: skip
    if latency_ms > budget_ms:
        return RouteHealth(
            ok=False, task_class=task_class, model_id=routed.model_id, latency_ms=latency_ms,
            detail=f"too slow: {latency_ms}ms over {budget_ms}ms budget",
        )  # fmt: skip
    return RouteHealth(
        ok=True, task_class=task_class, model_id=routed.model_id, latency_ms=latency_ms,
        detail="healthy",
    )  # fmt: skip
