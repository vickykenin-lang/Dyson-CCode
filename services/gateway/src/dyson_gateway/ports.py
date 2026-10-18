"""What the Gateway reaches. Step 9 connects these to B, D and I."""

from datetime import date, datetime
from enum import StrEnum
from typing import Protocol
from uuid import UUID

from dyson_contracts.common import Contract, NonEmptyStr
from dyson_contracts.interface import FounderMessage, Language, TaskStatusUpdate
from dyson_contracts.tasks import TaskState


class ReplyKind(StrEnum):
    CLARIFY = "clarify"
    ACCEPTED = "accepted"
    ANSWER = "answer"
    PROPOSAL = "proposal"
    UNAVAILABLE = "unavailable"


class ConversationReply(Contract):
    """B's reply, as the Gateway receives it."""

    kind: ReplyKind
    text: NonEmptyStr
    language: Language
    task_id: UUID | None = None
    task_state: TaskState | None = None
    proposal_id: UUID | None = None


class ThreadMessage(Contract):
    role: str  # user | assistant
    content: NonEmptyStr
    modality: str = "text"


class ConversationPort(Protocol):
    """B. The only component the Founder talks to (LA-GW-03, LA-HER-04)."""

    def handle(self, message: FounderMessage) -> ConversationReply: ...


class StatusPort(Protocol):
    """Read-only task state and thread history, so a reconnecting app loses nothing (LA-APP-05)."""

    def task(self, task_id: UUID) -> TaskStatusUpdate | None: ...

    def tasks(self, thread_id: UUID) -> list[TaskStatusUpdate]: ...

    def thread(self, thread_id: UUID, limit: int) -> list[ThreadMessage]: ...


class AuditPort(Protocol):
    def record(self, event: str, detail: dict) -> None: ...


class Notice(Contract):
    """Something waiting on the Founder: an open approval, a reminder or an escalation."""

    at: datetime
    kind: str  # approval | reminder
    text: NonEmptyStr


class NoticesPort(Protocol):
    def notices(self) -> list[Notice]: ...


class StatementsPort(Protocol):
    """H's statement intake. Returns the lines kept; raises ValueError for a bad statement."""

    def upload(
        self, filename: str, period_start: date, period_end: date, content: bytes
    ) -> int: ...
