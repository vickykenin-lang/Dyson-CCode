"""Founder-facing messages between App, Entry Gateway and the Conversation Engine (B)."""

from enum import StrEnum
from typing import Literal
from uuid import UUID

from pydantic import model_validator

from .common import Contract, NonEmptyStr, Timestamp
from .tasks import TaskState


class Modality(StrEnum):
    TEXT = "text"
    VOICE = "voice"


class Language(StrEnum):
    HINDI = "hi"
    ENGLISH = "en"
    HINGLISH = "hinglish"
    UNKNOWN = "unknown"


class FounderMessage(Contract):
    message_id: UUID
    thread_id: UUID
    modality: Modality
    text: NonEmptyStr  # typed text, or the transcript of speech
    language: Language = Language.UNKNOWN
    # Uncertain speech is flagged, never acted on silently (LA-APP-07).
    transcription_uncertain: bool = False
    sent_at: Timestamp

    @model_validator(mode="after")
    def _checks(self) -> "FounderMessage":
        if self.modality is Modality.TEXT and self.transcription_uncertain:
            raise ValueError("typed text has no transcription")
        return self


class CommandAcknowledgment(Contract):
    """The immediate honest acknowledgment. It can never say completed (LA-APP-04)."""

    task_id: UUID
    state: Literal[TaskState.ACCEPTED, TaskState.APPROVAL_NEEDED]
    at: Timestamp


class TaskStatusUpdate(Contract):
    task_id: UUID
    state: TaskState
    message: str = ""
    verified_evidence_ids: tuple[UUID, ...] = ()
    at: Timestamp

    @model_validator(mode="after")
    def _checks(self) -> "TaskStatusUpdate":
        if self.state is TaskState.COMPLETED_VERIFIED and not self.verified_evidence_ids:
            raise ValueError("completed-verified must cite verified evidence")
        return self
