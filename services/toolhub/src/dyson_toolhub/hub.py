"""ToolHub: authorizes every individual tool call, then runs it (LA-TOOL-01..04, 06, 07).

Six checks run on every call, all of them, every time:
  identity & permission, Receptor scope, risk & spend limits, approval status, STOP state, registry.
Any check that cannot be answered fails. A call runs only when all six pass; every decision,
allowed or denied, is recorded and audited.
"""

from collections.abc import Callable
from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID, uuid4

from pydantic import JsonValue

from dyson_contracts.approvals import ApprovalCategory
from dyson_contracts.audit import AuditEvent, AuditKind
from dyson_contracts.common import Component, Contract, Money, RiskLevel
from dyson_contracts.control import ControlMode
from dyson_contracts.integrations import IntegrationStatus
from dyson_contracts.toolcalls import CheckName, CheckResult, ToolCallDecision, ToolCallRequest

from .catalog import Catalog, ToolScope, ToolSpec
from .ports import (
    CallerAuthenticator,
    GovernancePort,
    action_digest,
    revive_digest,
    spends_money,
)
from .store import Execution, Outcome, Switch, ToolStore

RISK_ORDER = [RiskLevel.LOW, RiskLevel.MEDIUM, RiskLevel.HIGH]


class ToolResult(Contract):
    """What the caller gets back. "executed" means the tool ran; it is not task completion:
    only the QA/QC Controller's verification completes a task (LA-CONV-07, LA-EVD-02)."""

    call_id: UUID
    decision: ToolCallDecision
    status: str  # denied | executed | failed | duplicate
    result: JsonValue = None
    error: str = ""


class ToolHub:
    def __init__(
        self,
        catalog: Catalog,
        governance: GovernancePort,
        callers: CallerAuthenticator,
        store: ToolStore,
        audit_sink: Callable[[AuditEvent], None] | None = None,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ):
        self._catalog = catalog
        self._gov = governance
        self._callers = callers
        self._store = store
        self._audit_sink = audit_sink
        self._clock = clock
        self.audit_backlog: list[AuditEvent] = []

    # The one entry point to every tool ---------------------------------------------------
    def call(self, request: ToolCallRequest, credential: str) -> ToolResult:
        caller = self._callers.authenticate(credential)
        now = self._clock()
        with self._store.transaction() as tx:
            prior = tx.execution(request.idempotency_key)
            checks = self._checks(request, caller, tx, now, prior is not None)
            decision = ToolCallDecision(
                call_id=request.call_id,
                allowed=all(c.passed for c in checks),
                checks=checks,
                decided_by=Component.TOOL_HUB,
                decided_at=now,
            )
            tx.record_decision(
                request.call_id,
                request.idempotency_key,
                caller.value if caller else None,
                decision.allowed,
                decision.model_dump(mode="json"),
                request.model_dump(mode="json"),
                now,
            )
            if decision.allowed and prior is None:
                spend = request.estimated_spend
                tx.claim(
                    Execution(
                        idempotency_key=request.idempotency_key,
                        call_id=request.call_id,
                        receptor_id=request.receptor_id,
                        tool_id=request.tool_id,
                        amount=spend.amount if spend else Decimal("0"),
                        currency=spend.currency if spend else None,
                        claimed_at=now,
                    )
                )
        self._audit(decision, request, caller)
        if not decision.allowed:
            return ToolResult(call_id=request.call_id, decision=decision, status="denied")
        if prior is not None:  # a retry: never run the action twice (idempotency key)
            out = self._store.outcome(request.idempotency_key)
            return ToolResult(
                call_id=request.call_id,
                decision=decision,
                status="duplicate",
                result=out.result if out else None,
                error="" if out else "first attempt still running",
            )
        return self._execute(request, decision)

    def _execute(self, request: ToolCallRequest, decision: ToolCallDecision) -> ToolResult:
        _spec, adapter = self._catalog.get(request.tool_id)
        needed, category = self._needs_approval(request)
        try:
            if needed:  # use the approval exactly once, before acting
                self._gov.consume_approval(
                    request.approval_id, action_digest(request), category, Component.TOOL_HUB
                )
            result = adapter(dict(request.arguments))
            outcome = Outcome("executed", result, "")
        except Exception as exc:  # record the failure; never pretend success
            outcome = Outcome("failed", None, f"{type(exc).__name__}: {exc}")
        self._store.record_outcome(request.idempotency_key, outcome, self._clock())
        return ToolResult(
            call_id=request.call_id,
            decision=decision,
            status=outcome.status,
            result=outcome.result,
            error=outcome.error,
        )

    # The six checks ----------------------------------------------------------------------
    def _checks(
        self, req: ToolCallRequest, caller, tx, now, is_retry: bool
    ) -> tuple[CheckResult, ...]:
        entry = self._catalog.get(req.tool_id)
        spec = entry[0] if entry else None
        out = []
        for name, fn in (
            (CheckName.IDENTITY_PERMISSION, lambda: self._identity(req, caller, spec)),
            (CheckName.RECEPTOR_SCOPE, lambda: self._scope(req, spec)),
            (CheckName.RISK_SPEND_LIMITS, lambda: self._risk_spend(req, spec, tx, now, is_retry)),
            (CheckName.APPROVAL_STATUS, lambda: self._approval(req, spec, is_retry)),
            (CheckName.STOP_STATE, lambda: self._stop(req)),
            (CheckName.REGISTRY, lambda: self._registry(req, spec, tx)),
        ):
            try:
                passed, detail = fn()
            except Exception as exc:  # cannot answer => deny (fail closed)
                passed, detail = False, f"check unavailable: {type(exc).__name__}"
            out.append(CheckResult(check=name, passed=passed, detail=detail))
        return tuple(out)

    def _identity(self, req, caller, spec: ToolSpec | None):
        if caller is None:
            return False, "caller not authenticated"
        if caller is not req.requested_by:
            return False, f"credential is {caller}, request claims {req.requested_by}"
        if spec is None or caller not in spec.allowed_callers:
            return False, f"{caller} may not call {req.tool_id}"
        return True, f"authenticated as {caller}"

    def _scope(self, req, spec: ToolSpec | None):
        if spec is None:
            return False, "unknown tool"
        if spec.scope is ToolScope.CORE:
            return (
                req.receptor_id is None,
                "core tool" if req.receptor_id is None else "core tool takes no Receptor",
            )
        if req.receptor_id is None:
            return False, "this tool acts for a Receptor; receptor_id is required"
        if spec.scope is ToolScope.RECEPTOR_SUPPORT:
            if req.receptor_id == spec.target_receptor:
                return False, "a Receptor cannot request support from itself"
            op = req.arguments.get("operation")
            if op not in spec.allowed_operations:
                return False, f"operation {op!r} is outside the support scope"
        if not self._gov.receptor_permits(req.receptor_id, req.tool_id):
            return False, f"{req.tool_id} is not in {req.receptor_id}'s Founder-set permissions"
        return True, f"within {req.receptor_id}'s permissions"

    def _effective_risk(self, req, spec: ToolSpec | None) -> RiskLevel:
        floor = spec.min_risk if spec else RiskLevel.HIGH
        return max(req.risk, floor, key=RISK_ORDER.index)

    def _risk_spend(self, req, spec, tx, now, is_retry: bool):
        risk = self._effective_risk(req, spec)
        if not spends_money(req):
            return True, f"risk {risk}, no spend"
        if req.receptor_id is None:
            return False, "spending needs a Receptor budget"
        if is_retry:
            return True, "already counted against the budget"
        spend = req.estimated_spend
        start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        end = (start.replace(year=start.year + 1, month=1) if start.month == 12
               else start.replace(month=start.month + 1))  # fmt: skip
        used = tx.month_spend(req.receptor_id, spend.currency, start, end)
        ok, reason = self._gov.spend_allowed(
            req.receptor_id, req.tool_id, spend, Money(amount=used, currency=spend.currency)
        )
        return ok, f"risk {risk}; {reason}"

    def _needs_approval(self, req) -> tuple[bool, ApprovalCategory | None]:
        if spends_money(req):
            return True, ApprovalCategory.FINANCIAL  # AMD-2: every money-out action
        spec = self._catalog.get(req.tool_id)
        if self._effective_risk(req, spec[0] if spec else None) is RiskLevel.HIGH:
            return True, ApprovalCategory.OTHER
        return False, None

    def _approval(self, req, spec, is_retry: bool):
        needed, category = self._needs_approval(req)
        if not needed:
            return True, "no approval required"
        if is_retry:
            return True, "approval was used by the first attempt"
        if req.approval_id is None:
            return False, f"{category} approval required"
        if not self._gov.check_approval(req.approval_id, action_digest(req), category):
            return False, "no approved, unused approval for this exact action"
        return True, f"{category} approval matches this exact action"

    def _stop(self, req):
        mode = self._gov.effective_mode(req.receptor_id)
        return mode is ControlMode.RUNNING, f"control state {mode}"

    def _registry(self, req, spec: ToolSpec | None, tx):
        if spec is None:
            return False, "not in G's catalog"
        killed = self._killed(tx.switches())
        if ("tool", req.tool_id) in killed:
            return False, "tool kill switch is on"
        if ("connector", spec.connector_id) in killed:
            return False, f"connector {spec.connector_id} kill switch is on"
        rec = self._gov.registry().get(req.tool_id)
        if rec is None or rec.status is not IntegrationStatus.ADMITTED:
            return False, "not admitted through the Supply Chain / Integration Gate"
        return True, f"admitted {rec.name} {rec.version}"

    # Kill switches (LA-TOOL-06) ----------------------------------------------------------
    @staticmethod
    def _killed(switches: list[Switch]) -> set[tuple[str, str]]:
        state: dict[tuple[str, str], bool] = {}
        for s in switches:
            state[(s.target_kind, s.target_id)] = s.killed
        return {k for k, v in state.items() if v}

    def kill(self, target_kind: str, target_id: str, reason: str) -> None:
        """Immediate. Making things safer never waits for approval."""
        if target_kind not in ("tool", "connector"):
            raise ValueError("kill a tool or a connector")
        with self._store.transaction() as tx:
            tx.record_switch(Switch(target_kind, target_id, True, reason, None, self._clock()))
        self._emit(AuditKind.CONFIG_CHANGE, f"kill switch on: {target_kind} {target_id}", None,
                   {"reason": reason})  # fmt: skip

    def revive(self, target_kind: str, target_id: str, approval_id: UUID) -> None:
        """Turning a kill switch off needs a Founder approval naming exactly this revival."""
        digest = revive_digest(target_kind, target_id)
        if not self._gov.check_approval(approval_id, digest, ApprovalCategory.INTEGRATION):
            raise PermissionError("no approval for this revival")
        self._gov.consume_approval(
            approval_id, digest, ApprovalCategory.INTEGRATION, Component.TOOL_HUB
        )
        with self._store.transaction() as tx:
            tx.record_switch(
                Switch(target_kind, target_id, False, "revived", approval_id, self._clock())
            )
        self._emit(AuditKind.CONFIG_CHANGE, f"kill switch off: {target_kind} {target_id}", None,
                   {"approval_id": str(approval_id)})  # fmt: skip

    # Audit (LA-TOOL-04) ------------------------------------------------------------------
    def _audit(self, decision: ToolCallDecision, req: ToolCallRequest, caller) -> None:
        kind = AuditKind.TOOL_CALL if decision.allowed else AuditKind.TOOL_CALL_DENIED
        failed = [c.check.value for c in decision.checks if not c.passed]
        summary = f"{'allowed' if decision.allowed else 'denied'} {req.tool_id}"
        if failed:
            summary += f" (failed: {', '.join(failed)})"
        self._emit(kind, summary, req.task_id,
                   {"call_id": str(req.call_id), "caller": caller.value if caller else None,
                    "decision": decision.model_dump(mode="json")})  # fmt: skip

    def _emit(self, kind, summary, task_id, data) -> None:
        event = AuditEvent(
            event_id=uuid4(), kind=kind, actor=Component.TOOL_HUB, at=self._clock(),
            summary=summary, task_id=task_id, data=data,
        )  # fmt: skip
        try:
            if self._audit_sink is None:
                raise RuntimeError("no audit sink")
            self._audit_sink(event)
        except Exception:
            self.audit_backlog.append(event)  # G's own decision log stays the durable record
