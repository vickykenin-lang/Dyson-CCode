"""Serve the OpenAI shim for the Milestone A benchmark (D-027).

Runs from the layer-a image on the benchmark-only network. It reads only the Hermes router token
from the secrets volume, forwards each OpenAI call to C's edge with that token, and serves the
OpenAI API to the Nous Hermes Agent. It holds no model and no other secret. Torn down after the
benchmark; nothing depends on it.
"""

import json
import os

import httpx
import uvicorn

from dyson_intelligence.models import ModelRequest, RoutedResponse
from dyson_intelligence.openai_shim import create_app


def _router_token() -> str:
    path = os.environ.get("DYSON_HERMES_SECRETS", "/hermes/secrets.json")
    with open(path, encoding="utf-8") as f:
        return json.load(f)["hermes_router_token"]


def _router_call(url: str, token: str):
    client = httpx.Client(base_url=url.rstrip("/"), timeout=60.0)

    def call(task_class: str, request: ModelRequest) -> RoutedResponse:
        r = client.post(
            "/v1/complete",
            json={"task_class": task_class, "request": request.model_dump(mode="json")},
            headers={"Authorization": f"Bearer {token}"},
        )
        r.raise_for_status()  # a refusal or STOP from C becomes a 502 at the shim, never a guess
        return RoutedResponse.model_validate(r.json())

    return call


def main() -> None:
    url = os.environ["DYSON_ROUTER_URL"]  # C's edge, e.g. http://172.31.0.10:8090/c
    bind = os.environ.get("DYSON_SHIM_BIND", "0.0.0.0")
    app = create_app(_router_call(url, _router_token()))
    uvicorn.run(app, host=bind, port=8099, log_level="warning")


if __name__ == "__main__":
    main()
