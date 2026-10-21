"""The sandbox control server: Layer A drives the browser here, over the sealed network.

Layer A (and only Layer A) reaches this API. It never holds a model or a secret; it just carries
out what the engine, through the Tool Hub (G), tells it — within hard limits it enforces itself:

- navigate / interact are safe browsing and run on their own.
- act is a sensitive action (login, submit, pay). It is refused unless an approval proof is
  present — G attaches one only after the Founder approves on Direct Founder Controls.
- stop is the kill-switch: once stopped, nothing acts until the control plane resumes it.

The server returns only small dicts of what is on screen; the live picture is the separate
view-only screen relay (ScreenRelaySession), not this API.
"""

from collections.abc import Callable

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from .browser import SAFE_ACTIONS, BrowserDriver
from .net import UnsafeUrl, safe_public_url


class _Navigate(BaseModel):
    url: str


class _Interact(BaseModel):
    action: str
    selector: str | None = None
    text: str | None = None


class _Act(_Interact):
    approval: str = ""  # a proof from G that the Founder approved this one action


def create_app(
    driver: BrowserDriver, verify_approval: Callable[[str], bool] | None = None
) -> FastAPI:
    """driver drives Chromium; verify_approval checks G's proof (default: any non-empty proof)."""
    app = FastAPI(title="Dyson sandbox", docs_url=None, redoc_url=None, openapi_url=None)
    ok_approval = verify_approval or (lambda proof: bool(proof))
    state = {"stopped": False}

    def _guard_running() -> None:
        if state["stopped"]:
            raise HTTPException(409, "sandbox is stopped; resume it first")

    @app.get("/health")
    def health() -> dict:
        return {"ok": True, "stopped": state["stopped"]}

    @app.get("/state")
    async def current() -> dict:
        return {**await driver.state(), "stopped": state["stopped"]}

    @app.post("/navigate")
    async def navigate(body: _Navigate) -> dict:
        _guard_running()
        try:
            url = safe_public_url(body.url)
        except UnsafeUrl as exc:
            raise HTTPException(422, str(exc)) from None
        return await driver.navigate(url)

    @app.post("/interact")
    async def interact(body: _Interact) -> dict:
        _guard_running()
        if body.action not in SAFE_ACTIONS:
            # Anything not on the safe list is a sensitive action and must go through /act.
            raise HTTPException(403, f"{body.action!r} is not safe; use /act with approval")
        return await driver.interact(body.action, body.selector, body.text)

    @app.post("/act")
    async def act(body: _Act) -> dict:
        _guard_running()
        if not ok_approval(body.approval):
            raise HTTPException(403, "a sensitive action needs a Founder approval proof")
        return await driver.interact(body.action, body.selector, body.text)

    @app.post("/stop")
    def stop() -> dict:
        state["stopped"] = True
        return {"stopped": True}

    @app.post("/resume")
    def resume() -> dict:
        state["stopped"] = False
        return {"stopped": False}

    return app
