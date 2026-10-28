"""The self-test control server: /run runs the checks; /stop is the kill-switch."""

from dyson_selftest.app import create_app
from fastapi.testclient import TestClient


def _client(result=None):
    return TestClient(create_app(run=lambda: result or {"ok": True, "checks": []}))


def test_run_returns_the_result():
    c = _client({"ok": False, "checks": [{"name": "pytest", "ok": False}]})
    r = c.post("/run")
    assert r.status_code == 200
    assert r.json()["ok"] is False


def test_stop_blocks_run_until_resume():
    c = _client()
    assert c.post("/stop").json()["stopped"] is True
    assert c.post("/run").status_code == 409  # stopped: refuses to run
    assert c.post("/resume").json()["stopped"] is False
    assert c.post("/run").status_code == 200


def test_health_reports_state():
    c = _client()
    h = c.get("/health").json()
    assert h["ok"] is True and h["stopped"] is False and h["running"] is False
