"""Receptor Monitoring & Health Controller (card E).

E observes and escalates; it never acts on a Receptor (LA-MON-05). It reports what it does not
know as plainly as what it does: a subject that never reported is "unknown", one whose last report
is older than the staleness window is "unverified", never silently "healthy" (LA-MON-06).

The staleness window and the repeated-failure threshold have no figures in the PRD; they are
constructor arguments with no defaults and become Founder-set parameters when Step 9 wires E.
"""

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from enum import StrEnum

from psycopg.types.json import Jsonb

from dyson_contracts.common import Contract
from dyson_contracts.lanes import HealthReport, HealthStatus

from .ports import EscalationSink

BAD = {HealthStatus.FAILING, HealthStatus.OFFLINE}


class SubjectKind(StrEnum):
    RECEPTOR = "receptor"
    MODEL = "model"
    TOOL = "tool"
    CORE = "core"


class Truth(StrEnum):
    """How much E actually knows about a subject right now."""

    REPORTED = "reported"  # a fresh report
    UNVERIFIED = "unverified"  # the last report is stale
    UNKNOWN = "unknown"  # never reported


class HealthView(Contract):
    subject_kind: SubjectKind
    subject_id: str
    status: HealthStatus
    truth: Truth
    last_report_at: datetime | None
    tasks_running: int | None
    tasks_failed: int | None
    kpis: dict[str, float]
    failures: tuple[str, ...]
    consecutive_bad_reports: int


class Monitor:
    def __init__(
        self,
        conn,
        escalation: EscalationSink,
        stale_after: timedelta,
        repeated_failure_threshold: int,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ):
        if repeated_failure_threshold < 1:
            raise ValueError("repeated_failure_threshold must be at least 1")
        self._c, self._esc = conn, escalation
        self._stale_after = stale_after
        self._threshold = repeated_failure_threshold
        self._clock = clock

    # Intake (LA-MON-01, LA-MON-02) ------------------------------------------------------
    def ingest(self, report: HealthReport) -> HealthView:
        """A Receptor's report on the Monitoring / Health lane."""
        return self._record(SubjectKind.RECEPTOR, report.receptor_id, report.status,
                            report.model_dump(mode="json"), report.reported_at)  # fmt: skip

    def report_component(self, kind: SubjectKind, subject_id: str, status: HealthStatus,
                         detail: str = "") -> HealthView:  # fmt: skip
        """Health of a model, tool or Core component, as seen by its own checks."""
        if kind is SubjectKind.RECEPTOR:
            raise ValueError("Receptors report through the Monitoring / Health lane")
        now = self._clock()
        report = {"status": status.value, "detail": detail, "reported_at": now.isoformat()}
        return self._record(kind, subject_id, status, report, now)

    def _record(self, kind, subject_id, status, report, at) -> HealthView:
        before = self.view(kind, subject_id)
        self._c.execute(
            "INSERT INTO assurance.health (subject_kind, subject_id, status, report, at)"
            " VALUES (%s, %s, %s, %s, %s)",
            [kind.value, subject_id, status.value, Jsonb(report), at],
        )
        after = self.view(kind, subject_id)
        self._detect(before, after)
        return after

    # Views (LA-MON-04, LA-MON-06) -------------------------------------------------------
    def view(self, kind: SubjectKind, subject_id: str) -> HealthView:
        rows = self._c.execute(
            "SELECT status, report, at FROM assurance.health WHERE subject_kind = %s"
            " AND subject_id = %s ORDER BY seq DESC LIMIT %s",
            [kind.value, subject_id, self._threshold],
        ).fetchall()
        if not rows:
            return HealthView(
                subject_kind=kind, subject_id=subject_id, status=HealthStatus.UNKNOWN,
                truth=Truth.UNKNOWN, last_report_at=None, tasks_running=None, tasks_failed=None,
                kpis={}, failures=(), consecutive_bad_reports=0,
            )  # fmt: skip
        last = rows[0]
        stale = self._clock() - last["at"] > self._stale_after
        bad = 0
        for r in rows:
            if HealthStatus(r["status"]) not in BAD:
                break
            bad += 1
        rep = last["report"]
        return HealthView(
            subject_kind=kind,
            subject_id=subject_id,
            status=HealthStatus.UNKNOWN if stale else HealthStatus(last["status"]),
            truth=Truth.UNVERIFIED if stale else Truth.REPORTED,
            last_report_at=last["at"],
            tasks_running=rep.get("tasks_running"),
            tasks_failed=rep.get("tasks_failed"),
            kpis=rep.get("kpis", {}),
            failures=tuple(rep.get("failures", ())),
            consecutive_bad_reports=bad,
        )

    def overview(self) -> list[HealthView]:
        subjects = self._c.execute(
            "SELECT DISTINCT subject_kind, subject_id FROM assurance.health ORDER BY 1, 2"
        ).fetchall()
        return [self.view(SubjectKind(s["subject_kind"]), s["subject_id"]) for s in subjects]

    def expected(self, kind: SubjectKind, subject_ids: list[str]) -> list[HealthView]:
        """Views for subjects that should exist, so a silent one shows as unknown."""
        return [self.view(kind, s) for s in subject_ids]

    # Detection and escalation (LA-MON-03, LA-MON-05) ------------------------------------
    def _detect(self, before: HealthView, after: HealthView) -> None:
        name = f"{after.subject_kind.value} {after.subject_id}"
        if after.status in BAD and before.status not in BAD:
            self._raise(after, f"{name} is {after.status.value}")
        if (after.consecutive_bad_reports == self._threshold
                and before.consecutive_bad_reports < self._threshold):  # fmt: skip
            self._raise(after, f"{name}: repeated failure ({self._threshold} bad reports in a row)")

    def sweep(self, kind: SubjectKind, subject_ids: list[str]) -> list[HealthView]:
        """Escalate subjects that went silent. Run periodically by the worker in Step 9."""
        stale = [v for v in self.expected(kind, subject_ids) if v.truth is not Truth.REPORTED]
        for v in stale:
            what = "has never reported" if v.truth is Truth.UNKNOWN else "is unverified (stale)"
            self._raise(v, f"{v.subject_kind.value} {v.subject_id} {what}")
        return stale

    def _raise(self, view: HealthView, message: str) -> None:
        """E escalates to the Governance Core and the Founder Dashboard; A decides."""
        receptor = view.subject_id if view.subject_kind is SubjectKind.RECEPTOR else None
        self._c.execute(
            "INSERT INTO assurance.escalations (source, receptor_id, message, at)"
            " VALUES ('monitoring', %s, %s, %s)",
            [receptor, message, self._clock()],
        )
        self._esc.escalate("governance", view.subject_id, message)
        self._esc.escalate("founder_dashboard", view.subject_id, message)
