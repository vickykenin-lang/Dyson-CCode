"""HTTP API of the Governance Core.

Founder decisions and STOP / PAUSE must carry X-Founder-Proof from Direct Founder Controls.
Component identity for the other endpoints is bound in Step 9; until then this API must only be
reachable from inside Layer A.
"""

from typing import Annotated
from uuid import UUID

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import JsonValue

from dyson_contracts.approvals import ApprovalCategory, ApprovalDecision, ApprovalRequest
from dyson_contracts.common import Component, Contract, Money
from dyson_contracts.control import ControlCommand, ControlMode, ControlScope, ControlState
from dyson_contracts.integrations import IntegrationRecord

from .core import GovernanceCore, GovernanceError
from .events import ProposalKind, ReceptorLimits
from .state import ProposalStatus


class ProposalIn(Contract):
    kind: ProposalKind
    payload: dict[str, JsonValue]
    summary: str
    requested_by: Component
    category: ApprovalCategory | None = None


class ConsumeIn(Contract):
    action_digest: str
    category: ApprovalCategory
    by: Component


class SpendCheckIn(Contract):
    receptor_id: str
    tool_id: str
    amount: Money
    month_to_date: Money


def create_app(core: GovernanceCore) -> FastAPI:
    app = FastAPI(title="Dyson Governance Core (A)")
    Proof = Annotated[str, Header(alias="X-Founder-Proof")]

    @app.exception_handler(GovernanceError)
    async def _refused(_: Request, exc: GovernanceError):
        return JSONResponse(status_code=409, content={"detail": str(exc)})

    @app.post("/control")
    def control(command: ControlCommand, proof: Proof) -> ControlState:
        if command.issued_by is not Component.FOUNDER:
            raise HTTPException(403, "only Founder commands are accepted over HTTP")
        return core.control(command, proof)

    @app.get("/control/effective")
    def effective(receptor_id: str | None = None) -> dict[str, ControlMode]:
        return {"mode": core.effective_mode(receptor_id)}

    @app.get("/control/{scope}")
    def control_state(scope: ControlScope, receptor_id: str | None = None) -> ControlState:
        return core.control_state(scope, receptor_id)

    @app.post("/proposals", status_code=201)
    def propose(p: ProposalIn) -> ApprovalRequest:
        if p.requested_by is Component.FOUNDER:
            raise HTTPException(422, "the Founder decides; components propose")
        return core.propose(p.kind, p.payload, p.summary, p.requested_by, p.category)

    @app.post("/decisions")
    def decide(decision: ApprovalDecision, proof: Proof) -> dict[str, ProposalStatus]:
        return {"status": core.decide(decision, proof)}

    @app.get("/approvals/{approval_id}")
    def approval(approval_id: UUID) -> dict[str, ProposalStatus]:
        status = core.approval_status(approval_id)
        if status is None:
            raise HTTPException(404, "unknown approval")
        return {"status": status}

    @app.post("/approvals/{approval_id}/consume", status_code=204)
    def consume(approval_id: UUID, body: ConsumeIn) -> None:
        core.consume_approval(approval_id, body.action_digest, body.category, body.by)

    @app.get("/registry")
    def registry() -> dict[str, IntegrationRecord]:
        return core.registry()

    @app.get("/limits/{receptor_id}")
    def limits(receptor_id: str) -> ReceptorLimits:
        lim = core.limits(receptor_id)
        if lim is None:
            raise HTTPException(404, "no Founder-set limits")
        return lim

    @app.post("/spend-check")
    def spend_check(body: SpendCheckIn) -> dict:
        allowed, reason = core.check_spend(
            body.receptor_id, body.tool_id, body.amount, body.month_to_date
        )
        return {"allowed": allowed, "reason": reason}

    return app
