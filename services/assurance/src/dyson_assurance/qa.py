"""Independent QA/QC Controller (card F).

F owns versioned quality standards. A standard has two separate lists of deterministic checks:
  technical  - run against what the tool returned;
  fitness    - run against F's own independent observation of the real output (Probe).
A task passes only when both lists pass (AMD-3). The Receptor's own report is never an input to a
pass (LA-QA-05). Superficial answers - "ok", "200 OK", "connected", "working", an empty result -
fail every check (LA-QA-06, LA-EVD-02).
"""

import hashlib
import json
from collections.abc import Callable
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any
from uuid import UUID, uuid4

from psycopg.types.json import Jsonb
from pydantic import Field, JsonValue

from dyson_contracts.common import Component, Contract, NonEmptyStr, ReceptorId
from dyson_contracts.evidence import EvidenceOutcome, EvidenceRecord, EvidenceStage
from dyson_contracts.lanes import ReceptorTaskResult, VerificationVerdict
from dyson_contracts.tasks import QA_CONSECUTIVE_FAILURE_LIMIT

from .ports import EscalationSink, EvidenceSink, Probe

SUPERFICIAL = {"", "ok", "200", "200 ok", "connected", "working", "done", "success", "true", "yes"}


def superficial(value: Any) -> bool:
    """True for answers that look like success but prove nothing."""
    if value is None or value == {} or value == []:
        return True
    if isinstance(value, bool):
        return True
    return isinstance(value, str | int) and str(value).strip().lower() in SUPERFICIAL


class CheckKind(StrEnum):
    EQUALS = "equals"  # value at path equals `value`
    PRESENT = "present"  # path exists and is not superficial
    AT_LEAST = "at_least"  # number at path >= `value`
    AT_MOST = "at_most"  # number at path <= `value`
    NOT_CONTAINS = "not_contains"  # text at path does not contain `value`


class Check(Contract):
    name: NonEmptyStr
    kind: CheckKind
    path: NonEmptyStr  # dotted path into the JSON, e.g. "receptor.status"
    value: JsonValue = None


class QualityStandard(Contract):
    standard_id: NonEmptyStr
    version: int = Field(ge=1)
    receptor_id: ReceptorId | None = None  # None: applies to any Receptor
    description: NonEmptyStr
    technical: tuple[Check, ...] = Field(min_length=1)
    fitness: tuple[Check, ...] = Field(min_length=1)


class Finding(Contract):
    check: str
    passed: bool
    detail: str


_MISSING = object()


def _get(data: Any, path: str) -> Any:
    for part in path.split("."):
        if not isinstance(data, dict) or part not in data:
            return _MISSING
        data = data[part]
    return data


def run_check(check: Check, data: Any) -> Finding:
    if superficial(data):
        return Finding(check=check.name, passed=False, detail="superficial or empty output")
    got = _get(data, check.path)
    if got is _MISSING:
        return Finding(check=check.name, passed=False, detail=f"{check.path} missing")
    match check.kind:
        case CheckKind.EQUALS:
            ok = got == check.value
        case CheckKind.PRESENT:
            ok = not superficial(got)
        case CheckKind.AT_LEAST | CheckKind.AT_MOST:
            if not isinstance(got, int | float) or isinstance(got, bool):
                return Finding(check=check.name, passed=False, detail=f"{check.path} not a number")
            ok = got >= check.value if check.kind is CheckKind.AT_LEAST else got <= check.value
        case CheckKind.NOT_CONTAINS:
            ok = isinstance(got, str) and str(check.value) not in got
    return Finding(check=check.name, passed=ok, detail=f"{check.path}={got!r}")


class QAError(Exception):
    pass


class QAController:
    def __init__(
        self,
        conn,
        probe: Probe,
        evidence: EvidenceSink,
        escalation: EscalationSink,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
        environment: str = "local",
    ):
        self._c, self._probe, self._evidence, self._esc = conn, probe, evidence, escalation
        self._clock = clock
        self._env = environment

    # Standards (LA-QA-01) ---------------------------------------------------------------
    def define_standard(self, standard: QualityStandard) -> None:
        """Standards are versioned; a published version never changes."""
        latest = self.standard(standard.standard_id)
        expected = (latest.version + 1) if latest else 1
        if standard.version != expected:
            raise QAError(f"next version of {standard.standard_id} must be {expected}")
        self._c.execute(
            "INSERT INTO assurance.qa_standards (standard_id, version, body, defined_at)"
            " VALUES (%s, %s, %s, %s)",
            [standard.standard_id, standard.version, Jsonb(standard.model_dump(mode="json")),
             self._clock()],
        )  # fmt: skip

    def standard(self, standard_id: str) -> QualityStandard | None:
        row = self._c.execute(
            "SELECT body FROM assurance.qa_standards WHERE standard_id = %s"
            " ORDER BY version DESC LIMIT 1",
            [standard_id],
        ).fetchone()
        return QualityStandard.model_validate(row["body"]) if row else None

    # Verification (LA-QA-02, LA-QA-05, LA-QA-06) ------------------------------------------
    def verify(
        self,
        task_id: UUID,
        receptor_id: str | None,
        standard_id: str,
        tool_result: JsonValue,
        receptor_claim: ReceptorTaskResult | None = None,
    ) -> VerificationVerdict:
        """Verify one task. The Receptor's claim is recorded for audit but never decides."""
        std = self.standard(standard_id)
        if std is None:
            raise QAError(f"no quality standard {standard_id}")
        if std.receptor_id is not None and std.receptor_id != receptor_id:
            raise QAError(f"{standard_id} is not a standard for {receptor_id}")
        observed = self._probe.observe(task_id, receptor_id, standard_id)  # raises: no verdict
        technical = [run_check(c, tool_result) for c in std.technical]
        fitness = [run_check(c, observed) for c in std.fitness]
        tech_ok = all(f.passed for f in technical)
        fit_ok = all(f.passed for f in fitness)
        now = self._clock()
        ref = "sha256:" + _digest({"tool_result": tool_result, "observed": observed})
        # Stage 6: the live request reached the Receptor and its result passed the technical
        # checks. Stage 7 adds F's own observation of the output (AMD-3: checked separately).
        live = EvidenceRecord(
            evidence_id=uuid4(),
            capability=standard_id,
            provider=receptor_id or "core",
            stage=EvidenceStage.LIVE_REQUEST_VERIFIED,
            outcome=EvidenceOutcome.PASSED if tech_ok else EvidenceOutcome.FAILED,
            environment=self._env,
            scope=receptor_id or "core",
            recorded_by=Component.QA_QC,
            recorded_at=now,
            artifact_ref=ref,
            task_id=task_id,
            detail="; ".join(
                f"{f.check}: {'pass' if f.passed else 'FAIL'} ({f.detail})" for f in technical
            )[:2000],  # fmt: skip
        )
        evidence = EvidenceRecord(
            evidence_id=uuid4(),
            capability=standard_id,
            provider=receptor_id or "core",
            stage=EvidenceStage.REAL_OUTPUT_VERIFIED,
            outcome=EvidenceOutcome.PASSED if tech_ok and fit_ok else EvidenceOutcome.FAILED,
            environment=self._env,
            scope=receptor_id or "core",
            recorded_by=Component.QA_QC,
            recorded_at=now,
            artifact_ref=ref,
            task_id=task_id,
            detail="; ".join(
                f"{f.check}: {'pass' if f.passed else 'FAIL'} ({f.detail})"
                for f in technical + fitness
            )[:2000],  # fmt: skip
        )
        findings = {
            "technical": [f.model_dump() for f in technical],
            "fitness": [f.model_dump() for f in fitness],
            "receptor_claim": receptor_claim.model_dump(mode="json") if receptor_claim else None,
        }
        self._c.execute(
            "INSERT INTO assurance.qa_verdicts (task_id, receptor_id, standard_id,"
            " standard_version, technical_success, fit_for_purpose, findings, evidence_id, at)"
            " VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)",
            [task_id, receptor_id, std.standard_id, std.version, tech_ok, fit_ok, Jsonb(findings),
             evidence.evidence_id, now],
        )  # fmt: skip
        self._evidence.record(live, receptor_id)
        self._evidence.record(evidence, receptor_id)
        if not (tech_ok and fit_ok):
            self._maybe_hold(task_id, receptor_id)
        return VerificationVerdict(
            task_id=task_id,
            receptor_id=receptor_id,
            technical_success=tech_ok,
            fit_for_purpose=fit_ok,
            evidence_ids=(evidence.evidence_id,),
            verified_by=Component.QA_QC,
            verified_at=now,
        )

    def consecutive_failures(self, task_id: UUID) -> int:
        rows = self._c.execute(
            "SELECT technical_success AND fit_for_purpose AS ok FROM assurance.qa_verdicts"
            " WHERE task_id = %s ORDER BY seq DESC",
            [task_id],
        ).fetchall()
        n = 0
        for r in rows:
            if r["ok"]:
                break
            n += 1
        return n

    def _maybe_hold(self, task_id: UUID, receptor_id: str | None) -> None:
        """LA-QA-03: after three consecutive failures F triggers HOLD and notifies a person."""
        n = self.consecutive_failures(task_id)
        if n == QA_CONSECUTIVE_FAILURE_LIMIT:
            msg = f"HOLD: {n} consecutive QA/QC failures on task {task_id}"
            self._record_escalation("qa", receptor_id, task_id, msg)
            self._esc.escalate("human_reviewer", receptor_id or "core", msg, task_id)
            self._esc.escalate("governance", receptor_id or "core", msg, task_id)

    # Audit and escalations (LA-QA-04) ---------------------------------------------------
    def receive_escalation(self, receptor_id: str, task_id: UUID | None, message: str) -> None:
        self._record_escalation("receptor", receptor_id, task_id, message)

    def audit_task(self, task_id: UUID) -> list[dict]:
        return self._c.execute(
            "SELECT standard_id, standard_version, technical_success, fit_for_purpose, findings,"
            " evidence_id, at FROM assurance.qa_verdicts WHERE task_id = %s ORDER BY seq",
            [task_id],
        ).fetchall()

    def escalations(self, source: str | None = None) -> list[dict]:
        if source:
            return self._c.execute(
                "SELECT * FROM assurance.escalations WHERE source = %s ORDER BY seq", [source]
            ).fetchall()
        return self._c.execute("SELECT * FROM assurance.escalations ORDER BY seq").fetchall()

    def _record_escalation(self, source, receptor_id, task_id, message) -> None:
        self._c.execute(
            "INSERT INTO assurance.escalations (source, receptor_id, task_id, message, at)"
            " VALUES (%s, %s, %s, %s, %s)",
            [source, receptor_id, task_id, message, self._clock()],
        )

    def summary(self) -> dict[str, int]:
        row = self._c.execute(
            "SELECT count(*) FILTER (WHERE technical_success AND fit_for_purpose) AS passed,"
            " count(*) FILTER (WHERE NOT (technical_success AND fit_for_purpose)) AS failed"
            " FROM assurance.qa_verdicts"
        ).fetchone()
        return {"passed": row["passed"], "failed": row["failed"]}


def _digest(value: Any) -> str:
    blob = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(blob.encode()).hexdigest()
