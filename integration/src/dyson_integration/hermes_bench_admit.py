"""Create the Founder admission request for the Milestone A benchmark wiring (D-027).

Run once inside the Layer A container on the server:

    python -m dyson_integration.hermes_bench_admit propose   # creates the pending approval
    python -m dyson_integration.hermes_bench_admit status    # shows whether it is approved

The wiring is recorded as a high-risk capability, so admitting it returns an approval request that
appears on Direct Founder Controls. Only the Founder can approve it, with a passkey. Nothing runs
until then; after the benchmark the capability is disabled and Hermes is re-isolated (D-025, D-023).
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

CAPABILITY_ID = "dyson.benchmark.hermes-wiring"
DIGEST = "79c98751d8d772ac0f7bfc31a75b123b9cfac254c2e15e4d0ac8762d6b119212"


def manifest() -> CapabilityManifest:
    return CapabilityManifest(
        id=CAPABILITY_ID,
        version="0.1.0",
        kind=CapabilityKind.PROCESS,
        contract_version="1.0.0",
        publisher="Dyson",
        license="MIT",
        summary="Benchmark wiring: Hermes reaches a model only through C; tools denied; time-boxed",
        provenance=Provenance(source_url="dyson://benchmark/hermes-wiring", artifact_digest=DIGEST),
        operations=(
            Operation(
                name="benchmark_run",
                summary="run the task set through C with tool side effects denied",
                open_world=True,  # it activates the Nous agent, so the Founder admits it
                risk=RiskLevel.HIGH,
                requires_approval=True,
            ),
        ),
        rule_of_two=RuleOfTwo(untrusted_input=False, sensitive_access=False, external_effect=True),
        requests=Requests(egress_hosts=("172.34.0.10",), models=("dyson-router",)),
        budget=Budget(cpus=Decimal("1"), memory_mb=1536, timeout_s=600, calls_per_minute=60),
        isolation=IsolationTier.CONTAINER,
        risk=RiskLevel.HIGH,
    )


def main() -> None:
    from .serve import build_from_env

    core = build_from_env().core
    m = manifest()
    if sys.argv[1:] == ["propose"]:
        if core.capabilities().get(CAPABILITY_ID) is None:
            core.propose_capability(m, "D-027 benchmark wiring")
            core.check_capability(CAPABILITY_ID, True, "model-only via C; tools denied; time-boxed")
        result = core.admit_capability(CAPABILITY_ID)
        approval_id = getattr(result, "approval_id", None)
        print(f"admission request on Direct Founder Controls: {approval_id}")
    elif sys.argv[1:] == ["status"]:
        rec = core.capabilities().get(CAPABILITY_ID)
        print("admitted" if rec and rec.admitted else "waiting for the Founder")
    else:
        raise SystemExit("usage: hermes_bench_admit propose|status")


if __name__ == "__main__":
    main()
