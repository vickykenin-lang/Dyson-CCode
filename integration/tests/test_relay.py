"""The view-only screen relay and the sandbox panel: the Founder watches, never drives."""

from uuid import uuid4

from fastapi.testclient import TestClient

from dyson_contracts.screen import RelayState
from dyson_integration.relay import SANDBOX_CAPABILITY, RelaySessions
from dyson_integration.relay_app import create_relay_app


def test_a_session_opens_live_and_view_only():
    s = RelaySessions().open(uuid4())
    assert s.state is RelayState.LIVE and s.view_only is True
    assert s.capability_id == SANDBOX_CAPABILITY


def test_ending_a_session_takes_it_out_of_live():
    r = RelaySessions()
    s = r.open(uuid4())
    assert r.live() == [s]
    ended = r.end(s.session_id)
    assert ended.state is RelayState.ENDED and r.live() == []


def test_stop_ends_every_live_session():
    r = RelaySessions()
    r.open(uuid4())
    r.open(uuid4())
    assert r.end_all() == 2 and r.live() == []


def test_panel_descriptor_tracks_the_live_session():
    r = RelaySessions()
    c = TestClient(create_relay_app(r, novnc_url="/sandbox-vnc/", controls_url="/dfc"))
    assert c.get("/sandbox").json()["active"] is False
    s = r.open(uuid4())
    body = c.get("/sandbox").json()
    assert body["active"] and body["view_only"] and body["session_id"] == str(s.session_id)


def test_the_panel_page_is_view_only_with_a_stop_and_no_action_path():
    r = RelaySessions()
    r.open(uuid4())
    app = create_relay_app(r, novnc_url="/sandbox-vnc/vnc.html?view_only=1", controls_url="/dfc")
    # read-only: every route is GET/HEAD only (LA-DASH-02)
    for route in app.routes:
        assert getattr(route, "methods", {"GET"}) <= {"GET", "HEAD"}
    html = TestClient(app).get("/panel").text
    assert "view-only" in html and 'href="/dfc"' in html  # watch + STOP to Direct Founder Controls
    assert "/sandbox-vnc/vnc.html?view_only=1" in html  # embeds the live stream when one is up


def test_the_panel_is_idle_when_nothing_is_live():
    html = TestClient(create_relay_app(RelaySessions(), novnc_url="/x")).get("/panel").text
    assert "idle" in html.lower() and "<iframe" not in html
