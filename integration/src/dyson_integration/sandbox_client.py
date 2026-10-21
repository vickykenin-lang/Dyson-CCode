"""G's adapter to the sealed sandbox: it turns an authorized tool call into one control request.

Only G holds this adapter (LA-TOOL-02). G has already run its six checks before the adapter is
called, so by the time `act` runs here the Founder's approval has been consumed (the act tool is
min_risk HIGH, so G required it). The sandbox server is refused reach back to the core, holds no
model and no secret; this client just forwards navigate / interact / act to it over sandbox_net and
hands back what is on screen as data.
"""

import os
from collections.abc import Callable

from dyson_contracts.toolcalls import ToolCallRequest

Post = Callable[[str, dict], dict]


class SandboxUnavailable(RuntimeError):
    """The sandbox is not wired in this environment (no URL, not brought up)."""


class SandboxClient:
    def __init__(self, url: str | None = None, post: Post | None = None):
        self._url = (url or os.environ.get("DYSON_SANDBOX_URL") or "").rstrip("/")
        self._post = post  # injected in tests; otherwise a real HTTP POST is used

    def _call(self, path: str, body: dict) -> dict:
        if self._post is not None:
            return self._post(path, body)
        if not self._url:
            raise SandboxUnavailable("sandbox not wired (DYSON_SANDBOX_URL unset)")
        import httpx

        r = httpx.post(self._url + path, json=body, timeout=30.0)
        r.raise_for_status()
        return r.json()

    def browse(self, args: dict) -> dict:
        """Safe browsing: open a site, or click/type/scroll within it. No Founder approval."""
        op = str(args.get("operation", "navigate"))
        if op == "navigate":
            return self._call("/navigate", {"url": str(args["url"])})
        if op == "interact":
            return self._call(
                "/interact",
                {"action": str(args["action"]), "selector": args.get("selector"),
                 "text": args.get("text")},
            )  # fmt: skip
        raise ValueError(f"browse: unknown operation {op!r} (use navigate or interact)")

    def act(self, request: ToolCallRequest) -> dict:
        """A sensitive action (login, submit, pay). The proof is the approval G just consumed."""
        args = dict(request.arguments)
        return self._call(
            "/act",
            {"action": str(args["action"]), "selector": args.get("selector"),
             "text": args.get("text"), "approval": str(request.approval_id or "")},
        )  # fmt: skip
