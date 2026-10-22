"""The OpenAI-compatible adapter: maps a ModelRequest to /v1/chat/completions and back."""

import pytest

from dyson_integration.openai_compat_model import OpenAICompatModel
from dyson_intelligence.models import ChatMessage, ModelRequest


class _FakeResp:
    def __init__(self, data: dict):
        self._data = data

    def raise_for_status(self) -> None:
        pass

    def json(self) -> dict:
        return self._data


class _FakeClient:
    """Captures the one POST and returns a canned OpenAI-shaped reply."""

    def __init__(self, data: dict):
        self.data = data
        self.sent: dict = {}

    def post(self, url, json, headers, timeout):  # noqa: A002 - matches httpx.post
        self.sent = {"url": url, "json": json, "headers": headers, "timeout": timeout}
        return _FakeResp(self.data)


def _reply(text: str, pin: int = 11, pout: int = 7) -> dict:
    return {
        "choices": [{"message": {"role": "assistant", "content": text}}],
        "usage": {"prompt_tokens": pin, "completion_tokens": pout},
    }


def _req(text: str, system: str = "", schema=None) -> ModelRequest:
    return ModelRequest(
        system=system,
        messages=(ChatMessage(role="user", content=text),),
        max_output_tokens=256,
        response_schema=schema,
    )


def test_completes_and_reports_tokens():
    fake = _FakeClient(_reply("Namaste, kaise ho?"))
    m = OpenAICompatModel("https://api.example.com/v1", "sk-test", client=fake)
    out = m.complete(_req("hi", system="You are Dyson."), "free/deepseek-v4.1-flash")
    assert out.text == "Namaste, kaise ho?"
    assert out.input_tokens == 11 and out.output_tokens == 7
    # the endpoint, model id and payload shape
    assert fake.sent["url"] == "https://api.example.com/v1/chat/completions"
    assert fake.sent["json"]["model"] == "free/deepseek-v4.1-flash"
    assert fake.sent["json"]["max_tokens"] == 256
    assert fake.sent["headers"]["Authorization"] == "Bearer sk-test"
    # system goes first, then the user turn
    assert fake.sent["json"]["messages"][0] == {"role": "system", "content": "You are Dyson."}
    assert fake.sent["json"]["messages"][1] == {"role": "user", "content": "hi"}


def test_no_system_message_when_empty():
    fake = _FakeClient(_reply("ok"))
    m = OpenAICompatModel("https://api.example.com/v1", "k", client=fake)
    m.complete(_req("hi"), "m")
    assert fake.sent["json"]["messages"] == [{"role": "user", "content": "hi"}]


def test_json_schema_request_extracts_one_object():
    # the model wraps the JSON in prose; the adapter returns just the object, and asks for JSON.
    fake = _FakeClient(_reply('Sure!\n{"kind": "answer", "text": "hi"}\nHope that helps.'))
    m = OpenAICompatModel("https://api.example.com/v1", "k", client=fake)
    out = m.complete(_req("hi", schema={"type": "object"}), "m")
    assert out.text == '{"kind": "answer", "text": "hi"}'
    assert "JSON schema" in fake.sent["json"]["messages"][0]["content"]


def test_missing_usage_defaults_to_zero():
    fake = _FakeClient({"choices": [{"message": {"content": "ok"}}]})
    m = OpenAICompatModel("https://api.example.com/v1", "k", client=fake)
    out = m.complete(_req("hi"), "m")
    assert out.text == "ok" and out.input_tokens == 0 and out.output_tokens == 0


def test_null_content_is_empty_string():
    fake = _FakeClient({"choices": [{"message": {"content": None}}], "usage": {}})
    m = OpenAICompatModel("https://api.example.com/v1", "k", client=fake)
    assert m.complete(_req("hi"), "m").text == ""


def test_callable_key_is_read_at_call_time():
    # the key is resolved on each call, so a key saved later (e.g. on DFC) is picked up with no
    # restart; until one exists the call fails and the router can fall back.
    box = {"k": ""}
    fake = _FakeClient(_reply("ok"))
    m = OpenAICompatModel("https://api.example.com/v1", lambda: box["k"], client=fake)
    with pytest.raises(RuntimeError):
        m.complete(_req("hi"), "m")  # no key yet
    box["k"] = "sk-live"
    m.complete(_req("hi"), "m")
    assert fake.sent["headers"]["Authorization"] == "Bearer sk-live"
