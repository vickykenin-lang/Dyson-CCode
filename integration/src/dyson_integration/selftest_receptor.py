"""The self-test receptor: a sealed sandbox where Dyson runs its own ruff + pytest.

The foundation of self-development. Before Dyson ever proposes a change, it validates it here — the
repo's own checks, run in a container sealed from the core, its data and every secret (an egress
firewall allows only the throwaway test database; verified live). It holds no model and no secret,
reaches nothing outward, and only Layer A drives it. Running the checks is safe and needs no
per-call approval; what stays gated is the deploy that a passing change later asks for (the
Founder's passkey), never the testing itself.

This module records the capability and the tool, and builds the admission request; admitting it is
the Founder's passkey action on Direct Founder Controls (it runs code, so it is admitted
deliberately):

    python -m dyson_integration.selftest_receptor propose   # creates the pending approval
    python -m dyson_integration.selftest_receptor status    # shows whether it is admitted
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

CAPABILITY_ID = "dyson.receptor.selftest"
TOOL_IDS = ("selftest.run",)
_PENDING = "0" * 64  # the real image digest is pinned once that image is built


def manifest() -> CapabilityManifest:
    return CapabilityManifest(
        id=CAPABILITY_ID,
        version="0.1.0",
        kind=CapabilityKind.PROCESS,
        contract_version="1.0.0",
        publisher="Dyson",
        license="MIT",
        summary="A sealed sandbox that runs the repo's own ruff + pytest and reports pass/fail",
        provenance=Provenance(source_url="dyson://receptors/selftest", artifact_digest=_PENDING),
        operations=(
            Operation(
                name="run",
                summary="run the repository's ruff + pytest and return pass/fail per check",
                input_schema={"type": "object", "properties": {}},
                open_world=False,  # sealed: no web, no outward reach
                idempotent=True,
                risk=RiskLevel.MEDIUM,
            ),
        ),
        # It runs code that may later be model-written (untrusted input), but it is sealed from the
        # Founder's data and has no outward effect — so it stays well within the Rule of Two.
        rule_of_two=RuleOfTwo(untrusted_input=True, sensitive_access=False, external_effect=False),
        requests=Requests(open_web_sealed=False),  # no web, no model, no secrets, no hosts
        budget=Budget(cpus=Decimal("2"), memory_mb=2048, timeout_s=1800, calls_per_minute=4),
        isolation=IsolationTier.CONTAINER,
        # High risk so the Founder admits it deliberately (it runs code, model-written later),
        # even though the seal makes each run safe and needing no per-call approval.
        risk=RiskLevel.HIGH,
    )


def _propose_tools(core) -> None:
    """Record the self-test tool in A's integration registry so G can gate it by id."""
    from dyson_contracts.integrations import IntegrationKind

    for tid in TOOL_IDS:
        if core.registry().get(tid) is None:
            core.propose_integration(
                tid, IntegrationKind.INTEGRATION, f"Dyson self-test tool ({tid})", "0.1.0",
                RiskLevel.HIGH, "self-test receptor (self-development foundation)",
            )  # fmt: skip
            core.record_security_check(
                tid,
                True,
                "sealed sandbox; no model; no secrets; no route to core; egress to pg only",
            )


def main() -> None:
    from .serve import build_from_env

    core = build_from_env().core
    if sys.argv[1:] == ["propose"]:
        m = manifest()
        if core.capabilities().get(CAPABILITY_ID) is None:
            core.propose_capability(m, "Self-test receptor (self-development foundation)")
            core.check_capability(
                CAPABILITY_ID, True, "sealed; no model; no secrets; no core route"
            )
        _propose_tools(core)
        print("admission requests on Direct Founder Controls:")
        for tid in TOOL_IDS:
            result = core.admit_integration(tid)
            print(f"  {tid}: {getattr(result, 'approval_id', None)}")
    elif sys.argv[1:] == ["status"]:
        cap = core.capabilities().get(CAPABILITY_ID)
        print("capability:", "recorded" if cap else "absent")
        for tid in TOOL_IDS:
            rec = core.registry().get(tid)
            print(f"  {tid}:", rec.status.value if rec else "absent")
    else:
        raise SystemExit("usage: selftest_receptor propose|status")


if __name__ == "__main__":
    main()
