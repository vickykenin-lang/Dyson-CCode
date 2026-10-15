"""Shared helpers for the Step 9 integration tests."""

from datetime import UTC, datetime, timedelta

ADMIN = "postgresql://postgres@127.0.0.1:5433/postgres"
NOW = datetime(2026, 10, 15, 12, 0, tzinfo=UTC)
CANARY = "sk-canary-" + "7" * 32  # looks like a real API secret; must never leak


class Clock:
    def __init__(self):
        self.now = NOW

    def __call__(self):
        return self.now

    def advance(self, **kw):
        self.now += timedelta(**kw)


def say(gateway, founder, text, thread=None, **extra):
    from uuid import uuid4

    body = {"thread_id": str(thread or uuid4()), "text": text, **extra}
    r = gateway.post("/messages", json=body, headers=founder)
    assert r.status_code == 200, r.text
    return r.json()


def task_of(out):
    from uuid import UUID

    assert out["acknowledgment"] is not None, out
    return UUID(out["acknowledgment"]["task_id"])


def status(gateway, founder, task_id):
    return gateway.get(f"/tasks/{task_id}", headers=founder).json()
