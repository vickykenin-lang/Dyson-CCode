"""A spoken/typed command -> a governed sandbox navigate, watched on the panel."""

from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import uuid4

import pytest

from dyson_contracts.interface import FounderMessage, Language, Modality
from dyson_gateway.ports import ReplyKind
from dyson_integration.relay import RelaySessions
from dyson_integration.sandbox_command import SandboxOperator, parse_open_command


@pytest.mark.parametrize(
    "text,expected",
    [
        ("YouTube kholo", "https://www.youtube.com/"),
        ("open facebook please", "https://www.facebook.com/"),
        ("dikhao gmail", "https://mail.google.com/"),
        ("open example.com", "https://example.com"),
        ("go to https://news.ycombinator.com/", "https://news.ycombinator.com/"),
    ],
)
def test_parse_recognises_open_commands(text, expected):
    assert parse_open_command(text) == expected


@pytest.mark.parametrize(
    "text",
    [
        "what do you think about youtube as a business?",  # mentions a site, no open-verb
        "remind me to call Sam",
        "how is T0 doing today?",
    ],
)
def test_parse_leaves_ordinary_chat_alone(text):
    assert parse_open_command(text) is None


@dataclass
class _Run:
    status: str
    result: dict | None = None
    error: str = ""
    denied_checks: tuple = ()


def _msg(text: str) -> FounderMessage:
    return FounderMessage(
        message_id=uuid4(),
        thread_id=uuid4(),
        text=text,
        language=Language.HINGLISH,
        modality=Modality.TEXT,
        sent_at=datetime.now(UTC),
    )


def _op(run: _Run, relay: RelaySessions) -> SandboxOperator:
    calls = []

    def call(req):
        calls.append(req)
        return run

    op = SandboxOperator(call, relay, lambda: datetime.now(UTC))
    op.calls = calls  # type: ignore[attr-defined]
    return op


def test_an_open_command_navigates_and_opens_a_live_panel():
    relay = RelaySessions()
    op = _op(_Run("executed", {"url": "https://www.youtube.com/", "title": "YouTube"}), relay)
    reply = op.try_handle(_msg("YouTube kholo"))
    assert reply is not None and reply.kind is ReplyKind.ACCEPTED
    assert "youtube.com" in reply.text
    req = op.calls[0]  # type: ignore[attr-defined]
    assert req.tool_id == "sandbox.browse"
    assert req.arguments == {"operation": "navigate", "url": "https://www.youtube.com/"}
    assert len(relay.live()) == 1  # the panel is now live for the Founder to watch


def test_ordinary_chat_is_not_handled_here():
    op = _op(_Run("executed"), RelaySessions())
    assert op.try_handle(_msg("how is T0 today?")) is None  # falls through to B


def test_a_denied_tool_is_reported_and_leaves_no_live_panel():
    # The sandbox is not admitted yet: G denies, so the reply is honest and the session is ended.
    relay = RelaySessions()
    op = _op(_Run("denied", denied_checks=("registry",)), relay)
    reply = op.try_handle(_msg("open youtube"))
    assert reply.kind is ReplyKind.UNAVAILABLE and "registry" in reply.text
    assert relay.live() == []  # nothing to watch
