"""Ports of the intelligence plane. Step 9 connects them to A, D and I.

Note what is absent: no port lets B or C approve anything, run a tool, read a secret, write
evidence or touch the STOP controls. Hermes has its own, narrower ports (hermes/runtime.py).
"""

from collections.abc import Sequence
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


class GroundingHit(Protocol):
    """One chunk retrieved from the Founder's second brain, enough for B to answer and cite it."""

    path: str
    text: str
    similarity: float  # best vector cosine (0..1); B grounds only above a relevance threshold


class KnowledgePort(Protocol):
    """B's read-only window into the Founder's knowledge index (the second brain). Optional: when
    it is absent or unreachable, B simply answers without grounding."""

    def search(self, query: str) -> Sequence[GroundingHit]: ...


class TriageSignal(Protocol):
    """A decision model's read of one Founder message: what kind of request it is, how hard it is,
    and how safe it looks. All advisory — B uses them to calibrate its reply, never to bypass a
    rule or the approval the Founder must give."""

    category: str  # coding | general | analysis | creative
    complexity: str  # trivial | easy | moderate | hard | expert
    is_safe: float  # 0..1; low means the request looks risky and B should confirm first
    assessment: float  # 0..1; the decision model's own overall score for the request


class TriagePort(Protocol):
    """A decision model (Jev) that classifies a request before B interprets it. Optional: when it
    is absent or unreachable, B interprets without a triage hint and nothing changes."""

    def triage(self, text: str) -> "TriageSignal | None": ...
