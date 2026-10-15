"""QA/QC Controller (F) and Monitoring & Health Controller (E)."""

from uuid import uuid4

import psycopg
import pytest
from assurance_testkit import NOW

from dyson_assurance.monitoring import SubjectKind, Truth
from dyson_assurance.qa import Check, CheckKind, QAError, QualityStandard, superficial
from dyson_contracts.common import Component
from dyson_contracts.evidence import EvidenceOutcome, EvidenceStage
from dyson_contracts.lanes import HealthReport, HealthStatus, ReceptorClaim, ReceptorTaskResult


def _standard(version=1, receptor="T0"):
    return QualityStandard(
        standard_id="t0-inspection",
        version=version,
        receptor_id=receptor,
        description="Inspection names a real fault and the target is healthy afterwards",
        technical=(
            Check(name="report has fault", kind=CheckKind.PRESENT, path="fault"),
            Check(name="no error text", kind=CheckKind.NOT_CONTAINS, path="log", value="ERROR"),
        ),
        fitness=(
            Check(
                name="target healthy", kind=CheckKind.EQUALS, path="target.status", value="healthy"
            ),
            Check(name="latency ok", kind=CheckKind.AT_MOST, path="target.latency_ms", value=500),
        ),
    )


GOOD_TOOL = {"fault": "disk full on /var", "log": "fixed"}
GOOD_REAL = {"target": {"status": "healthy", "latency_ms": 120}}


def test_standards_are_versioned_and_immutable(qa, db):
    qa.define_standard(_standard())
    with pytest.raises(QAError):
        qa.define_standard(_standard(version=1))
    qa.define_standard(_standard(version=2))
    assert qa.standard("t0-inspection").version == 2
    with (
        psycopg.connect(db["app"], autocommit=True) as c,
        pytest.raises(psycopg.errors.InsufficientPrivilege),
    ):
        c.execute("UPDATE assurance.qa_standards SET version = 9")


def test_passes_only_when_technical_and_fitness_both_pass(qa, probe, evidence):
    qa.define_standard(_standard())
    task = uuid4()
    probe.sees[task] = GOOD_REAL
    v = qa.verify(task, "T0", "t0-inspection", GOOD_TOOL)
    assert v.passed and v.verified_by is Component.QA_QC
    ev, rid = evidence[-1]
    assert ev.stage is EvidenceStage.REAL_OUTPUT_VERIFIED and ev.outcome is EvidenceOutcome.PASSED
    assert rid == "T0" and ev.evidence_id in v.evidence_ids
    task2 = uuid4()
    probe.sees[task2] = {"target": {"status": "degraded", "latency_ms": 120}}
    v2 = qa.verify(task2, "T0", "t0-inspection", GOOD_TOOL)
    assert v2.technical_success and not v2.fit_for_purpose  # checked separately
    assert evidence[-1][0].outcome is EvidenceOutcome.FAILED


def test_receptor_self_certification_never_passes(qa, probe):
    qa.define_standard(_standard())
    task = uuid4()
    probe.sees[task] = {"target": {"status": "down"}}
    claim = ReceptorTaskResult(task_id=task, receptor_id="T0", claim=ReceptorClaim.DONE,
                               output_ref="all good", reported_at=NOW)  # fmt: skip
    v = qa.verify(task, "T0", "t0-inspection", GOOD_TOOL, receptor_claim=claim)
    assert not v.passed
    assert qa.audit_task(task)[0]["findings"]["receptor_claim"]["claim"] == "done"  # kept for audit


@pytest.mark.parametrize("answer", ["200 OK", "connected", "working", "ok", "", True, {}, None])
def test_superficial_answers_are_not_evidence(qa, probe, answer):
    assert superficial(answer)
    qa.define_standard(_standard())
    task = uuid4()
    probe.sees[task] = answer
    assert not qa.verify(task, "T0", "t0-inspection", answer).passed


def test_no_observation_means_no_verdict(qa, probe):
    qa.define_standard(_standard())
    probe.unreachable = True
    with pytest.raises(ConnectionError):
        qa.verify(uuid4(), "T0", "t0-inspection", GOOD_TOOL)


def test_standard_must_fit_the_receptor(qa):
    qa.define_standard(_standard())
    with pytest.raises(QAError):
        qa.verify(uuid4(), "R11", "t0-inspection", GOOD_TOOL)


def test_three_consecutive_failures_trigger_hold_and_notify_once(qa, probe, escalations):
    qa.define_standard(_standard())
    task = uuid4()
    probe.sees[task] = {"target": {"status": "down", "latency_ms": 9}}
    for _ in range(4):
        qa.verify(task, "T0", "t0-inspection", GOOD_TOOL)
    holds = [e for e in escalations if "HOLD" in e[2]]
    assert [h[0] for h in holds] == ["human_reviewer", "governance"]
    assert qa.consecutive_failures(task) == 4
    probe.sees[task] = GOOD_REAL
    assert qa.verify(task, "T0", "t0-inspection", GOOD_TOOL).passed
    assert qa.consecutive_failures(task) == 0


def test_audit_and_receptor_escalations(qa, probe):
    qa.define_standard(_standard())
    task = uuid4()
    probe.sees[task] = GOOD_REAL
    qa.verify(task, "T0", "t0-inspection", GOOD_TOOL)
    qa.receive_escalation("T0", task, "customer complained")
    assert len(qa.audit_task(task)) == 1
    assert qa.escalations("receptor")[0]["message"] == "customer complained"


# Monitoring -----------------------------------------------------------------------------
def _health(rid="R11", status=HealthStatus.HEALTHY, failures=(), at=NOW):
    return HealthReport(receptor_id=rid, status=status, tasks_running=2, tasks_failed=len(failures),
                        kpis={"orders": 14.0}, failures=failures, reported_at=at)  # fmt: skip


def test_tracks_status_kpis_and_failures_per_receptor(monitor):
    v = monitor.ingest(_health())
    assert v.status is HealthStatus.HEALTHY and v.truth is Truth.REPORTED
    assert v.kpis == {"orders": 14.0} and v.tasks_running == 2
    v = monitor.ingest(_health(status=HealthStatus.DEGRADED, failures=("slow api",)))
    assert v.failures == ("slow api",)


def test_silence_is_reported_as_unknown_or_unverified_never_healthy(monitor, clock, escalations):
    monitor.ingest(_health())
    clock.advance(minutes=11)
    v = monitor.view(SubjectKind.RECEPTOR, "R11")
    assert v.status is HealthStatus.UNKNOWN and v.truth is Truth.UNVERIFIED
    never = monitor.view(SubjectKind.RECEPTOR, "R12")
    assert never.truth is Truth.UNKNOWN and never.status is HealthStatus.UNKNOWN
    stale = monitor.sweep(SubjectKind.RECEPTOR, ["R11", "R12"])
    assert {s.subject_id for s in stale} == {"R11", "R12"}
    assert any("never reported" in e[2] for e in escalations)


def test_failure_and_repeated_failure_escalate_to_governance_and_dashboard(monitor, escalations):
    monitor.ingest(_health(status=HealthStatus.FAILING, failures=("db down",)))
    assert {e[0] for e in escalations} == {"governance", "founder_dashboard"}
    monitor.ingest(_health(status=HealthStatus.FAILING, failures=("db down",)))
    monitor.ingest(_health(status=HealthStatus.OFFLINE))
    repeated = [e for e in escalations if "repeated failure" in e[2]]
    assert len(repeated) == 2  # once to A, once to J
    monitor.ingest(_health(status=HealthStatus.OFFLINE))
    assert len([e for e in escalations if "repeated failure" in e[2]]) == 2  # not spammed


def test_models_tools_and_core_are_monitored_too(monitor):
    monitor.report_component(SubjectKind.MODEL, "model-a", HealthStatus.OFFLINE, "timeouts")
    monitor.report_component(SubjectKind.CORE, "G", HealthStatus.HEALTHY)
    views = {(v.subject_kind, v.subject_id): v for v in monitor.overview()}
    assert views[(SubjectKind.MODEL, "model-a")].status is HealthStatus.OFFLINE
    with pytest.raises(ValueError):
        monitor.report_component(SubjectKind.RECEPTOR, "R11", HealthStatus.HEALTHY)


def test_monitor_has_no_way_to_act():
    from dyson_assurance.monitoring import Monitor

    public = {n for n in dir(Monitor) if not n.startswith("_")}
    assert public == {"ingest", "report_component", "view", "overview", "expected", "sweep"}
