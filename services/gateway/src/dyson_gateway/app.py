"""HTTP API of the Entry Gateway.

- POST /session logs the Founder in and returns a session token (LA-GW-01).
- Every other endpoint needs that token, and every request is rate limited (LA-GW-02, LA-GW-03).
- POST /messages hands the Founder's message to B and answers at once with an honest
  acknowledgment: accepted or approval-needed, never completed (LA-APP-04, LA-PERF-01).
- GET /tasks/{id}/events streams the task's state until it settles (LA-G-09).
- GET /dashboard is the Founder's read-only dashboard data (gate 8): J's verified figures and the
  system's state. Nothing on it can act.
- GET /notices lists what waits on the Founder: open approvals and reminders. Read only.
- GET /threads lists conversations; POST /threads/{id}/archive and /restore move one in or out
  of the archive. There is no delete: nothing the Founder said is ever removed (D-023).
- POST /statements hands a bank statement the Founder uploads to H (LA-VLT-01). H keeps only
  the parsed fields, never the file (D-017).
- There is no approve, reject, STOP, PAUSE or RESUME endpoint, and no route to Hermes.
"""

import asyncio
import base64
import binascii
import json
from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta
from typing import Annotated
from uuid import UUID, uuid4

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import Field

from dyson_contracts.common import Contract, NonEmptyStr
from dyson_contracts.interface import (
    CommandAcknowledgment,
    FounderMessage,
    Language,
    Modality,
    TaskStatusUpdate,
)
from dyson_contracts.tasks import TaskState

from .auth import FounderAuthenticator, SessionStore
from .ports import (
    AuditPort,
    ConversationPort,
    ConversationReply,
    DashboardPort,
    Notice,
    NoticesPort,
    StatementsPort,
    StatusPort,
    ThreadMessage,
    ThreadsPort,
    ThreadSummary,
)
from .ratelimit import Limits, LoginGuard, TokenBucket

SETTLED = frozenset(
    {TaskState.COMPLETED_VERIFIED, TaskState.FAILED, TaskState.REJECTED, TaskState.CLOSED}
)


class LoginIn(Contract):
    username: NonEmptyStr
    secret: NonEmptyStr


class LoginOut(Contract):
    token: str


class MessageIn(Contract):
    thread_id: UUID
    # Set by the client once per message. A network retry resends the same id, so the same
    # command can never start two tasks (LA-REL-02). Added in Step 9.
    client_message_id: UUID | None = None
    text: NonEmptyStr = Field(max_length=8000)
    modality: Modality = Modality.TEXT
    language: Language = Language.UNKNOWN
    transcription_uncertain: bool = False


MAX_STATEMENT_BYTES = 2_000_000


class StatementIn(Contract):
    filename: NonEmptyStr = Field(max_length=200)
    period_start: date
    period_end: date
    content_base64: NonEmptyStr = Field(max_length=MAX_STATEMENT_BYTES * 4 // 3 + 4)


class StatementOut(Contract):
    lines_kept: int


class MessageOut(Contract):
    """The reply to a message. `acknowledgment` is set only when a task was created, and its
    contract allows only accepted or approval-needed."""

    message_id: UUID
    reply: ConversationReply
    acknowledgment: CommandAcknowledgment | None = None


def create_app(
    authenticator: FounderAuthenticator,
    sessions: SessionStore,
    limits: Limits,
    conversation: ConversationPort,
    status: StatusPort,
    audit: AuditPort,
    clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    poll_seconds: float = 1.0,
    stream_seconds: float = 300.0,
    notices: NoticesPort | None = None,
    statements: StatementsPort | None = None,
    threads: ThreadsPort | None = None,
    dashboard: DashboardPort | None = None,
) -> FastAPI:
    app = FastAPI(title="Dyson Entry Gateway")
    bucket = TokenBucket(limits.requests_per_minute, limits.burst, clock)
    guard = LoginGuard(limits.login_failures_before_lockout, limits.lockout, clock)

    @app.middleware("http")
    async def rate_limit(request: Request, call_next):
        client = request.client.host if request.client else "unknown"
        if not bucket.allow(f"addr:{client}"):
            audit.record("rate_limited", {"client": client, "path": request.url.path})
            return JSONResponse(status_code=429, content={"detail": "too many requests"})
        return await call_next(request)

    def founder(request: Request, authorization: Annotated[str, Header()] = "") -> str:
        scheme, _, token = authorization.partition(" ")
        if scheme.lower() != "bearer" or sessions.check(token) is None:
            raise HTTPException(401, "log in first")
        if not bucket.allow(f"session:{token}"):
            raise HTTPException(429, "too many requests")
        return token

    Founder = Annotated[str, Depends(founder)]

    @app.post("/session")
    def login(body: LoginIn, request: Request) -> LoginOut:
        client = request.client.host if request.client else "unknown"
        if guard.locked(client):
            audit.record("login_locked_out", {"client": client})
            raise HTTPException(429, "too many failed logins; try later")
        if not authenticator.authenticate(body.username, body.secret):
            guard.failed(client)
            audit.record("login_failed", {"client": client})
            raise HTTPException(401, "login failed")
        guard.succeeded(client)
        audit.record("login", {"client": client})
        return LoginOut(token=sessions.issue())

    @app.delete("/session", status_code=204)
    def logout(token: Founder) -> None:
        sessions.end(token)

    @app.post("/messages")
    def message(body: MessageIn, _: Founder) -> MessageOut:
        msg = FounderMessage(
            message_id=body.client_message_id or uuid4(),
            thread_id=body.thread_id,
            modality=body.modality,
            text=body.text,
            language=body.language,
            transcription_uncertain=body.transcription_uncertain,
            sent_at=clock(),
        )
        reply = conversation.handle(msg)
        ack = None
        if reply.task_id is not None and reply.task_state in (
            TaskState.ACCEPTED,
            TaskState.APPROVAL_NEEDED,
        ):
            ack = CommandAcknowledgment(task_id=reply.task_id, state=reply.task_state, at=clock())
        return MessageOut(message_id=msg.message_id, reply=reply, acknowledgment=ack)

    @app.get("/threads")
    def thread_list(_: Founder, archived: bool = False) -> list[ThreadSummary]:
        return threads.summaries(archived) if threads is not None else []

    @app.post("/threads/{thread_id}/archive", status_code=204)
    def archive(thread_id: UUID, _: Founder) -> None:
        if threads is None:
            raise HTTPException(503, "the archive is not connected")
        threads.set_archived(thread_id, True)
        audit.record("thread_archived", {"thread_id": thread_id})

    @app.post("/threads/{thread_id}/restore", status_code=204)
    def restore(thread_id: UUID, _: Founder) -> None:
        if threads is None:
            raise HTTPException(503, "the archive is not connected")
        threads.set_archived(thread_id, False)
        audit.record("thread_restored", {"thread_id": thread_id})

    @app.get("/threads/{thread_id}")
    def thread(thread_id: UUID, _: Founder, limit: int = 100) -> list[ThreadMessage]:
        return status.thread(thread_id, min(max(limit, 1), 500))

    @app.get("/threads/{thread_id}/tasks")
    def thread_tasks(thread_id: UUID, _: Founder) -> list[TaskStatusUpdate]:
        return status.tasks(thread_id)

    @app.get("/tasks/{task_id}")
    def task(task_id: UUID, _: Founder) -> TaskStatusUpdate:
        update = status.task(task_id)
        if update is None:
            raise HTTPException(404, "unknown task")
        return update

    @app.get("/dashboard")
    def founder_dashboard(_: Founder) -> dict:
        if dashboard is None:
            raise HTTPException(503, "the dashboard is not connected")
        return dashboard.snapshot()

    @app.get("/notices")
    def founder_notices(_: Founder) -> list[Notice]:
        return notices.notices() if notices is not None else []

    @app.post("/statements")
    def statement(body: StatementIn, _: Founder) -> StatementOut:
        if statements is None:
            raise HTTPException(503, "statement upload is not connected")
        try:
            content = base64.b64decode(body.content_base64, validate=True)
        except (binascii.Error, ValueError):
            raise HTTPException(422, "the file is not valid base64") from None
        if len(content) > MAX_STATEMENT_BYTES:
            raise HTTPException(413, "statement file is too large")
        try:
            kept = statements.upload(body.filename, body.period_start, body.period_end, content)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from None
        audit.record("statement_uploaded", {"lines": kept, "period_start": body.period_start,
                                            "period_end": body.period_end})  # fmt: skip
        return StatementOut(lines_kept=kept)

    @app.get("/tasks/{task_id}/events")
    async def events(task_id: UUID, _: Founder) -> StreamingResponse:
        if status.task(task_id) is None:
            raise HTTPException(404, "unknown task")

        async def stream():
            last, deadline = None, clock() + timedelta(seconds=stream_seconds)
            while True:
                update = status.task(task_id)
                if update is not None and update != last:
                    last = update
                    yield f"data: {json.dumps(update.model_dump(mode='json'))}\n\n"
                    if update.state in SETTLED:
                        return
                if clock() >= deadline:
                    return
                await asyncio.sleep(poll_seconds)

        return StreamingResponse(stream(), media_type="text/event-stream")

    return app
