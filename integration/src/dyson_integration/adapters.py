"""Port adapters: each one connects a port a component declared in its own step to the real
component on the other side. No adapter adds authority; each only translates.
"""

from collections.abc import Callable
from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

import psycopg
from psycopg.errors import UniqueViolation
from psycopg.rows import dict_row

from dyson_assurance.qa import QAController
from dyson_contracts.approvals import ApprovalCategory, ApprovalDecision, ApprovalRequest
from dyson_contracts.audit import AuditEvent, AuditKind
from dyson_contracts.common import Component, Money
from dyson_contracts.control import ControlCommand, ControlMode, ControlScope, ControlState
from dyson_contracts.evidence import EvidenceRecord
from dyson_contracts.integrations import IntegrationRecord, IntegrationStatus
from dyson_contracts.interface import FounderMessage, Modality, TaskStatusUpdate
from dyson_contracts.tasks import TaskState, TaskTransition
from dyson_contracts.toolcalls import ToolCallRequest
from dyson_gateway.ports import ConversationReply, ThreadMessage
from dyson_governance.core import GovernanceCore
from dyson_governance.events import ProposalKind, ReceptorStatus
from dyson_intelligence.conversation import ConversationEngine
from dyson_intelligence.models import ModelRequest, RoutedResponse
from dyson_intelligence.router import ModelRouter, RouterError
from dyson_memory.models import ArchivedMessage, Thread
from dyson_memory.secrets import SecretGuard, SecretLeak
from dyson_memory.store import MemoryStore
from dyson_orchestrator.orchestrator import Orchestrator, OrchestratorError
from dyson_orchestrator.ports import TaskPlan, ToolRun
from dyson_toolhub.catalog import Catalog, ToolScope
from dyson_toolhub.hub import ToolHub

Clock = Callable[[], datetime]


# --- I: Memory & Evidence ----------------------------------------------------------------
class EvidenceToMemory:
    """F's and H's EvidenceSink: every verdict and reconciliation lands in I's registry."""

    def __init__(self, store: MemoryStore):
        self._store = store

    def record(self, evidence: EvidenceRecord, receptor_id: str | None) -> None:
        self._store.record_evidence(evidence, receptor_id)


class AuditToMemory:
    """A's and G's audit sink: I's hash-chained, append-only audit log."""

    def __init__(self, store: MemoryStore):
        self._store = store

    def __call__(self, event: AuditEvent) -> None:
        self._store.audit(event)


class TaskEventsToMemory:
    """D's TaskEventSink: task state and evidence references into I (LA-ORC-07)."""

    def __init__(self, store: MemoryStore, evidence_of: Callable[[UUID], tuple[UUID, ...]]):
        self._store, self._evidence_of = store, evidence_of

    def record(self, transition: TaskTransition) -> None:
        evidence = self._evidence_of(transition.task_id)
        if transition.to_state is not TaskState.COMPLETED_VERIFIED:
            evidence = ()
        self._store.audit(
            AuditEvent(
                event_id=uuid4(),
                kind=AuditKind.TASK_TRANSITION,
                actor=transition.actor,
                at=transition.at,
                summary=f"task {transition.from_state or 'new'} -> {transition.to_state}",
                task_id=transition.task_id,
                data={
                    "from": transition.from_state.value if transition.from_state else None,
                    "to": transition.to_state.value,
                    "trigger": transition.trigger.value if transition.trigger else None,
                    "reason": transition.reason,
                    "evidence_ids": [str(e) for e in evidence],
                },
            )
        )


class FounderInbox:
    """Where escalations and reminders for the Founder and the human reviewer go. Each is also
    written to I's audit log. Step 10 adds push delivery to the app."""

    def __init__(self, store: MemoryStore, clock: Clock):
        self._store, self._clock = store, clock
        self.messages: list[tuple[str, str, str, UUID | None]] = []

    def escalate(self, to: str, subject: str, message: str, task_id: UUID | None = None) -> None:
        self.messages.append((to, subject, message, task_id))
        self._store.audit(
            AuditEvent(
                event_id=uuid4(),
                kind=AuditKind.POLICY_DECISION,
                actor=Component.MONITORING if to != "human_reviewer" else Component.QA_QC,
                at=self._clock(),
                summary=f"escalation to {to}: {message}"[:500],
                task_id=task_id,
                data={"to": to, "subject": subject},
            )
        )

    def for_orchestrator(self) -> "OrchestratorEscalation":
        return OrchestratorEscalation(self)


class OrchestratorEscalation:
    def __init__(self, inbox: FounderInbox):
        self._inbox = inbox

    def escalate(self, task_id: UUID, reason: str) -> None:
        self._inbox.escalate("founder", "task", reason, task_id)


# --- A: Governance Core, as each component sees it ---------------------------------------
class GovernanceForToolHub:
    def __init__(self, core: GovernanceCore):
        self._core = core

    def effective_mode(self, receptor_id: str | None) -> ControlMode:
        return self._core.effective_mode(receptor_id)

    def registry(self) -> dict[str, IntegrationRecord]:
        return self._core.registry()

    def receptor_permits(self, receptor_id: str, tool_id: str) -> bool:
        s = self._core.sync()
        r = s.receptors.get(receptor_id)
        lim = s.limits.get(receptor_id)
        return bool(r and r.status is ReceptorStatus.ACTIVE and lim and tool_id in lim.permissions)

    def spend_allowed(self, receptor_id, tool_id, amount: Money, month_to_date: Money):
        return self._core.check_spend(receptor_id, tool_id, amount, month_to_date)

    def check_approval(self, approval_id, action_digest, category) -> bool:
        return self._core.check_approval(approval_id, action_digest, category)

    def consume_approval(self, approval_id, action_digest, category, by: Component) -> None:
        self._core.consume_approval(approval_id, action_digest, category, by)


class GovernanceForOrchestrator:
    def __init__(self, core: GovernanceCore):
        self._core = core

    def effective_mode(self, receptor_id: str | None) -> ControlMode:
        return self._core.effective_mode(receptor_id)

    def propose_external_action(
        self, payload, category: ApprovalCategory, summary: str, task_id: UUID
    ) -> UUID:
        return self._core.propose(
            ProposalKind.EXTERNAL_ACTION,
            payload,
            summary,
            Component.ORCHESTRATOR,
            category,
            task_id,
        ).approval_id

    def approval_status(self, approval_id: UUID) -> str:
        status = self._core.approval_status(approval_id)
        return status.value if status else "unknown"


class GovernanceForIntelligence:
    def __init__(self, core: GovernanceCore):
        self._core = core

    def registry(self) -> dict[str, IntegrationRecord]:
        return self._core.registry()

    def check_approval(self, approval_id, action_digest, category) -> bool:
        return self._core.check_approval(approval_id, action_digest, category)

    def consume_approval(self, approval_id, action_digest, category) -> None:
        self._core.consume_approval(approval_id, action_digest, category, Component.MODEL_ROUTER)

    def propose_amendment(self, rule_id: str, diff: str, rationale: str) -> UUID:
        return self._core.propose_amendment(
            rule_id, diff, rationale, Component.CONVERSATION_ENGINE
        ).approval_id


def open_approvals(core: GovernanceCore, now) -> list[ApprovalRequest]:
    from dyson_governance.state import ProposalStatus

    return [
        p.request
        for p in core.sync().proposals.values()
        if p.status is ProposalStatus.OPEN
        and (p.request.expires_at is None or now <= p.request.expires_at)
    ]


class ApprovalReminders:
    """D-014: while an approval waits, the Founder is reminded every reminder interval; when it
    expires unanswered, the Founder is told once that it must be asked again."""

    def __init__(self, core: GovernanceCore, inbox: FounderInbox, interval, clock: Clock):
        self._core, self._inbox, self._interval, self._clock = core, inbox, interval, clock
        self._last: dict[UUID, object] = {}
        self._expired: set[UUID] = set()

    def check(self) -> None:
        from dyson_governance.state import ProposalStatus

        now = self._clock()
        for p in self._core.sync().proposals.values():
            r = p.request
            if p.status is not ProposalStatus.OPEN or r.approval_id in self._expired:
                continue
            if r.expires_at is not None and now > r.expires_at:
                self._expired.add(r.approval_id)
                self._inbox.escalate("founder", "approval",
                                     f"Expired unanswered, ask again: {r.action_summary}",
                                     r.task_id)  # fmt: skip
                continue
            if now - self._last.get(r.approval_id, r.created_at) >= self._interval:
                self._last[r.approval_id] = now
                until = f" (expires {r.expires_at:%Y-%m-%d %H:%M} UTC)" if r.expires_at else ""
                self._inbox.escalate("founder", "approval",
                                     f"Reminder: waiting for you: {r.action_summary}{until}",
                                     r.task_id)  # fmt: skip


class GovernanceForControls:
    """Direct Founder Controls reach A and nothing else (LA-DFC-02)."""

    def __init__(self, core: GovernanceCore, clock: Clock):
        self._core, self._clock = core, clock

    def pending_approvals(self) -> list[ApprovalRequest]:
        """Open approvals that have not expired (D-014: an expired one must be asked again)."""
        return open_approvals(self._core, self._clock())

    def decide(self, decision: ApprovalDecision, proof: str) -> str:
        return self._core.decide(decision, proof).value

    def control(self, command: ControlCommand, proof: str) -> ControlState:
        return self._core.control(command, proof)

    def propose_resume(self, scope: ControlScope, receptor_id: str | None) -> ApprovalRequest:
        return self._core.propose_resume(scope, receptor_id, Component.DIRECT_FOUNDER_CONTROLS)


# --- G and F, as D sees them -------------------------------------------------------------
class ToolHubForOrchestrator:
    def __init__(self, hub: ToolHub, credential: str):
        self._hub, self._credential = hub, credential

    def call(self, request: ToolCallRequest) -> ToolRun:
        r = self._hub.call(request, self._credential)
        return ToolRun(
            status=r.status,
            result=r.result,
            error=r.error,
            denied_checks=tuple(c.check.value for c in r.decision.checks if not c.passed),
        )


class QAForOrchestrator:
    """The QA / verification lane: D asks F; F asks its independent verifier."""

    def __init__(self, qa: QAController):
        self._qa = qa

    def verify(self, task_id: UUID, plan: TaskPlan, run: ToolRun):
        from dyson_contracts.lanes import ReceptorTaskResult

        claim = None
        raw = run.result.get("claim") if isinstance(run.result, dict) else None
        if isinstance(raw, dict) and raw.get("task_id"):
            claim = ReceptorTaskResult.model_validate(raw)  # kept for audit; never decides
        return self._qa.verify(task_id, plan.receptor_id, plan.standard_id, run.result, claim)


# --- B's view of I, D and G --------------------------------------------------------------
class MemoryForConversation:
    def __init__(self, store: MemoryStore, rule_ids: list[str]):
        self._store, self._rule_ids = store, rule_ids

    def thread_context(self, thread_id: UUID, limit: int) -> list[dict[str, str]]:
        msgs = self._store.thread_messages(thread_id)[-limit:]
        return [
            {"role": "user" if m.participant == "founder" else "assistant", "content": m.body}
            for m in msgs
        ]

    def locked_rules(self) -> list[dict[str, str]]:
        out = []
        for rule_id in self._rule_ids:
            view = self._store.register_view(rule_id)
            if view and view.locked:
                out.append(
                    {"id": rule_id, "version": view.current.version, "title": view.current.title}
                )
        return out


class OrchestratorForConversation:
    def __init__(self, orch: Orchestrator, status: "TaskStatus"):
        self._orch, self._status = orch, status

    def submit(self, instruction_key: str, instruction: str, plan: dict) -> TaskStatusUpdate:
        view = self._orch.submit(instruction_key, instruction, TaskPlan.model_validate(plan))
        return self._status.task(view.task_id)

    def status(self, task_id: UUID) -> TaskStatusUpdate:
        return self._status.task(task_id)


class CatalogForConversation:
    """B's tool list, after A's policy checks (LA-CONV-06): only tools admitted at A's gate,
    each offered only for Receptors that are active and whose Founder-set limits permit it."""

    def __init__(
        self,
        catalog: Catalog,
        core: GovernanceCore,
        standards: dict[str, str],
        descriptions: dict[str, str],
    ):
        self._catalog, self._core = catalog, core
        self._standards, self._descriptions = standards, descriptions

    def tools(self) -> dict[str, dict[str, Any]]:
        s = self._core.sync()
        out = {}
        for spec in self._catalog.specs():
            rec = s.integrations.get(spec.tool_id)
            if (
                rec is None
                or rec.status is not IntegrationStatus.ADMITTED
                or spec.tool_id not in self._standards
                or Component.ORCHESTRATOR not in spec.allowed_callers
            ):
                continue
            receptors = []
            if spec.scope is not ToolScope.CORE:
                receptors = sorted(
                    rid
                    for rid, r in s.receptors.items()
                    if r.status is ReceptorStatus.ACTIVE
                    and rid in s.limits
                    and spec.tool_id in s.limits[rid].permissions
                )
                if not receptors:
                    continue
            out[spec.tool_id] = {
                "receptors": receptors,
                "standard_id": self._standards[spec.tool_id],
                "description": self._descriptions.get(spec.tool_id, ""),
            }
        return out


# --- Gateway's view of B, D and I --------------------------------------------------------
class TaskStatus:
    """D's tasks as the Founder sees them; a thread's tasks come from the integration schema."""

    def __init__(self, orch: Orchestrator, conn: psycopg.Connection, store: MemoryStore):
        self._orch, self._conn, self._store = orch, conn, store

    def task(self, task_id: UUID) -> TaskStatusUpdate | None:
        try:
            view = self._orch.get(task_id)
        except OrchestratorError:
            return None
        history = self._orch.history(task_id)
        done = view.state is TaskState.COMPLETED_VERIFIED
        return TaskStatusUpdate(
            task_id=task_id,
            state=view.state,
            message=history[-1].reason if history else "",
            verified_evidence_ids=view.evidence_ids if done else (),
            at=history[-1].at,
        )

    def tasks(self, thread_id: UUID) -> list[TaskStatusUpdate]:
        rows = self._conn.execute(
            "SELECT task_id FROM integration.thread_tasks WHERE thread_id = %s ORDER BY seq",
            [thread_id],
        ).fetchall()
        return [u for r in rows if (u := self.task(r["task_id"])) is not None]

    def thread(self, thread_id: UUID, limit: int) -> list[ThreadMessage]:
        return [
            ThreadMessage(
                role="user" if m.participant == "founder" else "assistant",
                content=m.body,
                modality=m.modality.value,
            )
            for m in self._store.thread_messages(thread_id)[-limit:]
        ]

    def task_for_message(self, message_id: UUID) -> TaskStatusUpdate | None:
        row = self._conn.execute(
            "SELECT task_id FROM integration.thread_tasks WHERE message_id = %s", [message_id]
        ).fetchone()
        return self.task(row["task_id"]) if row else None

    def link(self, thread_id: UUID, task_id: UUID, message_id: UUID, at: datetime) -> None:
        self._conn.execute(
            "INSERT INTO integration.thread_tasks (thread_id, task_id, message_id, at)"
            " VALUES (%s, %s, %s, %s) ON CONFLICT (task_id) DO NOTHING",
            [thread_id, task_id, message_id, at],
        )


class ConversationForGateway:
    """The Gateway's only destination: B. Both sides of the conversation are archived in I, so
    text and voice share one history whatever model or app is used (LA-APP-03, LA-MEM-10)."""

    def __init__(
        self,
        b: ConversationEngine,
        store: MemoryStore,
        status: TaskStatus,
        guard: SecretGuard,
        clock: Clock,
    ):
        self._b, self._store, self._status, self._clock = b, store, status, clock
        self._guard = guard

    def handle(self, message: FounderMessage) -> ConversationReply:
        try:  # a credential typed into chat never reaches a model or memory (LA-SEC-01)
            self._guard.check(message.text)
        except SecretLeak:
            return ConversationReply(
                kind="clarify",
                language=message.language,
                text="That looks like a password or key. I did not send "
                "or store it. Please keep it in the secret store.",
            )
        retried = self._status.task_for_message(message.message_id)
        if retried is not None:  # a network retry of a command already accepted: no second task
            return ConversationReply(
                kind="accepted",
                language=message.language,
                text="Already accepted; this is the same command.",
                task_id=retried.task_id,
                task_state=retried.state,
            )
        self._ensure_thread(message.thread_id, message.sent_at)
        reply = self._b.handle(message)  # B reads the thread so far from I
        try:
            self._store.append_message(
                ArchivedMessage(
                    message_id=message.message_id,
                    thread_id=message.thread_id,
                    participant="founder",
                    modality=message.modality,
                    body=message.text,
                    language=message.language,
                    transcription_uncertain=message.transcription_uncertain,
                    sent_at=message.sent_at,
                )
            )
        except UniqueViolation:  # a retried question: archived once already
            return ConversationReply.model_validate(reply.model_dump(mode="json"))
        now = self._clock()
        self._store.append_message(
            ArchivedMessage(
                message_id=uuid4(),
                thread_id=message.thread_id,
                participant="dyson",
                modality=Modality.TEXT,
                body=reply.text,
                language=reply.language,
                sent_at=max(now, message.sent_at),
            )
        )
        if reply.task_id is not None:
            self._status.link(message.thread_id, reply.task_id, message.message_id, now)
        return ConversationReply.model_validate(reply.model_dump(mode="json"))

    def _ensure_thread(self, thread_id: UUID, at: datetime) -> None:
        try:
            self._store.create_thread(Thread(thread_id=thread_id, title="Founder", created_at=at))
        except UniqueViolation:
            pass


# --- C, gated for Hermes by A's control state (LA-HER-05) -------------------------------
class HermesGatedRouter:
    """C's API object. Hermes's model calls are refused while A has the master scope stopped or
    paused; Hermes has no way to change that, so it cannot resume itself."""

    def __init__(self, router: ModelRouter, core: GovernanceCore):
        self._router, self._core = router, core

    def complete(self, caller: Component, task_class: str, request: ModelRequest) -> RoutedResponse:
        if (
            caller is Component.HERMES
            and self._core.effective_mode(None) is not ControlMode.RUNNING
        ):
            raise RouterError("Hermes is stopped by the Governance Core")
        return self._router.complete(caller, task_class, request)

    def route(self, task_class: str) -> list[str]:
        return self._router.route(task_class)


class FounderNotices:
    """The Gateway's read-only view of what waits on the Founder: open approvals (acted on only
    on Direct Founder Controls) and the reminders and escalations of the last 7 days."""

    def __init__(self, core: GovernanceCore, store: MemoryStore, clock: Clock):
        self._core, self._store, self._clock = core, store, clock

    def notices(self):
        from datetime import timedelta

        from dyson_gateway.ports import Notice

        now = self._clock()
        out = [
            Notice(
                at=r.created_at, kind="approval", text=f"Approval waiting: {r.action_summary}"
            )  # fmt: skip
            for r in open_approvals(self._core, now)
        ]
        since = now - timedelta(days=7)
        for e in reversed(self._store.audit_events(limit=500)):
            if e.data.get("to") == "founder" and e.at >= since and len(out) < 20:
                text = e.summary.removeprefix("escalation to founder: ")
                out.append(Notice(at=e.at, kind="reminder", text=text))
        return out


class StatementsForGateway:
    """The Gateway's statement upload, to H. Only the Founder's session reaches it."""

    def __init__(self, finance, clock: Clock):
        self._finance, self._clock = finance, clock

    def upload(self, filename, period_start, period_end, content: bytes) -> int:
        import hashlib

        from dyson_contracts.finance import BankStatementUpload

        upload = BankStatementUpload(
            upload_id=uuid4(),
            uploaded_by=Component.FOUNDER,
            file_sha256=hashlib.sha256(content).hexdigest(),
            filename=filename,
            period_start=period_start,
            period_end=period_end,
            uploaded_at=self._clock(),
        )
        return self._finance.upload_statement(upload, content)


class ThreadsForGateway:
    """Conversations for the app. Archiving is a row in integration.thread_archive; the latest row
    per thread decides. Nothing is deleted (D-023)."""

    def __init__(self, store: MemoryStore, integ_dsn: str, clock: Clock):
        self._store, self._dsn, self._clock = store, integ_dsn, clock

    def _archived(self) -> set[UUID]:
        with psycopg.connect(self._dsn, row_factory=dict_row) as c:
            rows = c.execute(
                "SELECT DISTINCT ON (thread_id) thread_id, archived FROM integration.thread_archive"
                " ORDER BY thread_id, seq DESC"
            ).fetchall()
        return {r["thread_id"] for r in rows if r["archived"]}

    def summaries(self, archived: bool):
        from dyson_gateway.ports import ThreadSummary

        hidden = self._archived()
        return [
            ThreadSummary(
                thread_id=r["thread_id"],
                title=(r["first_line"] or "Conversation")[:80],
                last_at=r["last_at"],
                archived=r["thread_id"] in hidden,
            )  # fmt: skip
            for r in self._store.thread_summaries()
            if (r["thread_id"] in hidden) == archived
        ]

    def set_archived(self, thread_id: UUID, archived: bool) -> None:
        with psycopg.connect(self._dsn, autocommit=True) as c:
            c.execute(
                "INSERT INTO integration.thread_archive (thread_id, archived, at)"
                " VALUES (%s, %s, %s)",
                [thread_id, archived, self._clock()],
            )
