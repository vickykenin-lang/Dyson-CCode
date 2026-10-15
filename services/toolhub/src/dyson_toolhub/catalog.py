"""G's own catalog: which tools exist, who may call them, in what scope, and their adapters.

A tool is callable only when it is in this catalog AND admitted in A's integration registry AND
neither it nor its connector is killed (LA-TOOL-03, LA-TOOL-06).
"""

from collections.abc import Callable
from enum import StrEnum
from typing import Any

from pydantic import JsonValue

from dyson_contracts.common import Component, Contract, NonEmptyStr, ReceptorId, RiskLevel


class ToolScope(StrEnum):
    CORE = "core"  # Layer A internal tools; no Receptor
    RECEPTOR = "receptor"  # acts for one Receptor, inside that Receptor's permissions
    RECEPTOR_SUPPORT = "receptor_support"  # one Receptor helping another (AMD-6, LA-IF-08)


class ToolSpec(Contract):
    tool_id: NonEmptyStr  # also the integration_id in A's registry
    connector_id: NonEmptyStr
    allowed_callers: frozenset[Component]
    scope: ToolScope
    target_receptor: ReceptorId | None = None  # only for RECEPTOR_SUPPORT
    allowed_operations: frozenset[str] = frozenset()  # limits RECEPTOR_SUPPORT to named operations
    min_risk: RiskLevel = RiskLevel.LOW  # callers cannot declare a tool safer than this


# An adapter performs the real action. Only G holds adapters (LA-TOOL-02).
Adapter = Callable[[dict[str, JsonValue]], Any]


class Catalog:
    def __init__(self) -> None:
        self._tools: dict[str, tuple[ToolSpec, Adapter]] = {}

    def register(self, spec: ToolSpec, adapter: Adapter) -> None:
        if spec.scope is ToolScope.RECEPTOR_SUPPORT and not (
            spec.target_receptor and spec.allowed_operations
        ):
            raise ValueError("receptor support needs a target Receptor and named operations")
        if not spec.allowed_callers <= {Component.ORCHESTRATOR, Component.HERMES}:
            raise ValueError("only the Orchestrator and Hermes call tools")
        self._tools[spec.tool_id] = (spec, adapter)

    def get(self, tool_id: str) -> tuple[ToolSpec, Adapter] | None:
        return self._tools.get(tool_id)

    def specs(self) -> list[ToolSpec]:
        return [s for s, _ in self._tools.values()]
