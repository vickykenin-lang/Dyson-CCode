"""Founder approvals (LA-GOV-02, LA-DFC-01..05)."""

from enum import StrEnum
from typing import Literal
from uuid import UUID

from pydantic import model_validator

from .common import Component, Contract, NonEmptyStr, Sha256Hex, Timestamp


class ApprovalCategory(StrEnum):
    FINANCIAL = "financial"
    RULE_CHANGE = "rule_change"
    RECEPTOR_LIMITS = "receptor_limits"
    RECEPTOR_LIFECYCLE = "receptor_lifecycle"
    INTEGRATION = "integration"
    REGULATED_ACTIVITY = "regulated_activity"
    DEPLOYMENT = "deployment"
    RESUME = "resume"
    OTHER = "other"


class ApprovalRequest(Contract):
    approval_id: UUID
    task_id: UUID | None = None
    category: ApprovalCategory
    action_summary: NonEmptyStr
    # sha256 of the exact action or diff shown to the Founder (LA-DFC-05).
    action_digest: Sha256Hex
    requested_by: Component
    created_at: Timestamp
    expires_at: Timestamp | None = None  # expiry semantics decided at gate 3

    @model_validator(mode="after")
    def _checks(self) -> "ApprovalRequest":
        if self.requested_by is Component.FOUNDER:
            raise ValueError("the Founder decides approvals; they do not request them")
        if self.expires_at is not None and self.expires_at <= self.created_at:
            raise ValueError("expires_at must be after created_at")
        return self


class ApprovalDecisionKind(StrEnum):
    APPROVE = "approve"
    REJECT = "reject"


class ApprovalDecision(Contract):
    """Only the Founder, on Direct Founder Controls, can produce a valid decision."""

    approval_id: UUID
    action_digest: Sha256Hex
    decision: ApprovalDecisionKind
    decided_by: Literal[Component.FOUNDER]
    channel: Literal[Component.DIRECT_FOUNDER_CONTROLS]
    auth_method: NonEmptyStr  # step-up method decided at gate 3
    decided_at: Timestamp

    def applies_to(self, request: ApprovalRequest) -> bool:
        """True when this decision binds to the exact action shown and was made before expiry."""
        if self.approval_id != request.approval_id or self.action_digest != request.action_digest:
            return False
        if self.decided_at < request.created_at:
            return False
        return request.expires_at is None or self.decided_at <= request.expires_at
