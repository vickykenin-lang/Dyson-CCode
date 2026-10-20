"""The OpenAI shim (D-027): a thin, governed translator to C, no model and no choice of its own."""

from decimal import Decimal
from uuid import uuid4

from fastapi.testclient import TestClient

from dyson_intelligence.models import Attempt, ModelResponse, RoutedResponse
from dyson_intelligence.openai_shim import (
    MODEL_NAME,
    _ChatIn,
    _Msg,
    create_app,
    to_model_request,
)


def _routed(text="hello from C"):
    return RoutedResponse(
        call_id=uuid4(),
        model_id="deepseek.v3.2",
        response=ModelResponse(text=text, input_tokens=12, output_tokens=5),
        cost=Decimal("0"),
        currency="INR",
        attempts=(Attempt(model_id="deepseek.v3.2", ok=True),),
    )


def test_system_messages_fold_into_system_and_turns_keep_order():
    body = _ChatIn(
        messages=[
            _Msg(role="system", content="be brief"),
            _Msg(role="user", content="hi"),
            _Msg(role="assistant", content="hello"),
            _Msg(role="user", content="more"),
        ]
    )
    req = to_model_request(body)
    assert req.system == "be brief"
    assert [m.role for m in req.messages] == ["user", "assistant", "user"]
    assert req.messages[0].content == "hi"


def test_the_shim_forwards_to_c_and_returns_openai_shape():
    seen = {}

    def router_call(task_class, request):
        seen["task_class"] = task_class
        seen["request"] = request
        return _routed()

    client = TestClient(create_app(router_call))
    r = client.post(
        "/v1/chat/completions",
        json={"model": MODEL_NAME, "messages": [{"role": "user", "content": "hi"}]},
    )
    assert r.status_code == 200
    data = r.json()
    assert data["choices"][0]["message"]["content"] == "hello from C"
    assert data["usage"]["total_tokens"] == 17
    assert seen["task_class"] == "hermes.benchmark"  # a fixed class; the caller cannot choose


def test_models_endpoint_advertises_only_the_router():
    client = TestClient(create_app(lambda tc, req: _routed()))
    data = client.get("/v1/models").json()
    assert [m["id"] for m in data["data"]] == [MODEL_NAME]


def test_a_router_refusal_becomes_a_502_not_a_made_up_answer():
    def router_call(task_class, request):
        raise RuntimeError("stopped")

    client = TestClient(create_app(router_call))
    r = client.post(
        "/v1/chat/completions",
        json={"messages": [{"role": "user", "content": "hi"}]},
    )
    assert r.status_code == 502  # the shim never invents a reply when C refuses
