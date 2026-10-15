"""The only component Direct Founder Controls reaches is the Governance Core (A)."""

import hashlib
import hmac
from typing import Protocol

from pydantic import BaseModel

from dyson_contracts.approvals import ApprovalDecision, ApprovalRequest
from dyson_contracts.control import ControlCommand, ControlScope, ControlState
from dyson_contracts.digests import signing_bytes


class GovernancePort(Protocol):
    def pending_approvals(self) -> list[ApprovalRequest]: ...

    def decide(self, decision: ApprovalDecision, proof: str) -> str: ...

    def control(self, command: ControlCommand, proof: str) -> ControlState: ...

    def propose_resume(self, scope: ControlScope, receptor_id: str | None) -> ApprovalRequest: ...


class AuditPort(Protocol):
    def record(self, event: str, detail: dict) -> None: ...


class HmacChannelSigner:
    """Proves to A that a decision or command came over this channel. Gate 3 may replace it
    with signed approvals; the key lives only in the secret store."""

    def __init__(self, key: bytes):
        if len(key) < 32:
            raise ValueError("channel key must be at least 32 bytes")
        self._key = key

    def sign(self, message: BaseModel) -> str:
        return hmac.new(self._key, signing_bytes(message), hashlib.sha256).hexdigest()
