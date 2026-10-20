"""The browser capability and the screen relay (phase 6, D-026)."""

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from pydantic import ValidationError

from dyson_contracts.capability import CapabilityKind, IsolationTier
from dyson_contracts.common import RiskLevel
from dyson_contracts.screen import RelayState, ScreenRelaySession
from dyson_intelligence.browser import ALLOWED_HOSTS, BROWSER

NOW = datetime(2026, 10, 20, 9, 0, tzinfo=UTC)


def test_the_browser_runs_in_a_container_holds_no_secrets_and_is_high_risk():
    assert BROWSER.kind is CapabilityKind.TOOL
    assert BROWSER.isolation is IsolationTier.CONTAINER  # not in-process
    assert BROWSER.requests.secrets == ()  # no logins held
    assert BROWSER.risk is RiskLevel.HIGH and BROWSER.needs_founder_admission


def test_reading_is_allowed_but_acting_out_needs_approval():
    snapshot = next(op for op in BROWSER.operations if op.name == "snapshot")
    submit = next(op for op in BROWSER.operations if op.name == "submit")
    assert snapshot.read_only and not snapshot.requires_approval
    assert submit.destructive and submit.requires_approval


def test_the_browser_names_its_allowlisted_hosts():
    assert set(BROWSER.requests.egress_hosts) == set(ALLOWED_HOSTS)
    assert all(op.open_world for op in BROWSER.operations)  # everything it does reaches the web


def test_a_screen_relay_is_always_view_only():
    session = ScreenRelaySession(
        session_id=uuid4(),
        capability_id="dyson.tool.browser",
        task_id=uuid4(),
        started_at=NOW,
    )
    assert session.view_only and session.state is RelayState.LIVE
    with pytest.raises(ValidationError):
        ScreenRelaySession(
            session_id=uuid4(),
            capability_id="dyson.tool.browser",
            task_id=uuid4(),
            view_only=False,  # refused: the Founder watches, never drives
            started_at=NOW,
        )
