"""GovernanceCore: policy and control authority (card A).

Every consequential change follows one path:
  1. a component proposes it (ProposalCreated, with a digest of the exact payload);
  2. the Founder decides on the independently authenticated channel (DecisionRecorded);
  3. A executes it (internal kinds) or another component consumes it once (external kinds).
STOP and PAUSE skip the queue: they apply immediately and need no model, no approval and no
network beyond the database.
"""

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from uuid import UUID, uuid4

import yaml
from pydantic import JsonValue

from dyson_contracts.approvals import ApprovalDecision, ApprovalDecisionKind, ApprovalRequest
from dyson_contracts.audit import AuditEvent, AuditKind
from dyson_contracts.common import Component, Money, RiskLevel
from dyson_contracts.control import (
    ControlCommand,
    ControlCommandType,
    ControlMode,
    ControlScope,
    ControlState,
)
from dyson_contracts.integrations import IntegrationKind, IntegrationRecord, IntegrationStatus
from dyson_contracts.receptor import ReceptorManifest

from .channel import ChannelVerifier
from .events import (
    EXTERNAL_KINDS,
    KIND_CATEGORY,
    ApprovalConsumed,
    BreachDeclared,
    BreachKind,
    ComplianceItemRecorded,
    ComplianceKind,
    ControlApplied,
    DecisionRecorded,
    GovernanceEvent,
    IntegrationRecorded,
    LegalReviewRecorded,
    LimitsRecommended,
    LimitsSet,
    ParameterSet,
    ProposalCreated,
    ProposalExecuted,
    ProposalKind,
    ReceptorLimits,
    ReceptorRegistered,
    ReceptorStatus,
    ReceptorStatusChanged,
    RecoveryAttempted,
    RecoveryEscalated,
    canonical_digest,
)
from .policy import PolicyEngine
from .state import GovernanceState, ProposalStatus
from .store import EventStore


# Operational parameters (AMD-02): set by Founder approval, validated here, never an AMD control.
# No code defaults: initial values come from policy/parameters.yaml, each citing a Founder
# decision; with neither that nor an approved change, a limit is 0 ("no automatic attempts").
def _int_at_least(n: int) -> Callable[[JsonValue], bool]:
    return lambda v: isinstance(v, int) and not isinstance(v, bool) and v >= n


PARAMETERS: dict[str, Callable[[JsonValue], bool]] = {
    "recovery_attempt_limit": _int_at_least(0),
    "repeated_failure_threshold": _int_at_least(1),  # read by E (Step 9)
    "founder_reminder_interval_minutes": _int_at_least(1),  # read by E (Step 9)
    "stale_after_hours": _int_at_least(1),  # read by E (Step 9)
    "approval_expiry_hours": _int_at_least(1),  # D-014: unanswered approvals expire
}


def load_initial_parameters(policy_dir: Path) -> dict[str, JsonValue]:
    """Initial values from policy/parameters.yaml. Each must cite a recorded Founder decision."""
    params = yaml.safe_load((policy_dir / "parameters.yaml").read_text("utf-8"))["parameters"]
    decisions = yaml.safe_load((policy_dir / "decisions.yaml").read_text("utf-8"))["decisions"]
    known = {d["id"] for d in decisions}
    out: dict[str, JsonValue] = {}
    for p in params:
        name, value = p["name"], p["value"]
        if name not in PARAMETERS or not PARAMETERS[name](value):
            raise ValueError(f"invalid operational parameter {name}={value!r}")
        if p.get("decision") not in known:
            raise ValueError(f"{name} does not cite a recorded Founder decision")
        out[name] = value
    return out


AuditSink = Callable[[AuditEvent], None]
ControlListener = Callable[[ControlCommand | None, ControlState], None]


class GovernanceError(Exception):
    """A request A refuses. Nothing is recorded when this is raised."""


class GateClosed(GovernanceError):
    """A capability blocked by a Founder implementation gate."""


class GovernanceCore:
    def __init__(
        self,
        store: EventStore,
        policy: PolicyEngine,
        founder_channel: ChannelVerifier,
        audit_sink: AuditSink | None = None,
        control_listeners: list[ControlListener] | None = None,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
        initial_parameters: dict[str, JsonValue] | None = None,
    ):
        self._initial_parameters = dict(initial_parameters or {})
        self._store = store
        self.policy = policy
        self._channel = founder_channel
        self._audit_sink = audit_sink
        self._listeners = list(control_listeners or [])
        self._clock = clock
        self._state = GovernanceState()
        self._seq = 0
        self.audit_backlog: list[AuditEvent] = []  # forwarded later from the event log (Step 9)
        # Controls committed by another process (Direct Founder Controls runs separately on
        # AWS, LA-DEP-02) reach this process's listeners when it catches up. History read at
        # start is state only: it was dispatched when it happened.
        self._foreign: list[ControlApplied | BreachDeclared] = []
        self._replaying = True
        self.sync()
        self._replaying = False

    # Plumbing ---------------------------------------------------------------------------
    def sync(self) -> GovernanceState:
        with self._store.transaction() as tx:
            self._catch_up(tx)
        self._dispatch_foreign()
        return self._state

    def _catch_up(self, tx) -> None:
        for seq, event in tx.read_since(self._seq):
            self._state.apply(event)
            self._seq = seq
            if not self._replaying and isinstance(event, ControlApplied | BreachDeclared):
                self._foreign.append(event)

    def _dispatch_foreign(self) -> None:
        pending, self._foreign = self._foreign, []
        for e in pending:
            self._dispatch_control(e)

    def _commit(self, build: Callable[[GovernanceState], list[GovernanceEvent]]):
        """Validate against current state under the store lock, then append and apply."""
        with self._store.transaction() as tx:
            self._catch_up(tx)
            events = build(self._state)
            if events:
                self._seq = tx.append(events)
                for e in events:
                    self._state.apply(e)
        self._dispatch_foreign()
        for e in events:
            self._emit_audit(e)
            if isinstance(e, ControlApplied | BreachDeclared):
                self._dispatch_control(e)
        return events

    def _new(self, cls, **fields):
        return cls(event_id=uuid4(), at=self._clock(), **fields)

    def _emit_audit(self, e: GovernanceEvent) -> None:
        kind = {
            "control_applied": AuditKind.CONTROL_EVENT,
            "breach_declared": AuditKind.CONTROL_EVENT,
            "decision_recorded": AuditKind.APPROVAL,
            "proposal_created": AuditKind.APPROVAL,
            "approval_consumed": AuditKind.CONSEQUENTIAL_ACTION,
            "proposal_executed": AuditKind.CONFIG_CHANGE,
        }.get(e.type, AuditKind.POLICY_DECISION)
        actor = Component.FOUNDER if e.type == "decision_recorded" else Component.GOVERNANCE_CORE
        event = AuditEvent(
            event_id=uuid4(),
            kind=kind,
            actor=actor,
            at=e.at,
            summary=f"governance: {e.type}",
            ref_id=e.event_id,
            data=e.model_dump(mode="json"),
        )
        try:
            if self._audit_sink is None:
                raise RuntimeError("no audit sink")
            self._audit_sink(event)
        except Exception:
            self.audit_backlog.append(event)

    def _dispatch_control(self, e: ControlApplied | BreachDeclared) -> list[Exception]:
        """Push the new state to G, Hermes and every Receptor lane. State is already committed,
        and G reads it on every call, so a listener failure cannot leave work running."""
        cmd = e.command if isinstance(e, ControlApplied) else None
        scope = e.command.scope if cmd else e.scope
        rid = e.command.receptor_id if cmd else e.receptor_id
        state = self._state.control_for(scope, rid, e.at)
        errors = []
        for listener in self._listeners:
            try:
                listener(cmd, state)
            except Exception as exc:  # recorded, never blocks the STOP
                errors.append(exc)
        return errors

    # Approvals (LA-GOV-02, LA-GOV-05, LA-AMD-01) -------------------------------------------
    def propose(
        self,
        kind: ProposalKind,
        payload: dict[str, JsonValue],
        summary: str,
        requested_by: Component,
        category=None,
        task_id: UUID | None = None,
        expires_at: datetime | None = None,
    ) -> ApprovalRequest:
        if kind is ProposalKind.EXTERNAL_ACTION and category is None:
            raise GovernanceError("an external action needs an approval category")
        now = self._clock()
        hours = self.parameter("approval_expiry_hours")
        if expires_at is None and isinstance(hours, int) and hours > 0:
            expires_at = now + timedelta(hours=hours)  # D-014: then it must be asked again
        request = ApprovalRequest(
            approval_id=uuid4(),
            task_id=task_id,
            category=category or KIND_CATEGORY[kind],
            action_summary=summary,
            action_digest=canonical_digest({"kind": kind.value, "payload": payload}),
            requested_by=requested_by,
            created_at=now,
            expires_at=expires_at,
        )
        self._commit(
            lambda s: [self._new(ProposalCreated, request=request, kind=kind, payload=payload)]
        )
        return request

    def decide(self, decision: ApprovalDecision, proof: str) -> ProposalStatus:
        """Record the Founder's decision; an approved internal proposal is executed at once."""
        if not self._channel.verify(decision, proof):
            raise GovernanceError("decision did not arrive on the authenticated Founder channel")

        def build(s: GovernanceState):
            p = s.proposals.get(decision.approval_id)
            if p is None:
                raise GovernanceError("unknown approval")
            if p.status is not ProposalStatus.OPEN:
                raise GovernanceError(f"approval is already {p.status}")
            if not decision.applies_to(p.request):
                raise GovernanceError("decision does not match the exact action or has expired")
            events = [self._new(DecisionRecorded, decision=decision)]
            if decision.decision is ApprovalDecisionKind.APPROVE and p.kind not in EXTERNAL_KINDS:
                events += self._execute(s, decision.approval_id)
                events.append(self._new(ProposalExecuted, approval_id=decision.approval_id))
            return events

        self._commit(build)
        return self._state.proposals[decision.approval_id].status

    def approval_status(self, approval_id: UUID) -> ProposalStatus | None:
        p = self.sync().proposals.get(approval_id)
        return p.status if p else None

    def check_approval(self, approval_id: UUID, action_digest: str, category) -> bool:
        """For G: is there an approved, unused external approval for exactly this action?"""
        p = self.sync().proposals.get(approval_id)
        return bool(
            p
            and p.kind in EXTERNAL_KINDS
            and p.status is ProposalStatus.APPROVED
            and p.request.category is category
            and p.request.action_digest == action_digest
        )

    def consume_approval(
        self, approval_id: UUID, action_digest: str, category, by: Component
    ) -> None:
        """Use an external approval once. Every financial action passes here (LA-GOV-05)."""

        def build(s: GovernanceState):
            p = s.proposals.get(approval_id)
            if not (
                p
                and p.kind in EXTERNAL_KINDS
                and p.status is ProposalStatus.APPROVED
                and p.request.category is category
                and p.request.action_digest == action_digest
            ):
                raise GovernanceError("no approved, unused approval for this exact action")
            return [self._new(ApprovalConsumed, approval_id=approval_id, by=by)]

        self._commit(build)

    def external_action_digest(self, payload: dict[str, JsonValue]) -> str:
        return canonical_digest({"kind": ProposalKind.EXTERNAL_ACTION.value, "payload": payload})

    # Execution of approved internal proposals --------------------------------------------
    def _execute(self, s: GovernanceState, approval_id: UUID) -> list[GovernanceEvent]:
        p = s.proposals[approval_id]
        d = p.payload
        match p.kind:
            case ProposalKind.SET_PARAMETER:
                name, value = str(d["name"]), d["value"]
                if name not in PARAMETERS:
                    raise GovernanceError(f"{name} is not an operational parameter")
                if not PARAMETERS[name](value):
                    raise GovernanceError(f"invalid value for {name}")
                return [self._new(ParameterSet, name=name, value=value, approval_id=approval_id)]
            case ProposalKind.SET_LIMITS:
                limits = ReceptorLimits.model_validate(d["limits"])
                return [self._new(LimitsSet, limits=limits, approval_id=approval_id)]
            case ProposalKind.ADMIT_INTEGRATION:
                rec = s.integrations.get(str(d["integration_id"]))
                if (
                    rec is None
                    or rec.status is not IntegrationStatus.PROPOSED
                    or not rec.security_checked
                ):
                    raise GovernanceError("integration must be proposed and security-checked")
                return [self._integration(rec, IntegrationStatus.ADMITTED, approval_id)]
            case ProposalKind.ACTIVATE_RECEPTOR:
                return [self._activation(s, d, approval_id)]
            case ProposalKind.ARCHIVE_RECEPTOR | ProposalKind.REPLACE_RECEPTOR:
                return [self._retire(s, p.kind, d, approval_id)]
            case ProposalKind.RESUME:
                return [self._resume(s, d, approval_id)]
            case ProposalKind.AUTHORIZE_RECOVERY:
                if int(d["extra_attempts"]) < 1:
                    raise GovernanceError("extra_attempts must be at least 1")
                return []
            case ProposalKind.CLEAR_COMPLIANCE:
                item = s.compliance.get(UUID(str(d["item_id"])))
                if item is None:
                    raise GovernanceError("unknown compliance item")
                if item.requires_legal_review and not item.reviewed:
                    raise GovernanceError("legal review by a person is required first")
                return []
        raise GovernanceError(f"{p.kind} is not executed by A")

    # STOP / PAUSE / RESUME (LA-GOV-03, LA-GOV-08, LA-SAF-01, LA-SAF-04) ------------------
    def control(self, command: ControlCommand, proof: str | None = None) -> ControlState:
        """STOP and PAUSE apply immediately, with no approval and no model in the path.

        RESUME is never a free-standing command: the Founder approves a resume proposal that
        names the exact stop it lifts, and the approval itself performs the resume.
        """
        if command.command is ControlCommandType.RESUME:
            raise GovernanceError("resume by approving a resume proposal (propose_resume)")
        if command.issued_by is Component.FOUNDER and not self._channel.verify(
            command, proof or ""
        ):
            raise GovernanceError("command did not arrive on the authenticated Founder channel")
        self._commit(lambda s: [self._new(ControlApplied, command=command)])
        return self.control_state(command.scope, command.receptor_id)

    def _resume(self, s: GovernanceState, d: dict, approval_id: UUID) -> ControlApplied:
        scope = ControlScope(str(d["scope"]))
        rid = d.get("receptor_id")
        current = s.control_for(scope, rid, self._clock())
        if current.mode is ControlMode.RUNNING:
            raise GovernanceError("nothing to resume")
        # The approval names the exact STOP, PAUSE or breach it lifts; an old approval cannot
        # lift a newer stop.
        if str(d.get("lifts")) != str(current.last_command_id):
            raise GovernanceError("the approval is for an earlier stop, not the current one")
        return self._new(
            ControlApplied,
            command=ControlCommand(
                command_id=uuid4(),
                command=ControlCommandType.RESUME,
                scope=scope,
                receptor_id=rid,
                issued_by=Component.FOUNDER,
                issued_at=self._clock(),
                authorization_id=approval_id,
            ),
        )

    def propose_resume(self, scope: ControlScope, receptor_id: str | None, requested_by: Component):
        state = self.control_state(scope, receptor_id)
        if state.mode is ControlMode.RUNNING:
            raise GovernanceError("nothing to resume")
        payload = {
            "scope": scope.value,
            "receptor_id": receptor_id,
            "lifts": str(state.last_command_id),
        }
        what = "master" if scope is ControlScope.MASTER else receptor_id
        note = " after a serious breach" if state.serious_breach else ""
        return self.propose(ProposalKind.RESUME, payload, f"Resume {what}{note}", requested_by)

    def declare_breach(
        self,
        kind: BreachKind,
        scope: ControlScope,
        receptor_id: str | None,
        declared_by: Component,
        detail: str = "",
    ) -> ControlState:
        """Stops the scope at once and marks it; it never resumes without the Founder."""
        self._commit(
            lambda s: [
                self._new(
                    BreachDeclared,
                    breach_id=uuid4(),
                    kind=kind,
                    scope=scope,
                    receptor_id=receptor_id,
                    declared_by=declared_by,
                    detail=detail,
                )
            ]
        )
        return self.control_state(scope, receptor_id)

    def control_state(self, scope: ControlScope, receptor_id: str | None = None) -> ControlState:
        return self.sync().control_for(scope, receptor_id, self._clock())

    def effective_mode(self, receptor_id: str | None) -> ControlMode:
        """What G checks on every call: the master state overrides the Receptor's own."""
        s = self.sync()
        now = self._clock()
        modes = [s.control_for(ControlScope.MASTER, None, now).mode]
        if receptor_id is not None:
            modes.append(s.control_for(ControlScope.RECEPTOR, receptor_id, now).mode)
        for mode in (ControlMode.STOPPED, ControlMode.PAUSED):
            if mode in modes:
                return mode
        return ControlMode.RUNNING

    # Recovery (LA-GOV-09, LA-SAF-03) -----------------------------------------------------
    def record_recovery_attempt(
        self, incident_id: UUID, receptor_id: str | None, succeeded: bool, detail: str = ""
    ) -> bool:
        """Record one attempt. Returns False (and escalates) when no attempt is allowed."""
        refused = []

        def build(s: GovernanceState):
            inc = s.incidents.get(incident_id)
            used = inc.attempts if inc else 0
            limit = int(self.parameter("recovery_attempt_limit", s) or 0) + (
                inc.allowed if inc else 0
            )
            if used >= limit:
                refused.append(True)
                if inc and inc.escalated:
                    return []
                return [self._new(RecoveryEscalated, incident_id=incident_id, attempts_used=used)]
            return [
                self._new(
                    RecoveryAttempted,
                    incident_id=incident_id,
                    receptor_id=receptor_id,
                    attempt=used + 1,
                    succeeded=succeeded,
                    detail=detail,
                )
            ]

        self._commit(build)
        return not refused

    def propose_recovery_authorization(
        self, incident_id: UUID, extra_attempts: int, requested_by: Component
    ):
        payload = {"incident_id": str(incident_id), "extra_attempts": extra_attempts}
        return self.propose(
            ProposalKind.AUTHORIZE_RECOVERY,
            payload,
            f"Allow {extra_attempts} more recovery attempt(s) for incident {incident_id}",
            requested_by,
        )

    # Operational parameters vs core amendments (LA-AMD-02) ---------------------------------
    def parameter(self, name: str, state: GovernanceState | None = None) -> JsonValue | None:
        """The approved value from the log, else the initial Founder-decided value, else None."""
        s = state or self.sync()
        return s.parameters.get(name, self._initial_parameters.get(name))

    def propose_parameter(self, name: str, value: JsonValue, requested_by: Component):
        if name not in PARAMETERS:
            raise GovernanceError(
                f"{name} is not an operational parameter; AMD rules change only by amendment"
            )
        if not PARAMETERS[name](value):
            raise GovernanceError(f"invalid value for {name}")
        return self.propose(
            ProposalKind.SET_PARAMETER,
            {"name": name, "value": value},
            f"Set {name} to {value}",
            requested_by,
        )

    def propose_amendment(self, rule_id: str, diff: str, rationale: str, requested_by: Component):
        """A core amendment is approved here but never applied at runtime: it goes through the
        Governed Amendment Workflow (register version, lock update, regression tests)."""
        payload = {"rule_id": rule_id, "diff": diff, "rationale": rationale}
        return self.propose(ProposalKind.AMENDMENT, payload, f"Amend {rule_id}", requested_by)

    # Budget and permission limits (LA-GOV-04, LA-IF-09, AMD-11) --------------------------
    def recommend_limits(self, limits: ReceptorLimits, by: Component, rationale: str) -> None:
        self._commit(
            lambda s: [self._new(LimitsRecommended, limits=limits, by=by, rationale=rationale)]
        )

    def propose_limits(self, limits: ReceptorLimits, requested_by: Component):
        return self.propose(
            ProposalKind.SET_LIMITS,
            {"limits": limits.model_dump(mode="json")},
            f"Set limits for {limits.receptor_id}",
            requested_by,
        )

    def limits(self, receptor_id: str) -> ReceptorLimits | None:
        return self.sync().limits.get(receptor_id)

    def check_spend(
        self, receptor_id: str, tool_id: str, amount: Money, month_to_date: Money
    ) -> tuple[bool, str]:
        """Bounded autonomy: with no Founder-set limits, nothing is allowed."""
        lim = self.limits(receptor_id)
        if lim is None:
            return False, "no Founder-set limits for this Receptor"
        if tool_id not in lim.permissions:
            return False, "tool not permitted for this Receptor"
        cap = lim.max_spend_per_action
        if amount.currency != cap.currency or month_to_date.currency != cap.currency:
            return False, "currency differs from the limit"
        if amount.amount > cap.amount:
            return False, "over the per-action limit"
        if month_to_date.amount + amount.amount > lim.max_spend_per_month.amount:
            return False, "over the monthly limit"
        return True, "within limits"

    # Supply chain / integration gate (LA-GOV-06, LA-SEC-04, AMD-13) ----------------------
    def _integration(
        self, rec: IntegrationRecord, status: IntegrationStatus, approval_id=None, **upd
    ):
        record = rec.model_copy(
            update={
                "status": status,
                "founder_approval_id": approval_id or rec.founder_approval_id,
                "updated_at": self._clock(),
                **upd,
            }
        )
        return self._new(
            IntegrationRecorded, record=IntegrationRecord.model_validate(record.model_dump())
        )

    def propose_integration(
        self,
        integration_id: str,
        kind: IntegrationKind,
        name: str,
        version: str,
        risk: RiskLevel,
        change_record_ref: str,
    ) -> IntegrationRecord:
        rec = IntegrationRecord(
            integration_id=integration_id,
            kind=kind,
            name=name,
            version=version,
            risk=risk,
            status=IntegrationStatus.PROPOSED,
            security_checked=False,
            change_record_ref=change_record_ref,
            updated_at=self._clock(),
        )

        def build(s: GovernanceState):
            if integration_id in s.integrations:
                raise GovernanceError("integration already recorded; propose a new version id")
            return [self._new(IntegrationRecorded, record=rec)]

        self._commit(build)
        return rec

    def record_security_check(
        self, integration_id: str, passed: bool, report_ref: str
    ) -> IntegrationRecord:
        def build(s: GovernanceState):
            rec = s.integrations[integration_id]
            if rec.status is not IntegrationStatus.PROPOSED:
                raise GovernanceError("only a proposed integration is checked")
            status = IntegrationStatus.PROPOSED if passed else IntegrationStatus.BLOCKED
            return [
                self._integration(
                    rec,
                    status,
                    security_checked=passed,
                    change_record_ref=f"{rec.change_record_ref}; check:{report_ref}",
                )
            ]

        self._commit(build)
        return self.sync().integrations[integration_id]

    def admit_integration(self, integration_id: str) -> IntegrationRecord | ApprovalRequest:
        """Low and medium risk: admitted once checked. High risk: returns an approval request."""
        rec = self.sync().integrations[integration_id]
        if rec.risk is RiskLevel.HIGH:
            return self.propose(
                ProposalKind.ADMIT_INTEGRATION,
                {"integration_id": integration_id, "version": rec.version},
                f"Admit high-risk {rec.kind} {rec.name} {rec.version}",
                Component.GOVERNANCE_CORE,
            )

        def build(s: GovernanceState):
            r = s.integrations[integration_id]
            if r.status is not IntegrationStatus.PROPOSED or not r.security_checked:
                raise GovernanceError("integration must be proposed and security-checked")
            return [self._integration(r, IntegrationStatus.ADMITTED)]

        self._commit(build)
        return self.sync().integrations[integration_id]

    def restrict_integration(
        self, integration_id: str, status: IntegrationStatus
    ) -> IntegrationRecord:
        """Block, isolate or revoke at once. Making things safer never waits for approval."""
        if status not in (
            IntegrationStatus.BLOCKED,
            IntegrationStatus.ISOLATED,
            IntegrationStatus.REVOKED,
        ):
            raise GovernanceError("restrict only blocks, isolates or revokes")
        self._commit(lambda s: [self._integration(s.integrations[integration_id], status)])
        return self.sync().integrations[integration_id]

    def registry(self) -> dict[str, IntegrationRecord]:
        return dict(self.sync().integrations)

    # Legal and compliance (LA-GOV-07, AMD-9) ---------------------------------------------
    def record_compliance_item(
        self, receptor_id: str, kind: ComplianceKind, description: str, requires_legal_review: bool
    ) -> tuple[UUID, ApprovalRequest]:
        """Every new legal policy, regulated activity or activation goes to the Founder."""
        item_id = uuid4()
        self._commit(
            lambda s: [
                self._new(
                    ComplianceItemRecorded,
                    item_id=item_id,
                    receptor_id=receptor_id,
                    kind=kind,
                    description=description,
                    requires_legal_review=requires_legal_review,
                )
            ]
        )
        req = self.propose(
            ProposalKind.CLEAR_COMPLIANCE,
            {
                "item_id": str(item_id),
                "receptor_id": receptor_id,
                "kind": kind.value,
                "description": description,
            },
            f"{kind.value} for {receptor_id}: {description}",
            Component.GOVERNANCE_CORE,
        )
        return item_id, req

    def record_legal_review(self, item_id: UUID, reviewer: Component, review_ref: str) -> None:
        self._commit(
            lambda s: [
                self._new(
                    LegalReviewRecorded, item_id=item_id, reviewer=reviewer, review_ref=review_ref
                )
            ]
        )

    def compliance_cleared(self, receptor_id: str) -> bool:
        items = [i for i in self.sync().compliance.values() if i.receptor_id == receptor_id]
        return all(i.cleared for i in items)

    # Receptor lifecycle (LA-IF-10, LA-IF-11, AMD-7) --------------------------------------
    def register_receptor(self, manifest: ReceptorManifest) -> None:
        def build(s: GovernanceState):
            if manifest.receptor_id in s.receptors:
                raise GovernanceError("Receptor already registered")
            return [self._new(ReceptorRegistered, manifest=manifest)]

        self._commit(build)

    def propose_activation(
        self, receptor_id: str, acceptance_evidence_ids: list[UUID], requested_by: Component
    ):
        payload = {
            "receptor_id": receptor_id,
            "acceptance_evidence_ids": [str(e) for e in acceptance_evidence_ids],
        }
        return self.propose(
            ProposalKind.ACTIVATE_RECEPTOR,
            payload,
            f"Activate Receptor {receptor_id}",
            requested_by,
        )

    def _activation(self, s: GovernanceState, d: dict, approval_id: UUID) -> ReceptorStatusChanged:
        rid = str(d["receptor_id"])
        r = s.receptors.get(rid)
        if r is None or r.status is not ReceptorStatus.PROPOSED:
            raise GovernanceError("only a registered, not yet active Receptor can be activated")
        lim = s.limits.get(rid)
        if lim is None:
            raise GovernanceError("no Founder-approved budget and permissions")
        missing = [t for t in r.manifest.tools if t not in lim.permissions]
        if missing:
            raise GovernanceError(f"manifest tools without permission: {missing}")
        not_admitted = [
            t
            for t in r.manifest.tools
            if t not in s.integrations or s.integrations[t].status is not IntegrationStatus.ADMITTED
        ]
        if not_admitted:
            raise GovernanceError(
                f"tools not admitted through the integration gate: {not_admitted}"
            )
        if any(not i.cleared for i in s.compliance.values() if i.receptor_id == rid):
            raise GovernanceError("compliance items are not cleared")
        evidence = [UUID(str(e)) for e in d["acceptance_evidence_ids"]]
        if not evidence:
            raise GovernanceError("acceptance evidence is required")
        return self._new(
            ReceptorStatusChanged,
            receptor_id=rid,
            status=ReceptorStatus.ACTIVE,
            approval_id=approval_id,
            acceptance_evidence_ids=tuple(evidence),
        )

    def propose_archive(self, receptor_id: str, requested_by: Component):
        return self.propose(
            ProposalKind.ARCHIVE_RECEPTOR,
            {"receptor_id": receptor_id},
            f"Archive Receptor {receptor_id}",
            requested_by,
        )

    def propose_replacement(self, receptor_id: str, replacement_id: str, requested_by: Component):
        return self.propose(
            ProposalKind.REPLACE_RECEPTOR,
            {"receptor_id": receptor_id, "replacement_id": replacement_id},
            f"Replace Receptor {receptor_id} with {replacement_id}",
            requested_by,
        )

    def _retire(self, s: GovernanceState, kind: ProposalKind, d: dict, approval_id: UUID):
        rid = str(d["receptor_id"])
        r = s.receptors.get(rid)
        if r is None or r.status in (ReceptorStatus.ARCHIVED, ReceptorStatus.REPLACED):
            raise GovernanceError("Receptor is not live")
        state = s.control_for(ControlScope.RECEPTOR, rid, self._clock())
        if state.mode is ControlMode.RUNNING and r.status is ReceptorStatus.ACTIVE:
            raise GovernanceError("pause or stop the Receptor before archiving or replacing it")
        if kind is ProposalKind.REPLACE_RECEPTOR:
            return self._new(
                ReceptorStatusChanged,
                receptor_id=rid,
                status=ReceptorStatus.REPLACED,
                approval_id=approval_id,
                replacement_id=str(d["replacement_id"]),
            )
        return self._new(
            ReceptorStatusChanged,
            receptor_id=rid,
            status=ReceptorStatus.ARCHIVED,
            approval_id=approval_id,
        )

    # Safe Continuity (LA-GOV-10, AMD-12) --------------------------------------------------
    def trigger_safe_continuity_automatically(self) -> None:
        if self.policy.control("AMD-12", "automatic_48h_trigger_enabled") is not True:
            raise GateClosed("AMD-12 48-hour trigger is blocked until presence detection (gate 7)")
        raise GateClosed("presence detection is not implemented")


def money(amount: str, currency: str) -> Money:
    return Money(amount=Decimal(amount), currency=currency)
