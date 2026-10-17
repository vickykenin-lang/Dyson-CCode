"""Passkey step-up for Direct Founder Controls (gate 3, D-014).

Every approval, rejection, STOP, PAUSE and resume request is confirmed with a passkey on the
Founder's phone. The WebAuthn challenge is bound to the exact purpose of the action: it is
SHA-256(nonce | purpose), so an assertion made for one action cannot be used for another.

Enrollment: the first passkey is registered with the development device key as proof (it is
handed to the Founder through the encrypted parameter store); later passkeys (the backup) need
a confirmation from an enrolled passkey. Once a passkey is enrolled, the device key no longer
confirms anything.
"""

import hashlib
import hmac
import json
import secrets
import threading
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid4

from webauthn import (
    generate_authentication_options,
    generate_registration_options,
    options_to_json,
    verify_authentication_response,
    verify_registration_response,
)
from webauthn.helpers import base64url_to_bytes, bytes_to_base64url
from webauthn.helpers.structs import (
    AuthenticatorSelectionCriteria,
    PublicKeyCredentialDescriptor,
    ResidentKeyRequirement,
    UserVerificationRequirement,
)

from .stepup import Challenge, DeviceKeyStepUp

MAX_PASSKEYS = 3
FOUNDER_USER_ID = b"dyson-founder"


def purpose_for_add_passkey(label: str) -> str:
    return f"add-passkey|{label}"


def webauthn_challenge(nonce: str, purpose: str) -> bytes:
    """The bytes the authenticator signs over: binds the assertion to this one action."""
    return hashlib.sha256(f"{nonce}|{purpose}".encode()).digest()


@dataclass
class StoredPasskey:
    credential_id: str  # base64url
    public_key: str  # base64url COSE key
    sign_count: int
    label: str
    created_at: str


class PasskeyStore:
    """The Founder's enrolled passkeys, in a private file on the server's data volume."""

    def __init__(self, path: Path):
        self._path, self._lock = path, threading.Lock()

    def all(self) -> list[StoredPasskey]:
        if not self._path.exists():
            return []
        return [StoredPasskey(**p) for p in json.loads(self._path.read_text())]

    def _save(self, keys: list[StoredPasskey]) -> None:
        tmp = self._path.with_suffix(".tmp")
        tmp.write_text(json.dumps([p.__dict__ for p in keys]))
        tmp.chmod(0o600)
        tmp.replace(self._path)

    def add(self, key: StoredPasskey) -> None:
        with self._lock:
            keys = self.all()
            if len(keys) >= MAX_PASSKEYS:
                raise ValueError("passkey limit reached")
            self._save([*keys, key])

    def update_count(self, credential_id: str, count: int) -> None:
        with self._lock:
            keys = self.all()
            for k in keys:
                if k.credential_id == credential_id:
                    k.sign_count = count
            self._save(keys)


class PasskeyStepUp:
    """A `StepUpVerifier`: passkeys once enrolled, the device key only before that."""

    method = "passkey"

    def __init__(
        self,
        store: PasskeyStore,
        device: DeviceKeyStepUp,
        device_key: bytes,
        rp_id: str,
        origin: str,
        ttl: timedelta,
        clock: Callable[[], datetime],
    ):
        self._store, self._device, self._device_key = store, device, device_key
        self._rp_id, self._origin, self._ttl, self._clock = rp_id, origin, ttl, clock
        self._open: dict[UUID, Challenge] = {}
        self._registrations: dict[UUID, tuple[bytes, str, datetime]] = {}

    @property
    def enrolled(self) -> int:
        return len(self._store.all())

    # Challenges for actions --------------------------------------------------------------
    def issue(self, purpose: str) -> Challenge:
        """Device-key challenges (development client) keep working until a passkey exists."""
        return self._device.issue(purpose)

    def issue_passkey(self, purpose: str) -> tuple[Challenge, str]:
        c = Challenge(challenge_id=uuid4(), nonce=secrets.token_hex(16), purpose=purpose,
                      expires_at=self._clock() + self._ttl)  # fmt: skip
        self._open[c.challenge_id] = c
        options = generate_authentication_options(
            rp_id=self._rp_id,
            challenge=webauthn_challenge(c.nonce, purpose),
            allow_credentials=[
                PublicKeyCredentialDescriptor(id=base64url_to_bytes(k.credential_id))
                for k in self._store.all()
            ],
            user_verification=UserVerificationRequirement.REQUIRED,
        )
        return c, options_to_json(options)

    def verify(self, challenge_id: UUID, purpose: str, assertion: str) -> str | None:
        if not (assertion or "").startswith("{"):
            if self.enrolled:  # D-014: once a passkey exists, only a passkey confirms
                self._device.verify(challenge_id, purpose, "")  # use the challenge up
                return None
            return self._device.verify(challenge_id, purpose, assertion)
        c = self._open.pop(challenge_id, None)  # single use
        if c is None or c.purpose != purpose or self._clock() > c.expires_at:
            return None
        try:
            credential = json.loads(assertion)
            stored = {k.credential_id: k for k in self._store.all()}.get(credential.get("id"))
            if stored is None:
                return None
            result = verify_authentication_response(
                credential=credential,
                expected_challenge=webauthn_challenge(c.nonce, purpose),
                expected_rp_id=self._rp_id,
                expected_origin=self._origin,
                credential_public_key=base64url_to_bytes(stored.public_key),
                credential_current_sign_count=stored.sign_count,
                require_user_verification=True,
            )
        except Exception:  # any malformed or failing assertion is a refusal
            return None
        self._store.update_count(stored.credential_id, result.new_sign_count)
        return self.method

    # Enrollment ----------------------------------------------------------------------------
    def registration_options(
        self,
        label: str,
        device_key: str | None = None,
        challenge_id: UUID | None = None,
        assertion: str | None = None,
    ) -> tuple[UUID, str]:
        """Allowed with the device key while nothing is enrolled; afterwards only with a
        passkey confirmation for adding exactly this label."""
        keys = self._store.all()
        if len(keys) >= MAX_PASSKEYS:
            raise PermissionError("passkey limit reached")
        if not keys:
            if not hmac.compare_digest((device_key or "").encode(), self._device_key):
                raise PermissionError("the device key does not match")
        elif not (
            challenge_id
            and self.verify(challenge_id, purpose_for_add_passkey(label), assertion or "")
        ):
            raise PermissionError("adding a passkey needs a confirmation from an enrolled one")
        challenge = secrets.token_bytes(32)
        options = generate_registration_options(
            rp_id=self._rp_id,
            rp_name="Dyson Direct Founder Controls",
            user_id=FOUNDER_USER_ID,
            user_name="founder",
            user_display_name="Dyson Founder",
            challenge=challenge,
            exclude_credentials=[
                PublicKeyCredentialDescriptor(id=base64url_to_bytes(k.credential_id)) for k in keys
            ],
            authenticator_selection=AuthenticatorSelectionCriteria(
                resident_key=ResidentKeyRequirement.PREFERRED,
                user_verification=UserVerificationRequirement.REQUIRED,
            ),
        )
        registration_id = uuid4()
        self._registrations[registration_id] = (challenge, label, self._clock() + self._ttl)
        return registration_id, options_to_json(options)

    def register(self, registration_id: UUID, credential: str) -> StoredPasskey:
        pending = self._registrations.pop(registration_id, None)
        if pending is None or self._clock() > pending[2]:
            raise PermissionError("no such registration is open")
        challenge, label, _ = pending
        try:
            v = verify_registration_response(
                credential=json.loads(credential),
                expected_challenge=challenge,
                expected_origin=self._origin,
                expected_rp_id=self._rp_id,
                require_user_verification=True,
            )
        except Exception as exc:
            raise PermissionError("the passkey could not be verified") from exc
        key = StoredPasskey(
            credential_id=bytes_to_base64url(v.credential_id),
            public_key=bytes_to_base64url(v.credential_public_key),
            sign_count=v.sign_count,
            label=label,
            created_at=self._clock().isoformat(),
        )
        self._store.add(key)
        return key
