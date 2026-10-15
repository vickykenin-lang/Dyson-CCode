"""Tool calls through the Governed Tool Hub (G). "Model proposes; gateway enforces."""

from enum import StrEnum
from typing import Literal
from uuid import UUID

from pydantic import JsonValue, model_validator

from .common import (
    Component,
    Contract,
    IdempotencyKey,
    Money,
    NonEmptyStr,
    ReceptorId,
    RiskLevel,
    Timestamp,
)


class ToolCallRequest(Contract):
    call_id: UUID
    task_id: UUID
    idempotency_key: IdempotencyKey
    tool_id: NonEmptyStr
    # Only the Orchestrator and Hermes call tools, and only through G (LA-ORC-05, LA-HER-03).
    requested_by: Literal[Component.ORCHESTRATOR, Component.HERMES]
    receptor_id: ReceptorId | None = None
    arguments: dict[str, JsonValue] = {}
    risk: RiskLevel
    estimated_spend: Money | None = None
    approval_id: UUID | None = None
    requested_at: Timestamp


class CheckName(StrEnum):
    """The per-call checks drawn on card G, plus the registry check (LA-TOOL-01, LA-TOOL-03)."""

    IDENTITY_PERMISSION = "identity_permission"
    RECEPTOR_SCOPE = "receptor_scope"
    RISK_SPEND_LIMITS = "risk_spend_limits"
    APPROVAL_STATUS = "approval_status"
    STOP_STATE = "stop_state"
    REGISTRY = "registry"


class CheckResult(Contract):
    check: CheckName
    passed: bool
    detail: str = ""


class ToolCallDecision(Contract):
    call_id: UUID
    allowed: bool
    checks: tuple[CheckResult, ...]
    decided_by: Literal[Component.TOOL_HUB]
    decided_at: Timestamp

    @model_validator(mode="after")
    def _checks(self) -> "ToolCallDecision":
        names = [c.check for c in self.checks]
        if sorted(names) != sorted(CheckName):
            raise ValueError("every check must appear exactly once")
        if self.allowed != all(c.passed for c in self.checks):
            raise ValueError("a call is allowed only when every check passed")
        return self
