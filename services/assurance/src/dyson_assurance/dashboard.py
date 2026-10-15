"""Founder Financial Dashboard data API (card J). Read-only.

Only GET endpoints exist: J has no authority to act and no write path into any Core control
(LA-DASH-02, AMD-10). It never talks to a bank (LA-DASH-03). The screens themselves are deferred
to implementation gate 8 (LA-DASH-05); this is the verified data they will show.
"""

from fastapi import FastAPI

from .finance import FinancialController, LedgerLine, Receipt
from .monitoring import HealthView, Monitor
from .qa import QAController


def create_app(finance: FinancialController, monitor: Monitor, qa: QAController) -> FastAPI:
    app = FastAPI(title="Dyson Founder Dashboard data (J) - read only")

    @app.get("/finance/ledger")
    def ledger() -> list[LedgerLine]:
        return finance.ledger()

    @app.get("/finance/receipts")
    def receipts() -> list[Receipt]:
        return finance.receipts()

    @app.get("/finance/reconciliation")
    def reconciliation() -> dict:
        return {"reported_not_final": finance.open_items()}

    @app.get("/finance/performance/{currency}")
    def performance(currency: str) -> list[dict]:
        return [
            {"receptor_id": r, "verified_net_profit": str(p)}
            for r, p in finance.performance(currency)
        ]

    @app.get("/health")
    def health() -> list[HealthView]:
        return monitor.overview()

    @app.get("/qa/summary")
    def qa_summary() -> dict[str, int]:
        return qa.summary()

    @app.get("/alerts")
    def alerts() -> list[dict]:
        return [
            {"source": e["source"], "receptor_id": e["receptor_id"], "message": e["message"],
             "at": e["at"].isoformat()}
            for e in qa.escalations()
        ]  # fmt: skip

    return app
