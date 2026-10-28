"""G's self-test client: one authorized tool call turns into one /run on the sealed sandbox."""

import pytest

from dyson_integration.selftest_client import SelftestClient, SelftestUnavailable


def test_run_forwards_to_the_sandbox_and_returns_the_result():
    seen = {}

    def post(path, body):
        seen["path"], seen["body"] = path, body
        return {"ok": True, "checks": [{"name": "pytest", "ok": True, "summary": "508 passed"}]}

    out = SelftestClient(post=post).run({})
    assert out["ok"] is True
    assert seen["path"] == "/run"


def test_unwired_raises(monkeypatch):
    monkeypatch.delenv("DYSON_SELFTEST_URL", raising=False)
    with pytest.raises(SelftestUnavailable):
        SelftestClient().run({})
