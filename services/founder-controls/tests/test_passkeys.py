"""Gate 3 (D-014): passkeys on the Founder's phone confirm every action on this channel."""

from datetime import timedelta

import pytest
from controls_testkit import CHANNEL_KEY, DEVICE_KEY, Audit, Clock, FakeGovernance
from fastapi.testclient import TestClient
from soft_authenticator import SoftAuthenticator

from dyson_founder_controls.app import create_app, purpose_for_control, purpose_for_decision
from dyson_founder_controls.passkey import PasskeyStepUp, PasskeyStore
from dyson_founder_controls.ports import HmacChannelSigner
from dyson_founder_controls.stepup import DeviceKeyStepUp, device_assertion

RP, ORIGIN = "control.example.test", "https://control.example.test"


@pytest.fixture
def setup(tmp_path):
    clock, gov, audit = Clock(), FakeGovernance(), Audit()

    def build():
        ttl = timedelta(minutes=2)
        passkeys = PasskeyStepUp(
            PasskeyStore(tmp_path / "passkeys.json"),
            DeviceKeyStepUp(DEVICE_KEY, ttl, clock),
            DEVICE_KEY, RP, ORIGIN, ttl, clock,
        )  # fmt: skip
        app = create_app(gov, passkeys, HmacChannelSigner(CHANNEL_KEY), audit, clock, passkeys)
        return TestClient(app)

    return build, gov, audit


def enroll(http, phone, label="Founder phone", **auth):
    r = http.post("/passkeys/registration-options", json={"label": label, **auth})
    assert r.status_code == 201, r.text
    body = r.json()
    r = http.post("/passkeys/register",
                  json={"registration_id": body["registration_id"],
                        "credential": phone.create(body["options"])})  # fmt: skip
    assert r.status_code == 201, r.text
    return r.json()


def confirm(http, phone, purpose, **kw):
    c = http.post("/passkeys/challenges", json={"purpose": purpose}).json()
    return {"challenge_id": c["challenge_id"], "assertion": phone.get(c["options"], **kw)}


def stop(http, confirmation):
    return http.post("/control", json={"command": "stop", "scope": "master", **confirmation})


def test_page_is_served_and_nothing_is_enrolled_at_first(setup):
    http = setup[0]()
    assert "Register your passkey" in http.get("/").text
    assert http.get("/passkeys").json() == {"enrolled": 0}
    assert http.post("/passkeys/challenges", json={"purpose": "list-approvals"}).status_code == 403


def test_first_passkey_needs_the_device_key(setup):
    build, _, audit = setup
    http, phone = build(), SoftAuthenticator(RP, ORIGIN)
    bad = http.post("/passkeys/registration-options", json={"label": "x", "device_key": "nope"})
    assert bad.status_code == 403 and audit[-1][0] == "passkey_refused"
    assert enroll(http, phone, device_key=DEVICE_KEY.decode()) == {
        "label": "Founder phone", "enrolled": 1}  # fmt: skip


def test_passkey_confirms_stop_and_decisions(setup):
    build, gov, _ = setup
    http, phone = build(), SoftAuthenticator(RP, ORIGIN)
    enroll(http, phone, device_key=DEVICE_KEY.decode())
    r = stop(http, confirm(http, phone, purpose_for_control("stop", "master", None)))
    assert r.status_code == 200 and r.json()["mode"] == "stopped"
    a = gov.add()
    c = confirm(http, phone, purpose_for_decision(a.approval_id, a.action_digest, "approve"))
    r = http.post(
        "/decisions",
        json={
            "approval_id": str(a.approval_id),
            "action_digest": a.action_digest,
            "decision": "approve",
            **c,
        },
    )
    assert r.status_code == 200 and r.json()["status"] == "approved"
    assert gov.decisions[-1].auth_method == "passkey"


def test_device_key_stops_working_once_a_passkey_exists(setup):
    build, gov, _ = setup
    http = build()
    enroll(http, SoftAuthenticator(RP, ORIGIN), device_key=DEVICE_KEY.decode())
    purpose = purpose_for_control("stop", "master", None)
    c = http.post("/challenges", json={"purpose": purpose}).json()
    r = stop(http, {"challenge_id": c["challenge_id"],
                    "assertion": device_assertion(DEVICE_KEY, c["nonce"], purpose)})  # fmt: skip
    assert r.status_code == 403
    assert gov.commands == []


def test_an_assertion_is_bound_to_one_action_and_used_once(setup):
    build, gov, _ = setup
    http, phone = build(), SoftAuthenticator(RP, ORIGIN)
    enroll(http, phone, device_key=DEVICE_KEY.decode())
    for_pause = confirm(http, phone, purpose_for_control("pause", "master", None))
    assert stop(http, for_pause).status_code == 403  # made for PAUSE, used for STOP
    ok = confirm(http, phone, purpose_for_control("stop", "master", None))
    assert stop(http, ok).status_code == 200
    assert stop(http, ok).status_code == 403  # replay
    assert len(gov.commands) == 1


def test_no_user_verification_or_wrong_site_is_refused(setup):
    build, gov, _ = setup
    http, phone = build(), SoftAuthenticator(RP, ORIGIN)
    enroll(http, phone, device_key=DEVICE_KEY.decode())
    purpose = purpose_for_control("stop", "master", None)
    assert stop(http, confirm(http, phone, purpose, user_verified=False)).status_code == 403
    phished = confirm(http, phone, purpose, origin="https://control.evil.test")
    assert stop(http, phished).status_code == 403
    assert stop(http, confirm(http, phone, purpose, rp_id="evil.test")).status_code == 403
    other = SoftAuthenticator(RP, ORIGIN)  # a passkey that was never enrolled
    assert stop(http, confirm(http, other, purpose)).status_code == 403
    assert gov.commands == []


def test_backup_passkey_needs_an_enrolled_one_and_both_work(setup):
    build, _, _ = setup
    http, phone, backup = build(), SoftAuthenticator(RP, ORIGIN), SoftAuthenticator(RP, ORIGIN)
    enroll(http, phone, device_key=DEVICE_KEY.decode())
    refused = http.post("/passkeys/registration-options",
                        json={"label": "Backup", "device_key": DEVICE_KEY.decode()})  # fmt: skip
    assert refused.status_code == 403
    assert enroll(http, backup, "Backup", **confirm(http, phone, "add-passkey|Backup")) == {
        "label": "Backup", "enrolled": 2}  # fmt: skip
    purpose = purpose_for_control("stop", "master", None)
    assert stop(http, confirm(http, backup, purpose)).status_code == 200


def test_passkeys_survive_a_restart(setup):
    build, _, _ = setup
    phone = SoftAuthenticator(RP, ORIGIN)
    enroll(build(), phone, device_key=DEVICE_KEY.decode())
    http = build()  # a new process on the same data volume
    assert http.get("/passkeys").json() == {"enrolled": 1}
    assert stop(http, confirm(http, phone, purpose_for_control("stop", "master", None))).is_success
