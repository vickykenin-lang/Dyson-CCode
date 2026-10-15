"""Founder authentication and sessions (LA-GW-01, LA-SEC-03).

The login method is pluggable: gate 3 chooses the real one. `PasswordAuthenticator` is the
development stand-in; it stores only an scrypt hash. Session tokens are random, returned once,
and kept only as sha256 digests.
"""

import hashlib
import hmac
import secrets
from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Protocol

from dyson_contracts.common import Contract


class FounderAuthenticator(Protocol):
    def authenticate(self, username: str, secret: str) -> bool: ...


class PasswordAuthenticator:
    N, R, P = 2**14, 8, 1

    def __init__(self, username: str, salt: bytes, password_hash: bytes):
        self._username, self._salt, self._hash = username, salt, password_hash

    @classmethod
    def create(cls, username: str, password: str) -> "PasswordAuthenticator":
        salt = secrets.token_bytes(16)
        return cls(username, salt, cls._derive(password, salt))

    @classmethod
    def _derive(cls, password: str, salt: bytes) -> bytes:
        return hashlib.scrypt(password.encode(), salt=salt, n=cls.N, r=cls.R, p=cls.P)

    def authenticate(self, username: str, secret: str) -> bool:
        ok_user = hmac.compare_digest(username.encode(), self._username.encode())
        ok_pw = hmac.compare_digest(self._derive(secret, self._salt), self._hash)
        return ok_user and ok_pw


class Session(Contract):
    session_id: str  # sha256 of the token
    created_at: datetime
    last_seen: datetime


class SessionStore:
    """In-memory sessions. A Gateway restart ends every session; the Founder logs in again and
    loses nothing, because tasks and history live in D and I."""

    def __init__(self, clock: Callable[[], datetime], max_age: timedelta, idle_timeout: timedelta):
        self._clock, self._max_age, self._idle = clock, max_age, idle_timeout
        self._sessions: dict[str, Session] = {}

    def issue(self) -> str:
        token = secrets.token_urlsafe(32)
        now = self._clock()
        sid = _digest(token)
        self._sessions[sid] = Session(session_id=sid, created_at=now, last_seen=now)
        return token

    def check(self, token: str) -> Session | None:
        sid = _digest(token or "")
        s = self._sessions.get(sid)
        if s is None:
            return None
        now = self._clock()
        if now - s.created_at > self._max_age or now - s.last_seen > self._idle:
            del self._sessions[sid]
            return None
        s = s.model_copy(update={"last_seen": now})
        self._sessions[sid] = s
        return s

    def end(self, token: str) -> None:
        self._sessions.pop(_digest(token or ""), None)


def _digest(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()
