"""The Founder's sandbox receptor: a governed cloud computer shown live on the dashboard.

A Dyson-built sandbox — Chromium driven by Playwright, with a virtual display relayed view-only to
the dashboard. The Founder speaks or types a task ("open YouTube"), Dyson's own engine does it in
the sandbox, and the Founder watches it live with a STOP always in reach (the ScreenRelaySession
contract). It is cloud-only: nothing touches the Founder's own machine, and it carries NO Hermes
dependency — the smartness is Dyson's engine, the browser is open-source Chromium. (The archived
Nous agent is kept for a later, separate purpose, not for this.)

Containment (why an open web is safe here): the sandbox has its own internet egress but NO route to
the core, to Layer A's data, or to any secret — it is sealed at the network layer, so it may reach
any site without a host allowlist (Requests.open_web_sealed). It reaches a model only through C. It
holds no credential, so safe browsing runs on its own; anything that commits or spends (login, form
submit, payment) is a sensitive operation that waits for a Founder approval.

This module records the capability and builds the admission request; admitting it is the Founder's
passkey action on Direct Founder Controls (it is high risk and open-world):

    python -m dyson_integration.sandbox_receptor propose   # creates the pending approval
    python -m dyson_integration.sandbox_receptor status     # shows whether it is admitted
"""

import sys
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

CAPABILITY_ID = "dyson.receptor.sandbox"
# The artifact is Dyson's own sandbox image; the real digest is pinned once that image is built.
_PENDING = "0" * 64


def manifest() -> CapabilityManifest:
    return CapabilityManifest(
        id=CAPABILITY_ID,
        version="0.1.0",
        kind=CapabilityKind.PROCESS,
        contract_version="1.0.0",
        publisher="Dyson",
        license="MIT",
        summary="A sealed cloud sandbox (Chromium via Playwright) the Founder drives and watches",
        provenance=Provenance(source_url="dyson://receptors/sandbox", artifact_digest=_PENDING),
        operations=(
            Operation(
                name="navigate",
                summary="open a website in the sandbox (e.g. YouTube, Facebook)",
                input_schema={"type": "object", "properties": {"url": {"type": "string"}}},
                open_world=True,
                idempotent=True,
                risk=RiskLevel.MEDIUM,
            ),
            Operation(
                name="interact",
                summary="click, type, scroll or search within the open page",
                open_world=True,
                risk=RiskLevel.MEDIUM,
            ),
            Operation(
                name="act_sensitive",
                summary="log in, submit a form, or anything that commits or spends",
                open_world=True,
                risk=RiskLevel.HIGH,
                requires_approval=True,  # the Founder approves each one on Direct Founder Controls
            ),
        ),
        # Two of the three Rule-of-Two flags, never the third: it reads untrusted web and acts on
        # the web, but is sealed from the Founder's data — so it stays within the rule.
        rule_of_two=RuleOfTwo(untrusted_input=True, sensitive_access=False, external_effect=True),
        requests=Requests(open_web_sealed=True, models=("dyson-router",)),  # no secrets, no hosts
        budget=Budget(cpus=Decimal("1"), memory_mb=1536, timeout_s=1800, calls_per_minute=60),
        isolation=IsolationTier.CONTAINER,
        risk=RiskLevel.HIGH,
    )


def main() -> None:
    from .serve import build_from_env

    core = build_from_env().core
    m = manifest()
    if sys.argv[1:] == ["propose"]:
        if core.capabilities().get(CAPABILITY_ID) is None:
            core.propose_capability(m, "Founder sandbox receptor (dashboard panel)")
            core.check_capability(CAPABILITY_ID, True, "sealed sandbox; model via C; no secrets")
        result = core.admit_capability(CAPABILITY_ID)
        approval_id = getattr(result, "approval_id", None)
        print(f"admission request on Direct Founder Controls: {approval_id}")
    elif sys.argv[1:] == ["status"]:
        rec = core.capabilities().get(CAPABILITY_ID)
        print("admitted" if rec and rec.admitted else "waiting for the Founder")
    else:
        raise SystemExit("usage: sandbox_receptor propose|status")


if __name__ == "__main__":
    main()
