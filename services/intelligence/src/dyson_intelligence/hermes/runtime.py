"""What Hermes can do, and nothing else.

- Think: through C only (LA-HER-02). C records every call with caller "hermes".
- Act: through G only, as Component.HERMES, so G's six checks apply (LA-HER-03).
- Load a skill, agent, subagent or plugin: only one A's supply-chain gate admitted (LA-HER-06).
- Report: a HermesOutput that is always unverified. F verifies it like any other output
  (LA-HER-08); there is no field or method by which Hermes marks its own work as verified.

Whether anything may rely on Hermes at all is decided outside it (gate.py, LA-HER-07).
"""

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any, Literal, Protocol
from uuid import UUID, uuid4

from pydantic import JsonValue

from dyson_contracts.common import (
    Component,
    Contract,
    NonEmptyStr,
    ReceptorId,
    RiskLevel,
    Timestamp,
)
from dyson_contracts.integrations import IntegrationKind, IntegrationRecord
from dyson_contracts.toolcalls import ToolCallRequest

from ..models import ModelRequest, RoutedResponse

SKILL_KINDS = frozenset({IntegrationKind.SKILL, IntegrationKind.PLUGIN, IntegrationKind.MCP_SERVER})


class RouterClient(Protocol):
    """The Hermes side of C's API. Hermes's identity is bound to its credential, not chosen."""

    def complete(self, task_class: str, request: ModelRequest) -> RoutedResponse: ...


class ToolHubClient(Protocol):
    """The Hermes side of G's API."""

    def call(self, request: ToolCallRequest) -> dict[str, Any]: ...


class RegistryView(Protocol):
    """Read-only view of A's integration registry."""

    def registry(self) -> dict[str, IntegrationRecord]: ...


class HermesError(Exception):
    pass


class HermesOutput(Contract):
    """Hermes's result. Always unverified: only F's verdict can make it count (LA-HER-08)."""

    task_id: UUID
    output: JsonValue
    produced_by: Literal[Component.HERMES] = Component.HERMES
    verified: Literal[False] = False
    produced_at: Timestamp


class HermesRuntime:
    def __init__(
        self,
        router: RouterClient,
        toolhub: ToolHubClient,
        registry: RegistryView,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ):
        self._router = router
        self._toolhub = toolhub
        self._registry = registry
        self._clock = clock
        self._skills: dict[str, IntegrationRecord] = {}

    def think(self, task_class: str, request: ModelRequest) -> RoutedResponse:
        return self._router.complete(task_class, request)

    def call_tool(
        self,
        task_id: UUID,
        tool_id: str,
        arguments: dict[str, JsonValue],
        idempotency_key: str,
        risk: RiskLevel = RiskLevel.LOW,
        receptor_id: ReceptorId | None = None,
    ) -> dict[str, Any]:
        request = ToolCallRequest(
            call_id=uuid4(),
            task_id=task_id,
            idempotency_key=idempotency_key,
            tool_id=tool_id,
            requested_by=Component.HERMES,
            receptor_id=receptor_id,
            arguments=arguments,
            risk=risk,
            requested_at=self._clock(),
        )
        return self._toolhub.call(request)

    def load_skill(self, integration_id: NonEmptyStr) -> IntegrationRecord:
        record = self._registry.registry().get(integration_id)
        if record is None or record.kind not in SKILL_KINDS or not record.callable:
            raise HermesError(
                f"{integration_id} has not been admitted through the integration gate"
            )
        self._skills[integration_id] = record
        return record

    def skills(self) -> list[str]:
        """Loaded skills that are still admitted; a revoked one is dropped at once."""
        current = self._registry.registry()
        self._skills = {
            k: v for k, v in self._skills.items() if k in current and current[k].callable
        }
        return sorted(self._skills)

    def report(self, task_id: UUID, output: JsonValue) -> HermesOutput:
        return HermesOutput(task_id=task_id, output=output, produced_at=self._clock())
