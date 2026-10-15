"""Orchestrator (card D): task IDs, the durable queue, the state machine, retries and escalation.

Each task moves only through the legal transitions in dyson_contracts.tasks. Every move is one
database transaction that updates the queue row and appends to the transition history, so a
restart resumes exactly where work stopped, with or without any voice session open.

Idempotency key per attempt: "<task_id>:a<attempt>". A network retry of the same attempt reuses
the key, so G never runs it twice; a QA correction-and-retest is a new attempt with a new key.
"""

from collections.abc import Callable
from datetime import UTC, datetime
from decimal import Decimal
from importlib.resources import files
from typing import Any
from uuid import UUID, uuid4

import psycopg
from psycopg import sql
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from dyson_contracts.approvals import ApprovalCategory
from dyson_contracts.common import Component, Contract, RiskLevel
from dyson_contracts.control import ControlMode, ControlScope, ControlState
from dyson_contracts.tasks import (
    ACTIVE_STATES,
    QA_CONSECUTIVE_FAILURE_LIMIT,
    TaskState,
    TaskTransition,
    TaskTrigger,
    next_state,
)
from dyson_contracts.toolcalls import ToolCallRequest

from .ports import (
    EscalationPort,
    GovernancePort,
    QAPort,
    TaskEventSink,
    TaskPlan,
    ToolHubPort,
)

S, T = TaskState, TaskTrigger
WORKABLE = (S.ACCEPTED, S.APPROVAL_NEEDED, S.RUNNING, S.FAILED)


class TaskView(Contract):
    task_id: UUID
    instruction: str
    receptor_id: str | None
    state: TaskState
    attempt: int
    consecutive_qa_failures: int
    approval_id: UUID | None
    hold_reason: str | None
    escalated: bool
    last_error: str
    evidence_ids: tuple[UUID, ...]
    plan: TaskPlan


class OrchestratorError(Exception):
    pass


def action_payload(plan: TaskPlan) -> dict[str, Any]:
    """The exact action an approval names. Matches the Tool Hub's action payload (Step 9 test)."""
    spend = plan.estimated_spend
    return {
        "tool_id": plan.tool_id,
        "receptor_id": plan.receptor_id,
        "arguments": plan.arguments,
        "amount": str(spend.amount) if spend else "0",
        "currency": spend.currency if spend else None,
    }


def approval_needed(plan: TaskPlan) -> ApprovalCategory | None:
    if plan.estimated_spend is not None and plan.estimated_spend.amount > Decimal("0"):
        return ApprovalCategory.FINANCIAL  # AMD-2
    if plan.risk is RiskLevel.HIGH:
        return ApprovalCategory.OTHER
    return None


class Orchestrator:
    def __init__(
        self,
        dsn: str,
        tool_hub: ToolHubPort,
        governance: GovernancePort,
        qa: QAPort,
        escalation: EscalationPort,
        events: TaskEventSink | None = None,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ):
        self._conn = psycopg.connect(dsn, autocommit=True, row_factory=dict_row)
        self._hub, self._gov, self._qa, self._esc = tool_hub, governance, qa, escalation
        self._events = events
        self._clock = clock
        self.event_backlog: list[TaskTransition] = []

    def close_connection(self) -> None:
        self._conn.close()

    # Intake (LA-ORC-01) -----------------------------------------------------------------
    def submit(self, instruction_key: str, instruction: str, plan: TaskPlan) -> TaskView:
        """Accept an instruction once. Sending the same instruction_key again returns the
        same task instead of creating a second one (LA-REL-02)."""
        now = self._clock()
        pending: list[TaskTransition] = []
        with self._conn.transaction():
            row = self._conn.execute(
                "INSERT INTO orchestrator.tasks (task_id, instruction_key, instruction,"
                " receptor_id,"
                " plan, state, created_at, updated_at) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)"
                " ON CONFLICT (instruction_key) DO NOTHING RETURNING task_id",
                [uuid4(), instruction_key, instruction, plan.receptor_id,
                 Jsonb(plan.model_dump(mode="json")), S.ACCEPTED.value, now, now],
            ).fetchone()  # fmt: skip
            if row is not None:
                tr = TaskTransition(
                    task_id=row["task_id"], from_state=None, to_state=S.ACCEPTED, trigger=None,
                    actor=Component.ORCHESTRATOR, at=now, reason="instruction accepted",
                )  # fmt: skip
                self._insert_transition(tr)
                pending.append(tr)
                task_id = row["task_id"]
            else:
                task_id = self._conn.execute(
                    "SELECT task_id FROM orchestrator.tasks WHERE instruction_key = %s",
                    [instruction_key],
                ).fetchone()["task_id"]
        self._forward(pending)
        return self.get(task_id)

    def get(self, task_id: UUID) -> TaskView:
        row = self._conn.execute(
            "SELECT * FROM orchestrator.tasks WHERE task_id = %s", [task_id]
        ).fetchone()
        if row is None:
            raise OrchestratorError("unknown task")
        return _view(row)

    def history(self, task_id: UUID) -> list[TaskTransition]:
        rows = self._conn.execute(
            "SELECT task_id, from_state, to_state, trigger, actor, reason, at"
            " FROM orchestrator.transitions WHERE task_id = %s ORDER BY seq",
            [task_id],
        ).fetchall()
        return [TaskTransition(**r) for r in rows]

    # The worker (LA-ORC-02) -------------------------------------------------------------
    def tick(self, limit: int = 50) -> int:
        """Advance up to `limit` tasks one step each. Safe to run from several workers at
        once: each task is claimed with FOR UPDATE SKIP LOCKED."""
        done: set[UUID] = set()
        for _ in range(limit):
            pending: list[TaskTransition] = []
            with self._conn.transaction():
                row = self._conn.execute(
                    "SELECT * FROM orchestrator.tasks WHERE state = ANY(%s)"
                    " AND NOT (state = 'failed' AND escalated) AND NOT (task_id = ANY(%s))"
                    " ORDER BY updated_at LIMIT 1 FOR UPDATE SKIP LOCKED",
                    [[s.value for s in WORKABLE], list(done)],
                ).fetchone()
                if row is None:
                    break
                done.add(row["task_id"])
                self._advance(row, pending)
            self._forward(pending)
        return len(done)

    def _advance(self, row: dict, pending: list[TaskTransition]) -> None:
        plan = TaskPlan.model_validate(row["plan"])
        try:
            mode = self._gov.effective_mode(plan.receptor_id)
        except Exception as exc:
            self._note(row, f"governance unreachable: {type(exc).__name__}")
            return
        if mode is not ControlMode.RUNNING:
            return  # STOP / PAUSE reach tasks through on_control; nothing moves meanwhile
        state = TaskState(row["state"])
        if state is S.ACCEPTED:
            category = approval_needed(plan)
            if category is None:
                self._move(row, T.CHECKS_PASSED, "no approval required", pending)
                return
            approval_id = self._gov.propose_external_action(
                action_payload(plan), category, plan.summary, row["task_id"]
            )
            self._move(row, T.APPROVAL_REQUIRED, f"{category} approval requested", pending,
                       approval_id=approval_id)  # fmt: skip
        elif state is S.APPROVAL_NEEDED:
            status = self._gov.approval_status(row["approval_id"])
            if status == "approved":
                self._move(row, T.FOUNDER_APPROVED, "Founder approved", pending)
            elif status == "rejected":
                self._move(row, T.FOUNDER_REJECTED, "Founder rejected", pending)
        elif state is S.RUNNING:
            self._run(row, plan, pending)
        elif state is S.FAILED:
            # Only QA failures below the limit reach here (others are escalated): correct and
            # retest as a new attempt with a new idempotency key.
            self._move(row, T.RETRY, "retest after QA/QC failure", pending,
                       attempt=row["attempt"] + 1)  # fmt: skip

    def _run(self, row: dict, plan: TaskPlan, pending: list[TaskTransition]) -> None:
        request = ToolCallRequest(
            call_id=uuid4(),
            task_id=row["task_id"],
            idempotency_key=f"{row['task_id']}:a{row['attempt']}",
            tool_id=plan.tool_id,
            requested_by=Component.ORCHESTRATOR,
            receptor_id=plan.receptor_id,
            arguments=plan.arguments,
            risk=plan.risk,
            estimated_spend=plan.estimated_spend,
            approval_id=row["approval_id"],
            requested_at=self._clock(),
        )
        try:
            run = self._hub.call(request)
        except Exception as exc:  # outcome unknown: same key next tick, never a duplicate
            self._note(row, f"tool hub unreachable: {type(exc).__name__}")
            return
        if run.status == "duplicate" and run.result is None and not run.error:
            return  # the first attempt is still running
        if run.status == "denied":
            self._fail_and_escalate(row, f"denied by G: {', '.join(run.denied_checks)}", pending)
            return
        if run.status == "failed" or (run.status == "duplicate" and run.error):
            self._fail_and_escalate(row, f"tool failed: {run.error}", pending)
            return
        try:
            verdict = self._qa.verify(row["task_id"], plan, run)
        except Exception as exc:  # F unreachable: stay running, verify on a later tick
            self._note(row, f"QA/QC unreachable: {type(exc).__name__}")
            return
        if verdict.task_id != row["task_id"]:
            self._note(row, "verdict for a different task ignored")
            return
        if verdict.passed:  # the only way to completed-verified (LA-ORC-06)
            evidence = Jsonb([str(e) for e in verdict.evidence_ids])
            self._move(row, T.VERIFIED, "QA/QC verified the real output", pending,
                       consecutive_qa_failures=0, evidence_ids=evidence)  # fmt: skip
            return
        failures = row["consecutive_qa_failures"] + 1
        what = "fitness for purpose" if verdict.technical_success else "technical success"
        reason = f"QA/QC failed ({what}), failure {failures}"
        self._move(row, T.VERIFICATION_FAILED, reason, pending,
                   consecutive_qa_failures=failures)  # fmt: skip
        if failures >= QA_CONSECUTIVE_FAILURE_LIMIT:  # AMD-3: HOLD and a human reviewer
            row = self._reload(row["task_id"])
            self._move(row, T.QA_FAILURE_LIMIT, f"{failures} consecutive QA/QC failures", pending,
                       hold_reason="qa", escalated=True)  # fmt: skip
            self._esc.escalate(row["task_id"], f"HOLD after {failures} consecutive QA/QC failures")

    def _fail_and_escalate(self, row: dict, reason: str, pending) -> None:
        self._move(row, T.EXECUTION_FAILED, reason, pending, escalated=True, last_error=reason)
        self._esc.escalate(row["task_id"], reason)

    # STOP / PAUSE / RESUME (AMD-5, D-002, D-007) ----------------------------------------
    def on_control(self, command: Any, state: ControlState) -> int:
        """Listener for the Governance Core's control bus. Signature matches A's listeners:
        (command or None for a breach, resulting ControlState)."""
        scope = "master" if state.scope is ControlScope.MASTER else state.receptor_id
        where, params = ("TRUE", []) if scope == "master" else ("receptor_id = %s", [scope])
        pending: list[TaskTransition] = []
        moved = 0
        with self._conn.transaction():
            if state.mode is ControlMode.RUNNING:
                rows = self._conn.execute(
                    "SELECT * FROM orchestrator.tasks WHERE control_scope = %s AND resume_to IS NOT"
                    " NULL AND (state = 'stopped' OR (state = 'held' AND hold_reason = 'control'))"
                    " FOR UPDATE",
                    [scope],
                ).fetchall()
                for row in rows:
                    self._move(row, T.RESUME_AUTHORIZED, "resumed by the Governance Core", pending,
                               resume_to=TaskState(row["resume_to"]), hold_reason=None,
                               control_scope=None, clear_resume=True)  # fmt: skip
                    moved += 1
            else:
                trigger = T.STOP if state.mode is ControlMode.STOPPED else T.PAUSE
                targets = ACTIVE_STATES if trigger is T.STOP else ACTIVE_STATES - {S.HELD}
                rows = self._conn.execute(
                    f"SELECT * FROM orchestrator.tasks WHERE {where} AND state = ANY(%s)"
                    " FOR UPDATE",
                    [*params, [s.value for s in targets]],
                ).fetchall()
                for row in rows:
                    current = TaskState(row["state"])
                    if current is S.HELD and row["hold_reason"] == "control":
                        resume_to = row["resume_to"]  # paused earlier: keep what it interrupted
                    elif current is S.HELD:
                        resume_to = None  # QA hold: stays with the reviewer, never auto-resumed
                    else:
                        resume_to = current.value
                    self._move(row, trigger, f"{trigger.value} from the Governance Core", pending,
                               hold_reason="control" if trigger is T.PAUSE else None,
                               control_scope=scope, set_resume_to=resume_to)  # fmt: skip
                    moved += 1
        self._forward(pending)
        return moved

    # Human decisions --------------------------------------------------------------------
    def review(self, task_id: UUID, resume: bool, by: Component) -> TaskView:
        """A human reviewer or the Founder decides a task held after QA/QC failures."""
        if by not in (Component.HUMAN_REVIEWER, Component.FOUNDER):
            raise OrchestratorError("only a human reviewer or the Founder decides a held task")
        pending: list[TaskTransition] = []
        with self._conn.transaction():
            row = self._lock(task_id)
            if row["state"] != S.HELD.value or row["hold_reason"] != "qa":
                raise OrchestratorError("task is not held for review")
            if resume:
                self._move(row, T.REVIEWER_RESUME, f"{by.value} allowed another attempt", pending,
                           actor=by, attempt=row["attempt"] + 1, consecutive_qa_failures=0,
                           hold_reason=None, escalated=False)  # fmt: skip
            else:
                self._move(row, T.REVIEWER_CLOSE, f"{by.value} closed the task", pending, actor=by)
        self._forward(pending)
        return self.get(task_id)

    def close(self, task_id: UUID) -> TaskView:
        """Housekeeping once the outcome is recorded."""
        pending: list[TaskTransition] = []
        with self._conn.transaction():
            self._move(self._lock(task_id), T.HOUSEKEEPING, "outcome recorded", pending)
        self._forward(pending)
        return self.get(task_id)

    # Internals --------------------------------------------------------------------------
    def _lock(self, task_id: UUID) -> dict:
        row = self._conn.execute(
            "SELECT * FROM orchestrator.tasks WHERE task_id = %s FOR UPDATE", [task_id]
        ).fetchone()
        if row is None:
            raise OrchestratorError("unknown task")
        return row

    def _reload(self, task_id: UUID) -> dict:
        return self._lock(task_id)

    def _move(
        self,
        row: dict,
        trigger: TaskTrigger,
        reason: str,
        pending: list,
        *,
        actor: Component = Component.ORCHESTRATOR,
        resume_to: TaskState | None = None,
        set_resume_to: str | None = None,
        clear_resume: bool = False,
        **updates,
    ) -> None:
        current = TaskState(row["state"])
        target = next_state(current, trigger, resume_to=resume_to)
        now = self._clock()
        tr = TaskTransition(
            task_id=row["task_id"], from_state=current, to_state=target, trigger=trigger,
            actor=actor, at=now, reason=reason,
        )  # fmt: skip
        if trigger in (T.STOP, T.PAUSE):
            updates["resume_to"] = set_resume_to
        if clear_resume:
            updates["resume_to"] = None
        updates.update(state=target.value, updated_at=now)
        cols = sql.SQL(", ").join(
            sql.SQL("{} = {}").format(sql.Identifier(k), sql.Placeholder()) for k in updates
        )
        self._conn.execute(
            sql.SQL("UPDATE orchestrator.tasks SET {} WHERE task_id = {}").format(
                cols, sql.Placeholder()
            ),
            [*updates.values(), row["task_id"]],
        )
        self._insert_transition(tr)
        pending.append(tr)
        row.update(updates)

    def _note(self, row: dict, error: str) -> None:
        self._conn.execute(
            "UPDATE orchestrator.tasks SET last_error = %s, updated_at = %s WHERE task_id = %s",
            [error, self._clock(), row["task_id"]],
        )

    def _insert_transition(self, tr: TaskTransition) -> None:
        self._conn.execute(
            "INSERT INTO orchestrator.transitions (task_id, from_state, to_state, trigger, actor,"
            " reason, at) VALUES (%s, %s, %s, %s, %s, %s, %s)",
            [tr.task_id, tr.from_state.value if tr.from_state else None, tr.to_state.value,
             tr.trigger.value if tr.trigger else None, tr.actor.value, tr.reason, tr.at],
        )  # fmt: skip

    def _forward(self, transitions: list[TaskTransition]) -> None:
        for tr in transitions:
            try:
                if self._events is None:
                    raise RuntimeError("no event sink")
                self._events.record(tr)
            except Exception:
                self.event_backlog.append(tr)  # the transitions table stays the durable record


def _view(row: dict) -> TaskView:
    return TaskView(
        task_id=row["task_id"],
        instruction=row["instruction"],
        receptor_id=row["receptor_id"],
        state=TaskState(row["state"]),
        attempt=row["attempt"],
        consecutive_qa_failures=row["consecutive_qa_failures"],
        approval_id=row["approval_id"],
        hold_reason=row["hold_reason"],
        escalated=row["escalated"],
        last_error=row["last_error"],
        evidence_ids=tuple(UUID(e) for e in row["evidence_ids"]),
        plan=TaskPlan.model_validate(row["plan"]),
    )


def migrate(dsn: str, app_role: str) -> None:
    """Run as the owner role. The app role reads and inserts; it updates only the queue table."""
    with psycopg.connect(dsn, autocommit=True, row_factory=dict_row) as conn:
        exists = conn.execute(
            "SELECT to_regclass('orchestrator.schema_migrations') AS t"
        ).fetchone()
        done = (
            {
                r["version"]
                for r in conn.execute("SELECT version FROM orchestrator.schema_migrations")
            }
            if exists["t"]
            else set()
        )
        mig = files("dyson_orchestrator").joinpath("migrations")
        for path in sorted(
            (p for p in mig.iterdir() if p.name.endswith(".sql")), key=lambda p: p.name
        ):
            if int(path.name.split("_", 1)[0]) not in done:
                with conn.transaction():
                    conn.execute(path.read_text("utf-8"))
        role = sql.Identifier(app_role)
        with conn.transaction():
            for stmt in (
                "GRANT USAGE ON SCHEMA orchestrator TO {}",
                "GRANT SELECT, INSERT, UPDATE ON orchestrator.tasks TO {}",
                "GRANT SELECT, INSERT ON orchestrator.transitions TO {}",
                "GRANT USAGE ON SEQUENCE orchestrator.transitions_seq_seq TO {}",
                "GRANT SELECT ON orchestrator.schema_migrations TO {}",
            ):
                conn.execute(sql.SQL(stmt).format(role))
