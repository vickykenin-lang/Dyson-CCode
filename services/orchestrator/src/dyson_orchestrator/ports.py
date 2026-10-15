"""What D needs from other components. Step 9 connects these to G, A, F and I.

D has no path to a tool except ToolHubPort (LA-ORC-05): it holds no adapters and no credentials
for any tool.
"""

from typing import Any, Protocol
from uuid import UUID

from pydantic import JsonValue

from dyson_contracts.approvals import ApprovalCategory
from dyson_contracts.common import Contract, Money, NonEmptyStr, ReceptorId, RiskLevel
from dyson_contracts.control import ControlMode
from dyson_contracts.lanes import VerificationVerdict
from dyson_contracts.tasks import TaskTransition
from dyson_contracts.toolcalls import ToolCallRequest


class TaskPlan(Contract):
    """The single governed action a task performs, prepared by the Conversation Engine (B)."""

    tool_id: NonEmptyStr
    arguments: dict[str, JsonValue] = {}
    receptor_id: ReceptorId | None = None
    risk: RiskLevel = RiskLevel.LOW
    estimated_spend: Money | None = None
    standard_id: NonEmptyStr  # the QA/QC standard F verifies the output against
    summary: NonEmptyStr  # what the Founder sees if an approval is needed


class ToolRun(Contract):
    """What G answered. "executed" means the tool ran, never that the task is complete."""

    status: str  # executed | failed | denied | duplicate
    result: JsonValue = None
    error: str = ""
    denied_checks: tuple[str, ...] = ()


class ToolHubPort(Protocol):
    def call(self, request: ToolCallRequest) -> ToolRun:
        """Raises on a network failure: the outcome is then unknown and the same request,
        with the same idempotency key, is sent again later."""
        ...


class GovernancePort(Protocol):
    def effective_mode(self, receptor_id: str | None) -> ControlMode: ...

    def propose_external_action(
        self, payload: dict[str, Any], category: ApprovalCategory, summary: str, task_id: UUID
    ) -> UUID:
        """Create an approval request for exactly this action; returns its approval_id."""
        ...

    def approval_status(self, approval_id: UUID) -> str:
        """open | approved | rejected | consumed | executed"""
        ...


class QAPort(Protocol):
    def verify(self, task_id: UUID, plan: TaskPlan, run: ToolRun) -> VerificationVerdict:
        """Independent verification by F. Raises if F cannot be reached."""
        ...


class EscalationPort(Protocol):
    def escalate(self, task_id: UUID, reason: str) -> None:
        """Notify the human reviewer / Founder."""
        ...


class TaskEventSink(Protocol):
    def record(self, transition: TaskTransition) -> None:
        """Forward task state to the Memory & Evidence Layer (wired in Step 9, LA-ORC-07)."""
        ...
