"""Proactive inbox and the morning briefing (phase 4, D-026).

Dyson acts on its own, but on the Founder's terms. The research is clear: constant interruption
annoys; batching a few times a day helps. So every proactive item is one of three kinds and is
either urgent (it interrupts now) or saved for the next digest. Only a few defined classes are
urgent. The Founder's response to a briefing is the signal Dyson learns from.
"""

from enum import StrEnum
from typing import Annotated
from uuid import UUID

from pydantic import Field, model_validator

from .common import Contract, NonEmptyStr, Timestamp


class InboxKind(StrEnum):
    NOTIFY = "notify"  # just so you know; no answer needed
    QUESTION = "question"  # Dyson needs a clarification
    REVIEW = "review"  # a prepared draft or action to approve


class Urgency(StrEnum):
    NOW = "now"  # interrupts: shown at once
    DIGEST = "digest"  # waits for the next batch


class UrgentClass(StrEnum):
    """The only reasons Dyson interrupts. Everything else waits for a digest."""

    MONEY_OUT = "money_out"  # anything that would move money
    DEADLINE_24H = "deadline_24h"  # something due within a day
    RECEPTOR_FAILING = "receptor_failing"  # a business unit is failing
    SECURITY = "security"  # a security concern


class InboxItem(Contract):
    item_id: UUID
    kind: InboxKind
    subject: NonEmptyStr
    body: str = ""
    urgency: Urgency
    urgent_class: UrgentClass | None = None  # set only when urgency is NOW
    review_ref: str = ""  # points at the draft or proposed action a REVIEW item approves
    created_at: Timestamp

    @model_validator(mode="after")
    def _checks(self) -> "InboxItem":
        if self.urgency is Urgency.NOW and self.urgent_class is None:
            raise ValueError("an urgent item must name its urgent class")
        if self.urgency is Urgency.DIGEST and self.urgent_class is not None:
            raise ValueError("a digest item has no urgent class")
        if self.kind is InboxKind.REVIEW and not self.review_ref:
            raise ValueError("a review item must point at what it approves")
        return self


class BriefingSection(Contract):
    heading: NonEmptyStr
    lines: tuple[str, ...] = ()


class Briefing(Contract):
    """The one morning artifact. Replying to it teaches Dyson what the Founder cares about."""

    briefing_id: UUID
    for_date: Timestamp
    sections: tuple[BriefingSection, ...] = ()
    item_ids: tuple[UUID, ...] = ()  # the inbox items this briefing gathered


class Disposition(StrEnum):
    ACTED = "acted"  # the Founder approved or answered
    DISMISSED = "dismissed"  # the Founder set it aside
    IGNORED = "ignored"  # no response by the time it expired


class Feedback(Contract):
    """What the Founder did with a proactive item; the tuner reads these to adjust interrupts."""

    item_id: UUID
    disposition: Disposition
    note: str = ""
    at: Timestamp


class ClassTuning(Contract):
    """A suggestion only: should this class keep interrupting, by the Founder's history."""

    urgent_class: UrgentClass
    acted: Annotated[int, Field(ge=0)]
    dismissed: Annotated[int, Field(ge=0)]
    suggest_demote: bool  # the Founder keeps dismissing it; propose it stop interrupting
