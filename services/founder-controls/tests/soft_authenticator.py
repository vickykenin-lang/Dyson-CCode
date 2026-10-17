"""A software passkey (ES256, attestation "none") that behaves like a phone's platform
authenticator, so the WebAuthn path is tested end to end without a browser."""

import hashlib
import json
import secrets

import cbor2
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec
from webauthn.helpers import base64url_to_bytes, bytes_to_base64url

UP, UV, AT = 0x01, 0x04, 0x40


class SoftAuthenticator:
    def __init__(self, rp_id: str, origin: str):
        self.rp_id, self.origin = rp_id, origin
        self.key = ec.generate_private_key(ec.SECP256R1())
        self.credential_id = secrets.token_bytes(16)
        self.count = 0

    def _client_data(self, kind: str, challenge: str, origin: str | None) -> bytes:
        return json.dumps(
            {
                "type": kind,
                "challenge": challenge,
                "origin": origin or self.origin,
                "crossOrigin": False,
            }  # fmt: skip
        ).encode()

    def _auth_data(self, flags: int, extra: bytes = b"", rp_id: str | None = None) -> bytes:
        self.count += 1
        rp_hash = hashlib.sha256((rp_id or self.rp_id).encode()).digest()
        return rp_hash + bytes([flags]) + self.count.to_bytes(4, "big") + extra

    def create(self, options_json: str, origin: str | None = None) -> str:
        o = json.loads(options_json)
        nums = self.key.public_key().public_numbers()
        cose = cbor2.dumps({1: 2, 3: -7, -1: 1, -2: nums.x.to_bytes(32, "big"),
                            -3: nums.y.to_bytes(32, "big")})  # fmt: skip
        attested = bytes(16) + len(self.credential_id).to_bytes(2, "big") + self.credential_id
        auth = self._auth_data(UP | UV | AT, attested + cose)
        att = cbor2.dumps({"fmt": "none", "attStmt": {}, "authData": auth})
        cid = bytes_to_base64url(self.credential_id)
        cd = self._client_data("webauthn.create", o["challenge"], origin)
        return json.dumps({
            "id": cid, "rawId": cid, "type": "public-key", "clientExtensionResults": {},
            "response": {"clientDataJSON": bytes_to_base64url(cd),
                         "attestationObject": bytes_to_base64url(att)},
        })  # fmt: skip

    def get(self, options_json: str, user_verified: bool = True, origin: str | None = None,
            rp_id: str | None = None) -> str:  # fmt: skip
        o = json.loads(options_json)
        assert base64url_to_bytes(o["challenge"])  # well-formed
        auth = self._auth_data(UP | (UV if user_verified else 0), rp_id=rp_id)
        cd = self._client_data("webauthn.get", o["challenge"], origin)
        sig = self.key.sign(auth + hashlib.sha256(cd).digest(), ec.ECDSA(hashes.SHA256()))
        cid = bytes_to_base64url(self.credential_id)
        return json.dumps({
            "id": cid, "rawId": cid, "type": "public-key", "clientExtensionResults": {},
            "response": {"clientDataJSON": bytes_to_base64url(cd),
                         "authenticatorData": bytes_to_base64url(auth),
                         "signature": bytes_to_base64url(sig), "userHandle": None},
        })  # fmt: skip
