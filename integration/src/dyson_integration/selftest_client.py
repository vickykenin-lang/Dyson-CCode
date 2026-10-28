"""G's adapter to the sealed self-test sandbox: one authorized tool call turns into one /run.

Only G holds this adapter (LA-TOOL-02), and only after the Founder has admitted the self-test
receptor. The self-test server holds no model and no secret and is refused reach back to the core;
this client just asks it to run the repo's own ruff + pytest and hands the result dict back as data.
A run is slow (the whole suite), so the client waits on it with a long timeout.
"""

import os
from collections.abc import Callable

Post = Callable[[str, dict], dict]


class SelftestUnavailable(RuntimeError):
    """The self-test sandbox is not wired in this environment (no URL, or not brought up)."""


class SelftestClient:
    def __init__(self, url: str | None = None, post: Post | None = None, timeout: float = 1200.0):
        self._url = (url or os.environ.get("DYSON_SELFTEST_URL") or "").rstrip("/")
        self._post = post  # injected in tests; otherwise a real HTTP POST is used
        self._timeout = timeout

    def run(self, args: dict | None = None) -> dict:
        """Run the repo's checks in the sealed sandbox; return {ok, checks:[...]} as data."""
        if self._post is not None:
            return self._post("/run", dict(args or {}))
        if not self._url:
            raise SelftestUnavailable("self-test not wired (DYSON_SELFTEST_URL unset)")
        import httpx

        r = httpx.post(self._url + "/run", json={}, timeout=self._timeout)
        r.raise_for_status()
        return r.json()
