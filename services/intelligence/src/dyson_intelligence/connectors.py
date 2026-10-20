"""Personal connectors as capability manifests (phase 3, D-026).

These declare, in the extension contract, how Gmail and Calendar enter Dyson: what they do, what
they reach, which secret they need (by name only), and their governance posture. The Supply Chain
Gate admits them; the Tool Hub enforces them. The live OAuth token is the Founder's own one-time
sign-in and is stored in SSM, never here. Reading mail is untrusted input, so its output goes
through the quarantined parser; sending is an external effect and needs a Founder approval.
"""

from decimal import Decimal

from dyson_contracts.capability import (
    Budget,
    CapabilityKind,
    CapabilityManifest,
    IsolationTier,
    Operation,
    Provenance,
    Requests,
    RuleOfTwo,
)
from dyson_contracts.common import RiskLevel

# Placeholder digests: the real artifact digest is pinned by the Gate when the connector is built.
_PENDING = "0" * 64


GMAIL = CapabilityManifest(
    id="dyson.connector.gmail",
    version="0.1.0",
    kind=CapabilityKind.CONNECTOR,
    contract_version="1.0.0",
    publisher="Dyson",
    license="MIT",
    summary="Read and send the Founder's Gmail, by the Founder's own OAuth grant",
    provenance=Provenance(source_url="dyson://connectors/gmail", artifact_digest=_PENDING),
    operations=(
        Operation(
            name="list_recent",
            summary="list recent message headers",
            read_only=True,
            open_world=True,
            idempotent=True,
            risk=RiskLevel.MEDIUM,
        ),
        Operation(
            name="get_message",
            summary="fetch one message body (untrusted; goes through the quarantined parser)",
            read_only=True,
            open_world=True,
            idempotent=True,
            risk=RiskLevel.MEDIUM,
        ),
        Operation(
            name="send",
            summary="send an email the Founder approved",
            destructive=True,
            open_world=True,
            requires_approval=True,
            risk=RiskLevel.HIGH,
        ),
    ),
    rule_of_two=RuleOfTwo(untrusted_input=True, sensitive_access=True, external_effect=True),
    requests=Requests(
        egress_hosts=("gmail.googleapis.com", "oauth2.googleapis.com"),
        secrets=("gmail_oauth_token",),
    ),
    budget=Budget(cpus=Decimal("0.25"), memory_mb=128, timeout_s=30, calls_per_minute=30),
    isolation=IsolationTier.GVISOR,
    risk=RiskLevel.HIGH,
)


CALENDAR = CapabilityManifest(
    id="dyson.connector.calendar",
    version="0.1.0",
    kind=CapabilityKind.CONNECTOR,
    contract_version="1.0.0",
    publisher="Dyson",
    license="MIT",
    summary="Read the Founder's calendar and add events the Founder approved",
    provenance=Provenance(source_url="dyson://connectors/calendar", artifact_digest=_PENDING),
    operations=(
        Operation(
            name="list_events",
            summary="list upcoming events",
            read_only=True,
            open_world=True,
            idempotent=True,
            risk=RiskLevel.MEDIUM,
        ),
        Operation(
            name="create_event",
            summary="add an event the Founder approved",
            destructive=True,
            open_world=True,
            requires_approval=True,
            risk=RiskLevel.HIGH,
        ),
    ),
    rule_of_two=RuleOfTwo(untrusted_input=False, sensitive_access=True, external_effect=True),
    requests=Requests(
        egress_hosts=("www.googleapis.com", "oauth2.googleapis.com"),
        secrets=("calendar_oauth_token",),
    ),
    budget=Budget(cpus=Decimal("0.25"), memory_mb=128, timeout_s=30, calls_per_minute=30),
    isolation=IsolationTier.GVISOR,
    risk=RiskLevel.HIGH,
)

CONNECTORS = (GMAIL, CALENDAR)
