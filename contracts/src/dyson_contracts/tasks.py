"""Task states and the only legal transitions (PRD section 9, Founder decisions D-001..D-003)."""

from enum import StrEnum
from typing import Annotated
from uuid import UUID

from pydantic import Field, model_validator

from .common import Component, Contract, IdempotencyKey, NonEmptyStr, ReceptorId, Timestamp

# AMD-3: three consecutive QA/QC failures put the task on HOLD.
QA_CONSECUTIVE_FAILURE_LIMIT = 3


class TaskState(StrEnum):
    ACCEPTED = "accepted"
    APPROVAL_NEEDED = "approval-needed"
    RUNNING = "running"
    HELD = "held"
    STOPPED = "stopped"
    FAILED = "failed"
    COMPLETED_VERIFIED = "completed-verified"
    REJECTED = "rejected"  # D-003
    CLOSED = "closed"


class TaskTrigger(StrEnum):
    APPROVAL_REQUIRED = "approval_required"
    FOUNDER_APPROVED = "founder_approved"
    FOUNDER_REJECTED = "founder_rejected"
    CHECKS_PASSED = "checks_passed"
    VERIFIED = "verified"
    EXECUTION_FAILED = "execution_failed"
    VERIFICATION_FAILED = "verification_failed"
    RETRY = "retry"
    QA_FAILURE_LIMIT = "qa_failure_limit"
    STOP = "stop"
    PAUSE = "pause"
    RESUME_AUTHORIZED = "resume_authorized"
    REVIEWER_RESUME = "reviewer_resume"
    REVIEWER_CLOSE = "reviewer_close"
    HOUSEKEEPING = "housekeeping"


S, T = TaskState, TaskTrigger

ACTIVE_STATES = frozenset({S.ACCEPTED, S.APPROVAL_NEEDED, S.RUNNING, S.FAILED, S.HELD})

# A RESUME returns the task to the state it was in when STOP or PAUSE hit it, so a resume can
# never skip an approval that was still pending.
RESUMABLE_STATES = frozenset({S.HELD, S.STOPPED})
RESUME_TARGETS = frozenset({S.ACCEPTED, S.APPROVAL_NEEDED, S.RUNNING, S.FAILED})

TRANSITIONS: dict[tuple[TaskState, TaskTrigger], TaskState] = {
    (S.ACCEPTED, T.APPROVAL_REQUIRED): S.APPROVAL_NEEDED,
    (S.ACCEPTED, T.CHECKS_PASSED): S.RUNNING,
    (S.APPROVAL_NEEDED, T.FOUNDER_APPROVED): S.RUNNING,
    (S.APPROVAL_NEEDED, T.FOUNDER_REJECTED): S.REJECTED,
    (S.RUNNING, T.VERIFIED): S.COMPLETED_VERIFIED,
    (S.RUNNING, T.EXECUTION_FAILED): S.FAILED,
    (S.RUNNING, T.VERIFICATION_FAILED): S.FAILED,
    (S.FAILED, T.RETRY): S.RUNNING,
    (S.RUNNING, T.QA_FAILURE_LIMIT): S.HELD,
    (S.FAILED, T.QA_FAILURE_LIMIT): S.HELD,
    (S.HELD, T.REVIEWER_RESUME): S.RUNNING,
    (S.HELD, T.REVIEWER_CLOSE): S.CLOSED,
    (S.COMPLETED_VERIFIED, T.HOUSEKEEPING): S.CLOSED,
    (S.FAILED, T.HOUSEKEEPING): S.CLOSED,
    (S.STOPPED, T.HOUSEKEEPING): S.CLOSED,
    (S.REJECTED, T.HOUSEKEEPING): S.CLOSED,
    **{(state, T.STOP): S.STOPPED for state in ACTIVE_STATES},
    # D-002: PAUSE moves an active task to held.
    **{(state, T.PAUSE): S.HELD for state in ACTIVE_STATES - {S.HELD}},
}

del S, T


class IllegalTransition(ValueError):
    pass


def next_state(
    current: TaskState, trigger: TaskTrigger, *, resume_to: TaskState | None = None
) -> TaskState:
    """Return the state a trigger moves a task to, or raise IllegalTransition.

    resume_to is required for RESUME_AUTHORIZED: the state the task held before STOP or PAUSE.
    """
    if trigger is TaskTrigger.RESUME_AUTHORIZED:
        if current not in RESUMABLE_STATES:
            raise IllegalTransition(f"cannot resume a task in {current}")
        if resume_to not in RESUME_TARGETS:
            raise IllegalTransition(f"cannot resume into {resume_to}")
        return resume_to
    if resume_to is not None:
        raise IllegalTransition("resume_to is only valid with RESUME_AUTHORIZED")
    try:
        return TRANSITIONS[(current, trigger)]
    except KeyError:
        raise IllegalTransition(f"{trigger} is not allowed from {current}") from None


class Task(Contract):
    task_id: UUID
    idempotency_key: IdempotencyKey
    instruction: NonEmptyStr
    state: TaskState
    receptor_id: ReceptorId | None = None
    consecutive_qa_failures: Annotated[int, Field(ge=0)] = 0
    created_at: Timestamp
    updated_at: Timestamp


class TaskTransition(Contract):
    """One recorded state change. from_state is None only for a new task entering accepted."""

    task_id: UUID
    from_state: TaskState | None
    to_state: TaskState
    trigger: TaskTrigger | None
    actor: Component
    at: Timestamp
    reason: str = ""

    @model_validator(mode="after")
    def _legal(self) -> "TaskTransition":
        if self.from_state is None:
            if self.to_state is not TaskState.ACCEPTED or self.trigger is not None:
                raise ValueError("a new task enters accepted with no trigger")
            return self
        if self.trigger is None:
            raise ValueError("trigger is required for an existing task")
        resume_to = self.to_state if self.trigger is TaskTrigger.RESUME_AUTHORIZED else None
        expected = next_state(self.from_state, self.trigger, resume_to=resume_to)
        if expected is not self.to_state:
            raise ValueError(f"{self.trigger} from {self.from_state} leads to {expected}")
        return self
