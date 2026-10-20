"""Records owned by the Memory & Evidence Layer.

These are Step 2's own shapes. The ones other components will send or read over the wire are
listed in services/memory/NOTES.md as contract additions to make before Step 9.
"""

from datetime import date
from enum import StrEnum
from typing import Annotated
from uuid import UUID

from pydantic import Field, model_validator

from dyson_contracts.common import Contract, NonEmptyStr, ReceptorId, Sha256Hex, Timestamp
from dyson_contracts.evidence import EvidenceRecord
from dyson_contracts.interface import Language, Modality

Scope = Annotated[str, Field(pattern=r"^(core|T0|R[1-9][0-9]*)$")]


class Citation(Contract):
    """Points at the underlying record a memory or answer came from (LA-MEM-02, LA-MEM-09)."""

    kind: NonEmptyStr  # message, evidence, register, document, ...
    ref: NonEmptyStr


class Attachment(Contract):
    name: NonEmptyStr
    sha256: Sha256Hex
    ref: NonEmptyStr  # where the bytes live (S3 key from Step 10)


class Thread(Contract):
    thread_id: UUID
    receptor_id: ReceptorId | None = None
    title: str = ""
    created_at: Timestamp


class ArchivedMessage(Contract):
    message_id: UUID
    thread_id: UUID
    participant: NonEmptyStr  # founder, dyson, ...
    modality: Modality
    body: NonEmptyStr
    language: Language = Language.UNKNOWN
    transcription_uncertain: bool = False
    raw_transcript_ref: str | None = None
    attachments: tuple[Attachment, ...] = ()
    sent_at: Timestamp

    @model_validator(mode="after")
    def _checks(self) -> "ArchivedMessage":
        if self.modality is Modality.TEXT and self.transcription_uncertain:
            raise ValueError("typed text has no transcription")
        return self


class MessageHit(Contract):
    message: ArchivedMessage
    citation: Citation
    uncertain: bool  # flags uncertain speech transcription (LA-MEM-09)


class MemoryKind(StrEnum):
    FACT = "fact"
    PREFERENCE = "preference"
    PROJECT_STATUS = "project_status"
    SUMMARY = "summary"


class MemoryItem(Contract):
    item_id: UUID
    receptor_id: ReceptorId | None = None
    kind: MemoryKind
    content: NonEmptyStr
    sources: tuple[Citation, ...] = Field(min_length=1)
    uncertain: bool = False
    supersedes: UUID | None = None
    created_at: Timestamp


class Fact(Contract):
    """A bi-temporal personal fact (phase 2): what is true, for how long, and when learned.

    valid_from/valid_to are world time; recorded_at is when Dyson learned it. A newer fact may
    supersede an older one by naming it, so a point-in-time question has an honest answer. Every
    fact cites at least one source (LA-MEM-09).
    """

    fact_id: UUID
    receptor_id: ReceptorId | None = None  # None = a core (personal) fact about the Founder
    subject: NonEmptyStr
    attribute: NonEmptyStr
    value: NonEmptyStr
    statement: NonEmptyStr
    valid_from: Timestamp
    valid_to: Timestamp | None = None
    sources: tuple[Citation, ...] = Field(min_length=1)
    confidence: Annotated[float, Field(gt=0, le=1)] = 1.0
    supersedes: UUID | None = None
    recorded_at: Timestamp

    @model_validator(mode="after")
    def _checks(self) -> "Fact":
        if self.valid_to is not None and self.valid_to < self.valid_from:
            raise ValueError("valid_to cannot be before valid_from")
        return self


class SharedLearning(Contract):
    learning_id: UUID
    content: NonEmptyStr
    origin_receptor_id: ReceptorId | None = None
    sources: tuple[Citation, ...] = Field(min_length=1)
    approval_id: UUID
    verified_evidence_id: UUID
    created_at: Timestamp


class RegisterStatus(StrEnum):
    PROPOSED = "PROPOSED"
    OPEN = "OPEN"
    DESIGN_LOCKED = "DESIGN LOCKED"
    APPROVED = "APPROVED"
    SUPERSEDED = "SUPERSEDED"


LOCKED_STATUSES = frozenset({RegisterStatus.DESIGN_LOCKED, RegisterStatus.APPROVED})


class RegisterEntry(Contract):
    entry_id: UUID
    rule_id: Annotated[str, Field(pattern=r"^(AMD-[1-9][0-9]*|D-[0-9]{3})$")]
    version: NonEmptyStr
    status: RegisterStatus
    title: NonEmptyStr
    body: NonEmptyStr  # the exact approved text
    decision_date: date | None = None
    evidence: tuple[Citation, ...] = ()
    founder_approval_ref: str | None = None
    recorded_at: Timestamp


class RegisterView(Contract):
    """The authoritative state of one rule: its latest entry. locked is derived, never stored."""

    current: RegisterEntry
    locked: bool
    history_length: int


class StageStatus(Contract):
    """Latest evidence for one stage of one capability, with expiry applied."""

    record: EvidenceRecord
    expired: bool
