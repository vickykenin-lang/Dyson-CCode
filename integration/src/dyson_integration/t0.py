"""Test T0: the first Receptor. Synthetic, no money, with a planted fault (LA-IF-12).

T0 lives in Layer B. Layer A reaches it only through the five lanes (LA-IF-01):

- tasks:      `assign`, called only by G's lane adapter, with task ID and idempotency key;
- QA:         nothing from T0 itself; F's independent verifier (`T0Verifier`) looks at what T0
              actually published, never at what T0 says;
- financial:  `revenue_report` (always 0, T0 handles no money);
- monitoring: `health_report`;
- control:    `on_control`, A's STOP / PAUSE / RESUME.

The planted fault: asked to tally more than five numbers, T0 silently drops the last one, still
claims "done" and returns a receipt. Only independent verification catches it.
"""

from collections.abc import Callable
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

from dyson_contracts.common import Money
from dyson_contracts.control import ControlMode, ControlScope, ControlState
from dyson_contracts.finance import PaymentMethod, RevenueReport
from dyson_contracts.lanes import (
    HealthReport,
    HealthStatus,
    ReceptorClaim,
    ReceptorTaskResult,
    TaskAssignment,
)
from dyson_contracts.receptor import ReceptorManifest
from dyson_contracts.toolcalls import ToolCallRequest

RECEPTOR_ID = "T0"
FAULT_THRESHOLD = 5  # more numbers than this triggers the planted fault

MANIFEST = ReceptorManifest(
    receptor_id=RECEPTOR_ID,
    purpose="Synthetic, no-money test Receptor that tallies numbers and publishes notes.",
    tools=("t0.tally", "t0.publish", "t0.restart", "t0.read"),
    permissions=("t0.tally", "t0.publish", "t0.restart", "t0.read"),
    boundaries="Synthetic data only. No money, no customers, no external systems.",
    recovery_policy="Restart the T0 worker, at most recovery_attempt_limit times (D-008), "
    "then escalate to the Founder.",
    synthetic=True,
    handles_money=False,
)


class ReceptorDown(ConnectionError):
    pass


class TestReceptorT0:
    __test__ = False  # not a pytest test class

    def __init__(self, clock: Callable[[], datetime] = lambda: datetime.now(UTC)):
        self._clock = clock
        self.mode = ControlMode.RUNNING
        self.reachable = True  # False: T0's host is down
        self.broken = False  # True: T0 runs but fails; a restart clears it
        self.hard_broken = False  # True: a restart does not help
        self.published: dict[UUID, dict[str, Any]] = {}  # the real outputs, by task
        self.claims: list[ReceptorTaskResult] = []
        self.assignments: list[TaskAssignment] = []
        self.restarts = 0

    # Tasks lane (via G only) -------------------------------------------------------------
    def assign(self, assignment: TaskAssignment, arguments: dict[str, Any]) -> dict[str, Any]:
        self._up()
        if self.mode is not ControlMode.RUNNING:
            raise RuntimeError(f"T0 is {self.mode.value}; it takes no work")
        self.assignments.append(assignment)
        op = arguments.get("operation", "tally")
        if op == "restart":
            return self._restart(assignment)
        if self.broken or self.hard_broken:
            raise RuntimeError("T0 worker is failing")
        if op == "tally":
            numbers = [Decimal(str(n)) for n in arguments.get("numbers", [])]
            used = numbers[:-1] if len(numbers) > FAULT_THRESHOLD else numbers  # planted fault
            output = {"total": str(sum(used, Decimal(0))), "count": len(used)}
        elif op == "publish":
            output = {"note": str(arguments.get("note", "")), "published": True}
        elif op == "read":
            return {"status": self.mode.value, "tasks_done": len(self.published)}
        else:
            raise ValueError(f"T0 has no operation {op!r}")
        self.published[assignment.task_id] = output
        claim = ReceptorTaskResult(
            task_id=assignment.task_id,
            receptor_id=RECEPTOR_ID,
            claim=ReceptorClaim.DONE,
            output_ref=f"t0:{assignment.task_id}",
            reported_at=self._clock(),
            note="done",
        )
        self.claims.append(claim)
        return {
            "receipt_id": str(uuid4()),
            "output_ref": claim.output_ref,
            "claim": claim.model_dump(mode="json"),
        }

    def _restart(self, assignment: TaskAssignment) -> dict[str, Any]:
        self.restarts += 1
        if not self.hard_broken:
            self.broken = False
        self.published[assignment.task_id] = {"restarted": True}
        return {
            "receipt_id": str(uuid4()),
            "output_ref": f"t0:{assignment.task_id}",
            "claim": {"claim": "done", "note": "restarted"},
        }

    # Monitoring lane ---------------------------------------------------------------------
    def health_report(self) -> HealthReport | None:
        """None when T0 is down: it cannot report, and E sees silence, not health."""
        if not self.reachable:
            return None
        if self.mode is ControlMode.STOPPED:
            status = HealthStatus.OFFLINE
        elif self.broken or self.hard_broken:
            status = HealthStatus.FAILING
        else:
            status = HealthStatus.HEALTHY
        return HealthReport(
            receptor_id=RECEPTOR_ID,
            status=status,
            tasks_running=0,
            tasks_failed=0,
            kpis={"tasks_done": float(len(self.published))},
            failures=("worker failing",) if status is HealthStatus.FAILING else (),
            reported_at=self._clock(),
        )

    # Financial lane ----------------------------------------------------------------------
    def revenue_report(self, period_start: date, period_end: date) -> RevenueReport:
        return RevenueReport(
            report_id=uuid4(),
            receptor_id=RECEPTOR_ID,
            period_start=period_start,
            period_end=period_end,
            amount=Money(amount=Decimal("0"), currency="INR"),
            payment_method=PaymentMethod.OTHER,
            reference="synthetic T0",
            reported_at=self._clock(),
        )

    # Control lane ------------------------------------------------------------------------
    def on_control(self, command: Any, state: ControlState) -> None:
        """A's control bus. T0 never changes its own mode: only A's state does."""
        if state.scope is ControlScope.RECEPTOR and state.receptor_id != RECEPTOR_ID:
            return
        self.mode = state.mode

    def _up(self) -> None:
        if not self.reachable:
            raise ReceptorDown("T0 is unreachable")


def lane_delivery(t0: TestReceptorT0, operation: str) -> Callable[[ToolCallRequest], Any]:
    """G's adapter for one T0 tool: turns an authorized call into a Tasks-lane assignment."""

    def deliver(request: ToolCallRequest) -> Any:
        assignment = TaskAssignment(
            task_id=request.task_id,
            idempotency_key=request.idempotency_key,
            receptor_id=request.receptor_id,
            tool_call_id=request.call_id,
            instruction=operation,
            issued_via="G",
            issued_at=request.requested_at,
        )
        return t0.assign(assignment, {**request.arguments, "operation": operation})

    return deliver


class T0Verifier:
    """F's independent view of T0's real output (the QA / verification lane).

    It reads what T0 actually published and recomputes the expected result from the task as D
    recorded it. T0's claim plays no part.
    """

    def __init__(self, t0: TestReceptorT0, task_arguments: Callable[[UUID], dict[str, Any]]):
        self._t0 = t0
        self._args = task_arguments

    def observe(self, task_id: UUID, receptor_id: str | None, standard_id: str) -> Any:
        if receptor_id != RECEPTOR_ID:
            raise LookupError(f"this verifier only observes {RECEPTOR_ID}")
        published = self._t0.published.get(task_id)
        if standard_id == "STD-T0-TALLY":
            numbers = [Decimal(str(n)) for n in self._args(task_id).get("numbers", [])]
            expected = sum(numbers, Decimal(0))
            got = Decimal(published["total"]) if published else None
            return {
                "published": published,
                "expected_total": str(expected),
                "matches": got == expected,
            }
        if standard_id == "STD-T0-PUBLISH":
            return {"published": bool(published and published.get("published"))}
        if standard_id == "STD-T0-RESTART":
            report = self._t0.health_report()
            return {"health": report.status.value if report else "unreachable"}
        raise LookupError(f"no independent check for {standard_id}")
