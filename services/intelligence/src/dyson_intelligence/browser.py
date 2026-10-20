"""The browser as a capability manifest (phase 6, D-026).

Dyson's browser reaches the web only through the Tool Hub's internet gate (an allowlist), runs in a
hardened container with a throwaway profile, one at a time, and holds no credentials: the Founder's
own logins happen on the Founder's device, not here. Reading a page is untrusted (its result
goes through the quarantined parser); submitting a form, buying or sending is an external effect
and needs a Founder approval. The Founder watches it live through the screen relay.
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

_PENDING = "0" * 64

# The sites Dyson's browser may reach. The Founder adds to this; it starts small.
ALLOWED_HOSTS = ("youtube.com", "www.google.com")

BROWSER = CapabilityManifest(
    id="dyson.tool.browser",
    version="0.1.0",
    kind=CapabilityKind.TOOL,
    contract_version="1.0.0",
    publisher="Dyson",
    license="MIT",
    summary="A governed browser: allowlisted sites, live screen relay, approval before it acts out",
    provenance=Provenance(source_url="dyson://tools/browser", artifact_digest=_PENDING),
    operations=(
        Operation(
            name="navigate",
            summary="open an allowlisted page",
            open_world=True,
            idempotent=True,
            risk=RiskLevel.MEDIUM,
        ),
        Operation(
            name="snapshot",
            summary="read the current page (untrusted; goes through the quarantined parser)",
            read_only=True,
            open_world=True,
            idempotent=True,
            risk=RiskLevel.MEDIUM,
        ),
        Operation(
            name="interact",
            summary="click, type or scroll within the page",
            open_world=True,
            risk=RiskLevel.MEDIUM,
        ),
        Operation(
            name="submit",
            summary="submit a form, buy or send — the Founder approves",
            destructive=True,
            open_world=True,
            requires_approval=True,
            risk=RiskLevel.HIGH,
        ),
    ),
    rule_of_two=RuleOfTwo(untrusted_input=True, sensitive_access=False, external_effect=True),
    requests=Requests(egress_hosts=ALLOWED_HOSTS),  # no secrets: the browser holds no logins
    budget=Budget(cpus=Decimal("1"), memory_mb=900, timeout_s=120, calls_per_minute=60),
    isolation=IsolationTier.CONTAINER,
    risk=RiskLevel.HIGH,
)
