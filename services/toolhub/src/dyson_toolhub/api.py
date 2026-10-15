"""HTTP API of the Governed Tool Hub.

Callers present their service credential in X-Caller-Credential. Kill switches can be thrown by
the Governance Core; reviving needs a Founder approval. Network policy (Step 7 for Hermes,
Step 10 on AWS) makes this the only route to any tool.
"""

from typing import Annotated
from uuid import UUID

from fastapi import FastAPI, Header, HTTPException

from dyson_contracts.common import Component, Contract
from dyson_contracts.toolcalls import ToolCallRequest

from .catalog import ToolSpec
from .hub import ToolHub, ToolResult
from .ports import CallerAuthenticator


class KillIn(Contract):
    target_kind: str
    target_id: str
    reason: str


class ReviveIn(Contract):
    target_kind: str
    target_id: str
    approval_id: UUID


def create_app(hub: ToolHub, admins: CallerAuthenticator, specs: list[ToolSpec]) -> FastAPI:
    app = FastAPI(title="Dyson Governed Tool Hub (G)")
    Credential = Annotated[str, Header(alias="X-Caller-Credential")]

    def _governance(credential: str) -> None:
        if admins.authenticate(credential) is not Component.GOVERNANCE_CORE:
            raise HTTPException(403, "only the Governance Core operates kill switches")

    @app.post("/calls")
    def call(request: ToolCallRequest, credential: Credential) -> ToolResult:
        return hub.call(request, credential)

    @app.post("/kill", status_code=204)
    def kill(body: KillIn, credential: Credential) -> None:
        _governance(credential)
        hub.kill(body.target_kind, body.target_id, body.reason)

    @app.post("/revive", status_code=204)
    def revive(body: ReviveIn, credential: Credential) -> None:
        _governance(credential)
        try:
            hub.revive(body.target_kind, body.target_id, body.approval_id)
        except PermissionError as exc:
            raise HTTPException(409, str(exc)) from None

    @app.get("/tools")
    def tools() -> list[ToolSpec]:
        return specs

    return app
