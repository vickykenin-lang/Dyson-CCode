"""Independent Founder confirmation for every action on this channel (LA-DFC-03, LA-SEC-03).

The real method (passkey, hardware key or other) is chosen at gate 3. Whatever it is, it plugs in
here: a single-use challenge is issued for one exact purpose (for example "approve this approval
with this digest"), and only an assertion over that challenge and that purpose is accepted.

`DeviceKeyStepUp` is the development stand-in: the Founder's device holds a key and answers a
challenge with HMAC(key, nonce | purpose). The Gateway's session token is never accepted here.
"""

import hashlib
import hmac
import secrets
from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Protocol
from uuid import UUID, uuid4

from dyson_contracts.common import Contract


class Challenge(Contract):
    challenge_id: UUID
    nonce: str
    purpose: str
    expires_at: datetime


class StepUpVerifier(Protocol):
    def issue(self, purpose: str) -> Challenge: ...

    def verify(self, challenge_id: UUID, purpose: str, assertion: str) -> str | None:
        """The method name on success, None otherwise. A challenge is used up either way."""
        ...


def device_assertion(device_key: bytes, nonce: str, purpose: str) -> str:
    """What the Founder's device computes. It runs on the device, never on the server."""
    return hmac.new(device_key, f"{nonce}|{purpose}".encode(), hashlib.sha256).hexdigest()


class DeviceKeyStepUp:
    method = "dev-device-key"

    def __init__(self, device_key: bytes, ttl: timedelta, clock: Callable[[], datetime]):
        if len(device_key) < 32:
            raise ValueError("device key must be at least 32 bytes")
        self._key, self._ttl, self._clock = device_key, ttl, clock
        self._open: dict[UUID, Challenge] = {}

    def issue(self, purpose: str) -> Challenge:
        c = Challenge(challenge_id=uuid4(), nonce=secrets.token_hex(16), purpose=purpose,
                      expires_at=self._clock() + self._ttl)  # fmt: skip
        self._open[c.challenge_id] = c
        return c

    def verify(self, challenge_id: UUID, purpose: str, assertion: str) -> str | None:
        c = self._open.pop(challenge_id, None)  # single use
        if c is None or c.purpose != purpose or self._clock() > c.expires_at:
            return None
        expected = device_assertion(self._key, c.nonce, purpose)
        return self.method if hmac.compare_digest(expected, assertion or "") else None
