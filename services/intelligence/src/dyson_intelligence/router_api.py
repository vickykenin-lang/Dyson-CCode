"""HTTP API of the Model Router (C). This is the address B and the Hermes container are given.

The caller is identified by its bearer credential, never by anything in the body, so Hermes cannot
call as B. There is no endpoint to change models, bars or budgets: those changes go through
ModelRouter with a Founder approval, from inside Layer A.
"""

import hashlib

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse

from dyson_contracts.common import Component, Contract, NonEmptyStr

from .models import ModelRequest, RoutedResponse
from .router import ModelRouter, RouterError


class CompleteIn(Contract):
    task_class: NonEmptyStr
    request: ModelRequest


def create_app(router: ModelRouter, tokens: dict[Component, str]) -> FastAPI:
    """tokens holds one credential per caller, from the secret store (Step 9 issues them)."""
    if any(len(t) < 32 for t in tokens.values()):
        raise ValueError("tokens must be at least 32 characters")
    by_digest = {hashlib.sha256(t.encode()).hexdigest(): c for c, t in tokens.items()}
    app = FastAPI(title="Dyson Model Router (C)")

    @app.exception_handler(RouterError)
    async def _refused(_: Request, exc: RouterError):
        return JSONResponse(status_code=409, content={"detail": str(exc)})

    @app.post("/v1/complete")
    def complete(body: CompleteIn, authorization: str = Header(default="")) -> RoutedResponse:
        scheme, _, credential = authorization.partition(" ")
        digest = hashlib.sha256(credential.encode()).hexdigest()
        caller = by_digest.get(digest) if scheme.lower() == "bearer" else None
        if caller is None:
            raise HTTPException(401, "unknown caller")
        return router.complete(caller, body.task_class, body.request)

    @app.get("/v1/routes/{task_class}")
    def route(task_class: str) -> list[str]:
        return router.route(task_class)

    return app
