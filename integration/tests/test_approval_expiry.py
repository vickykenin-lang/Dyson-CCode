"""D-014: an unanswered approval expires after 24 hours and must be asked again; while it waits
the Founder is reminded every hour."""

from datetime import timedelta

import pytest

from dyson_contracts.common import Component


def _reminders(layer, text):
    return [m for m in layer.inbox.messages if m[1] == "approval" and text in m[2]]


def test_approvals_expire_after_24_hours_with_hourly_reminders(layer, clock):
    request = layer.core.propose_amendment(
        "AMD-7", "- 3 retries\n+ 2 retries", "Retries past 2 never succeed", Component.CORE_RD
    )
    assert request.expires_at - request.created_at == timedelta(hours=24)
    device = layer.founder_device()

    layer.tick()
    assert _reminders(layer, "Reminder") == []  # nothing yet: under an hour
    clock.advance(hours=1)
    layer.tick()
    layer.tick()  # once per interval, not once per tick
    assert len(_reminders(layer, "Reminder")) == 1
    clock.advance(hours=1)
    layer.tick()
    assert len(_reminders(layer, "Reminder")) == 2

    clock.advance(hours=22, seconds=1)  # past 24 hours, unanswered
    layer.tick()
    layer.tick()
    assert len(_reminders(layer, "Expired unanswered, ask again")) == 1
    assert str(request.approval_id) not in {p["approval_id"] for p in device.pending()}
    with pytest.raises(Exception):  # noqa: B017 - the channel refuses; the exact error is DFC's
        device.decide(request.approval_id, request.action_digest, "approve")
    assert layer.core.approval_status(request.approval_id).value == "open"


def test_an_approval_answered_in_time_is_not_reminded_again(layer, clock):
    request = layer.core.propose_amendment("AMD-5", "wording", "clarity", Component.CORE_RD)
    clock.advance(hours=3)
    layer.approve(request)
    before = len(_reminders(layer, ""))
    clock.advance(hours=30)
    layer.tick()
    assert len(_reminders(layer, "")) == before
