"""The sandbox control server: safe browsing runs; sensitive acts need approval; STOP holds."""

import pytest
from dyson_sandbox.app import create_app
from dyson_sandbox.net import UnsafeUrl, safe_public_url
from fastapi.testclient import TestClient


class FakeDriver:
    """Records calls and returns a plain on-screen state, like the real Playwright driver."""

    def __init__(self) -> None:
        self.calls: list = []
        self._url = "about:blank"

    async def navigate(self, url: str) -> dict:
        self.calls.append(("navigate", url))
        self._url = url
        return await self.state()

    async def interact(self, action, selector, text) -> dict:
        self.calls.append(("interact", action, selector, text))
        return await self.state()

    async def state(self) -> dict:
        return {"url": self._url, "title": "Fake"}

    async def close(self) -> None:
        self.calls.append(("close",))


def _client(**kw):
    return TestClient(create_app(FakeDriver(), **kw))


# --- URL guard (sealed open-web, never inward) -------------------------------------------

def test_public_https_is_allowed():
    assert safe_public_url("https://www.youtube.com/") == "https://www.youtube.com/"


@pytest.mark.parametrize(
    "url",
    [
        "file:///etc/passwd",  # not a web page
        "http://169.254.169.254/latest/meta-data/",  # cloud metadata — the dangerous one
        "http://127.0.0.1:8080/",  # loopback
        "http://10.0.0.5/",  # private
        "http://[::1]/",  # IPv6 loopback
    ],
)
def test_inward_or_non_web_urls_are_refused(url):
    with pytest.raises(UnsafeUrl):
        safe_public_url(url)


# --- control server ----------------------------------------------------------------------

def test_navigate_opens_a_public_site():
    c = _client()
    r = c.post("/navigate", json={"url": "https://www.youtube.com/"})
    assert r.status_code == 200 and r.json()["url"] == "https://www.youtube.com/"


def test_navigate_to_metadata_is_refused():
    r = _client().post("/navigate", json={"url": "http://169.254.169.254/"})
    assert r.status_code == 422  # the app guards even before the network firewall


def test_safe_interaction_runs_on_its_own():
    r = _client().post("/interact", json={"action": "click", "selector": "#play"})
    assert r.status_code == 200


def test_a_non_safe_action_is_refused_on_the_safe_endpoint():
    r = _client().post("/interact", json={"action": "submit", "selector": "form"})
    assert r.status_code == 403  # must go through /act with an approval


def test_a_sensitive_act_needs_an_approval_proof():
    c = _client()
    assert c.post("/act", json={"action": "submit", "selector": "form"}).status_code == 403
    ok = c.post("/act", json={"action": "submit", "selector": "form", "approval": "founder-ok"})
    assert ok.status_code == 200  # with a proof, it runs


def test_a_custom_verifier_can_reject_a_forged_proof():
    c = TestClient(create_app(FakeDriver(), verify_approval=lambda p: p == "real"))
    assert c.post("/act", json={"action": "submit", "approval": "forged"}).status_code == 403
    assert c.post("/act", json={"action": "submit", "approval": "real"}).status_code == 200


def test_stop_is_a_kill_switch_until_resumed():
    c = _client()
    assert c.post("/stop").json()["stopped"] is True
    assert c.post("/navigate", json={"url": "https://www.youtube.com/"}).status_code == 409
    assert c.post("/act", json={"action": "submit", "approval": "x"}).status_code == 409
    assert c.get("/state").json()["stopped"] is True  # state still readable while stopped
    assert c.post("/resume").json()["stopped"] is False
    assert c.post("/navigate", json={"url": "https://www.youtube.com/"}).status_code == 200
