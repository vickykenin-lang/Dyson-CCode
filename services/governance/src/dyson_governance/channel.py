"""Proof that a Founder decision or command came over the independently authenticated channel.

Direct Founder Controls (Step 8) signs what the Founder confirmed; A verifies before acting
(LA-GOV-02, LA-DFC-01). The step-up method itself is decided at gate 3, so this is an interface
with an HMAC implementation for development and tests.
"""

import hashlib
import hmac
from typing import Protocol

from pydantic import BaseModel

from dyson_contracts.digests import signing_bytes


class ChannelVerifier(Protocol):
    def verify(self, message: BaseModel, proof: str) -> bool: ...


class HmacChannel:
    """Shared-key signer and verifier. The key lives only in the secret store."""

    def __init__(self, key: bytes):
        if len(key) < 32:
            raise ValueError("channel key must be at least 32 bytes")
        self._key = key

    def sign(self, message: BaseModel) -> str:
        return hmac.new(self._key, signing_bytes(message), hashlib.sha256).hexdigest()

    def verify(self, message: BaseModel, proof: str) -> bool:
        return hmac.compare_digest(self.sign(message), proof or "")
