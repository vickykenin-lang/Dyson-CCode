"""Shared digests (v1.1.0): one definition for every component that binds or signs."""

from decimal import Decimal
from uuid import UUID

from dyson_contracts.common import Money
from dyson_contracts.control import ControlCommand
from dyson_contracts.digests import (
    canonical_digest,
    external_action_digest,
    signing_bytes,
    tool_action_payload,
)


def test_canonical_digest_ignores_key_order_and_keeps_unicode():
    assert canonical_digest({"b": 1, "a": "नमस्ते"}) == canonical_digest({"a": "नमस्ते", "b": 1})
    assert canonical_digest({"a": 1}) != canonical_digest({"a": 2})


def test_external_action_digest_is_frozen():
    # Pinned so a change here can never silently invalidate approvals already given.
    assert external_action_digest({"tool_id": "t0.tally"}) == (
        "9430cf07c40f9949db68818cfcd7deddd6c392715ba4ea4d907c9316628b55a5"
    )


def test_tool_action_payload_names_tool_scope_arguments_and_spend():
    spend = Money(amount=Decimal("250.00"), currency="INR")
    p = tool_action_payload("ads.buy", "R11", {"campaign": "x"}, spend)
    assert p == {"tool_id": "ads.buy", "receptor_id": "R11", "arguments": {"campaign": "x"},
                 "amount": "250.00", "currency": "INR"}  # fmt: skip
    assert tool_action_payload("t0.tally", "T0", {}, None)["amount"] == "0"


def test_signing_bytes_are_sorted_compact_json():
    cmd = ControlCommand.model_validate({
        "command_id": str(UUID(int=1)), "command": "stop", "scope": "master",
        "issued_by": "founder", "issued_at": "2026-10-15T12:00:00Z"})  # fmt: skip
    blob = signing_bytes(cmd)
    assert blob.startswith(b'{"authorization_id":null,"command":"stop"')
    assert b" " not in blob.replace(b'"reason":""', b"")
