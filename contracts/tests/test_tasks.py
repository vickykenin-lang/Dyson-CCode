from uuid import uuid4

import pytest
from pydantic import ValidationError

from dyson_contracts.common import Component
from dyson_contracts.tasks import (
    ACTIVE_STATES,
    QA_CONSECUTIVE_FAILURE_LIMIT,
    RESUME_TARGETS,
    IllegalTransition,
    TaskState,
    TaskTransition,
    TaskTrigger,
    next_state,
)

S, T = TaskState, TaskTrigger


def test_state_names_follow_closure_and_decisions():
    assert [s.value for s in TaskState] == [
        "accepted",
        "approval-needed",
        "running",
        "held",
        "stopped",
        "failed",
        "completed-verified",
        "rejected",
        "closed",
    ]


def test_happy_paths():
    assert next_state(S.ACCEPTED, T.CHECKS_PASSED) is S.RUNNING
    assert next_state(S.ACCEPTED, T.APPROVAL_REQUIRED) is S.APPROVAL_NEEDED
    assert next_state(S.APPROVAL_NEEDED, T.FOUNDER_APPROVED) is S.RUNNING
    assert next_state(S.RUNNING, T.VERIFIED) is S.COMPLETED_VERIFIED
    assert next_state(S.COMPLETED_VERIFIED, T.HOUSEKEEPING) is S.CLOSED


def test_only_verification_completes_a_task():
    sources = [k for k, v in _all_transitions() if v is S.COMPLETED_VERIFIED]
    assert sources == [(S.RUNNING, T.VERIFIED)]


def test_reject_ends_and_cannot_restart():  # D-003
    assert next_state(S.APPROVAL_NEEDED, T.FOUNDER_REJECTED) is S.REJECTED
    allowed = {trig for (src, trig), _ in _all_transitions() if src is S.REJECTED}
    assert allowed == {T.HOUSEKEEPING}
    with pytest.raises(IllegalTransition):
        next_state(S.REJECTED, T.RESUME_AUTHORIZED, resume_to=S.RUNNING)


@pytest.mark.parametrize("state", sorted(ACTIVE_STATES - {S.HELD}))
def test_pause_holds(state):  # D-002
    assert next_state(state, T.PAUSE) is S.HELD


@pytest.mark.parametrize("state", sorted(ACTIVE_STATES))
def test_stop_from_any_active_state(state):
    assert next_state(state, T.STOP) is S.STOPPED


def test_three_qa_failures_hold():
    assert QA_CONSECUTIVE_FAILURE_LIMIT == 3
    assert next_state(S.RUNNING, T.QA_FAILURE_LIMIT) is S.HELD
    assert next_state(S.FAILED, T.QA_FAILURE_LIMIT) is S.HELD


def test_resume_returns_to_prior_state_and_cannot_skip_approval():
    assert next_state(S.HELD, T.RESUME_AUTHORIZED, resume_to=S.APPROVAL_NEEDED) is (
        S.APPROVAL_NEEDED
    )
    assert next_state(S.STOPPED, T.RESUME_AUTHORIZED, resume_to=S.RUNNING) is S.RUNNING
    assert S.COMPLETED_VERIFIED not in RESUME_TARGETS
    with pytest.raises(IllegalTransition):
        next_state(S.STOPPED, T.RESUME_AUTHORIZED)
    with pytest.raises(IllegalTransition):
        next_state(S.RUNNING, T.RESUME_AUTHORIZED, resume_to=S.RUNNING)


def test_closed_is_terminal():
    assert not [k for k, _ in _all_transitions() if k[0] is S.CLOSED]


def test_illegal_transition_raises():
    with pytest.raises(IllegalTransition):
        next_state(S.ACCEPTED, T.VERIFIED)


def test_transition_record_is_checked(now):
    tid = uuid4()
    TaskTransition(
        task_id=tid,
        from_state=None,
        to_state=S.ACCEPTED,
        trigger=None,
        actor=Component.ORCHESTRATOR,
        at=now,
    )
    with pytest.raises(ValidationError):
        TaskTransition(
            task_id=tid,
            from_state=S.ACCEPTED,
            to_state=S.COMPLETED_VERIFIED,
            trigger=T.CHECKS_PASSED,
            actor=Component.ORCHESTRATOR,
            at=now,
        )


def _all_transitions():
    from dyson_contracts.tasks import TRANSITIONS

    return list(TRANSITIONS.items())
