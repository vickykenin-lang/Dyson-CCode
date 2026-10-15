"""Receptor Monitoring & Health Controller (card E).

E observes and escalates; it never acts on a Receptor (LA-MON-05). It reports what it does not
know as plainly as what it does: a subject that never reported is "unknown", one whose last report
is older than the staleness window is "unverified", never silently "healthy" (LA-MON-06).

Every issue E raises becomes a Founder alert. The Founder is reminded at the approved interval
until the Founder acts on it or puts it on hold (D-009); a subject getting better on its own does
not close the alert. The repeated-failure threshold is 3 (D-010) and a subject is stale after
3 days without a report (D-011). All three come from policy/parameters.yaml, not code defaults.
"""

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from uuid import UUID, uuid4

from psycopg.types.json import Jsonb

from dyson_contracts.common import Component, Contract
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


class AlertState(StrEnum):
    OPEN = "open"  # the Founder is reminded at the interval
    HELD = "held"  # the Founder said to hold it: no reminders until released
    ACTED = "acted"  # the Founder acted on it: closed


class Alert(Contract):
    alert_id: UUID
    subject_kind: SubjectKind
    subject_id: str
    issue: str
    message: str
    state: AlertState
    raised_at: datetime
    last_notified_at: datetime
    reminders: int


class AlertError(Exception):
    pass


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
        reminder_interval: timedelta,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ):
        if repeated_failure_threshold < 1:
            raise ValueError("repeated_failure_threshold must be at least 1")
        if reminder_interval <= timedelta(0):
            raise ValueError("reminder_interval must be positive")
        self._reminder_interval = reminder_interval
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
            self._raise(after, "bad_status", f"{name} is {after.status.value}")
        if (after.consecutive_bad_reports == self._threshold
                and before.consecutive_bad_reports < self._threshold):  # fmt: skip
            n = self._threshold
            self._raise(
                after, "repeated_failure", f"{name}: repeated failure ({n} bad reports in a row)"
            )

    def sweep(self, kind: SubjectKind, subject_ids: list[str]) -> list[HealthView]:
        """Escalate subjects that went silent. Run periodically by the worker in Step 9."""
        stale = [v for v in self.expected(kind, subject_ids) if v.truth is not Truth.REPORTED]
        for v in stale:
            what = "has never reported" if v.truth is Truth.UNKNOWN else "is unverified (stale)"
            self._raise(v, "silent", f"{v.subject_kind.value} {v.subject_id} {what}")
        return stale

    # Founder alerts and reminders (D-009) -----------------------------------------------
    def alerts(self, include_closed: bool = False) -> list[Alert]:
        rows = self._c.execute(
            "SELECT alert_id, subject_kind, subject_id, issue, message, event, at"
            " FROM assurance.alert_events ORDER BY seq"
        ).fetchall()
        by_id: dict[UUID, dict] = {}
        for r in rows:
            a = by_id.setdefault(r["alert_id"], {
                "alert_id": r["alert_id"], "subject_kind": r["subject_kind"],
                "subject_id": r["subject_id"], "issue": r["issue"], "message": r["message"],
                "raised_at": r["at"], "last_notified_at": r["at"], "reminders": 0,
                "state": AlertState.OPEN})  # fmt: skip
            event = r["event"]
            if event == "reminded":
                a["reminders"] += 1
                a["last_notified_at"] = r["at"]
            elif event == "held":
                a["state"] = AlertState.HELD
            elif event == "released":
                a["state"] = AlertState.OPEN
                a["last_notified_at"] = r["at"]
            elif event == "acted":
                a["state"] = AlertState.ACTED
        out = [Alert.model_validate(a) for a in by_id.values()]
        return out if include_closed else [a for a in out if a.state is not AlertState.ACTED]

    def remind(self) -> list[Alert]:
        """Remind the Founder of every open alert not notified within the interval. Run by the
        worker (Step 9) at least as often as the interval."""
        now, due = self._clock(), []
        for a in self.alerts():
            if a.state is AlertState.OPEN and now - a.last_notified_at >= self._reminder_interval:
                current = self.view(a.subject_kind, a.subject_id)
                message = (f"Reminder: {a.message}. Open since {a.raised_at:%Y-%m-%d %H:%M} UTC;"
                           f" now {current.status.value} ({current.truth.value}).")  # fmt: skip
                self._alert_event(a, "reminded", Component.MONITORING)
                self._esc.escalate("founder", a.subject_id, message)
                due.append(a)
        return due

    def founder_acted(self, alert_id: UUID, by: Component, note: str = "") -> Alert:
        return self._founder_event(alert_id, by, "acted", note, {AlertState.OPEN, AlertState.HELD})

    def hold(self, alert_id: UUID, by: Component, note: str = "") -> Alert:
        return self._founder_event(alert_id, by, "held", note, {AlertState.OPEN})

    def release_hold(self, alert_id: UUID, by: Component, note: str = "") -> Alert:
        return self._founder_event(alert_id, by, "released", note, {AlertState.HELD})

    def _founder_event(self, alert_id, by, event, note, allowed) -> Alert:
        if by is not Component.FOUNDER:
            raise AlertError("only the Founder closes or holds an alert")
        a = {x.alert_id: x for x in self.alerts(include_closed=True)}.get(alert_id)
        if a is None:
            raise AlertError("unknown alert")
        if a.state not in allowed:
            raise AlertError(f"alert is {a.state.value}")
        self._alert_event(a, event, by, note)
        return {x.alert_id: x for x in self.alerts(include_closed=True)}[alert_id]

    def _alert_event(self, a, event: str, by: Component, note: str = "") -> None:
        self._c.execute(
            "INSERT INTO assurance.alert_events (alert_id, subject_kind, subject_id, issue,"
            " message, event, by_component, note, at) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)",
            [
                a.alert_id,
                SubjectKind(a.subject_kind).value,
                a.subject_id,
                a.issue,
                a.message,
                event,
                by.value,
                note,
                self._clock(),
            ],  # fmt: skip
        )

    def _raise(self, view: HealthView, issue: str, message: str) -> None:
        """E escalates to the Governance Core, the Founder Dashboard and the Founder; A decides.

        One open alert per subject and issue: while it is open or held, the same issue is not
        raised again; reminders carry it instead.
        """
        for a in self.alerts():
            if (a.subject_kind, a.subject_id, a.issue) == (view.subject_kind, view.subject_id,
                                                           issue):  # fmt: skip
                return
        alert = Alert(alert_id=uuid4(), subject_kind=view.subject_kind,
                      subject_id=view.subject_id, issue=issue, message=message,
                      state=AlertState.OPEN, raised_at=self._clock(),
                      last_notified_at=self._clock(), reminders=0)  # fmt: skip
        self._alert_event(alert, "raised", Component.MONITORING)
        receptor = view.subject_id if view.subject_kind is SubjectKind.RECEPTOR else None
        self._c.execute(
            "INSERT INTO assurance.escalations (source, receptor_id, message, at)"
            " VALUES ('monitoring', %s, %s, %s)",
            [receptor, message, self._clock()],
        )
        self._esc.escalate("governance", view.subject_id, message)
        self._esc.escalate("founder_dashboard", view.subject_id, message)
        self._esc.escalate("founder", view.subject_id, message)
