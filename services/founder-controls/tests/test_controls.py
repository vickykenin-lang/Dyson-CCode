"""Direct Founder Controls."""

import ast
import sys
from pathlib import Path

import pytest
from controls_testkit import DEVICE_KEY
from httpx import HTTPStatusError

from dyson_contracts.common import Component
from dyson_contracts.control import ControlScope
from dyson_founder_controls.app import purpose_for_control, purpose_for_decision
from dyson_founder_controls.client import ControlsClient, main
from dyson_founder_controls.stepup import device_assertion

SRC = Path(__file__).resolve().parents[1] / "src" / "dyson_founder_controls"


def test_stop_and_pause_work_with_app_gateway_and_models_down(founder, gov):
    # LA-DFC-04, LA-DFC-01: this test builds nothing but DFC and a fake A.
    state = founder.control("stop", reason="emergency")
    assert state["mode"] == "stopped" and state["scope"] == "master"
    state = founder.control("pause", receptor_id="R11")
    assert state["mode"] == "paused" and state["receptor_id"] == "R11"
    assert [c.issued_by for c in gov.commands] == [Component.FOUNDER, Component.FOUNDER]


def test_the_cli_stops_everything(http, gov, tmp_path):  # LA-DFC-04
    key = tmp_path / "device.key"
    key.write_bytes(DEVICE_KEY)
    assert main(["--key-file", str(key), "stop"], http=http) == 0
    assert gov.modes[(ControlScope.MASTER, None)].value == "stopped"


def test_controls_reach_only_the_governance_core():  # LA-DFC-02, LA-DFC-01
    # webauthn only verifies passkey signatures locally; it reaches nothing (gate 3, D-014).
    allowed = {"dyson_contracts", "fastapi", "httpx", "pydantic", "webauthn"}
    for path in SRC.rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.Import):
                mods = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.level == 0:
                mods = [node.module]
            else:
                continue
            for m in mods:
                top = m.split(".")[0]
                assert top in allowed or top in sys.stdlib_module_names, f"{path.name}: {m}"
    import inspect

    from dyson_founder_controls import app

    params = inspect.signature(app.create_app).parameters
    assert list(params) == ["governance", "stepup", "signer", "audit", "clock", "passkeys"]


def test_every_action_needs_its_own_fresh_confirmation(http, gov, clock):  # LA-DFC-03, LA-SEC-03
    def control_with(purpose_used, assertion=None, challenge_id=None):
        c = http.post("/challenges", json={"purpose": purpose_used}).json()
        body = {
            "command": "stop",
            "scope": "master",
            "challenge_id": challenge_id or c["challenge_id"],
            "assertion": assertion or device_assertion(DEVICE_KEY, c["nonce"], purpose_used),
        }
        return http.post("/control", json=body), c

    stop = purpose_for_control("stop", "master", None)
    r, _ = control_with(purpose_for_control("pause", "master", None))  # confirmed a pause
    assert r.status_code == 403
    r, _ = control_with(stop, assertion="0" * 64)  # wrong key
    assert r.status_code == 403
    r, used = control_with(stop)
    assert r.status_code == 200
    r, _ = control_with(
        stop,
        challenge_id=used["challenge_id"],
        assertion=device_assertion(DEVICE_KEY, used["nonce"], stop),
    )  # replay
    assert r.status_code == 403
    c = http.post("/challenges", json={"purpose": stop}).json()
    clock.advance(minutes=3)  # expired
    body = {
        "command": "stop",
        "scope": "master",
        "challenge_id": c["challenge_id"],
        "assertion": device_assertion(DEVICE_KEY, c["nonce"], stop),
    }
    assert http.post("/control", json=body).status_code == 403
    gateway_style = http.post(
        "/control",
        json={"command": "stop", "scope": "master"},
        headers={"Authorization": "Bearer session-token"},
    )
    assert gateway_style.status_code == 422
    assert len(gov.commands) == 1


def test_another_device_cannot_confirm(http, gov):  # LA-DFC-03
    stranger = ControlsClient(http, b"x" * 32)
    with pytest.raises(HTTPStatusError):
        stranger.control("stop")
    with pytest.raises(HTTPStatusError):
        stranger.pending()
    assert gov.commands == []


def test_approval_binds_to_the_exact_action_shown(founder, http, gov, audit, clock):  # LA-DFC-05
    shown = gov.add()
    out = founder.decide(shown.approval_id, shown.action_digest, "approve")
    assert out["status"] == "approved"
    (d,) = gov.decisions
    assert d.action_digest == shown.action_digest and d.decided_by is Component.FOUNDER
    assert d.channel is Component.DIRECT_FOUNDER_CONTROLS and d.decided_at == clock()
    assert d.auth_method == "dev-device-key"
    event, detail = audit[-1]
    assert event == "decision" and detail["decided_by"] == "founder" and detail["decided_at"]


def test_a_changed_action_cannot_be_approved(founder, http, gov):  # LA-DFC-05
    shown = gov.add(digest="a" * 64)
    with pytest.raises(HTTPStatusError) as e:
        founder.decide(shown.approval_id, "f" * 64, "approve")  # not what A holds now
    assert e.value.response.status_code == 403
    purpose = purpose_for_decision(shown.approval_id, shown.action_digest, "approve")
    c = http.post("/challenges", json={"purpose": purpose}).json()
    body = {
        "approval_id": str(shown.approval_id),
        "action_digest": shown.action_digest,
        "decision": "reject",
        "challenge_id": c["challenge_id"],
        "assertion": device_assertion(DEVICE_KEY, c["nonce"], purpose),
    }
    assert http.post("/decisions", json=body).status_code == 403  # confirmed approve, sent reject
    assert gov.decisions == []


def test_reject_is_recorded_too(founder, gov):  # LA-DFC-05
    shown = gov.add()
    assert founder.decide(shown.approval_id, shown.action_digest, "reject")["status"] == "rejected"
    assert gov.decisions[0].decision.value == "reject"


def test_resume_is_requested_then_approved_never_commanded(founder, http, gov):  # LA-DFC-01
    founder.control("stop")
    c = http.post("/challenges", json={"purpose": "control|resume|master|-"}).json()
    body = {
        "command": "resume",
        "scope": "master",
        "challenge_id": c["challenge_id"],
        "assertion": device_assertion(DEVICE_KEY, c["nonce"], "control|resume|master|-"),
    }
    assert http.post("/control", json=body).status_code == 422
    request = founder.resume_request()
    assert request["action_summary"] == "Resume master"
    founder.decide(request["approval_id"], request["action_digest"], "approve")
    assert str(gov.decisions[-1].approval_id) == request["approval_id"]
