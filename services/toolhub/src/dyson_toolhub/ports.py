"""What G needs from outside itself. Step 9 connects these to the real Governance Core (A).

Every port call that fails or raises makes the check fail: G fails closed.
"""

import hashlib
import json
from decimal import Decimal
from typing import Any, Protocol

from dyson_contracts.approvals import ApprovalCategory
from dyson_contracts.common import Component, Money
from dyson_contracts.control import ControlMode
from dyson_contracts.integrations import IntegrationRecord
from dyson_contracts.toolcalls import ToolCallRequest


class GovernancePort(Protocol):
    def effective_mode(self, receptor_id: str | None) -> ControlMode: ...

    def registry(self) -> dict[str, IntegrationRecord]: ...

    def receptor_permits(self, receptor_id: str, tool_id: str) -> bool: ...

    def spend_allowed(
        self, receptor_id: str, tool_id: str, amount: Money, month_to_date: Money
    ) -> tuple[bool, str]: ...

    def check_approval(
        self, approval_id, action_digest: str, category: ApprovalCategory
    ) -> bool: ...

    def consume_approval(
        self, approval_id, action_digest: str, category: ApprovalCategory, by: Component
    ) -> None: ...


class CallerAuthenticator(Protocol):
    """Maps a presented credential to the component it proves. Step 9 binds real identities."""

    def authenticate(self, credential: str) -> Component | None: ...


class StaticTokens:
    """Development authenticator: one secret token per component, from the secret store."""

    def __init__(self, tokens: dict[Component, str]):
        if any(len(t) < 32 for t in tokens.values()):
            raise ValueError("tokens must be at least 32 characters")
        self._by_digest = {hashlib.sha256(t.encode()).hexdigest(): c for c, t in tokens.items()}

    def authenticate(self, credential: str) -> Component | None:
        return self._by_digest.get(hashlib.sha256((credential or "").encode()).hexdigest())


def action_payload(request: ToolCallRequest) -> dict[str, Any]:
    """The exact action a Founder approval must name: tool, scope, arguments and spend."""
    spend = request.estimated_spend
    return {
        "tool_id": request.tool_id,
        "receptor_id": request.receptor_id,
        "arguments": request.arguments,
        "amount": str(spend.amount) if spend else "0",
        "currency": spend.currency if spend else None,
    }


def external_action_digest(payload: dict[str, Any]) -> str:
    """Same canonical form as the Governance Core's external-action digest (checked in Step 9)."""
    value = {"kind": "external_action", "payload": payload}
    blob = json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def action_digest(request: ToolCallRequest) -> str:
    return external_action_digest(action_payload(request))


def revive_digest(target_kind: str, target_id: str) -> str:
    return external_action_digest({"revive": target_kind, "target_id": target_id})


def spends_money(request: ToolCallRequest) -> bool:
    return request.estimated_spend is not None and request.estimated_spend.amount > Decimal("0")
