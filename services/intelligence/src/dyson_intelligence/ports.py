"""Ports of the intelligence plane. Step 9 connects them to A, D and I.

Note what is absent: no port lets B or C approve anything, run a tool, read a secret, write
evidence or touch the STOP controls. Hermes has its own, narrower ports (hermes/runtime.py).
"""

from typing import Any, Protocol
from uuid import UUID

from dyson_contracts.approvals import ApprovalCategory
from dyson_contracts.common import Component
from dyson_contracts.integrations import IntegrationRecord
from dyson_contracts.interface import TaskStatusUpdate

from .models import ModelRequest, ModelResponse, RoutedResponse


class ModelAdapter(Protocol):
    """One external model provider. Adapters exist only inside C (LA-RTR-01)."""

    def complete(self, request: ModelRequest, model_id: str) -> ModelResponse: ...


class RouterPort(Protocol):
    """How B reaches a model: only through C."""

    def complete(
        self, caller: Component, task_class: str, request: ModelRequest
    ) -> RoutedResponse: ...


class GovernancePort(Protocol):
    """What the intelligence plane may ask of the Governance Core (A)."""

    def registry(self) -> dict[str, IntegrationRecord]: ...

    def check_approval(
        self, approval_id: UUID, action_digest: str, category: ApprovalCategory
    ) -> bool: ...

    def consume_approval(
        self, approval_id: UUID, action_digest: str, category: ApprovalCategory
    ) -> None: ...

    def propose_amendment(self, rule_id: str, diff: str, rationale: str) -> UUID:
        """B may propose; only the Founder approves (LA-CONV-05, LA-AMD-01)."""
        ...


class MemoryPort(Protocol):
    def thread_context(self, thread_id: UUID, limit: int) -> list[dict[str, str]]:
        """Recent messages of the thread as {"role", "content"}, oldest first."""
        ...

    def locked_rules(self) -> list[dict[str, str]]:
        """Authoritative register entries that are DESIGN LOCKED or APPROVED: id, version, title."""
        ...


class OrchestratorPort(Protocol):
    def submit(
        self, instruction_key: str, instruction: str, plan: dict[str, Any]
    ) -> TaskStatusUpdate:
        """Hand a prepared instruction to D. Submitting the same key twice runs it once."""
        ...

    def status(self, task_id: UUID) -> TaskStatusUpdate: ...


class ToolCatalogPort(Protocol):
    def tools(self) -> dict[str, dict[str, Any]]:
        """tool_id -> {"receptors": [...], "standard_id": ..., "description": ...}.

        Only tools G's registry currently admits are listed.
        """
        ...
