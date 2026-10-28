"""The Jev decision adapter: maps a message to /v1/decisions and back to a Triage signal."""

from dyson_integration.jev_model import JevTriage


class _FakeResp:
    def __init__(self, data: dict):
        self._data = data

    def raise_for_status(self) -> None:
        pass

    def json(self) -> dict:
        return self._data


class _FakeClient:
    def __init__(self, data: dict):
        self.data = data
        self.sent: dict = {}

    def post(self, url, json, headers, timeout):  # noqa: A002 - matches httpx.post
        self.sent = {"url": url, "json": json, "headers": headers, "timeout": timeout}
        return _FakeResp(self.data)


class _BadClient:
    def post(self, *a, **k):
        raise RuntimeError("the decision model is unreachable")


_ANSWERS = {
    "answers": {
        "assessment": {"type": "noul", "noul": 0.49},
        "is_safe": {"type": "noul", "noul": 0.92},
        "category": {"type": "choice", "choice": "coding", "probabilities": {"coding": 0.96}},
        "complexity": {"type": "score", "probabilities": {"0": 0.1, "2": 0.0, "4": 0.9}},
    }
}


def test_parses_the_decision_into_a_triage_signal():
    fake = _FakeClient(_ANSWERS)
    j = JevTriage("https://api.apinex.bond/v1", "sk-test", client=fake)
    t = j.triage("ek deploy script likho")
    assert t is not None
    assert t.category == "coding"
    assert t.complexity == "expert"  # argmax of the complexity probabilities is "4"
    assert t.is_safe == 0.92 and t.assessment == 0.49
    # endpoint, payload and auth
    assert fake.sent["url"] == "https://api.apinex.bond/v1/decisions"
    assert fake.sent["json"] == {"model": "free/jev-1.13", "input": "ek deploy script likho"}
    assert fake.sent["headers"]["Authorization"] == "Bearer sk-test"


def test_missing_fields_fall_back_to_safe_defaults():
    fake = _FakeClient({"answers": {}})
    t = JevTriage("https://x/v1", "k", client=fake).triage("hi")
    assert t is not None
    assert t.category == "general" and t.complexity == "moderate"
    assert t.is_safe == 1.0 and t.assessment == 0.0  # absent safety is treated as safe


def test_no_key_returns_none():
    # until a key is saved on DFC the triage is simply absent; B interprets without a hint.
    j = JevTriage("https://x/v1", lambda: "", client=_FakeClient(_ANSWERS))
    assert j.triage("hi") is None


def test_any_error_returns_none():
    assert JevTriage("https://x/v1", "k", client=_BadClient()).triage("hi") is None


def test_callable_key_is_read_at_call_time():
    box = {"k": ""}
    fake = _FakeClient(_ANSWERS)
    j = JevTriage("https://x/v1", lambda: box["k"], client=fake)
    assert j.triage("hi") is None  # no key yet
    box["k"] = "sk-live"
    assert j.triage("hi") is not None
    assert fake.sent["headers"]["Authorization"] == "Bearer sk-live"
