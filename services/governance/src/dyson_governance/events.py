"""Governance events. Every change in A is one of these, appended to an append-only log.

The log is the durable record: current state is rebuilt from it after a restart, and Step 9
forwards it to the audit log in I.
"""

import hashlib
import json
from enum import StrEnum
from typing import Annotated, Any, Literal
from uuid import UUID

from pydantic import Field, JsonValue, TypeAdapter

from dyson_contracts.approvals import ApprovalCategory, ApprovalDecision, ApprovalRequest
from dyson_contracts.common import Component, Contract, Money, NonEmptyStr, ReceptorId, Timestamp
from dyson_contracts.control import ControlCommand, ControlScope
from dyson_contracts.integrations import IntegrationRecord
from dyson_contracts.receptor import ReceptorManifest


def canonical_digest(value: Any) -> str:
    """sha256 of canonical JSON. Binds an approval to the exact proposal shown (LA-DFC-05)."""
    blob = json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


class ProposalKind(StrEnum):
    # Executed by A itself once approved.
    SET_PARAMETER = "set_parameter"
    SET_LIMITS = "set_limits"
    ADMIT_INTEGRATION = "admit_integration"
    ACTIVATE_RECEPTOR = "activate_receptor"
    ARCHIVE_RECEPTOR = "archive_receptor"
    REPLACE_RECEPTOR = "replace_receptor"
    RESUME = "resume"
    AUTHORIZE_RECOVERY = "authorize_recovery"
    CLEAR_COMPLIANCE = "clear_compliance"
    # Approved in A, carried out elsewhere: G consumes the approval, or the amendment
    # workflow updates the register.
    EXTERNAL_ACTION = "external_action"
    AMENDMENT = "amendment"


EXTERNAL_KINDS = frozenset({ProposalKind.EXTERNAL_ACTION, ProposalKind.AMENDMENT})

KIND_CATEGORY = {
    ProposalKind.SET_PARAMETER: ApprovalCategory.RULE_CHANGE,
    ProposalKind.SET_LIMITS: ApprovalCategory.RECEPTOR_LIMITS,
    ProposalKind.ADMIT_INTEGRATION: ApprovalCategory.INTEGRATION,
    ProposalKind.ACTIVATE_RECEPTOR: ApprovalCategory.RECEPTOR_LIFECYCLE,
    ProposalKind.ARCHIVE_RECEPTOR: ApprovalCategory.RECEPTOR_LIFECYCLE,
    ProposalKind.REPLACE_RECEPTOR: ApprovalCategory.RECEPTOR_LIFECYCLE,
    ProposalKind.RESUME: ApprovalCategory.RESUME,
    ProposalKind.AUTHORIZE_RECOVERY: ApprovalCategory.OTHER,
    ProposalKind.CLEAR_COMPLIANCE: ApprovalCategory.REGULATED_ACTIVITY,
    ProposalKind.AMENDMENT: ApprovalCategory.RULE_CHANGE,
}


class ReceptorLimits(Contract):
    """Permissions, authority and spending limits for one Receptor (AMD-11)."""

    receptor_id: ReceptorId
    permissions: tuple[NonEmptyStr, ...]  # tool IDs the Receptor may use
    authority: tuple[NonEmptyStr, ...] = ()
    max_spend_per_action: Money
    max_spend_per_month: Money


class ReceptorStatus(StrEnum):
    PROPOSED = "proposed"
    ACTIVE = "active"
    ARCHIVED = "archived"
    REPLACED = "replaced"


class ComplianceKind(StrEnum):
    NEW_LEGAL_POLICY = "new_legal_policy"
    REGULATED_ACTIVITY = "regulated_activity"
    ACTIVATION = "activation"


class BreachKind(StrEnum):
    SECURITY = "security"
    FINANCIAL = "financial"


class _Event(Contract):
    event_id: UUID
    at: Timestamp


class ProposalCreated(_Event):
    type: Literal["proposal_created"] = "proposal_created"
    request: ApprovalRequest
    kind: ProposalKind
    payload: dict[str, JsonValue]


class DecisionRecorded(_Event):
    type: Literal["decision_recorded"] = "decision_recorded"
    decision: ApprovalDecision


class ProposalExecuted(_Event):
    type: Literal["proposal_executed"] = "proposal_executed"
    approval_id: UUID


class ApprovalConsumed(_Event):
    """An external approval used once, by the component that carried out the action."""

    type: Literal["approval_consumed"] = "approval_consumed"
    approval_id: UUID
    by: Component


class ControlApplied(_Event):
    type: Literal["control_applied"] = "control_applied"
    command: ControlCommand


class BreachDeclared(_Event):
    type: Literal["breach_declared"] = "breach_declared"
    breach_id: UUID
    kind: BreachKind
    scope: ControlScope
    receptor_id: ReceptorId | None = None
    declared_by: Component
    detail: str = ""


class RecoveryAttempted(_Event):
    type: Literal["recovery_attempted"] = "recovery_attempted"
    incident_id: UUID
    receptor_id: ReceptorId | None = None
    attempt: int
    succeeded: bool
    detail: str = ""


class RecoveryEscalated(_Event):
    type: Literal["recovery_escalated"] = "recovery_escalated"
    incident_id: UUID
    attempts_used: int


class ParameterSet(_Event):
    type: Literal["parameter_set"] = "parameter_set"
    name: str
    value: JsonValue
    approval_id: UUID


class LimitsRecommended(_Event):
    """A recommendation only. It changes nothing until the Founder approves limits (AMD-11)."""

    type: Literal["limits_recommended"] = "limits_recommended"
    limits: ReceptorLimits
    by: Component
    rationale: NonEmptyStr


class LimitsSet(_Event):
    type: Literal["limits_set"] = "limits_set"
    limits: ReceptorLimits
    approval_id: UUID


class IntegrationRecorded(_Event):
    type: Literal["integration_recorded"] = "integration_recorded"
    record: IntegrationRecord


class ReceptorRegistered(_Event):
    type: Literal["receptor_registered"] = "receptor_registered"
    manifest: ReceptorManifest


class ReceptorStatusChanged(_Event):
    type: Literal["receptor_status_changed"] = "receptor_status_changed"
    receptor_id: ReceptorId
    status: ReceptorStatus
    approval_id: UUID
    replacement_id: ReceptorId | None = None
    acceptance_evidence_ids: tuple[UUID, ...] = ()


class ComplianceItemRecorded(_Event):
    type: Literal["compliance_item_recorded"] = "compliance_item_recorded"
    item_id: UUID
    receptor_id: ReceptorId
    kind: ComplianceKind
    description: NonEmptyStr
    requires_legal_review: bool


class LegalReviewRecorded(_Event):
    """Professional or legal review by a person, never an AI guess (AMD-9)."""

    type: Literal["legal_review_recorded"] = "legal_review_recorded"
    item_id: UUID
    reviewer: Literal[Component.HUMAN_REVIEWER, Component.FOUNDER]
    review_ref: NonEmptyStr


GovernanceEvent = Annotated[
    ProposalCreated
    | DecisionRecorded
    | ProposalExecuted
    | ApprovalConsumed
    | ControlApplied
    | BreachDeclared
    | RecoveryAttempted
    | RecoveryEscalated
    | ParameterSet
    | LimitsRecommended
    | LimitsSet
    | IntegrationRecorded
    | ReceptorRegistered
    | ReceptorStatusChanged
    | ComplianceItemRecorded
    | LegalReviewRecorded,
    Field(discriminator="type"),
]
EVENT_ADAPTER: TypeAdapter[GovernanceEvent] = TypeAdapter(GovernanceEvent)
