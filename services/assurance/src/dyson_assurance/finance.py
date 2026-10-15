"""Financial Control & Reconciliation Controller (card H).

H keeps a Receptor-wise ledger and reconciles it against bank statements the Founder uploads.
It has no bank connection, no bank credentials and no way to move money (LA-VLT-02): payments
are made outside Dyson, and H only records money-out actions that already carry a Founder approval.
Revenue is "reported, not final" until a statement line proves it (LA-FIN-02, LA-IF-05).

Statement upload format (CSV, UTF-8, header row required). Columns used:
  date (YYYY-MM-DD), direction (credit|debit), amount, currency, reference (optional)
Every other column (balances, account numbers, narration) is ignored and never stored
(LA-VLT-03). Long digit runs in references are masked to their last 4 digits.
"""

import csv
import hashlib
import io
import re
from collections.abc import Callable
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from typing import Literal
from uuid import UUID, uuid4

from dyson_contracts.common import Component, Contract, Money, ReceptorId, Timestamp
from dyson_contracts.evidence import EvidenceOutcome, EvidenceRecord, EvidenceStage
from dyson_contracts.finance import BankStatementUpload, RevenueReport, RevenueStatus

from .ports import EvidenceSink

REQUIRED_COLUMNS = {"date", "direction", "amount", "currency"}
_LONG_DIGITS = re.compile(r"\d{9,}")


class StatementError(ValueError):
    pass


class StatementLine(Contract):
    line_date: date
    direction: Literal["credit", "debit"]
    amount: Money
    reference: str = ""


class Payment(Contract):
    """A money-out action made outside Dyson, recorded only with its Founder approval."""

    payment_id: UUID
    receptor_id: ReceptorId
    amount: Money
    approval_id: UUID
    reference: str = ""
    recorded_at: Timestamp


class LedgerLine(Contract):
    receptor_id: str
    currency: str
    reported_revenue: Decimal
    verified_revenue: Decimal
    unverified_revenue: Decimal
    payments: Decimal
    payments_matched_to_bank: Decimal
    verified_net_profit: Decimal  # verified revenue minus every recorded payment


class Receipt(Contract):
    report_id: UUID
    receptor_id: str
    amount: Money
    line_date: date
    reference: str
    upload_id: UUID
    evidence_id: UUID


def mask(reference: str) -> str:
    return _LONG_DIGITS.sub(lambda m: "*" * (len(m.group()) - 4) + m.group()[-4:], reference)


def parse_statement(text: str) -> list[StatementLine]:
    reader = csv.DictReader(io.StringIO(text))
    cols = {c.strip().lower() for c in (reader.fieldnames or [])}
    if not REQUIRED_COLUMNS <= cols:
        raise StatementError(f"statement needs columns {sorted(REQUIRED_COLUMNS)}")
    lines = []
    for n, raw in enumerate(reader, start=2):
        row = {k.strip().lower(): (v or "").strip() for k, v in raw.items() if k}
        try:
            amount = Decimal(row["amount"])
            line = StatementLine(
                line_date=date.fromisoformat(row["date"]),
                direction=row["direction"].lower(),
                amount=Money(amount=amount, currency=row["currency"].upper()),
                reference=mask(row.get("reference", "")),
            )
        except (InvalidOperation, ValueError) as exc:
            raise StatementError(f"line {n}: {exc}") from None
        if amount <= 0:
            raise StatementError(f"line {n}: amount must be positive")
        lines.append(line)
    return lines


class FinancialController:
    def __init__(self, conn, evidence: EvidenceSink,
                 clock: Callable[[], datetime] = lambda: datetime.now(UTC)):  # fmt: skip
        self._c, self._evidence, self._clock = conn, evidence, clock

    # Revenue ledger (LA-FIN-01) ---------------------------------------------------------
    def ingest_revenue(self, report: RevenueReport) -> RevenueStatus:
        """A Receptor's revenue report on the Financial lane. It starts as a claim."""
        with self._c.transaction():
            self._c.execute(
                "INSERT INTO assurance.revenue_reports (report_id, receptor_id, period_start,"
                " period_end, amount, currency, payment_method, reference, reported_at)"
                " VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)",
                [report.report_id, report.receptor_id, report.period_start, report.period_end,
                 report.amount.amount, report.amount.currency, report.payment_method.value,
                 report.reference, report.reported_at],
            )  # fmt: skip
            self._c.execute(
                "INSERT INTO assurance.reconciliations (report_id, status, at)"
                " VALUES (%s, 'reported_not_final', %s)",
                [report.report_id, self._clock()],
            )
        self.reconcile()
        return self.status(report.report_id)

    def status(self, report_id: UUID) -> RevenueStatus:
        row = self._c.execute(
            "SELECT status FROM assurance.reconciliations WHERE report_id = %s"
            " ORDER BY seq DESC LIMIT 1",
            [report_id],
        ).fetchone()
        return RevenueStatus(row["status"])

    # Bank statement intake (LA-VLT-01, LA-VLT-03) --------------------------------------
    def upload_statement(self, upload: BankStatementUpload, content: bytes) -> int:
        """The only path from the Founder's bank records into Dyson. Returns lines kept."""
        if hashlib.sha256(content).hexdigest() != upload.file_sha256:
            raise StatementError("file does not match the uploaded sha256")
        lines = parse_statement(content.decode("utf-8"))
        outside = [x for x in lines if not upload.period_start <= x.line_date <= upload.period_end]
        if outside:
            raise StatementError("lines outside the statement period")
        with self._c.transaction():
            self._c.execute(
                "INSERT INTO assurance.statement_uploads (upload_id, file_sha256, period_start,"
                " period_end, uploaded_at) VALUES (%s, %s, %s, %s, %s)",
                [upload.upload_id, upload.file_sha256, upload.period_start, upload.period_end,
                 upload.uploaded_at],
            )  # fmt: skip
            for line in lines:
                self._c.execute(
                    "INSERT INTO assurance.statement_lines (line_id, upload_id, line_date,"
                    " direction, amount, currency, reference) VALUES (%s, %s, %s, %s, %s, %s, %s)",
                    [uuid4(), upload.upload_id, line.line_date, line.direction,
                     line.amount.amount, line.amount.currency, line.reference],
                )  # fmt: skip
        self.reconcile()
        return len(lines)

    # Reconciliation (LA-FIN-02, LA-FIN-04, LA-FIN-06) ----------------------------------
    def reconcile(self) -> int:
        """Match open revenue reports to unused statement credits, and payments to debits.

        A report matches a credit of exactly the same amount and currency, dated inside the
        report's period, whose reference contains the report's reference when one was given.
        Each statement line can prove at most one report or payment.
        """
        matched = 0
        open_reports = self._c.execute(
            "SELECT r.* FROM assurance.revenue_reports r WHERE (SELECT status FROM"
            " assurance.reconciliations x WHERE x.report_id = r.report_id ORDER BY seq DESC"
            " LIMIT 1) = 'reported_not_final' ORDER BY r.reported_at, r.report_id"
        ).fetchall()
        for rep in open_reports:
            with self._c.transaction():
                self._lock()
                line = self._c.execute(
                    "SELECT l.* FROM assurance.statement_lines l WHERE l.direction = 'credit'"
                    " AND l.amount = %s AND l.currency = %s AND l.line_date BETWEEN %s AND %s"
                    " AND (%s = '' OR position(%s in l.reference) > 0)"
                    " AND NOT EXISTS (SELECT 1 FROM assurance.reconciliations x"
                    "   WHERE x.line_id = l.line_id)"
                    " AND NOT EXISTS (SELECT 1 FROM assurance.payment_matches p"
                    "   WHERE p.line_id = l.line_id)"
                    " ORDER BY l.line_date, l.line_id LIMIT 1",
                    [rep["amount"], rep["currency"], rep["period_start"], rep["period_end"],
                     rep["reference"], rep["reference"]],
                ).fetchone()  # fmt: skip
                if line is None:
                    continue
                evidence = EvidenceRecord(
                    evidence_id=uuid4(),
                    capability="revenue",
                    provider=rep["receptor_id"],
                    stage=EvidenceStage.REAL_BUSINESS_OUTCOME_VERIFIED,
                    outcome=EvidenceOutcome.PASSED,
                    environment="bank-statement",
                    scope=rep["receptor_id"],
                    recorded_by=Component.FINANCIAL_CONTROL,
                    recorded_at=self._clock(),
                    artifact_ref=f"statement:{line['upload_id']}/line:{line['line_id']}",
                    detail=f"report {rep['report_id']} matched {line['amount']} {line['currency']}"
                    f" on {line['line_date']}",
                )
                self._c.execute(
                    "INSERT INTO assurance.reconciliations (report_id, status, line_id, upload_id,"
                    " evidence_id, at) VALUES (%s, 'final', %s, %s, %s, %s)",
                    [rep["report_id"], line["line_id"], line["upload_id"], evidence.evidence_id,
                     self._clock()],
                )  # fmt: skip
            self._evidence.record(evidence, rep["receptor_id"])
            matched += 1
        for pay in self._c.execute(
            "SELECT p.* FROM assurance.payments p WHERE NOT EXISTS"
            " (SELECT 1 FROM assurance.payment_matches m WHERE m.payment_id = p.payment_id)"
            " ORDER BY p.recorded_at"
        ).fetchall():
            with self._c.transaction():
                self._lock()
                line = self._c.execute(
                    "SELECT l.* FROM assurance.statement_lines l WHERE l.direction = 'debit'"
                    " AND l.amount = %s AND l.currency = %s AND l.line_date >= %s"
                    " AND NOT EXISTS (SELECT 1 FROM assurance.payment_matches m"
                    "   WHERE m.line_id = l.line_id)"
                    " ORDER BY l.line_date, l.line_id LIMIT 1",
                    [pay["amount"], pay["currency"], pay["recorded_at"].date()],
                ).fetchone()
                if line is not None:
                    self._c.execute(
                        "INSERT INTO assurance.payment_matches (payment_id, line_id, at)"
                        " VALUES (%s, %s, %s)",
                        [pay["payment_id"], line["line_id"], self._clock()],
                    )
                    matched += 1
        return matched

    def _lock(self) -> None:
        """One reconciler at a time; unique constraints also stop a line proving two items."""
        self._c.execute("SELECT pg_advisory_xact_lock(hashtext('assurance.reconcile'))")

    # Money out (LA-FIN-03) --------------------------------------------------------------
    def record_payment(self, payment: Payment) -> None:
        """Record a payment made outside Dyson. The approval reference is mandatory."""
        self._c.execute(
            "INSERT INTO assurance.payments (payment_id, receptor_id, amount, currency,"
            " approval_id, reference, recorded_at) VALUES (%s, %s, %s, %s, %s, %s, %s)",
            [payment.payment_id, payment.receptor_id, payment.amount.amount,
             payment.amount.currency, payment.approval_id, mask(payment.reference),
             payment.recorded_at],
        )  # fmt: skip
        self.reconcile()

    # Views for the Founder Financial Dashboard (LA-FIN-05 via I in Step 9) ---------------
    def ledger(self) -> list[LedgerLine]:
        rows = self._c.execute(
            "WITH latest AS (SELECT DISTINCT ON (report_id) report_id, status"
            "   FROM assurance.reconciliations ORDER BY report_id, seq DESC),"
            " rev AS (SELECT r.receptor_id, r.currency,"
            "   sum(r.amount) AS reported,"
            "   coalesce(sum(r.amount) FILTER (WHERE l.status = 'final'), 0) AS verified"
            "   FROM assurance.revenue_reports r JOIN latest l USING (report_id)"
            "   GROUP BY 1, 2),"
            " pay AS (SELECT p.receptor_id, p.currency, sum(p.amount) AS paid,"
            "   coalesce(sum(p.amount) FILTER (WHERE m.payment_id IS NOT NULL), 0) AS matched"
            "   FROM assurance.payments p LEFT JOIN assurance.payment_matches m USING (payment_id)"
            "   GROUP BY 1, 2)"
            " SELECT coalesce(rev.receptor_id, pay.receptor_id) AS receptor_id,"
            "   coalesce(rev.currency, pay.currency) AS currency,"
            "   coalesce(reported, 0) AS reported, coalesce(verified, 0) AS verified,"
            "   coalesce(paid, 0) AS paid, coalesce(matched, 0) AS matched"
            " FROM rev FULL JOIN pay ON rev.receptor_id = pay.receptor_id"
            "   AND rev.currency = pay.currency ORDER BY 1, 2"
        ).fetchall()
        return [
            LedgerLine(
                receptor_id=r["receptor_id"],
                currency=r["currency"],
                reported_revenue=r["reported"],
                verified_revenue=r["verified"],
                unverified_revenue=r["reported"] - r["verified"],
                payments=r["paid"],
                payments_matched_to_bank=r["matched"],
                verified_net_profit=r["verified"] - r["paid"],
            )
            for r in rows
        ]

    def performance(self, currency: str) -> list[tuple[str, Decimal]]:
        """Receptors ranked by verified net profit only (AMD-6, LA-FIN-07)."""
        lines = [x for x in self.ledger() if x.currency == currency]
        return sorted(((x.receptor_id, x.verified_net_profit) for x in lines),
                      key=lambda t: t[1], reverse=True)  # fmt: skip

    def receipts(self) -> list[Receipt]:
        rows = self._c.execute(
            "SELECT x.report_id, r.receptor_id, l.amount, l.currency, l.line_date, l.reference,"
            " x.upload_id, x.evidence_id FROM assurance.reconciliations x"
            " JOIN assurance.revenue_reports r USING (report_id)"
            " JOIN assurance.statement_lines l ON l.line_id = x.line_id"
            " WHERE x.status = 'final' ORDER BY l.line_date"
        ).fetchall()
        return [
            Receipt(
                report_id=r["report_id"],
                receptor_id=r["receptor_id"],
                amount=Money(amount=r["amount"], currency=r["currency"]),
                line_date=r["line_date"],
                reference=r["reference"],
                upload_id=r["upload_id"],
                evidence_id=r["evidence_id"],
            )  # fmt: skip
            for r in rows
        ]

    def open_items(self) -> int:
        """How many revenue reports are still "reported, not final"."""
        return self._c.execute(
            "SELECT count(*) AS n FROM (SELECT DISTINCT ON (report_id) status"
            " FROM assurance.reconciliations ORDER BY report_id, seq DESC) s"
            " WHERE status = 'reported_not_final'"
        ).fetchone()["n"]
