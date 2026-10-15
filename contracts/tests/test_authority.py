"""Contract-level guarantees about who may approve, resume, verify and complete."""

import hashlib
from datetime import timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
from pydantic import ValidationError

from dyson_contracts.approvals import (
    ApprovalCategory,
    ApprovalDecision,
    ApprovalDecisionKind,
    ApprovalRequest,
)
from dyson_contracts.common import Component, Money, RiskLevel
from dyson_contracts.control import ControlCommand, ControlCommandType, ControlScope
from dyson_contracts.evidence import EvidenceOutcome, EvidenceRecord, EvidenceStage
from dyson_contracts.finance import ReconciliationResult, RevenueStatus
from dyson_contracts.integrations import IntegrationKind, IntegrationRecord, IntegrationStatus
from dyson_contracts.interface import CommandAcknowledgment, TaskStatusUpdate
from dyson_contracts.lanes import LANE_OWNER, Lane, VerificationVerdict
from dyson_contracts.tasks import TaskState
from dyson_contracts.toolcalls import CheckName, CheckResult, ToolCallDecision, ToolCallRequest

DIGEST = hashlib.sha256(b"pay vendor 100").hexdigest()


def _request(now, **kw):
    base = dict(
        approval_id=uuid4(),
        category=ApprovalCategory.FINANCIAL,
        action_summary="pay vendor",
        action_digest=DIGEST,
        requested_by=Component.GOVERNANCE_CORE,
        created_at=now,
    )
    return ApprovalRequest(**(base | kw))


def _decision(req, at, **kw):
    base = dict(
        approval_id=req.approval_id,
        action_digest=req.action_digest,
        decision=ApprovalDecisionKind.APPROVE,
        decided_by=Component.FOUNDER,
        channel=Component.DIRECT_FOUNDER_CONTROLS,
        auth_method="passkey",
        decided_at=at,
    )
    return ApprovalDecision(**(base | kw))


@pytest.mark.parametrize(
    "who", [Component.CONVERSATION_ENGINE, Component.HERMES, Component.RECEPTOR]
)
def test_no_model_agent_or_receptor_can_decide(now, who):
    req = _request(now)
    with pytest.raises(ValidationError):
        _decision(req, now, decided_by=who)


def test_decision_must_come_from_founder_controls_channel(now):
    with pytest.raises(ValidationError):
        _decision(_request(now), now, channel=Component.APP)


def test_decision_binds_to_exact_action_and_expiry(now, later):
    req = _request(now, expires_at=later)
    assert _decision(req, now).applies_to(req)
    other = hashlib.sha256(b"pay vendor 1000").hexdigest()
    assert not _decision(req, now, action_digest=other).applies_to(req)
    assert not _decision(req, later + timedelta(seconds=1)).applies_to(req)


def test_resume_needs_founder_and_authorization(now):
    base = dict(
        command_id=uuid4(),
        command=ControlCommandType.RESUME,
        scope=ControlScope.MASTER,
        issued_at=now,
    )
    with pytest.raises(ValidationError):
        ControlCommand(**base, issued_by=Component.GOVERNANCE_CORE, authorization_id=uuid4())
    with pytest.raises(ValidationError):
        ControlCommand(**base, issued_by=Component.FOUNDER)
    ControlCommand(**base, issued_by=Component.FOUNDER, authorization_id=uuid4())


def test_receptor_scope_needs_receptor(now):
    with pytest.raises(ValidationError):
        ControlCommand(
            command_id=uuid4(),
            command=ControlCommandType.STOP,
            scope=ControlScope.RECEPTOR,
            issued_by=Component.FOUNDER,
            issued_at=now,
        )


def _checks(failing=()):
    return tuple(CheckResult(check=c, passed=c not in failing) for c in CheckName)


def test_tool_call_allowed_only_when_all_checks_pass(now):
    cid = uuid4()
    ok = ToolCallDecision(
        call_id=cid, allowed=True, checks=_checks(), decided_by=Component.TOOL_HUB, decided_at=now
    )
    assert ok.allowed
    with pytest.raises(ValidationError):
        ToolCallDecision(
            call_id=cid,
            allowed=True,
            checks=_checks({CheckName.STOP_STATE}),
            decided_by=Component.TOOL_HUB,
            decided_at=now,
        )
    with pytest.raises(ValidationError):  # a skipped check is not a pass
        ToolCallDecision(
            call_id=cid,
            allowed=True,
            checks=_checks()[:-1],
            decided_by=Component.TOOL_HUB,
            decided_at=now,
        )


def test_only_orchestrator_or_hermes_request_tools(now):
    base = dict(
        call_id=uuid4(),
        task_id=uuid4(),
        idempotency_key="task-0001-attempt-1",
        tool_id="t0.inspect",
        risk=RiskLevel.LOW,
        estimated_spend=Money(amount=Decimal("0"), currency="INR"),
        requested_at=now,
    )
    ToolCallRequest(**base, requested_by=Component.ORCHESTRATOR)
    with pytest.raises(ValidationError):
        ToolCallRequest(**base, requested_by=Component.CONVERSATION_ENGINE)


def _evidence(now, **kw):
    base = dict(
        evidence_id=uuid4(),
        capability="t0.inspect",
        provider="test-t0",
        stage=EvidenceStage.REAL_OUTPUT_VERIFIED,
        outcome=EvidenceOutcome.PASSED,
        environment="local",
        scope="R-T0",
        recorded_by=Component.QA_QC,
        recorded_at=now,
        artifact_ref="sha256:" + DIGEST,
    )
    return EvidenceRecord(**(base | kw))


def test_eight_evidence_stages():
    assert [s.value for s in EvidenceStage] == list(range(1, 9))


@pytest.mark.parametrize("who", [Component.RECEPTOR, Component.HERMES, Component.ORCHESTRATOR])
def test_no_self_certification_of_live_stages(now, who):
    with pytest.raises(ValidationError):
        _evidence(now, recorded_by=who)
    _evidence(now, recorded_by=who, outcome=EvidenceOutcome.FAILED)
    _evidence(now, recorded_by=who, stage=EvidenceStage.TEST_PASSED)


def test_verdict_needs_both_checks_and_evidence(now):
    v = VerificationVerdict(
        task_id=uuid4(),
        technical_success=True,
        fit_for_purpose=False,
        evidence_ids=(uuid4(),),
        verified_by=Component.QA_QC,
        verified_at=now,
    )
    assert not v.passed
    with pytest.raises(ValidationError):
        VerificationVerdict(
            task_id=uuid4(),
            technical_success=True,
            fit_for_purpose=True,
            evidence_ids=(),
            verified_by=Component.QA_QC,
            verified_at=now,
        )


def test_acknowledgment_is_never_completion(now):
    with pytest.raises(ValidationError):
        CommandAcknowledgment(task_id=uuid4(), state=TaskState.COMPLETED_VERIFIED, at=now)
    with pytest.raises(ValidationError):
        TaskStatusUpdate(task_id=uuid4(), state=TaskState.COMPLETED_VERIFIED, at=now)


def test_revenue_final_only_with_statement_match(now):
    with pytest.raises(ValidationError):
        ReconciliationResult(
            report_id=uuid4(),
            status=RevenueStatus.FINAL,
            reconciled_by=Component.FINANCIAL_CONTROL,
            reconciled_at=now,
        )


def test_high_risk_integration_needs_founder_approval(now):
    base = dict(
        integration_id="mcp.example",
        kind=IntegrationKind.MCP_SERVER,
        name="example",
        version="1.0",
        risk=RiskLevel.HIGH,
        status=IntegrationStatus.ADMITTED,
        security_checked=True,
        change_record_ref="CR-1",
        updated_at=now,
    )
    with pytest.raises(ValidationError):
        IntegrationRecord(**base)
    assert IntegrationRecord(**base, founder_approval_id=uuid4()).callable


def test_five_lanes_one_owner_each():
    assert len(Lane) == 5
    assert set(LANE_OWNER) == set(Lane)


def test_contracts_reject_unknown_fields(now):
    with pytest.raises(ValidationError):
        _request(now, sneaky="x")
