"""View-only screen relay sessions (phase 6/D-026): the Founder watches the sandbox, never drives.

A session is the shape behind the dashboard's sandbox panel: it names which capability's screen is
shown and which task is being watched, and it is always view-only (the contract refuses otherwise).
The live pixels are the sandbox's noVNC stream, carried to the browser by the edge; this manager
only governs the sessions — opening one, ending it, and listing what is live — so STOP and audit
have something concrete to act on.
"""

from collections.abc import Callable
from datetime import UTC, datetime
from uuid import UUID, uuid4

from dyson_contracts.screen import RelayState, ScreenRelaySession

SANDBOX_CAPABILITY = "dyson.receptor.sandbox"


class RelaySessions:
    def __init__(self, clock: Callable[[], datetime] = lambda: datetime.now(UTC)):
        self._clock = clock
        self._sessions: dict[UUID, ScreenRelaySession] = {}

    def open(self, task_id: UUID, capability_id: str = SANDBOX_CAPABILITY) -> ScreenRelaySession:
        session = ScreenRelaySession(
            session_id=uuid4(),
            capability_id=capability_id,
            task_id=task_id,
            started_at=self._clock(),
        )  # view_only defaults True and the contract forbids turning it off
        self._sessions[session.session_id] = session
        return session

    def end(self, session_id: UUID) -> ScreenRelaySession:
        current = self._sessions[session_id]
        ended = current.model_copy(update={"state": RelayState.ENDED})
        self._sessions[session_id] = ended
        return ended

    def end_all(self) -> int:
        """End every live session at once — what a STOP on the sandbox does to its watchers."""
        live = self.live()
        for s in live:
            self.end(s.session_id)
        return len(live)

    def get(self, session_id: UUID) -> ScreenRelaySession | None:
        return self._sessions.get(session_id)

    def live(self) -> list[ScreenRelaySession]:
        return [s for s in self._sessions.values() if s.state is RelayState.LIVE]
