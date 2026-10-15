"""Shared constants for the Tool Hub tests."""

from datetime import UTC, datetime

from dyson_contracts.common import Component

NOW = datetime(2026, 10, 15, 12, 0, tzinfo=UTC)

TOKENS = {
    Component.ORCHESTRATOR: "orchestrator-" + "o" * 32,
    Component.HERMES: "hermes-" + "h" * 32,
    Component.GOVERNANCE_CORE: "governance-" + "g" * 32,
}
