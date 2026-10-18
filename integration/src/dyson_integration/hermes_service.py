"""Hermes in its own container on AWS (LA-DEP-01, LA-TOOL-02, LA-HER-02, LA-HER-03).

Layer A serves Hermes an edge with only three things on it: C's API (/c), G's API (/g) and a
read-only view of A's integration registry. The edge listens only on the Hermes network, which
has no route to the internet, the database or anything else. Hermes holds just its own three
credentials; G hands it work over the same network with the job credential.
"""

import json
import secrets
from pathlib import Path
from typing import Any

import httpx
from fastapi import FastAPI, Header, HTTPException

from dyson_contracts.integrations import IntegrationRecord
from dyson_contracts.toolcalls import ToolCallRequest
from dyson_intelligence.hermes.runtime import HermesRuntime
from dyson_intelligence.models import ChatMessage, ModelRequest

HERMES_TASKS = "hermes.research"
HERMES_SECRETS = ("hermes_token", "hermes_router_token", "hermes_job_token")


def hermes_job(hermes: HermesRuntime, request: ToolCallRequest) -> Any:
    """The hermes.research lane: think through C, report an unverified result."""
    thought = hermes.think(
        HERMES_TASKS,
        ModelRequest(
            messages=(ChatMessage(role="user", content=str(request.arguments.get("question"))),),
            max_output_tokens=200,
        ),
    )
    return hermes.report(request.task_id, thought.response.text).model_dump(mode="json")


def _bearer(authorization: str | None, token: str) -> None:
    given = (authorization or "").removeprefix("Bearer ")
    if not secrets.compare_digest(given, token):
        raise HTTPException(401, "not Hermes")


def create_edge(router_api: FastAPI, toolhub_api: FastAPI, registry, token: str) -> FastAPI:
    """What Layer A serves to the Hermes network, and nothing more."""
    app = FastAPI(title="Hermes edge", docs_url=None, redoc_url=None, openapi_url=None)

    @app.get("/registry")
    def view(authorization: str | None = Header(default=None)) -> dict[str, Any]:
        _bearer(authorization, token)
        return {k: v.model_dump(mode="json") for k, v in registry().items()}

    app.mount("/c", router_api)
    app.mount("/g", toolhub_api)
    return app


def write_hermes_secrets(store, path: Path) -> None:
    """Copy Hermes's own credentials, and only those, where the Hermes container reads them."""
    data = {name: store.get("core", name) for name in HERMES_SECRETS}
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data))
    tmp.chmod(0o600)
    tmp.replace(path)


class _Registry:
    def __init__(self, http: httpx.Client, token: str):
        self._http, self._token = http, token

    def registry(self) -> dict[str, IntegrationRecord]:
        r = self._http.get("/registry", headers={"Authorization": f"Bearer {self._token}"})
        r.raise_for_status()
        return {k: IntegrationRecord.model_validate(v) for k, v in r.json().items()}


def build_hermes(edge_url: str, creds: dict[str, str], client=None) -> HermesRuntime:
    """`client(prefix)` gives an HTTP client for a path on the edge (tests pass one)."""
    from .system import _HermesRouterClient, _HermesToolHubClient

    if client is None:

        def client(prefix: str) -> httpx.Client:
            return httpx.Client(base_url=edge_url.rstrip("/") + prefix, timeout=60.0)

    return HermesRuntime(
        _HermesRouterClient(client("/c"), creds["hermes_router_token"]),  # type: ignore[arg-type]
        _HermesToolHubClient(client("/g"), creds["hermes_token"]),  # type: ignore[arg-type]
        _Registry(client(""), creds["hermes_router_token"]),
    )


def create_hermes_app(hermes: HermesRuntime, job_token: str) -> FastAPI:
    app = FastAPI(title="Hermes", docs_url=None, redoc_url=None, openapi_url=None)

    @app.get("/health")
    def health() -> dict:
        return {"status": "up"}  # says nothing about Hermes's work, only that it answers

    @app.post("/jobs")
    def job(request: ToolCallRequest, x_job_credential: str | None = Header(default=None)):
        if not secrets.compare_digest(x_job_credential or "", job_token):
            raise HTTPException(401, "only G hands Hermes work")
        return hermes_job(hermes, request)

    return app


class RemoteHermes:
    """G's side: the hermes.research lane over the Hermes network."""

    def __init__(self, url: str, job_token: str, http: httpx.Client | None = None):
        self._http = http or httpx.Client(base_url=url, timeout=120.0)
        self._token = job_token

    def health(self) -> str:
        r = self._http.get("/health", timeout=2)
        r.raise_for_status()
        return r.json()["status"]

    def job(self, request: ToolCallRequest) -> Any:
        r = self._http.post("/jobs", json=request.model_dump(mode="json"),
                            headers={"X-Job-Credential": self._token})  # fmt: skip
        r.raise_for_status()
        return r.json()
