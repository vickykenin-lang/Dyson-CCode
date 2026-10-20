"""The screen relay (phase 6, D-026): the Founder watches Dyson's screen, live and view-only.

When Dyson works in its browser or desktop, the Founder sees it in a popup. The relay is one-way:
the Founder watches and can STOP, but cannot drive it (driving stays with Dyson, inside its rules).
The actual pixels are streamed by the live runtime; this is the shape that describes the session.
"""

from enum import StrEnum
from uuid import UUID

from .common import Contract, NonEmptyStr, Timestamp


class RelayState(StrEnum):
    LIVE = "live"
    ENDED = "ended"


class ScreenRelaySession(Contract):
    """A view-only window onto Dyson's screen, with a STOP the Founder can always reach."""

    session_id: UUID
    capability_id: NonEmptyStr  # which capability's screen this shows (e.g. the browser)
    task_id: UUID  # the task the Founder is watching
    view_only: bool = True  # always: the Founder watches, Dyson drives
    state: RelayState = RelayState.LIVE
    started_at: Timestamp

    def model_post_init(self, _ctx) -> None:
        # view_only is a promise of this contract, not a setting a caller may turn off.
        if not self.view_only:
            raise ValueError("a screen relay is always view-only")
