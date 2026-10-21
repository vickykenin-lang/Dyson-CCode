"""`python -m dyson_sandbox`: the sandbox container's control server.

Launches Chromium on the virtual display and serves the control API on the sealed sandbox network.
Only Layer A reaches it. The real browser runs here; unit tests use a fake driver instead.
"""

import os

import uvicorn

from .app import create_app
from .browser import PlaywrightDriver


def main() -> None:
    bind = os.environ.get("DYSON_SANDBOX_BIND", "0.0.0.0")
    port = int(os.environ.get("DYSON_SANDBOX_PORT", "8097"))
    app = create_app(PlaywrightDriver(headless=False))  # headful: its screen is relayed to the app
    uvicorn.run(app, host=bind, port=port, log_level="warning")


if __name__ == "__main__":
    main()
