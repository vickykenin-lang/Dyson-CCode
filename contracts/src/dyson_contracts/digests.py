"""Canonical digests and signing bytes shared across components (added in v1.1.0).

Before v1.1.0, A, G, D, C and Direct Founder Controls each kept an identical copy of these.
They now live here so the bytes an approval binds to, and the bytes a Founder-channel proof
signs, cannot drift apart between components.
"""

import hashlib
import json
from typing import Any

from pydantic import BaseModel

from .common import Money


def canonical_json(value: Any) -> bytes:
    """Sorted keys, no whitespace, UTF-8, non-ASCII kept as is."""
    return json.dumps(
        value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), default=str
    ).encode("utf-8")


def canonical_digest(value: Any) -> str:
    """sha256 of canonical JSON. Binds an approval to the exact proposal shown (LA-DFC-05)."""
    return hashlib.sha256(canonical_json(value)).hexdigest()


def external_action_digest(payload: dict[str, Any]) -> str:
    """The digest of an external-action approval in A, checked by G, D and C."""
    return canonical_digest({"kind": "external_action", "payload": payload})


def tool_action_payload(
    tool_id: str,
    receptor_id: str | None,
    arguments: dict[str, Any],
    estimated_spend: Money | None,
) -> dict[str, Any]:
    """The exact tool action a Founder approval names. D proposes it; G checks and consumes it."""
    return {
        "tool_id": tool_id,
        "receptor_id": receptor_id,
        "arguments": arguments,
        "amount": str(estimated_spend.amount) if estimated_spend else "0",
        "currency": estimated_spend.currency if estimated_spend else None,
    }


def signing_bytes(message: BaseModel) -> bytes:
    """What a Founder-channel proof signs: the message's JSON, sorted, compact, ASCII."""
    data: Any = message.model_dump(mode="json")
    return json.dumps(data, sort_keys=True, separators=(",", ":")).encode("utf-8")
