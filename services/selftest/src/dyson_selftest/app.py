"""The self-test control server: Layer A asks it here, over the sealed network, to run the repo's
checks. Only Layer A reaches this API. It holds no model and no secret; it just runs ruff and
pytest in the baked repo against its throwaway Postgres and returns a small result dict.

- run is the one real operation: run ruff (lint + format) and pytest, return pass/fail per check.
- stop is the kill-switch: once stopped nothing runs until resume, matching the browser sandbox.

It refuses to start a second run while one is in flight, so the sandbox can never thrash.
"""

import os
import threading
from collections.abc import Callable

from fastapi import FastAPI, HTTPException

from .runner import run_checks

REPO_DIR = os.environ.get("DYSON_SELFTEST_REPO", "/app/repo")
PG_DSN = os.environ.get("DYSON_SELFTEST_PG", "postgresql://postgres@selftest-pg:5432/postgres")


def create_app(run: Callable[[], dict] | None = None) -> FastAPI:
    """run defaults to running the real checks on REPO_DIR against PG_DSN; tests pass a fake."""
    app = FastAPI(title="Dyson self-test", docs_url=None, redoc_url=None, openapi_url=None)
    do_run = run or (lambda: run_checks(REPO_DIR, PG_DSN))
    state = {"stopped": False}
    lock = threading.Lock()

    @app.get("/health")
    def health() -> dict:
        return {"ok": True, "stopped": state["stopped"], "running": lock.locked()}

    @app.post("/run")
    def run_endpoint() -> dict:
        if state["stopped"]:
            raise HTTPException(409, "self-test is stopped; resume it first")
        if not lock.acquire(blocking=False):
            raise HTTPException(409, "a self-test run is already in progress")
        try:
            return do_run()
        finally:
            lock.release()

    @app.post("/stop")
    def stop() -> dict:
        state["stopped"] = True
        return {"stopped": True}

    @app.post("/resume")
    def resume() -> dict:
        state["stopped"] = False
        return {"stopped": False}

    return app
