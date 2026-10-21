"""G's adapter to the sealed sandbox: navigate / interact go straight; act carries the approval."""

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from dyson_contracts.common import Component, RiskLevel
from dyson_contracts.toolcalls import ToolCallRequest
from dyson_integration.sandbox_client import SandboxClient, SandboxUnavailable


class Recorder:
    def __init__(self):
        self.calls: list = []

    def __call__(self, path: str, body: dict) -> dict:
        self.calls.append((path, body))
        return {"url": body.get("url", "about:blank"), "title": "ok"}


def test_browse_navigate_posts_the_url():
    rec = Recorder()
    SandboxClient(post=rec).browse({"operation": "navigate", "url": "https://www.youtube.com/"})
    assert rec.calls == [("/navigate", {"url": "https://www.youtube.com/"})]


def test_browse_interact_passes_action_selector_text():
    rec = Recorder()
    SandboxClient(post=rec).browse(
        {"operation": "interact", "action": "type", "selector": "#q", "text": "jazz"}
    )
    path, body = rec.calls[0]
    assert path == "/interact" and body["action"] == "type" and body["text"] == "jazz"


def test_browse_rejects_an_unknown_operation():
    with pytest.raises(ValueError):
        SandboxClient(post=Recorder()).browse({"operation": "download"})


def test_act_forwards_the_approval_id_as_the_proof():
    rec = Recorder()
    approval = uuid4()
    req = ToolCallRequest(
        call_id=uuid4(),
        task_id=uuid4(),
        idempotency_key="k-" + uuid4().hex,
        tool_id="sandbox.act",
        requested_by=Component.HERMES,
        arguments={"action": "submit", "selector": "form#login"},
        risk=RiskLevel.HIGH,
        approval_id=approval,
        requested_at=datetime.now(UTC),
    )
    SandboxClient(post=rec).act(req)
    path, body = rec.calls[0]
    assert path == "/act" and body["approval"] == str(approval)  # the Founder's approval, not blank


def test_unwired_sandbox_fails_loudly_never_silently():
    # No URL and no injected transport: the client refuses rather than pretend it acted.
    client = SandboxClient(url="")
    with pytest.raises(SandboxUnavailable):
        client.browse({"operation": "navigate", "url": "https://www.youtube.com/"})
