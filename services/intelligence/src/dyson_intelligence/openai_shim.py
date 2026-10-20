"""An OpenAI-compatible front door to the Model Router (C), for the Hermes benchmark (D-027).

The Nous Hermes Agent speaks the OpenAI chat-completions API. To benchmark it without giving it a
model of its own, this shim accepts that API and forwards every call to C, with the Hermes
credential and a fixed benchmark task class. So Hermes reaches a model only through C (LA-HER-02,
LA-RTR-01): no key of its own, no direct provider, no way to change the model or the budget. It is
a thin translator, nothing more — it holds no model and makes no decision.
"""

from collections.abc import Callable

from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel

from .models import ChatMessage, ModelRequest, RoutedResponse

BENCH_TASK_CLASS = "conversation.interpret"
MODEL_NAME = "dyson-router"  # the only "model" the shim advertises; C picks the real one


class _Msg(BaseModel):
    role: str
    content: str


class _ChatIn(BaseModel):
    model: str = MODEL_NAME
    messages: list[_Msg]
    max_tokens: int = 1024


def to_model_request(body: _ChatIn) -> ModelRequest:
    """OpenAI chat -> C's ModelRequest: system folds into `system`, the rest keep order."""
    system = "\n".join(m.content for m in body.messages if m.role == "system")
    turns = tuple(
        ChatMessage(role=("assistant" if m.role == "assistant" else "user"), content=m.content)
        for m in body.messages
        if m.role in ("user", "assistant") and m.content
    )
    if not turns:
        turns = (ChatMessage(role="user", content=" "),)
    return ModelRequest(system=system, messages=turns, max_output_tokens=max(1, body.max_tokens))


def to_openai_response(routed: RoutedResponse) -> dict:
    r = routed.response
    return {
        "id": f"chatcmpl-{routed.call_id}",
        "object": "chat.completion",
        "model": routed.model_id,
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": r.text},
                "finish_reason": "stop",
            }
        ],
        "usage": {
            "prompt_tokens": r.input_tokens,
            "completion_tokens": r.output_tokens,
            "total_tokens": r.input_tokens + r.output_tokens,
        },
    }


# The shim's one job: hand an OpenAI call to C and hand C's answer back in OpenAI's shape.
RouterCall = Callable[[str, ModelRequest], RoutedResponse]


def create_app(router_call: RouterCall, task_class: str = BENCH_TASK_CLASS) -> FastAPI:
    """router_call forwards to C with the Hermes credential already bound (never chosen here)."""
    app = FastAPI(title="Dyson OpenAI shim (benchmark)", docs_url=None, redoc_url=None)

    @app.get("/v1/models")
    def models() -> dict:
        return {"object": "list", "data": [{"id": MODEL_NAME, "object": "model"}]}

    @app.post("/v1/chat/completions")
    def chat(body: _ChatIn, authorization: str = Header(default="")) -> dict:
        try:
            routed = router_call(task_class, to_model_request(body))
        except Exception as exc:  # C refused, was stopped, or is unreachable: report, do not guess
            raise HTTPException(status_code=502, detail=f"router: {type(exc).__name__}") from exc
        return to_openai_response(routed)

    return app
