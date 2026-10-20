"""Financial Control (H) and the read-only dashboard data API (J)."""

import ast
import hashlib
from datetime import date
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

import psycopg
import pytest
from assurance_testkit import NOW
from fastapi.testclient import TestClient
from pydantic import ValidationError

from dyson_assurance.dashboard import create_app
from dyson_assurance.finance import Payment, StatementError, parse_statement
from dyson_contracts.common import Component, Money
from dyson_contracts.evidence import EvidenceStage
from dyson_contracts.finance import BankStatementUpload, PaymentMethod, RevenueReport, RevenueStatus

INR = "INR"


def revenue(rid="R11", amount="1500", ref="", start=date(2026, 10, 1), end=date(2026, 10, 15)):
    return RevenueReport(
        report_id=uuid4(), receptor_id=rid, period_start=start, period_end=end,
        amount=Money(amount=Decimal(amount), currency=INR), payment_method=PaymentMethod.UPI,
        reference=ref, reported_at=NOW,
    )  # fmt: skip


def statement(rows, start=date(2026, 10, 1), end=date(2026, 10, 31)):
    text = "date,narration,direction,amount,currency,reference,balance,account\n" + "\n".join(rows)
    content = text.encode()
    upload = BankStatementUpload(
        upload_id=uuid4(), uploaded_by=Component.FOUNDER,
        file_sha256=hashlib.sha256(content).hexdigest(), filename="oct.csv",
        period_start=start, period_end=end, uploaded_at=NOW,
    )  # fmt: skip
    return upload, content


def test_revenue_is_only_a_claim_until_a_statement_proves_it(finance, evidence):
    rep = revenue(ref="UPI-ORD-77")
    assert finance.ingest_revenue(rep) is RevenueStatus.REPORTED_NOT_FINAL
    up, content = statement(
        ["2026-10-09,upi in,credit,1500,INR,UPI-ORD-77 from cust,99999,123456789012"]
    )
    finance.upload_statement(up, content)
    assert finance.status(rep.report_id) is RevenueStatus.FINAL
    ev, rid = evidence[-1]
    assert (
        ev.stage is EvidenceStage.REAL_BUSINESS_OUTCOME_VERIFIED
        and ev.recorded_by is Component.FINANCIAL_CONTROL
    )
    assert rid == "R11"
    [receipt] = finance.receipts()
    assert receipt.report_id == rep.report_id and receipt.evidence_id == ev.evidence_id


def test_no_match_stays_not_final(finance):
    wrong_amount = revenue(amount="1499")
    outside_period = revenue(amount="1500", end=date(2026, 10, 5))
    wrong_ref = revenue(amount="1500", ref="UPI-ORD-99")
    for r in (wrong_amount, outside_period, wrong_ref):
        finance.ingest_revenue(r)
    up, content = statement(["2026-10-09,upi in,credit,1500,INR,UPI-ORD-77,0,0"])
    finance.upload_statement(up, content)
    assert {finance.status(r.report_id) for r in (wrong_amount, outside_period, wrong_ref)} == {
        RevenueStatus.REPORTED_NOT_FINAL
    }
    assert finance.open_items() == 3


def test_one_bank_line_proves_one_report(finance):
    a, b = revenue(amount="700"), revenue(amount="700")
    finance.ingest_revenue(a)
    finance.ingest_revenue(b)
    up, content = statement(["2026-10-09,upi,credit,700,INR,,0,0"])
    finance.upload_statement(up, content)
    statuses = sorted(finance.status(r.report_id).value for r in (a, b))
    assert statuses == ["final", "reported_not_final"]


def test_statement_keeps_only_what_reconciliation_needs(finance, db):
    up, content = statement(
        ["2026-10-09,salary,credit,1500,INR,ACC 123456789012 ref,88231.55,9876543210"]
    )
    finance.upload_statement(up, content)
    with psycopg.connect(db["admin"]) as c:
        cols = [r[0] for r in c.execute(
            "SELECT column_name FROM information_schema.columns WHERE table_schema = 'assurance'"
            " AND table_name = 'statement_lines'").fetchall()]  # fmt: skip
        line = c.execute("SELECT reference FROM assurance.statement_lines").fetchone()[0]
        dump = str(c.execute("SELECT * FROM assurance.statement_lines").fetchall())
    assert "balance" not in cols and "account" not in cols and "narration" not in cols
    assert line == "ACC ********9012 ref"  # long digit runs masked
    assert "88231.55" not in dump and "9876543210" not in dump


def test_statement_must_match_its_hash_and_period(finance):
    up, content = statement(["2026-10-09,x,credit,10,INR,,0,0"])
    with pytest.raises(StatementError):
        finance.upload_statement(up, content + b"tampered")
    up2, content2 = statement(["2026-11-09,x,credit,10,INR,,0,0"])
    with pytest.raises(StatementError):
        finance.upload_statement(up2, content2)
    with pytest.raises(StatementError):
        parse_statement("date,amount\n2026-10-01,5")


def test_only_the_founder_uploads_statements():
    with pytest.raises(ValidationError):
        BankStatementUpload(
            upload_id=uuid4(), uploaded_by=Component.RECEPTOR, file_sha256="0" * 64,
            filename="x.csv", period_start=date(2026, 10, 1), period_end=date(2026, 10, 2),
            uploaded_at=NOW,
        )  # fmt: skip


def test_payments_need_an_approval_and_net_profit_uses_verified_revenue_only(finance):
    with pytest.raises(ValidationError):
        Payment(payment_id=uuid4(), receptor_id="R11",
                amount=Money(amount=Decimal("200"), currency=INR), recorded_at=NOW)  # fmt: skip
    finance.ingest_revenue(revenue("R11", "1500", ref="UPI-1"))
    finance.ingest_revenue(revenue("R11", "900", ref="UPI-NOT-IN-BANK"))
    finance.ingest_revenue(revenue("R12", "400", ref="UPI-2"))
    finance.record_payment(Payment(payment_id=uuid4(), receptor_id="R11",
                                   amount=Money(amount=Decimal("200"), currency=INR),
                                   approval_id=uuid4(), recorded_at=NOW))  # fmt: skip
    up, content = statement([
        "2026-10-09,a,credit,1500,INR,UPI-1,0,0",
        "2026-10-10,b,credit,400,INR,UPI-2,0,0",
        "2026-10-16,c,debit,200,INR,ADS,0,0",
    ])  # fmt: skip
    finance.upload_statement(up, content)
    lines = {x.receptor_id: x for x in finance.ledger()}
    r11 = lines["R11"]
    assert r11.reported_revenue == Decimal("2400") and r11.verified_revenue == Decimal("1500")
    assert r11.unverified_revenue == Decimal("900") and r11.payments_matched_to_bank == Decimal(
        "200"
    )
    assert r11.verified_net_profit == Decimal("1300")  # the 900 claim earns nothing
    assert finance.performance(INR) == [("R11", Decimal("1300")), ("R12", Decimal("400"))]


def test_ledger_is_append_only(finance, db):
    finance.ingest_revenue(revenue())
    with psycopg.connect(db["app"], autocommit=True) as c:
        for stmt in ("UPDATE assurance.reconciliations SET status = 'final'",
                     "DELETE FROM assurance.revenue_reports"):  # fmt: skip
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                c.execute(stmt)


# No bank, no payments, no model ---------------------------------------------------------
ALLOWED = {
    "collections", "csv", "datetime", "decimal", "enum", "hashlib", "importlib", "io", "json",
    "re", "statistics", "typing", "uuid", "fastapi", "psycopg", "pydantic", "dyson_contracts",
    "dyson_assurance",
}  # fmt: skip


def test_no_bank_payment_network_or_model_client_anywhere():
    pkg = Path(__file__).resolve().parents[1] / "src" / "dyson_assurance"
    for path in pkg.glob("*.py"):
        for node in ast.walk(ast.parse(path.read_text())):
            names = (
                [a.name for a in node.names] if isinstance(node, ast.Import)
                else [node.module] if isinstance(node, ast.ImportFrom) and node.level == 0
                else []
            )  # fmt: skip
            for name in names:
                assert name.split(".")[0] in ALLOWED, f"{path.name} imports {name}"
    from dyson_assurance.finance import FinancialController

    methods = {n for n in dir(FinancialController) if not n.startswith("_")}
    assert not any(
        w in m for m in methods for w in ("pay_out", "transfer", "send", "charge", "topup")
    )


# Dashboard data (J) ---------------------------------------------------------------------
def test_dashboard_is_read_only_and_shows_verified_data(finance, monitor, qa):
    finance.ingest_revenue(revenue(ref="UPI-1"))
    finance.ingest_revenue(revenue(amount="50"))
    up, content = statement(["2026-10-09,a,credit,1500,INR,UPI-1,0,0"])
    finance.upload_statement(up, content)
    client = TestClient(create_app(finance, monitor, qa))
    methods = {m for r in client.app.routes for m in getattr(r, "methods", set())}
    assert methods <= {"GET", "HEAD"}  # no write path at all
    ledger = client.get("/finance/ledger").json()[0]
    assert ledger["verified_revenue"] == "1500" and ledger["unverified_revenue"] == "50"
    assert client.get("/finance/reconciliation").json() == {"reported_not_final": 1}
    assert client.post("/finance/ledger").status_code == 405
    assert client.get("/health").status_code == 200


BANK_EXPORT = """Account Statement,,,,,,
Account No :,50100123456789,,,,,
,,,,,,
Date,Narration,Chq./Ref.No.,Value Dt,Withdrawal Amt.,Deposit Amt.,Closing Balance
01/04/23,UPI-DESIGN INFRA-designinfra@okhdfc,0000345771173416,01/04/23,"10,000.00",,"41,845.82"
02/04/23,IMPS-309227039980-ACME TRADERS-XXXX9999,0000309227039980,02/04/23,,"51,358.00","73,503.82"
,,,,,,
********,,,,,,
"""


def test_the_founders_bank_export_is_read_and_only_parsed_fields_kept():  # D-017, LA-VLT-03
    debit, credit = parse_statement(BANK_EXPORT)
    assert (debit.line_date, debit.direction, debit.amount.amount) == (
        date(2023, 4, 1), "debit", Decimal("10000.00"))  # fmt: skip
    assert (credit.direction, credit.amount.amount, credit.amount.currency) == (
        "credit", Decimal("51358.00"), "INR")  # fmt: skip
    assert credit.reference == "************9980"  # the bank reference, masked
    kept = str([x.model_dump() for x in (debit, credit)])
    for secret in ("ACME", "designinfra@", "50100123456789", "73,503.82", "73503.82"):
        assert secret not in kept  # no narration, account number or balance
    with pytest.raises(StatementError):
        parse_statement(BANK_EXPORT.replace(',,"51,358.00"', ',"5.00","51,358.00"'))
