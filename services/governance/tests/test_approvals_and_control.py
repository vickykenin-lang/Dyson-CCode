"""Approvals, STOP / PAUSE / RESUME, breaches and recovery."""

from datetime import timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from pydantic import ValidationError

from dyson_contracts.approvals import ApprovalCategory
from dyson_contracts.audit import AuditKind
from dyson_contracts.common import Component
from dyson_contracts.control import ControlCommand, ControlCommandType, ControlMode, ControlScope
from dyson_governance.core import GovernanceError
from dyson_governance.events import BreachKind, ProposalKind
from dyson_governance.state import ProposalStatus

_POLICY_DIR = Path(__file__).resolve().parents[3] / "policy"


def _cmd(kind, scope=ControlScope.MASTER, receptor=None, by=Component.FOUNDER, clock=None):
    return ControlCommand(
        command_id=uuid4(),
        command=kind,
        scope=scope,
        receptor_id=receptor,
        issued_by=by,
        issued_at=clock(),
    )


def _founder_cmd(founder, kind, **kw):
    cmd = _cmd(kind, clock=founder.clock, **kw)
    return cmd, founder.channel.sign(cmd)


# Approval engine ------------------------------------------------------------------------
def _financial(core, payload=None):
    payload = payload or {"tool": "ads.topup", "amount": "500", "currency": "INR"}
    req = core.propose(
        ProposalKind.EXTERNAL_ACTION,
        payload,
        "Top up ad credit 500 INR",
        Component.ORCHESTRATOR,
        category=ApprovalCategory.FINANCIAL,
    )
    return req, payload


def test_financial_action_blocked_until_founder_approves_then_usable_once(core, founder):
    req, payload = _financial(core)
    digest = core.external_action_digest(payload)
    assert req.action_digest == digest
    assert not core.check_approval(req.approval_id, digest, ApprovalCategory.FINANCIAL)
    with pytest.raises(GovernanceError):
        core.consume_approval(
            req.approval_id, digest, ApprovalCategory.FINANCIAL, Component.TOOL_HUB
        )
    assert founder.decide(core, req) is ProposalStatus.APPROVED
    assert core.check_approval(req.approval_id, digest, ApprovalCategory.FINANCIAL)
    other = core.external_action_digest(payload | {"amount": "5000"})
    assert not core.check_approval(req.approval_id, other, ApprovalCategory.FINANCIAL)
    core.consume_approval(req.approval_id, digest, ApprovalCategory.FINANCIAL, Component.TOOL_HUB)
    assert core.approval_status(req.approval_id) is ProposalStatus.CONSUMED
    with pytest.raises(GovernanceError):  # single use
        core.consume_approval(
            req.approval_id, digest, ApprovalCategory.FINANCIAL, Component.TOOL_HUB
        )


def test_rejected_stays_blocked(core, founder):
    req, payload = _financial(core)
    assert founder.decide(core, req, approve=False) is ProposalStatus.REJECTED
    assert not core.check_approval(req.approval_id, req.action_digest, ApprovalCategory.FINANCIAL)
    with pytest.raises(GovernanceError):
        founder.decide(core, req)  # closed: no second decision


def test_decision_without_valid_channel_proof_is_refused(core, founder):
    req, _ = _financial(core)
    d, _proof = founder.decision(req)
    with pytest.raises(GovernanceError):
        core.decide(d, "forged")
    assert core.approval_status(req.approval_id) is ProposalStatus.OPEN


@pytest.mark.parametrize(
    "who", [Component.CONVERSATION_ENGINE, Component.HERMES, Component.RECEPTOR]
)
def test_models_agents_and_receptors_cannot_approve(core, founder, who):
    req, _ = _financial(core)
    with pytest.raises(ValidationError):
        founder.decision(req, decided_by=who)


def test_decision_binds_to_exact_action_and_expiry(core, founder, clock):
    req = core.propose(
        ProposalKind.EXTERNAL_ACTION,
        {"x": 1},
        "x",
        Component.ORCHESTRATOR,
        category=ApprovalCategory.OTHER,
        expires_at=clock() + timedelta(minutes=10),
    )
    d, proof = founder.decision(req, action_digest="0" * 64)
    with pytest.raises(GovernanceError):
        core.decide(d, proof)
    clock.advance(minutes=11)
    with pytest.raises(GovernanceError):
        founder.decide(core, req)


def test_rule_change_cannot_be_self_approved_and_is_never_applied_at_runtime(core, founder, policy):
    req = core.propose_amendment("AMD-3", "- three\n+ two", "faster", Component.CORE_RD)
    d, _ = founder.decision(req)
    with pytest.raises(GovernanceError):
        core.decide(d, "signed-by-core-rd")
    assert founder.decide(core, req) is ProposalStatus.APPROVED
    # Approved, but A changes nothing: amendments go through the Governed Amendment Workflow.
    assert core.policy.control("AMD-3", "qa_consecutive_failure_limit") == 3


def test_every_change_is_audited(core, founder, audit):
    req, _ = _financial(core)
    founder.decide(core, req)
    kinds = [a.kind for a in audit]
    assert kinds == [AuditKind.APPROVAL, AuditKind.APPROVAL]
    assert audit[1].actor is Component.FOUNDER


def test_audit_failure_never_blocks_and_is_kept_for_forwarding(policy, channel, clock):
    from dyson_governance.core import GovernanceCore
    from dyson_governance.store import InMemoryEventStore

    def broken(_):
        raise ConnectionError("I is down")

    core = GovernanceCore(InMemoryEventStore(), policy, channel, audit_sink=broken, clock=clock)
    core.control(_cmd(ControlCommandType.STOP, by=Component.GOVERNANCE_CORE, clock=clock))
    assert core.effective_mode(None) is ControlMode.STOPPED
    assert len(core.audit_backlog) == 1


# STOP / PAUSE / RESUME ------------------------------------------------------------------
def test_master_stop_reaches_everything_without_any_model(core, founder, heard):
    cmd, proof = _founder_cmd(founder, ControlCommandType.STOP)
    state = core.control(cmd, proof)
    assert state.mode is ControlMode.STOPPED
    assert core.effective_mode("R11") is ControlMode.STOPPED
    assert core.effective_mode("T0") is ControlMode.STOPPED
    assert heard and heard[-1][0] == cmd  # pushed to G, Hermes and Receptor lanes


def test_founder_command_needs_channel_proof(core, founder):
    cmd, _ = _founder_cmd(founder, ControlCommandType.STOP)
    with pytest.raises(GovernanceError):
        core.control(cmd, "forged")
    assert core.effective_mode(None) is ControlMode.RUNNING


def test_listener_failure_does_not_block_stop(policy, channel, clock):
    from dyson_governance.core import GovernanceCore
    from dyson_governance.store import InMemoryEventStore

    def dead_listener(cmd, state):
        raise ConnectionError("Hermes unreachable")

    core = GovernanceCore(
        InMemoryEventStore(), policy, channel, control_listeners=[dead_listener], clock=clock
    )
    core.control(_cmd(ControlCommandType.STOP, by=Component.GOVERNANCE_CORE, clock=clock))
    assert core.effective_mode("R11") is ControlMode.STOPPED


def test_receptor_pause_and_pause_never_softens_stop(core, founder):
    cmd, proof = _founder_cmd(
        founder, ControlCommandType.PAUSE, scope=ControlScope.RECEPTOR, receptor="R11"
    )
    core.control(cmd, proof)
    assert core.effective_mode("R11") is ControlMode.PAUSED
    assert core.effective_mode("R12") is ControlMode.RUNNING
    stop, p2 = _founder_cmd(
        founder, ControlCommandType.STOP, scope=ControlScope.RECEPTOR, receptor="R11"
    )
    core.control(stop, p2)
    pause, p3 = _founder_cmd(
        founder, ControlCommandType.PAUSE, scope=ControlScope.RECEPTOR, receptor="R11"
    )
    core.control(pause, p3)
    assert core.effective_mode("R11") is ControlMode.STOPPED


def test_resume_only_through_an_approval_for_the_current_stop(core, founder):
    stop1, p1 = _founder_cmd(founder, ControlCommandType.STOP)
    core.control(stop1, p1)
    with pytest.raises(GovernanceError):  # no free-standing RESUME
        core.control(
            ControlCommand(
                command_id=uuid4(),
                command=ControlCommandType.RESUME,
                scope=ControlScope.MASTER,
                issued_by=Component.FOUNDER,
                issued_at=founder.clock(),
                authorization_id=uuid4(),
            ),
            "x",
        )
    old = core.propose_resume(ControlScope.MASTER, None, Component.CONVERSATION_ENGINE)
    stop2, p2 = _founder_cmd(founder, ControlCommandType.STOP)
    core.control(stop2, p2)
    with pytest.raises(GovernanceError):  # the old approval named the earlier stop
        founder.decide(core, old)
    assert core.effective_mode(None) is ControlMode.STOPPED
    fresh = core.propose_resume(ControlScope.MASTER, None, Component.CONVERSATION_ENGINE)
    assert founder.decide(core, fresh) is ProposalStatus.EXECUTED
    assert core.effective_mode(None) is ControlMode.RUNNING


def test_no_automatic_resume_after_breach(core, founder, heard):
    state = core.declare_breach(
        BreachKind.FINANCIAL,
        ControlScope.RECEPTOR,
        "R11",
        Component.FINANCIAL_CONTROL,
        "ledger mismatch",
    )
    assert state.mode is ControlMode.STOPPED and state.serious_breach
    assert heard[-1][1].serious_breach
    # Nothing in A resumes it; only the Founder's approval of a resume proposal can.
    assert core.effective_mode("R11") is ControlMode.STOPPED
    req = core.propose_resume(ControlScope.RECEPTOR, "R11", Component.GOVERNANCE_CORE)
    assert "serious breach" in req.action_summary
    founder.decide(core, req)
    after = core.control_state(ControlScope.RECEPTOR, "R11")
    assert after.mode is ControlMode.RUNNING and not after.serious_breach


# Recovery -------------------------------------------------------------------------------
def test_recovery_is_bounded_recorded_and_escalated(core, founder):
    incident = uuid4()
    # No Founder-set limit yet: no automatic attempt is allowed; escalate at once, once.
    assert core.record_recovery_attempt(incident, "R11", succeeded=False) is False
    assert core.record_recovery_attempt(incident, "R11", succeeded=False) is False
    assert core.sync().incidents[incident].escalated
    founder.decide(core, core.propose_parameter("recovery_attempt_limit", 2, Component.MONITORING))
    other = uuid4()
    assert core.record_recovery_attempt(other, "R12", succeeded=False)
    assert core.record_recovery_attempt(other, "R12", succeeded=False)
    assert core.record_recovery_attempt(other, "R12", succeeded=False) is False
    assert core.sync().incidents[other].attempts == 2
    founder.decide(core, core.propose_recovery_authorization(other, 1, Component.MONITORING))
    assert core.record_recovery_attempt(other, "R12", succeeded=True)
    assert core.sync().incidents[other].resolved


# Operational parameters vs amendments ---------------------------------------------------
def test_parameters_and_amendments_take_different_paths(core):
    for name in ("AMD-3.qa_consecutive_failure_limit", "qa_consecutive_failure_limit"):
        with pytest.raises(GovernanceError):
            core.propose_parameter(name, 2, Component.CORE_RD)
    with pytest.raises(GovernanceError):
        core.propose_parameter("recovery_attempt_limit", -1, Component.CORE_RD)
    req = core.propose_amendment("AMD-3", "diff", "why", Component.CORE_RD)
    assert req.category is ApprovalCategory.RULE_CHANGE


def test_safe_continuity_trigger_stays_blocked(core):
    from dyson_governance.core import GateClosed

    with pytest.raises(GateClosed):
        core.trigger_safe_continuity_automatically()
    assert core.sync().safe_continuity_active is False


def test_founder_decided_recovery_limit_is_three_until_changed(policy, channel, clock, founder):
    from dyson_governance.core import GovernanceCore, load_initial_parameters
    from dyson_governance.store import InMemoryEventStore

    initial = load_initial_parameters(_POLICY_DIR)
    assert initial == {
        "recovery_attempt_limit": 3,  # D-008
        "repeated_failure_threshold": 3,  # D-010
        "founder_reminder_interval_minutes": 60,  # D-009
        "stale_after_hours": 72,  # D-011
        "approval_expiry_hours": 24,  # D-014
    }
    core = GovernanceCore(
        InMemoryEventStore(), policy, channel, clock=clock, initial_parameters=initial
    )
    incident = uuid4()
    assert [core.record_recovery_attempt(incident, "R11", False) for _ in range(4)] == [
        True,
        True,
        True,
        False,
    ]
    assert core.sync().incidents[incident].escalated
    founder.decide(core, core.propose_parameter("recovery_attempt_limit", 1, Component.MONITORING))
    assert core.parameter("recovery_attempt_limit") == 1  # an approved change replaces it


def test_initial_parameters_must_cite_a_founder_decision(tmp_path):
    import shutil

    from dyson_governance.core import load_initial_parameters

    shutil.copytree(_POLICY_DIR, tmp_path / "p")
    f = tmp_path / "p" / "parameters.yaml"
    f.write_text(f.read_text().replace("decision: D-008", "decision: D-999"))
    with pytest.raises(ValueError):
        load_initial_parameters(tmp_path / "p")
    f.write_text(
        f.read_text().replace("decision: D-999", "decision: D-008").replace("value: 3", "value: -1")
    )
    with pytest.raises(ValueError):
        load_initial_parameters(tmp_path / "p")
