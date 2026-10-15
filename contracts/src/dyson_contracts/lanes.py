"""The five Layer A to Layer B lanes (PRD section 8). Layer A talks to Receptors only here."""

from enum import StrEnum
from typing import Literal
from uuid import UUID

from pydantic import Field, model_validator

from .common import (
    Component,
    Contract,
    IdempotencyKey,
    NonEmptyStr,
    ReceptorId,
    Timestamp,
)


class Lane(StrEnum):
    QA_VERIFICATION = "qa_verification"
    TASKS = "tasks"
    FINANCIAL_REPORTING = "financial_reporting"
    MONITORING_HEALTH = "monitoring_health"
    CONTROL = "control"


# Each lane has exactly one Layer A owner (PRD section 8). Tasks are owned by D and pass through G.
LANE_OWNER = {
    Lane.QA_VERIFICATION: Component.QA_QC,
    Lane.TASKS: Component.ORCHESTRATOR,
    Lane.FINANCIAL_REPORTING: Component.FINANCIAL_CONTROL,
    Lane.MONITORING_HEALTH: Component.MONITORING,
    Lane.CONTROL: Component.GOVERNANCE_CORE,
}
# Message types per lane: tasks -> TaskAssignment / ReceptorTaskResult;
# qa -> VerificationRequest / VerificationVerdict; financial -> finance.RevenueReport;
# monitoring -> HealthReport; control -> control.ControlCommand.


# Tasks lane
class TaskAssignment(Contract):
    task_id: UUID
    idempotency_key: IdempotencyKey
    receptor_id: ReceptorId
    tool_call_id: UUID
    instruction: NonEmptyStr
    issued_via: Literal[Component.TOOL_HUB]
    issued_at: Timestamp


class ReceptorClaim(StrEnum):
    DONE = "done"
    FAILED = "failed"


class ReceptorTaskResult(Contract):
    """What the Receptor says happened. A report is not proof (LA-IF-04); F verifies it."""

    task_id: UUID
    receptor_id: ReceptorId
    claim: ReceptorClaim
    output_ref: str = ""
    reported_at: Timestamp
    note: str = ""


# QA / verification lane
class VerificationRequest(Contract):
    request_id: UUID
    task_id: UUID
    receptor_id: ReceptorId
    standard_id: NonEmptyStr
    issued_at: Timestamp


class VerificationVerdict(Contract):
    """F's independent verdict. Technical success and fitness for purpose are separate (AMD-3)."""

    task_id: UUID
    receptor_id: ReceptorId | None = None
    technical_success: bool
    fit_for_purpose: bool
    evidence_ids: tuple[UUID, ...] = Field(min_length=1)
    verified_by: Literal[Component.QA_QC]
    verified_at: Timestamp

    @property
    def passed(self) -> bool:
        return self.technical_success and self.fit_for_purpose


# Monitoring / health lane
class HealthStatus(StrEnum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    FAILING = "failing"
    OFFLINE = "offline"
    UNKNOWN = "unknown"  # reported plainly instead of guessing (LA-MON-06)


class HealthReport(Contract):
    receptor_id: ReceptorId
    status: HealthStatus
    tasks_running: int = Field(ge=0)
    tasks_failed: int = Field(ge=0)
    kpis: dict[str, float] = {}
    failures: tuple[str, ...] = ()
    reported_at: Timestamp

    @model_validator(mode="after")
    def _checks(self) -> "HealthReport":
        if self.status is HealthStatus.HEALTHY and self.failures:
            raise ValueError("a report listing failures cannot say healthy")
        return self
