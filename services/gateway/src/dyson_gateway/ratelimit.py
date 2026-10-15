"""Rate limiting and abuse protection for all inbound traffic (LA-GW-02)."""

from collections.abc import Callable
from datetime import datetime, timedelta

from dyson_contracts.common import Contract


class Limits(Contract):
    """Set per deployment (Step 10, gate 2). The PRD gives no numbers."""

    requests_per_minute: int  # per client address and per session
    burst: int
    login_failures_before_lockout: int  # per client address
    lockout: timedelta


class TokenBucket:
    def __init__(self, rate_per_minute: int, burst: int, clock: Callable[[], datetime]):
        self._rate = rate_per_minute / 60.0
        self._burst = float(burst)
        self._clock = clock
        self._state: dict[str, tuple[float, datetime]] = {}

    def allow(self, key: str) -> bool:
        now = self._clock()
        tokens, at = self._state.get(key, (self._burst, now))
        tokens = min(self._burst, tokens + (now - at).total_seconds() * self._rate)
        if tokens < 1:
            self._state[key] = (tokens, now)
            return False
        self._state[key] = (tokens - 1, now)
        return True


class LoginGuard:
    """Locks a client address out after repeated failed logins."""

    def __init__(self, failures: int, lockout: timedelta, clock: Callable[[], datetime]):
        self._max, self._lockout, self._clock = failures, lockout, clock
        self._failures: dict[str, int] = {}
        self._locked_until: dict[str, datetime] = {}

    def locked(self, client: str) -> bool:
        until = self._locked_until.get(client)
        if until is None:
            return False
        if self._clock() >= until:
            del self._locked_until[client]
            return False
        return True

    def failed(self, client: str) -> None:
        n = self._failures.get(client, 0) + 1
        if n >= self._max:
            self._locked_until[client] = self._clock() + self._lockout
            n = 0
        self._failures[client] = n

    def succeeded(self, client: str) -> None:
        self._failures.pop(client, None)
