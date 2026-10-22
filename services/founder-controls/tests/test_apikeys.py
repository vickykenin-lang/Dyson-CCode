"""The Founder's provider API-keys page: set/replace/remove behind a fresh passkey confirmation,
write-only (the value is never returned or audited)."""

from datetime import timedelta

from controls_testkit import CHANNEL_KEY, DEVICE_KEY, Audit, Clock, FakeGovernance
from fastapi.testclient import TestClient

from dyson_founder_controls.app import (
    create_app,
    purpose_for_delete_key,
    purpose_for_set_key,
)
from dyson_founder_controls.ports import HmacChannelSigner
from dyson_founder_controls.stepup import DeviceKeyStepUp, device_assertion


class _FakeKeys:
    def __init__(self):
        self.data: dict[str, dict[str, str]] = {}

    def names(self, scope):
        return sorted(self.data.get(scope, {}))

    def set(self, scope, name, value):
        self.data.setdefault(scope, {})[name] = value

    def delete(self, scope, name):
        self.data.get(scope, {}).pop(name, None)


def _setup():
    clock, gov, audit, keys = Clock(), FakeGovernance(), Audit(), _FakeKeys()
    stepup = DeviceKeyStepUp(DEVICE_KEY, ttl=timedelta(minutes=2), clock=clock)
    app = create_app(gov, stepup, HmacChannelSigner(CHANNEL_KEY), audit, clock, None, keys)
    return TestClient(app), keys, audit


def _confirmed(http, path, purpose, body):
    c = http.post("/challenges", json={"purpose": purpose}).json()
    a = device_assertion(DEVICE_KEY, c["nonce"], purpose)
    return http.post(path, json={**body, "challenge_id": c["challenge_id"], "assertion": a})


def test_set_key_stores_write_only_and_never_returns_the_value():
    http, keys, audit = _setup()
    r = _confirmed(http, "/apikeys", purpose_for_set_key("apinex"),
                   {"provider": "apinex", "value": "sk-secret-123"})  # fmt: skip
    assert r.status_code == 200 and r.json() == {"provider": "apinex", "set": True}
    assert keys.data["providers"]["apinex_api_key"] == "sk-secret-123"
    # the value is nowhere in the response or the audit trail
    assert "sk-secret-123" not in r.text
    assert all("sk-secret-123" not in str(e) for e in audit)
    assert any(e[0] == "api_key_set" for e in audit)


def test_list_shows_provider_names_only():
    http, keys, _ = _setup()
    _confirmed(http, "/apikeys", purpose_for_set_key("apinex"),
               {"provider": "apinex", "value": "k1"})  # fmt: skip
    _confirmed(http, "/apikeys", purpose_for_set_key("groq"),
               {"provider": "groq", "value": "k2"})  # fmt: skip
    body = http.get("/apikeys").json()
    assert body == {"providers": ["apinex", "groq"]}  # names only, no values
    assert "k1" not in http.get("/apikeys").text


def test_replace_then_remove():
    http, keys, _ = _setup()
    _confirmed(http, "/apikeys", purpose_for_set_key("apinex"),
               {"provider": "apinex", "value": "old"})  # fmt: skip
    _confirmed(http, "/apikeys", purpose_for_set_key("apinex"),
               {"provider": "apinex", "value": "new"})  # fmt: skip
    assert keys.data["providers"]["apinex_api_key"] == "new"
    r = _confirmed(http, "/apikeys/remove", purpose_for_delete_key("apinex"),
                   {"provider": "apinex"})  # fmt: skip
    assert r.status_code == 200 and r.json() == {"provider": "apinex", "set": False}
    assert http.get("/apikeys").json() == {"providers": []}


def test_a_wrong_confirmation_is_refused_and_nothing_is_stored():
    http, keys, _ = _setup()
    c = http.post("/challenges", json={"purpose": purpose_for_set_key("apinex")}).json()
    bad = device_assertion(DEVICE_KEY, c["nonce"], "set-key|someone-else")  # wrong purpose
    body = {"provider": "apinex", "value": "k", "challenge_id": c["challenge_id"], "assertion": bad}
    assert http.post("/apikeys", json=body).status_code == 403
    assert keys.data == {}


def test_a_bad_provider_slug_is_rejected():
    http, keys, _ = _setup()
    c = http.post("/challenges", json={"purpose": "set-key|bad"}).json()
    a = device_assertion(DEVICE_KEY, c["nonce"], "set-key|bad")
    cid = c["challenge_id"]
    body = {"provider": "BAD NAME!", "value": "k", "challenge_id": cid, "assertion": a}
    assert http.post("/apikeys", json=body).status_code == 422  # unsafe slug
    assert keys.data == {}


def test_apikeys_absent_when_no_store_is_wired():
    clock, gov, audit = Clock(), FakeGovernance(), Audit()
    stepup = DeviceKeyStepUp(DEVICE_KEY, ttl=timedelta(minutes=2), clock=clock)
    http = TestClient(create_app(gov, stepup, HmacChannelSigner(CHANNEL_KEY), audit, clock))
    assert http.get("/apikeys").status_code == 404  # no route when keys is None
