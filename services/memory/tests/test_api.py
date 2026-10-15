"""The HTTP API records and reads; it has no path that grants anything."""

from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from memory_testkit import CANARY, NOW

from dyson_memory.api import create_app
from dyson_memory.db import connect
from dyson_memory.store import MemoryStore


@pytest.fixture
def client(db, guard):
    def factory(scope):
        conn = connect(db["app"])
        try:
            yield MemoryStore(conn, scope, guard)
        finally:
            conn.close()

    return TestClient(create_app(factory))


CORE = {"X-Dyson-Scope": "core"}


def test_thread_round_trip(client):
    tid = str(uuid4())
    assert (
        client.post(
            "/threads", json={"thread_id": tid, "created_at": NOW.isoformat()}, headers=CORE
        ).status_code
        == 201
    )
    msg = {
        "message_id": str(uuid4()),
        "thread_id": tid,
        "participant": "founder",
        "modality": "voice",
        "body": "status of T0?",
        "language": "en",
        "sent_at": NOW.isoformat(),
    }
    assert client.post("/messages", json=msg, headers=CORE).status_code == 201
    got = client.get(f"/threads/{tid}/messages", headers=CORE).json()
    assert [m["body"] for m in got] == ["status of T0?"]


def test_scope_header_is_required_and_validated(client):
    assert client.get("/audit/verify").status_code == 422
    assert client.get("/audit/verify", headers={"X-Dyson-Scope": "admin"}).status_code == 422


def test_secret_leak_is_refused(client):
    tid = str(uuid4())
    client.post("/threads", json={"thread_id": tid, "created_at": NOW.isoformat()}, headers=CORE)
    msg = {
        "message_id": str(uuid4()),
        "thread_id": tid,
        "participant": "founder",
        "modality": "text",
        "body": f"key {CANARY}",
        "sent_at": NOW.isoformat(),
    }
    assert client.post("/messages", json=msg, headers=CORE).status_code == 422


def test_receptor_cannot_write_audit(client):
    event = {
        "event_id": str(uuid4()),
        "kind": "config_change",
        "actor": "A",
        "at": NOW.isoformat(),
        "summary": "x",
    }
    assert client.post("/audit", json=event, headers={"X-Dyson-Scope": "T0"}).status_code == 403
    assert client.post("/audit", json=event, headers=CORE).status_code == 201
    assert client.get("/audit/verify", headers=CORE).json() == {
        "intact": True,
        "first_broken_seq": None,
    }


def test_unknown_rule_is_404(client):
    assert client.get("/register/D-500", headers=CORE).status_code == 404


def test_no_endpoint_grants_or_approves(client):
    paths = {r.path for r in client.app.routes}
    assert not any(word in p for p in paths for word in ("approve", "grant", "permit", "allow"))
