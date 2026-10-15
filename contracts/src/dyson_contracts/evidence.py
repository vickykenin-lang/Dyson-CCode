"""The eight AMD-3 evidence stages. Never collapse them into "connected" or "working"."""

from enum import IntEnum, StrEnum
from uuid import UUID

from pydantic import model_validator

from .common import Component, Contract, NonEmptyStr, Timestamp


class EvidenceStage(IntEnum):
    CREDENTIAL_AVAILABLE = 1
    ENDPOINT_CONFIGURED = 2
    SOURCE_IMPLEMENTED = 3
    TEST_PASSED = 4
    PRODUCTION_DEPLOYED = 5
    LIVE_REQUEST_VERIFIED = 6
    REAL_OUTPUT_VERIFIED = 7
    REAL_BUSINESS_OUTCOME_VERIFIED = 8


STAGE_LABELS = {
    EvidenceStage.CREDENTIAL_AVAILABLE: "Credential available",
    EvidenceStage.ENDPOINT_CONFIGURED: "Endpoint / configuration present",
    EvidenceStage.SOURCE_IMPLEMENTED: "Source implemented",
    EvidenceStage.TEST_PASSED: "Test passed",
    EvidenceStage.PRODUCTION_DEPLOYED: "Production deployed",
    EvidenceStage.LIVE_REQUEST_VERIFIED: "Live request verified",
    EvidenceStage.REAL_OUTPUT_VERIFIED: "Real output verified",
    EvidenceStage.REAL_BUSINESS_OUTCOME_VERIFIED: "Real business outcome verified",
}

# Stages that prove live behaviour may only be passed by an independent verifier
# (LA-QA-05, LA-HER-08): never by the component that produced the output.
INDEPENDENT_VERIFIERS = frozenset({Component.QA_QC, Component.FINANCIAL_CONTROL})


class EvidenceOutcome(StrEnum):
    PASSED = "passed"
    FAILED = "failed"
    NEGATIVE = "negative"  # proof that something does not exist or is denied


class EvidenceRecord(Contract):
    evidence_id: UUID
    capability: NonEmptyStr
    provider: NonEmptyStr
    stage: EvidenceStage
    outcome: EvidenceOutcome
    environment: NonEmptyStr
    scope: NonEmptyStr
    recorded_by: Component
    recorded_at: Timestamp
    expires_at: Timestamp | None = None
    artifact_ref: NonEmptyStr
    task_id: UUID | None = None
    detail: str = ""

    @model_validator(mode="after")
    def _checks(self) -> "EvidenceRecord":
        if self.expires_at is not None and self.expires_at <= self.recorded_at:
            raise ValueError("expires_at must be after recorded_at")
        if (
            self.outcome is EvidenceOutcome.PASSED
            and self.stage >= EvidenceStage.LIVE_REQUEST_VERIFIED
            and self.recorded_by not in INDEPENDENT_VERIFIERS
        ):
            raise ValueError("stages 6-8 can only be passed by an independent verifier")
        return self
