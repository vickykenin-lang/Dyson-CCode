from datetime import timedelta

import pytest
from app_testkit import LIFETIME, PASSWORD, Audit, Backend, ScriptedVoice, clock
from fastapi.testclient import TestClient

from dyson_founder_app.app import create_app
from dyson_founder_app.gateway_client import GatewayClient
from dyson_founder_app.voice import NoVoice
from dyson_gateway.app import create_app as create_gateway
from dyson_gateway.auth import PasswordAuthenticator, SessionStore
from dyson_gateway.ratelimit import Limits


@pytest.fixture
def backend():
    return Backend()


@pytest.fixture
def gateway(backend):
    limits = Limits(requests_per_minute=6000, burst=500, login_failures_before_lockout=5,
                    lockout=timedelta(minutes=15))  # fmt: skip
    sessions = SessionStore(clock, max_age=LIFETIME, idle_timeout=LIFETIME)
    app = create_gateway(PasswordAuthenticator.create("founder", PASSWORD), sessions, limits,
                         backend, backend, Audit(), clock=clock)  # fmt: skip
    return GatewayClient(TestClient(app))


@pytest.fixture
def voice():
    return ScriptedVoice()


@pytest.fixture
def make(gateway):
    def _make(voice=None, speech=None):
        return TestClient(create_app(gateway, voice or NoVoice(), speech=speech,
                                     secure_cookies=False), follow_redirects=True)  # fmt: skip

    return _make


@pytest.fixture
def app(make, voice):
    return make(voice)


@pytest.fixture
def founder(app):
    r = app.post("/login", data={"username": "founder", "password": PASSWORD})
    assert r.status_code == 200 and "Conversation" in r.text
    app.get("/")  # sets the thread cookie
    return app
