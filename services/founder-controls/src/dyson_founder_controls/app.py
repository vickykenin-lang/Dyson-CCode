"""HTTP API of Direct Founder Controls.

Every action needs a fresh step-up confirmation for exactly that action:
1. POST /challenges with the purpose (built by `purpose_for_*` below, also on the device);
2. the Founder's device answers the challenge;
3. the action is sent with the challenge id and the assertion.

Decisions and commands are then signed for A and sent to A, the only component reached.
"""

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Annotated, Literal
from uuid import UUID, uuid4

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import Field

from dyson_contracts.approvals import ApprovalDecision, ApprovalDecisionKind, ApprovalRequest
from dyson_contracts.common import Component, Contract, NonEmptyStr, ReceptorId, Sha256Hex
from dyson_contracts.control import ControlCommand, ControlCommandType, ControlScope, ControlState

from .passkey import PasskeyStepUp
from .ports import AuditPort, GovernancePort, HmacChannelSigner
from .stepup import Challenge, StepUpVerifier
from .ui import PAGE


def purpose_for_list() -> str:
    return "list-approvals"


def purpose_for_decision(approval_id: UUID, action_digest: str, decision: str) -> str:
    return f"decide|{approval_id}|{action_digest}|{decision}"


def purpose_for_control(command: str, scope: str, receptor_id: str | None) -> str:
    return f"control|{command}|{scope}|{receptor_id or '-'}"


def purpose_for_resume_request(scope: str, receptor_id: str | None) -> str:
    return f"resume-request|{scope}|{receptor_id or '-'}"


class ChallengeIn(Contract):
    purpose: NonEmptyStr


class Confirmation(Contract):
    challenge_id: UUID
    assertion: NonEmptyStr


class DecisionIn(Confirmation):
    approval_id: UUID
    action_digest: Sha256Hex  # the digest the Founder was shown
    decision: ApprovalDecisionKind


class ControlIn(Confirmation):
    command: Literal[ControlCommandType.STOP, ControlCommandType.PAUSE]
    scope: ControlScope
    receptor_id: ReceptorId | None = None
    reason: str = ""


class ResumeRequestIn(Confirmation):
    scope: ControlScope
    receptor_id: ReceptorId | None = None


class PasskeyLabel(Contract):
    label: str = Field(min_length=1, max_length=40)


class RegistrationOptionsIn(PasskeyLabel):
    device_key: str | None = None  # only for the first passkey
    challenge_id: UUID | None = None  # for later ones: a passkey confirmation
    assertion: str | None = None


class RegisterIn(Contract):
    registration_id: UUID
    credential: NonEmptyStr  # the browser's credential, as JSON


class DecisionOut(Contract):
    approval_id: UUID
    status: str
    decided_at: datetime


class ControlsError(Exception):
    pass


def create_app(
    governance: GovernancePort,
    stepup: StepUpVerifier,
    signer: HmacChannelSigner,
    audit: AuditPort,
    clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    passkeys: PasskeyStepUp | None = None,
) -> FastAPI:
    app = FastAPI(title="Dyson Direct Founder Controls")

    @app.exception_handler(ControlsError)
    async def _refused(_: Request, exc: ControlsError):
        return JSONResponse(status_code=403, content={"detail": str(exc)})

    def confirmed(c: Confirmation, purpose: str) -> str:
        method = stepup.verify(c.challenge_id, purpose, c.assertion)
        if method is None:
            audit.record("confirmation_refused", {"purpose": purpose, "at": clock().isoformat()})
            raise ControlsError("Founder confirmation failed for this exact action")
        return method

    @app.post("/challenges", status_code=201)
    def challenge(body: ChallengeIn) -> Challenge:
        return stepup.issue(body.purpose)

    @app.get("/approvals")
    def pending(
        challenge_id: Annotated[UUID, Header(alias="X-Challenge")],
        assertion: Annotated[str, Header(alias="X-Assertion")],
    ) -> list[ApprovalRequest]:
        """What awaits the Founder: each with its summary and the digest of the exact action."""
        confirmed(Confirmation(challenge_id=challenge_id, assertion=assertion), purpose_for_list())
        return governance.pending_approvals()

    @app.post("/decisions")
    def decide(body: DecisionIn) -> DecisionOut:
        method = confirmed(
            body, purpose_for_decision(body.approval_id, body.action_digest, body.decision.value)
        )
        shown = {r.approval_id: r for r in governance.pending_approvals()}.get(body.approval_id)
        if shown is None:
            raise ControlsError("no such approval is waiting")
        if shown.action_digest != body.action_digest:  # LA-DFC-05
            raise ControlsError("the action changed since it was shown; nothing was decided")
        decision = ApprovalDecision(
            approval_id=body.approval_id,
            action_digest=body.action_digest,
            decision=body.decision,
            decided_by=Component.FOUNDER,
            channel=Component.DIRECT_FOUNDER_CONTROLS,
            auth_method=method,
            decided_at=clock(),
        )
        status = governance.decide(decision, signer.sign(decision))
        audit.record("decision", {**decision.model_dump(mode="json"), "status": str(status)})
        return DecisionOut(approval_id=body.approval_id, status=str(status),
                           decided_at=decision.decided_at)  # fmt: skip

    @app.post("/control")
    def control(body: ControlIn) -> ControlState:
        """STOP and PAUSE. No model, app or Gateway is involved (LA-DFC-04)."""
        if (body.scope is ControlScope.RECEPTOR) != (body.receptor_id is not None):
            raise HTTPException(422, "receptor_id is required exactly for receptor scope")
        confirmed(body, purpose_for_control(body.command.value, body.scope.value, body.receptor_id))
        command = ControlCommand(
            command_id=uuid4(),
            command=body.command,
            scope=body.scope,
            receptor_id=body.receptor_id,
            issued_by=Component.FOUNDER,
            issued_at=clock(),
            reason=body.reason,
        )
        state = governance.control(command, signer.sign(command))
        audit.record("control", command.model_dump(mode="json"))
        return state

    @app.post("/resume-requests", status_code=201)
    def resume_request(body: ResumeRequestIn) -> ApprovalRequest:
        """RESUME is never a direct command: it becomes an approval the Founder then decides."""
        confirmed(body, purpose_for_resume_request(body.scope.value, body.receptor_id))
        request = governance.propose_resume(body.scope, body.receptor_id)
        audit.record("resume_requested", request.model_dump(mode="json"))
        return request

    if passkeys is not None:
        _passkey_routes(app, passkeys, audit, clock)
    return app


def _passkey_routes(app: FastAPI, passkeys: PasskeyStepUp, audit: AuditPort, clock) -> None:
    """The Founder's page and passkey enrollment (gate 3, D-014)."""

    @app.get("/", response_class=HTMLResponse)
    def page() -> str:
        return PAGE

    @app.get("/passkeys")
    def enrolled() -> dict:
        return {"enrolled": passkeys.enrolled}

    @app.post("/passkeys/challenges", status_code=201)
    def passkey_challenge(body: ChallengeIn) -> dict:
        if not passkeys.enrolled:
            raise ControlsError("no passkey is enrolled yet")
        c, options = passkeys.issue_passkey(body.purpose)
        return {"challenge_id": str(c.challenge_id), "options": options}

    @app.post("/passkeys/registration-options", status_code=201)
    def registration_options(body: RegistrationOptionsIn) -> dict:
        try:
            rid, options = passkeys.registration_options(
                body.label, body.device_key, body.challenge_id, body.assertion
            )
        except PermissionError as exc:
            audit.record("passkey_refused", {"label": body.label, "at": clock().isoformat()})
            raise ControlsError(str(exc)) from exc
        return {"registration_id": str(rid), "options": options}

    @app.post("/passkeys/register", status_code=201)
    def register(body: RegisterIn) -> dict:
        try:
            key = passkeys.register(body.registration_id, body.credential)
        except PermissionError as exc:
            raise ControlsError(str(exc)) from exc
        audit.record("passkey_enrolled", {"label": key.label, "at": key.created_at})
        return {"label": key.label, "enrolled": passkeys.enrolled}
