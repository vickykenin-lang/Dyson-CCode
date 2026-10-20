"""The live route health probe (D-027 follow-up): catch a model that is dead at runtime."""

from decimal import Decimal
from itertools import count
from uuid import uuid4

from dyson_intelligence.models import Attempt, ModelResponse, RoutedResponse
from dyson_intelligence.routecheck import probe_route


def _routed(text="ok"):
    return RoutedResponse(
        call_id=uuid4(),
        model_id="amazon.nova-micro-v1:0",
        response=ModelResponse(text=text, input_tokens=8, output_tokens=1),
        cost=Decimal("0"),
        currency="INR",
        attempts=(Attempt(model_id="amazon.nova-micro-v1:0", ok=True),),
    )


def test_a_healthy_route_passes():
    ticks = count(0, 0.2)  # 200ms per reading
    health = probe_route(lambda tc, req: _routed(), "conversation.interpret",
                         monotonic=lambda: next(ticks))  # fmt: skip
    assert health.ok and health.model_id == "amazon.nova-micro-v1:0"
    assert health.latency_ms == 200


def test_a_timing_out_route_fails_not_guesses():
    def router_call(tc, req):
        raise TimeoutError("read timed out")

    health = probe_route(router_call, "conversation.interpret")
    assert not health.ok and "TimeoutError" in health.detail


def test_an_empty_answer_fails():
    health = probe_route(lambda tc, req: _routed(""), "conversation.interpret")
    assert not health.ok and health.detail == "empty answer"


def test_a_too_slow_route_fails_even_with_an_answer():
    ticks = count(0, 10)  # 10s per reading, well over the budget
    health = probe_route(lambda tc, req: _routed(), "conversation.interpret",
                         budget_ms=8000, monotonic=lambda: next(ticks))  # fmt: skip
    assert not health.ok and "too slow" in health.detail
