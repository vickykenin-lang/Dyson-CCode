"""Event stores. A transaction holds an exclusive lock, so decisions are made on current state."""

import threading
from collections.abc import Iterator
from contextlib import AbstractContextManager, contextmanager
from importlib.resources import files
from typing import Protocol

import psycopg
from psycopg import sql
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from .events import EVENT_ADAPTER, GovernanceEvent


class Txn(Protocol):
    def read_since(self, seq: int) -> list[tuple[int, GovernanceEvent]]: ...

    def append(self, events: list[GovernanceEvent]) -> int:
        """Append and return the last seq."""
        ...


class EventStore(Protocol):
    def transaction(self) -> AbstractContextManager[Txn]: ...


class InMemoryEventStore:
    """For unit tests. Same semantics as PgEventStore, without durability."""

    def __init__(self) -> None:
        self._events: list[GovernanceEvent] = []
        self._lock = threading.Lock()

    @contextmanager
    def transaction(self) -> Iterator["InMemoryEventStore._Txn"]:
        with self._lock:
            txn = self._Txn(self._events)
            yield txn
            self._events.extend(txn.pending)

    class _Txn:
        def __init__(self, events: list[GovernanceEvent]):
            self._events = events
            self.pending: list[GovernanceEvent] = []

        def read_since(self, seq: int) -> list[tuple[int, GovernanceEvent]]:
            return [(i + 1, e) for i, e in enumerate(self._events) if i + 1 > seq]

        def append(self, events: list[GovernanceEvent]) -> int:
            self.pending.extend(events)
            return len(self._events) + len(self.pending)


class PgEventStore:
    def __init__(self, dsn: str):
        self._conn = psycopg.connect(dsn, autocommit=True, row_factory=dict_row)

    def close(self) -> None:
        self._conn.close()

    @contextmanager
    def transaction(self) -> Iterator["PgEventStore._Txn"]:
        with self._conn.transaction():
            self._conn.execute("SELECT pg_advisory_xact_lock(hashtext('governance.events'))")
            yield self._Txn(self._conn)

    class _Txn:
        def __init__(self, conn: psycopg.Connection):
            self._conn = conn

        def read_since(self, seq: int) -> list[tuple[int, GovernanceEvent]]:
            rows = self._conn.execute(
                "SELECT seq, body FROM governance.events WHERE seq > %s ORDER BY seq", [seq]
            ).fetchall()
            return [(r["seq"], EVENT_ADAPTER.validate_python(r["body"])) for r in rows]

        def append(self, events: list[GovernanceEvent]) -> int:
            last = 0
            for e in events:
                last = self._conn.execute(
                    "INSERT INTO governance.events (event_id, type, at, body)"
                    " VALUES (%s, %s, %s, %s) RETURNING seq",
                    [e.event_id, e.type, e.at, Jsonb(e.model_dump(mode="json"))],
                ).fetchone()["seq"]
            return last


def migrate(dsn: str, app_role: str) -> None:
    """Run as the owner role. The app role may only read and append events."""
    with psycopg.connect(dsn, autocommit=True, row_factory=dict_row) as conn:
        exists = conn.execute("SELECT to_regclass('governance.schema_migrations') AS t").fetchone()
        done = (
            {r["version"] for r in conn.execute("SELECT version FROM governance.schema_migrations")}
            if exists["t"]
            else set()
        )
        mig_dir = files("dyson_governance").joinpath("migrations")
        for path in sorted(
            (p for p in mig_dir.iterdir() if p.name.endswith(".sql")), key=lambda p: p.name
        ):
            if int(path.name.split("_", 1)[0]) not in done:
                with conn.transaction():
                    conn.execute(path.read_text("utf-8"))
        role = sql.Identifier(app_role)
        with conn.transaction():
            conn.execute(sql.SQL("GRANT USAGE ON SCHEMA governance TO {}").format(role))
            conn.execute(sql.SQL("GRANT SELECT, INSERT ON governance.events TO {}").format(role))
            conn.execute(
                sql.SQL("GRANT USAGE ON SEQUENCE governance.events_seq_seq TO {}").format(role)
            )
            conn.execute(sql.SQL("GRANT SELECT ON governance.schema_migrations TO {}").format(role))
