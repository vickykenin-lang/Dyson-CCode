"""A fake Governance Core (A) that checks channel proofs the way A does."""

import hashlib
import hmac
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from dyson_contracts.approvals import ApprovalCategory, ApprovalRequest
from dyson_contracts.common import Component
from dyson_contracts.control import ControlMode, ControlScope, ControlState
from dyson_founder_controls.ports import signing_bytes

NOW = datetime(2026, 10, 15, 12, 0, tzinfo=UTC)
CHANNEL_KEY = b"c" * 32
DEVICE_KEY = b"d" * 32


class Clock:
    def __init__(self):
        self.now = NOW

    def __call__(self):
        return self.now

    def advance(self, **kw):
        self.now += timedelta(**kw)


class FakeGovernance:
    def __init__(self):
        self.requests: dict = {}
        self.decisions = []
        self.commands = []
        self.modes: dict = {}

    def _verify(self, message, proof):
        expected = hmac.new(CHANNEL_KEY, signing_bytes(message), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected, proof):
            raise PermissionError("not on the Founder channel")

    def add(self, summary="Pay supplier 5,000 INR", digest="a" * 64):
        r = ApprovalRequest(
            approval_id=uuid4(),
            category=ApprovalCategory.FINANCIAL,
            action_summary=summary,
            action_digest=digest,
            requested_by=Component.ORCHESTRATOR,
            created_at=NOW,
        )
        self.requests[r.approval_id] = r
        return r

    def pending_approvals(self):
        return list(self.requests.values())

    def decide(self, decision, proof):
        self._verify(decision, proof)
        self.decisions.append(decision)
        del self.requests[decision.approval_id]
        return "approved" if decision.decision.value == "approve" else "rejected"

    def control(self, command, proof):
        self._verify(command, proof)
        self.commands.append(command)
        mode = ControlMode.STOPPED if command.command.value == "stop" else ControlMode.PAUSED
        key = (command.scope, command.receptor_id)
        self.modes[key] = mode
        return ControlState(
            scope=command.scope,
            receptor_id=command.receptor_id,
            mode=mode,
            last_command_id=command.command_id,
            since=command.issued_at,
        )

    def propose_resume(self, scope, receptor_id):
        what = "master" if scope is ControlScope.MASTER else receptor_id
        return self.add(summary=f"Resume {what}", digest="b" * 64)


class Audit(list):
    def record(self, event, detail):
        self.append((event, detail))
