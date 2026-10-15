from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from gateway_testkit import PASSWORD, Audit, Clock, FakeBackend

from dyson_gateway.app import create_app
from dyson_gateway.auth import PasswordAuthenticator, SessionStore
from dyson_gateway.ratelimit import Limits


@pytest.fixture
def clock():
    return Clock()


@pytest.fixture
def backend():
    return FakeBackend()


@pytest.fixture
def audit():
    return Audit()


@pytest.fixture
def limits():
    return Limits(requests_per_minute=600, burst=50, login_failures_before_lockout=3,
                  lockout=timedelta(minutes=15))  # fmt: skip


@pytest.fixture
def make(clock, backend, audit):
    def _make(limits):
        sessions = SessionStore(clock, max_age=timedelta(hours=12), idle_timeout=timedelta(hours=1))
        app = create_app(PasswordAuthenticator.create("founder", PASSWORD), sessions, limits,
                         backend, backend, audit, clock=clock, poll_seconds=0.01)  # fmt: skip
        return TestClient(app)

    return _make


@pytest.fixture
def client(make, limits):
    return make(limits)


@pytest.fixture
def auth(client):
    token = client.post("/session", json={"username": "founder", "secret": PASSWORD}).json()
    return {"Authorization": f"Bearer {token['token']}"}
