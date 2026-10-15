"""Durable record of G's decisions, executions, outcomes and kill switches.

A transaction holds an exclusive lock, so the spend check and the claim of an execution happen
atomically: two concurrent calls cannot both spend the last of a budget or both run once.
"""

import threading
from collections.abc import Iterator
from contextlib import AbstractContextManager, contextmanager
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from importlib.resources import files
from typing import Any, Protocol
from uuid import UUID

import psycopg
from psycopg import sql
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb


@dataclass(frozen=True)
class Execution:
    idempotency_key: str
    call_id: UUID
    receptor_id: str | None
    tool_id: str
    amount: Decimal
    currency: str | None
    claimed_at: datetime


@dataclass(frozen=True)
class Outcome:
    status: str  # executed | failed
    result: Any
    error: str


@dataclass(frozen=True)
class Switch:
    target_kind: str
    target_id: str
    killed: bool
    reason: str
    approval_id: UUID | None
    at: datetime


class Txn(Protocol):
    def record_decision(self, call_id, key, caller, allowed, decision, request, at) -> None: ...
    def execution(self, key: str) -> Execution | None: ...
    def claim(self, e: Execution) -> None: ...
    def month_spend(
        self, receptor_id: str, currency: str, start: datetime, end: datetime
    ) -> Decimal: ...
    def switches(self) -> list[Switch]: ...
    def record_switch(self, s: Switch) -> None: ...


class ToolStore(Protocol):
    def transaction(self) -> AbstractContextManager[Txn]: ...
    def record_outcome(self, key: str, outcome: Outcome, at: datetime) -> None: ...
    def outcome(self, key: str) -> Outcome | None: ...
    def decisions(self) -> list[dict]: ...


class InMemoryToolStore:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._decisions: list[dict] = []
        self._executions: dict[str, Execution] = {}
        self._outcomes: dict[str, Outcome] = {}
        self._switches: list[Switch] = []

    @contextmanager
    def transaction(self) -> Iterator["InMemoryToolStore"]:
        with self._lock:
            yield self

    def record_decision(self, call_id, key, caller, allowed, decision, request, at) -> None:
        self._decisions.append(
            {"call_id": call_id, "idempotency_key": key, "caller": caller, "allowed": allowed,
             "decision": decision, "request": request, "decided_at": at}
        )  # fmt: skip

    def execution(self, key: str) -> Execution | None:
        return self._executions.get(key)

    def claim(self, e: Execution) -> None:
        if e.idempotency_key in self._executions:
            raise KeyError("already claimed")
        self._executions[e.idempotency_key] = e

    def month_spend(
        self, receptor_id: str, currency: str, start: datetime, end: datetime
    ) -> Decimal:
        return sum(
            (
                e.amount
                for e in self._executions.values()
                if e.receptor_id == receptor_id
                and e.currency == currency
                and start <= e.claimed_at < end
                and getattr(self._outcomes.get(e.idempotency_key), "status", None) != "failed"
            ),
            Decimal("0"),
        )

    def switches(self) -> list[Switch]:
        return list(self._switches)

    def record_switch(self, s: Switch) -> None:
        self._switches.append(s)

    def record_outcome(self, key: str, outcome: Outcome, at: datetime) -> None:
        with self._lock:
            if key in self._outcomes:
                raise KeyError("outcome already recorded")
            self._outcomes[key] = outcome

    def outcome(self, key: str) -> Outcome | None:
        return self._outcomes.get(key)

    def decisions(self) -> list[dict]:
        return list(self._decisions)


class PgToolStore:
    def __init__(self, dsn: str):
        self._conn = psycopg.connect(dsn, autocommit=True, row_factory=dict_row)

    def close(self) -> None:
        self._conn.close()

    @contextmanager
    def transaction(self) -> Iterator["PgToolStore._Txn"]:
        with self._conn.transaction():
            self._conn.execute("SELECT pg_advisory_xact_lock(hashtext('toolhub'))")
            yield self._Txn(self._conn)

    class _Txn:
        def __init__(self, conn: psycopg.Connection):
            self._c = conn

        def record_decision(self, call_id, key, caller, allowed, decision, request, at) -> None:
            self._c.execute(
                "INSERT INTO toolhub.decisions (call_id, idempotency_key, caller, allowed,"
                " decision, request, decided_at) VALUES (%s, %s, %s, %s, %s, %s, %s)",
                [call_id, key, caller, allowed, Jsonb(decision), Jsonb(request), at],
            )

        def execution(self, key: str) -> Execution | None:
            r = self._c.execute(
                "SELECT * FROM toolhub.executions WHERE idempotency_key = %s", [key]
            ).fetchone()
            return Execution(**r) if r else None

        def claim(self, e: Execution) -> None:
            self._c.execute(
                "INSERT INTO toolhub.executions (idempotency_key, call_id, receptor_id, tool_id,"
                " amount, currency, claimed_at) VALUES (%s, %s, %s, %s, %s, %s, %s)",
                [e.idempotency_key, e.call_id, e.receptor_id, e.tool_id, e.amount, e.currency,
                 e.claimed_at],
            )  # fmt: skip

        def month_spend(self, receptor_id, currency, start, end) -> Decimal:
            return self._c.execute(
                "SELECT coalesce(sum(e.amount), 0) AS s FROM toolhub.executions e"
                " LEFT JOIN toolhub.outcomes o USING (idempotency_key)"
                " WHERE e.receptor_id = %s AND e.currency = %s AND e.claimed_at >= %s"
                " AND e.claimed_at < %s AND coalesce(o.status, '') <> 'failed'",
                [receptor_id, currency, start, end],
            ).fetchone()["s"]

        def switches(self) -> list[Switch]:
            rows = self._c.execute(
                "SELECT target_kind, target_id, killed, reason, approval_id, at"
                " FROM toolhub.switches ORDER BY seq"
            ).fetchall()
            return [Switch(**r) for r in rows]

        def record_switch(self, s: Switch) -> None:
            self._c.execute(
                "INSERT INTO toolhub.switches (target_kind, target_id, killed, reason,"
                " approval_id, at) VALUES (%s, %s, %s, %s, %s, %s)",
                [s.target_kind, s.target_id, s.killed, s.reason, s.approval_id, s.at],
            )

    def record_outcome(self, key: str, outcome: Outcome, at: datetime) -> None:
        self._conn.execute(
            "INSERT INTO toolhub.outcomes (idempotency_key, status, result, error, finished_at)"
            " VALUES (%s, %s, %s, %s, %s)",
            [key, outcome.status, Jsonb(outcome.result), outcome.error, at],
        )

    def outcome(self, key: str) -> Outcome | None:
        r = self._conn.execute(
            "SELECT status, result, error FROM toolhub.outcomes WHERE idempotency_key = %s", [key]
        ).fetchone()
        return Outcome(**r) if r else None

    def decisions(self) -> list[dict]:
        return self._conn.execute("SELECT * FROM toolhub.decisions ORDER BY seq").fetchall()


def migrate(dsn: str, app_role: str) -> None:
    """Run as the owner role. The app role may only read and insert."""
    with psycopg.connect(dsn, autocommit=True, row_factory=dict_row) as conn:
        exists = conn.execute("SELECT to_regclass('toolhub.schema_migrations') AS t").fetchone()
        done = (
            {r["version"] for r in conn.execute("SELECT version FROM toolhub.schema_migrations")}
            if exists["t"]
            else set()
        )
        mig = files("dyson_toolhub").joinpath("migrations")
        for path in sorted(
            (p for p in mig.iterdir() if p.name.endswith(".sql")), key=lambda p: p.name
        ):
            if int(path.name.split("_", 1)[0]) not in done:
                with conn.transaction():
                    conn.execute(path.read_text("utf-8"))
        role = sql.Identifier(app_role)
        with conn.transaction():
            conn.execute(sql.SQL("GRANT USAGE ON SCHEMA toolhub TO {}").format(role))
            conn.execute(
                sql.SQL("GRANT SELECT, INSERT ON ALL TABLES IN SCHEMA toolhub TO {}").format(role)
            )
            conn.execute(
                sql.SQL("GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA toolhub TO {}").format(role)
            )
            conn.execute(sql.SQL("REVOKE INSERT ON toolhub.schema_migrations FROM {}").format(role))
