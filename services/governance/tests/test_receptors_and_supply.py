"""Limits, the integration gate, compliance and the Receptor lifecycle."""

from uuid import uuid4

import pytest
from pydantic import ValidationError

from dyson_contracts.common import Component, RiskLevel
from dyson_contracts.control import ControlCommand, ControlCommandType, ControlScope
from dyson_contracts.integrations import IntegrationKind, IntegrationStatus
from dyson_contracts.receptor import ReceptorManifest
from dyson_governance.core import GovernanceError, money
from dyson_governance.events import ComplianceKind, ReceptorLimits, ReceptorStatus
from dyson_governance.state import ProposalStatus


def _limits(rid="R11", tools=("t0.inspect",)):
    return ReceptorLimits(
        receptor_id=rid,
        permissions=tools,
        authority=("inspect",),
        max_spend_per_action=money("100", "INR"),
        max_spend_per_month=money("1000", "INR"),
    )


def _admit(core, tool="t0.inspect", risk=RiskLevel.LOW):
    core.propose_integration(tool, IntegrationKind.API, tool, "1.0", risk, "CR-1")
    core.record_security_check(tool, True, "scan-1")
    return core.admit_integration(tool)


# Budget and permissions -----------------------------------------------------------------
def test_no_limits_means_nothing_is_allowed(core):
    ok, reason = core.check_spend("R11", "t0.inspect", money("1", "INR"), money("0", "INR"))
    assert not ok and "no Founder-set limits" in reason


def test_recommendation_changes_nothing_until_founder_approves(core, founder):
    core.recommend_limits(_limits(), Component.GOVERNANCE_CORE, "verified profit is up")
    assert core.limits("R11") is None
    req = core.propose_limits(_limits(), Component.GOVERNANCE_CORE)
    assert core.limits("R11") is None
    assert founder.decide(core, req) is ProposalStatus.EXECUTED
    assert core.limits("R11") == _limits()


def test_spend_checks_against_limits(core, founder):
    founder.decide(core, core.propose_limits(_limits(), Component.GOVERNANCE_CORE))
    assert core.check_spend("R11", "t0.inspect", money("100", "INR"), money("900", "INR"))[0]
    assert not core.check_spend("R11", "t0.inspect", money("101", "INR"), money("0", "INR"))[0]
    assert not core.check_spend("R11", "t0.inspect", money("50", "INR"), money("960", "INR"))[0]
    assert not core.check_spend("R11", "ads.topup", money("1", "INR"), money("0", "INR"))[0]
    assert not core.check_spend("R11", "t0.inspect", money("1", "USD"), money("0", "USD"))[0]


# Supply chain / integration gate --------------------------------------------------------
def test_nothing_is_admitted_before_a_security_check(core):
    core.propose_integration(
        "mcp.files", IntegrationKind.MCP_SERVER, "files", "1.0", RiskLevel.LOW, "CR-7"
    )
    with pytest.raises(GovernanceError):
        core.admit_integration("mcp.files")
    assert not core.registry()["mcp.files"].callable


def test_failed_check_blocks(core):
    core.propose_integration(
        "pkg.bad", IntegrationKind.PACKAGE, "bad", "0.1", RiskLevel.LOW, "CR-8"
    )
    assert (
        core.record_security_check("pkg.bad", False, "scan-9").status is IntegrationStatus.BLOCKED
    )


def test_high_risk_needs_founder_approval(core, founder):
    core.propose_integration(
        "mcp.bank", IntegrationKind.MCP_SERVER, "bank", "1.0", RiskLevel.HIGH, "CR-9"
    )
    core.record_security_check("mcp.bank", True, "scan-2")
    req = core.admit_integration("mcp.bank")
    assert core.registry()["mcp.bank"].status is IntegrationStatus.PROPOSED
    founder.decide(core, req)
    rec = core.registry()["mcp.bank"]
    assert rec.callable and rec.founder_approval_id == req.approval_id


def test_suspect_integration_is_isolated_at_once(core):
    _admit(core)
    assert core.restrict_integration("t0.inspect", IntegrationStatus.ISOLATED).callable is False
    with pytest.raises(GovernanceError):
        core.restrict_integration("t0.inspect", IntegrationStatus.ADMITTED)


# Compliance -----------------------------------------------------------------------------
def test_legal_review_must_be_a_person(core):
    item, _ = core.record_compliance_item(
        "R11", ComplianceKind.REGULATED_ACTIVITY, "food delivery", True
    )
    for ai in (Component.CONVERSATION_ENGINE, Component.HERMES, Component.CORE_RD):
        with pytest.raises(ValidationError):
            core.record_legal_review(item, ai, "ai-opinion")


def test_compliance_goes_to_founder_and_needs_review_first(core, founder):
    item, req = core.record_compliance_item(
        "R11", ComplianceKind.REGULATED_ACTIVITY, "food delivery", True
    )
    assert req.requested_by is Component.GOVERNANCE_CORE
    with pytest.raises(GovernanceError):  # approval alone is not enough without legal review
        founder.decide(core, req)
    core.record_legal_review(item, Component.HUMAN_REVIEWER, "lawyer-memo-12")
    assert founder.decide(core, req) is ProposalStatus.EXECUTED
    assert core.compliance_cleared("R11")


# Receptor lifecycle ---------------------------------------------------------------------
def _manifest(rid="R11"):
    return ReceptorManifest(
        receptor_id=rid,
        purpose="inspection",
        tools=("t0.inspect",),
        permissions=("inspect",),
        boundaries="no money",
        recovery_policy="retry within AMD-5 bounds",
    )


def test_activation_needs_its_own_decision_budget_tools_and_evidence(core, founder):
    core.register_receptor(_manifest())
    evidence = [uuid4()]
    with pytest.raises(GovernanceError):  # no limits yet
        founder.decide(core, core.propose_activation("R11", evidence, Component.GOVERNANCE_CORE))
    founder.decide(core, core.propose_limits(_limits(), Component.GOVERNANCE_CORE))
    with pytest.raises(GovernanceError):  # tool not admitted through the gate
        founder.decide(core, core.propose_activation("R11", evidence, Component.GOVERNANCE_CORE))
    _admit(core)
    _item, creq = core.record_compliance_item("R11", ComplianceKind.ACTIVATION, "go live", False)
    with pytest.raises(GovernanceError):  # compliance not cleared
        founder.decide(core, core.propose_activation("R11", evidence, Component.GOVERNANCE_CORE))
    founder.decide(core, creq)
    with pytest.raises(GovernanceError):  # no acceptance evidence
        founder.decide(core, core.propose_activation("R11", [], Component.GOVERNANCE_CORE))
    assert founder.decide(
        core, core.propose_activation("R11", evidence, Component.GOVERNANCE_CORE)
    ) is (ProposalStatus.EXECUTED)
    assert core.sync().receptors["R11"].status is ReceptorStatus.ACTIVE


def _activate(core, founder):
    core.register_receptor(_manifest())
    founder.decide(core, core.propose_limits(_limits(), Component.GOVERNANCE_CORE))
    _admit(core)
    founder.decide(core, core.propose_activation("R11", [uuid4()], Component.GOVERNANCE_CORE))


def test_archive_needs_pause_and_founder_decision_and_keeps_records(core, founder):
    _activate(core, founder)
    with pytest.raises(GovernanceError):  # still running
        founder.decide(core, core.propose_archive("R11", Component.GOVERNANCE_CORE))
    core.control(
        ControlCommand(
            command_id=uuid4(),
            command=ControlCommandType.PAUSE,
            scope=ControlScope.RECEPTOR,
            receptor_id="R11",
            issued_by=Component.GOVERNANCE_CORE,
            issued_at=founder.clock(),
        )
    )
    req = core.propose_archive("R11", Component.GOVERNANCE_CORE)
    assert core.sync().receptors["R11"].status is ReceptorStatus.ACTIVE  # nothing until decided
    founder.decide(core, req)
    state = core.sync()
    assert state.receptors["R11"].status is ReceptorStatus.ARCHIVED
    assert state.receptors["R11"].manifest == _manifest()  # records kept, not deleted
    assert "R11" in state.limits


def test_replacement_is_the_founders_decision(core, founder):
    _activate(core, founder)
    core.control(
        ControlCommand(
            command_id=uuid4(),
            command=ControlCommandType.STOP,
            scope=ControlScope.RECEPTOR,
            receptor_id="R11",
            issued_by=Component.GOVERNANCE_CORE,
            issued_at=founder.clock(),
        )
    )
    req = core.propose_replacement("R11", "R12", Component.GOVERNANCE_CORE)
    founder.decide(core, req, approve=False)
    assert core.sync().receptors["R11"].status is ReceptorStatus.ACTIVE
