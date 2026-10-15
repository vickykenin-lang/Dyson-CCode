import os
from pathlib import Path
from uuid import uuid4

import psycopg
import pytest
from fastapi.testclient import TestClient
from integration_testkit import ADMIN, CANARY, Clock

from dyson_integration import db
from dyson_integration.system import LayerA, Settings, write_secret_file
from dyson_integration.t0 import TestReceptorT0

ROOT = Path(__file__).resolve().parents[2]
ADMIN_DSN = os.environ.get("DYSON_TEST_PG_ADMIN", ADMIN)


@pytest.fixture(scope="session")
def pg_admin():
    try:
        psycopg.connect(ADMIN_DSN, autocommit=True).close()
    except psycopg.OperationalError as exc:
        if os.environ.get("DYSON_TEST_REQUIRE_DB") == "1":
            raise
        pytest.skip(f"no test database: {exc}")
    return ADMIN_DSN


@pytest.fixture
def dsns(pg_admin):
    name = f"dyson_layer_a_{uuid4().hex[:8]}"
    out = db.prepare(pg_admin, name, password="local-" + uuid4().hex)
    yield out
    db.drop(pg_admin, name)


@pytest.fixture
def clock():
    return Clock()


@pytest.fixture
def settings(tmp_path):
    return Settings(
        policy_dir=ROOT / "policy",
        secret_file=write_secret_file(tmp_path / "secrets.json", canary=CANARY),
    )


@pytest.fixture
def t0(clock):
    return TestReceptorT0(clock)


@pytest.fixture
def make(dsns, settings, clock):
    """Build Layer A on the same database; calling it again is a restart of the central server."""
    built = []

    def _make(t0):
        layer = LayerA.build(dsns, settings, t0, clock)
        built.append(layer)
        return layer

    return _make


@pytest.fixture
def layer(make, t0):
    a = make(t0)
    a.bootstrap()
    return a


@pytest.fixture
def gateway(layer):
    return TestClient(layer.gateway)


@pytest.fixture
def founder(gateway, settings):
    r = gateway.post(
        "/session",
        json={"username": settings.founder_username, "secret": settings.founder_password},
    )
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}
