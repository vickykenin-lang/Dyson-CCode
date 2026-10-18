"""Current governance state, rebuilt deterministically by replaying the event log."""

from dataclasses import dataclass, field
from enum import StrEnum
from uuid import UUID

from pydantic import JsonValue

from dyson_contracts.approvals import ApprovalDecision, ApprovalDecisionKind, ApprovalRequest
from dyson_contracts.common import Timestamp
from dyson_contracts.control import ControlCommandType, ControlMode, ControlScope, ControlState
from dyson_contracts.integrations import IntegrationRecord
from dyson_contracts.receptor import ReceptorManifest

from .events import (
    ApprovalConsumed,
    BreachDeclared,
    ComplianceItemRecorded,
    ControlApplied,
    DecisionRecorded,
    GovernanceEvent,
    IntegrationRecorded,
    LegalReviewRecorded,
    LimitsRecommended,
    LimitsSet,
    ParameterSet,
    ProposalCreated,
    ProposalExecuted,
    ProposalKind,
    ReceptorLimits,
    ReceptorRegistered,
    ReceptorStatus,
    ReceptorStatusChanged,
    RecoveryAttempted,
    RecoveryEscalated,
    SurvivalModeChanged,
)


class ProposalStatus(StrEnum):
    OPEN = "open"
    APPROVED = "approved"
    REJECTED = "rejected"
    EXECUTED = "executed"  # internal kinds, applied by A
    CONSUMED = "consumed"  # external kinds, used once by the component that acted


@dataclass
class Proposal:
    request: ApprovalRequest
    kind: ProposalKind
    payload: dict[str, JsonValue]
    status: ProposalStatus = ProposalStatus.OPEN
    decision: ApprovalDecision | None = None


@dataclass
class Incident:
    attempts: int = 0
    allowed: int = 0  # extra attempts authorized by the Founder
    escalated: bool = False
    resolved: bool = False


@dataclass
class Receptor:
    manifest: ReceptorManifest
    status: ReceptorStatus = ReceptorStatus.PROPOSED


@dataclass
class ComplianceItem:
    receptor_id: str
    kind: str
    requires_legal_review: bool
    reviewed: bool = False
    cleared: bool = False


@dataclass
class GovernanceState:
    proposals: dict[UUID, Proposal] = field(default_factory=dict)
    master: ControlState | None = None
    receptor_controls: dict[str, ControlState] = field(default_factory=dict)
    incidents: dict[UUID, Incident] = field(default_factory=dict)
    parameters: dict[str, JsonValue] = field(default_factory=dict)
    limits: dict[str, ReceptorLimits] = field(default_factory=dict)
    recommendations: list[LimitsRecommended] = field(default_factory=list)
    integrations: dict[str, IntegrationRecord] = field(default_factory=dict)
    receptors: dict[str, Receptor] = field(default_factory=dict)
    compliance: dict[UUID, ComplianceItem] = field(default_factory=dict)
    # AMD-12 v1.1: Survival Mode, entered and left only by A from observed Founder presence.
    safe_continuity_active: bool = False
    survival_since: Timestamp | None = None

    def control_for(
        self, scope: ControlScope, receptor_id: str | None, at: Timestamp
    ) -> ControlState:
        current = (
            self.master if scope is ControlScope.MASTER else self.receptor_controls.get(receptor_id)
        )
        return current or ControlState(
            scope=scope, receptor_id=receptor_id, mode=ControlMode.RUNNING, since=at
        )

    def apply(self, e: GovernanceEvent) -> None:
        match e:
            case ProposalCreated():
                self.proposals[e.request.approval_id] = Proposal(e.request, e.kind, e.payload)
            case DecisionRecorded():
                p = self.proposals[e.decision.approval_id]
                p.decision = e.decision
                p.status = (
                    ProposalStatus.APPROVED
                    if e.decision.decision is ApprovalDecisionKind.APPROVE
                    else ProposalStatus.REJECTED
                )
            case ProposalExecuted():
                self.proposals[e.approval_id].status = ProposalStatus.EXECUTED
            case ApprovalConsumed():
                self.proposals[e.approval_id].status = ProposalStatus.CONSUMED
            case ControlApplied():
                self._set_control(e)
            case BreachDeclared():
                self._store_control(
                    ControlState(
                        scope=e.scope,
                        receptor_id=e.receptor_id,
                        mode=ControlMode.STOPPED,
                        serious_breach=True,
                        last_command_id=e.breach_id,
                        since=e.at,
                    )
                )
            case RecoveryAttempted():
                inc = self.incidents.setdefault(e.incident_id, Incident())
                inc.attempts = e.attempt
                inc.resolved = inc.resolved or e.succeeded
            case RecoveryEscalated():
                self.incidents.setdefault(e.incident_id, Incident()).escalated = True
            case ParameterSet():
                self.parameters[e.name] = e.value
            case LimitsRecommended():
                self.recommendations.append(e)
            case LimitsSet():
                self.limits[e.limits.receptor_id] = e.limits
            case SurvivalModeChanged():
                self.safe_continuity_active = e.active
                self.survival_since = e.at if e.active else None
            case IntegrationRecorded():
                self.integrations[e.record.integration_id] = e.record
            case ReceptorRegistered():
                self.receptors[e.manifest.receptor_id] = Receptor(e.manifest)
            case ReceptorStatusChanged():
                self.receptors[e.receptor_id].status = e.status
            case ComplianceItemRecorded():
                self.compliance[e.item_id] = ComplianceItem(
                    e.receptor_id, e.kind, e.requires_legal_review
                )
            case LegalReviewRecorded():
                self.compliance[e.item_id].reviewed = True
        if isinstance(e, ProposalExecuted):
            p = self.proposals[e.approval_id]
            if p.kind is ProposalKind.AUTHORIZE_RECOVERY:
                inc = self.incidents.setdefault(UUID(str(p.payload["incident_id"])), Incident())
                inc.allowed += int(p.payload["extra_attempts"])
                inc.escalated = False
            elif p.kind is ProposalKind.CLEAR_COMPLIANCE:
                self.compliance[UUID(str(p.payload["item_id"]))].cleared = True

    def _set_control(self, e: ControlApplied) -> None:
        c = e.command
        prev = self.control_for(c.scope, c.receptor_id, e.at)
        if c.command is ControlCommandType.STOP:
            mode, breach = ControlMode.STOPPED, prev.serious_breach
        elif c.command is ControlCommandType.PAUSE:
            # A pause never softens a stop.
            mode = ControlMode.STOPPED if prev.mode is ControlMode.STOPPED else ControlMode.PAUSED
            breach = prev.serious_breach
        else:  # RESUME, already authorized by GovernanceCore
            mode, breach = ControlMode.RUNNING, False
        self._store_control(
            ControlState(
                scope=c.scope,
                receptor_id=c.receptor_id,
                mode=mode,
                serious_breach=breach,
                last_command_id=c.command_id,
                since=e.at,
            )
        )

    def _store_control(self, s: ControlState) -> None:
        if s.scope is ControlScope.MASTER:
            self.master = s
        else:
            self.receptor_controls[s.receptor_id] = s
