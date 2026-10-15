"""Revenue, bank statements and reconciliation (card H, AMD-2, LA-VLT, LA-FIN)."""

from datetime import date
from enum import StrEnum
from typing import Literal
from uuid import UUID

from pydantic import model_validator

from .common import Component, Contract, Money, NonEmptyStr, ReceptorId, Sha256Hex, Timestamp


class PaymentMethod(StrEnum):
    UPI = "upi"
    QR = "qr"
    BARCODE = "barcode"
    OTHER = "other"


class RevenueReport(Contract):
    """A Receptor's revenue claim on the Financial lane. A claim is never final by itself."""

    report_id: UUID
    receptor_id: ReceptorId
    period_start: date
    period_end: date
    amount: Money
    payment_method: PaymentMethod
    reference: str = ""
    reported_at: Timestamp

    @model_validator(mode="after")
    def _checks(self) -> "RevenueReport":
        if self.period_end < self.period_start:
            raise ValueError("period_end is before period_start")
        return self


class BankStatementUpload(Contract):
    """The only path from the Founder's bank records into Dyson (LA-VLT-01). Upload only."""

    upload_id: UUID
    uploaded_by: Literal[Component.FOUNDER]
    file_sha256: Sha256Hex
    filename: NonEmptyStr
    period_start: date
    period_end: date
    uploaded_at: Timestamp

    @model_validator(mode="after")
    def _checks(self) -> "BankStatementUpload":
        if self.period_end < self.period_start:
            raise ValueError("period_end is before period_start")
        return self


class RevenueStatus(StrEnum):
    REPORTED_NOT_FINAL = "reported_not_final"
    FINAL = "final"


class ReconciliationResult(Contract):
    report_id: UUID
    status: RevenueStatus
    matched_upload_id: UUID | None = None
    reconciled_by: Literal[Component.FINANCIAL_CONTROL]
    reconciled_at: Timestamp

    @model_validator(mode="after")
    def _checks(self) -> "ReconciliationResult":
        if (self.status is RevenueStatus.FINAL) != (self.matched_upload_id is not None):
            raise ValueError("revenue is final exactly when it matches an uploaded statement")
        return self
