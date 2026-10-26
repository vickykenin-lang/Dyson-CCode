"""An OpenAI-compatible chat model behind C: one adapter for any provider that speaks the
OpenAI /v1/chat/completions API (apinex, Groq, Gemini's OpenAI endpoint, and others).

It is called only by C's router, like the Bedrock adapter. The base URL and key are given at
construction from the secret store or the environment, never hard-coded, so one class serves many
providers by instantiating it once per provider. A request that asks for JSON gets the schema in
the system prompt, and the first JSON object in the reply is returned, so C and B never see code
fences or reasoning text.
"""

import json
from collections.abc import Callable
from typing import Any

from dyson_intelligence.models import ModelRequest, ModelResponse

from .bedrock_model import first_json_object

TIMEOUT_S = 60.0


class OpenAICompatModel:
    def __init__(
        self,
        base_url: str,
        api_key: str | Callable[[], str | None],
        *,
        extra_body: dict | None = None,
        client: Any = None,
        timeout: float = TIMEOUT_S,
    ):
        # base_url like "https://api.apinex.bond/v1"; the endpoint is <base_url>/chat/completions.
        # api_key may be a string, or a callable read at call time (so a key the Founder saves on
        # Direct Founder Controls is picked up without a restart). extra_body holds provider
        # knobs merged into every request (e.g. Gemini's reasoning_effort="none" to skip slow
        # thinking); it must not set model/messages.
        self._url = base_url.rstrip("/") + "/chat/completions"
        self._key = api_key
        self._extra = extra_body or {}
        self._client = client  # an httpx.Client for tests; a one-shot request otherwise
        self._timeout = timeout

    def _resolve_key(self) -> str:
        key = self._key() if callable(self._key) else self._key
        if not key:
            raise RuntimeError("no API key is configured for this provider")
        return key

    def _post(self, payload: dict) -> dict:
        import httpx  # lazy: only needed when a real call is made

        headers = {
            "Authorization": f"Bearer {self._resolve_key()}",
            "Content-Type": "application/json",
        }
        caller = self._client or httpx
        resp = caller.post(self._url, json=payload, headers=headers, timeout=self._timeout)
        resp.raise_for_status()
        return resp.json()

    def complete(self, request: ModelRequest, model_id: str) -> ModelResponse:
        system = request.system
        if request.response_schema is not None:
            system += (
                "\n\nReply with exactly one JSON object and nothing else. It must match this "
                "JSON schema:\n" + json.dumps(request.response_schema, ensure_ascii=False)
            )
        messages: list[dict] = []
        if system:
            messages.append({"role": "system", "content": system})
        messages += [{"role": m.role, "content": m.content} for m in request.messages]
        payload = {
            "model": model_id,
            "messages": messages,
            "max_tokens": request.max_output_tokens,
            "temperature": 0,
        }
        payload.update(self._extra)  # provider knobs (e.g. reasoning_effort); never model/messages
        out = self._post(payload)
        text = out["choices"][0]["message"].get("content") or ""
        if request.response_schema is not None:
            text = first_json_object(text)
        usage = out.get("usage") or {}
        return ModelResponse(
            text=text,
            input_tokens=int(usage.get("prompt_tokens", 0)),
            output_tokens=int(usage.get("completion_tokens", 0)),
        )
