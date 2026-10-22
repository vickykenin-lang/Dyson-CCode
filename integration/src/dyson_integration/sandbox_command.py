"""Turn a spoken or typed command into a governed sandbox action, watched live on the panel.

"YouTube kholo" -> the Founder's words reach the sandbox the one allowed way: a sandbox.browse
call through G (its six checks, STOP, admission). A view-only relay session opens so the panel goes
live, and the reply tells the Founder to watch. Anything that is not a clear open-a-site command
returns None and falls through to B untouched — this never reinterprets the conversation, it only
routes the obvious cases. A sensitive action (login, submit, pay) is never taken here; it is the
HIGH-risk sandbox.act tool, which waits for a Founder approval on Direct Founder Controls.
"""

import re
from collections.abc import Callable
from datetime import datetime
from uuid import uuid4

from dyson_contracts.common import Component, RiskLevel
from dyson_contracts.interface import FounderMessage
from dyson_contracts.toolcalls import ToolCallRequest
from dyson_gateway.ports import ConversationReply, ReplyKind

from .relay import RelaySessions

# Common sites by name, in several spellings. An unknown name that looks like a domain is used
# as-is; the sandbox server's own guard refuses anything that is not a public web page.
SITES = {
    "youtube": "https://www.youtube.com/",
    "facebook": "https://www.facebook.com/",
    "google": "https://www.google.com/",
    "gmail": "https://mail.google.com/",
    "instagram": "https://www.instagram.com/",
    "twitter": "https://twitter.com/",
    "x": "https://x.com/",
    "linkedin": "https://www.linkedin.com/",
    "whatsapp": "https://web.whatsapp.com/",
    "wikipedia": "https://www.wikipedia.org/",
    "amazon": "https://www.amazon.in/",
}
# Open-verbs in Hinglish and English. One of these must be present (or an explicit URL) so ordinary
# chat that merely mentions a site is not hijacked.
_OPEN = re.compile(r"\b(open|kholo|khol|chalu|chalao|browse|dikhao|jao|visit)\b", re.I)
_URL = re.compile(r"https?://[^\s]+", re.I)
_DOMAIN = re.compile(r"\b([a-z0-9-]+(?:\.[a-z0-9-]+)+)\b", re.I)


def parse_open_command(text: str) -> str | None:
    """Return the URL to open for a clear open-a-site command, else None (let B handle it).

    A bare site name or domain on its own line ("youtube", "amazon.in") is the command too: the
    Founder naming a place to go wants to go there. A verb is required only when the name is buried
    in a longer sentence, so ordinary chat that merely mentions a site ("youtube kya hai?") is not
    hijacked.
    """
    if m := _URL.search(text):
        return m.group(0)
    bare = text.strip().strip("?!.,").lower()  # the whole message is just a place to go
    if bare in SITES:
        return SITES[bare]
    if _DOMAIN.fullmatch(bare):
        return "https://" + bare
    if not _OPEN.search(text):
        return None
    for name, url in SITES.items():
        if re.search(rf"\b{re.escape(name)}\b", bare):
            return url
    if m := _DOMAIN.search(text):  # "open example.com"
        return "https://" + m.group(1)
    return None


class SandboxOperator:
    """Routes a clear open-a-site command to the sandbox through G, with a live relay session."""

    def __init__(
        self,
        call: Callable[[ToolCallRequest], object],  # a ToolHubForOrchestrator.call -> ToolRun
        relay: RelaySessions,
        clock: Callable[[], datetime],
        audit: Callable[[str, str], None] | None = None,
    ):
        self._call, self._relay, self._clock, self._audit = call, relay, clock, audit

    def try_handle(self, message: FounderMessage) -> ConversationReply | None:
        url = parse_open_command(message.text)
        if url is None:
            return None
        task_id = uuid4()
        session = self._relay.open(task_id)
        req = ToolCallRequest(
            call_id=uuid4(),
            task_id=task_id,
            idempotency_key="sandbox-" + uuid4().hex,
            tool_id="sandbox.browse",
            requested_by=Component.ORCHESTRATOR,
            receptor_id=None,
            arguments={"operation": "navigate", "url": url},
            risk=RiskLevel.MEDIUM,  # safe browsing; a sensitive act is the separate HIGH tool
            requested_at=self._clock(),
        )
        run = self._call(req)
        status = getattr(run, "status", "failed")
        if self._audit:
            self._audit(f"sandbox navigate {url}", status)
        if status == "executed":
            return ConversationReply(
                kind=ReplyKind.ACCEPTED,
                language=message.language,
                text=f"Khol diya: {url} — panel mein live dekho.",
                task_id=task_id,
            )
        self._relay.end(session.session_id)  # nothing to watch if it did not open
        denied = ", ".join(getattr(run, "denied_checks", ()) or ())
        reason = denied or getattr(run, "error", "") or "unavailable"
        return ConversationReply(
            kind=ReplyKind.UNAVAILABLE,
            language=message.language,
            text=f"Sandbox abhi taiyaar nahi ({reason}).",
        )
