"""`python -m dyson_selftest`: the self-test container's control server.

Serves the control API on the sealed self-test network. Only Layer A reaches it. It runs ruff and
pytest in the baked repo against the throwaway Postgres on the same sealed network.
"""

import os

import uvicorn

from .app import create_app


def main() -> None:
    bind = os.environ.get("DYSON_SELFTEST_BIND", "0.0.0.0")
    port = int(os.environ.get("DYSON_SELFTEST_PORT", "8099"))
    uvicorn.run(create_app(), host=bind, port=port, log_level="warning")


if __name__ == "__main__":
    main()
