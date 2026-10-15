"""HTTP API of the Memory & Evidence Layer.

Read and record only: no endpoint grants, approves or checks permission (LA-MEM-08).
The caller's scope arrives in X-Dyson-Scope. Until Step 9 binds scope to an authenticated
service identity, this API must only be reachable from inside Layer A.
"""

from collections.abc import Callable, Iterator
from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID

import psycopg
from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse

from dyson_contracts.audit import AuditEvent
from dyson_contracts.evidence import EvidenceRecord

from .models import (
    ArchivedMessage,
    MemoryItem,
    MessageHit,
    RegisterView,
    Scope,
    StageStatus,
    Thread,
)
from .secrets import SecretLeak
from .store import MemoryStore

StoreFactory = Callable[[str], Iterator[MemoryStore]]


def create_app(store_factory: StoreFactory) -> FastAPI:
    app = FastAPI(title="Dyson Memory & Evidence Layer (I)")

    def get_store(scope: Annotated[Scope, Header(alias="X-Dyson-Scope")]) -> Iterator[MemoryStore]:
        yield from store_factory(scope)

    StoreDep = Annotated[MemoryStore, Depends(get_store)]

    @app.exception_handler(SecretLeak)
    async def _leak(_: Request, exc: SecretLeak):
        return JSONResponse(status_code=422, content={"detail": str(exc)})

    @app.exception_handler(psycopg.errors.InsufficientPrivilege)
    async def _denied(_: Request, exc: Exception):
        return JSONResponse(status_code=403, content={"detail": "not permitted in this scope"})

    @app.exception_handler(psycopg.errors.IntegrityError)
    async def _integrity(_: Request, exc: Exception):
        return JSONResponse(status_code=409, content={"detail": type(exc).__name__})

    @app.post("/threads", status_code=201)
    def create_thread(thread: Thread, store: StoreDep) -> None:
        store.create_thread(thread)

    @app.post("/messages", status_code=201)
    def append_message(message: ArchivedMessage, store: StoreDep) -> None:
        store.append_message(message)

    @app.get("/threads/{thread_id}/messages")
    def thread_messages(thread_id: UUID, store: StoreDep) -> list[ArchivedMessage]:
        return store.thread_messages(thread_id)

    @app.get("/search/messages")
    def search_messages(q: str, store: StoreDep, limit: int = 20) -> list[MessageHit]:
        return store.search_messages(q, limit)

    @app.post("/memory", status_code=201)
    def remember(item: MemoryItem, store: StoreDep) -> MemoryItem:
        return store.remember(item)

    @app.get("/memory/recall")
    def recall(q: str, store: StoreDep, limit: int = 10) -> list[MemoryItem]:
        return store.recall(q, limit)

    @app.get("/register/{rule_id}")
    def register(rule_id: str, store: StoreDep) -> RegisterView:
        view = store.register_view(rule_id)
        if view is None:
            raise HTTPException(404, f"no register entry for {rule_id}")
        return view

    @app.post("/evidence", status_code=201)
    def record_evidence(record: EvidenceRecord, store: StoreDep) -> None:
        store.record_evidence(record, None if store.scope == "core" else store.scope)

    @app.get("/evidence/status")
    def evidence_status(
        capability: str, provider: str, environment: str, store: StoreDep
    ) -> dict[int, StageStatus]:
        status = store.capability_status(capability, provider, environment, datetime.now(UTC))
        return {int(k): v for k, v in status.items()}

    @app.post("/audit", status_code=201)
    def audit(event: AuditEvent, store: StoreDep) -> None:
        store.audit(event)

    @app.get("/audit/verify")
    def audit_verify(store: StoreDep) -> dict:
        bad = store.verify_audit_chain()
        return {"intact": bad is None, "first_broken_seq": bad}

    return app
