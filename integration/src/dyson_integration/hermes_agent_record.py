"""Record Hermes Agent in A's Supply Chain / Integration Gate (LA-GOV-06, LA-HER-06, D-025).

Run once inside the Layer A container on the server:

    python -m dyson_integration.hermes_agent_record

Hermes Agent is high risk: an autonomous agent with a terminal, a browser and a desktop. It is
recorded at its pinned image, its provenance and isolation are checked, and it is held ISOLATED.
Nothing may call it. Admitting it waits for the Founder's wiring decision and an approval on
Direct Founder Controls.
"""

from dyson_contracts.common import RiskLevel
from dyson_contracts.integrations import IntegrationKind, IntegrationRecord, IntegrationStatus

INTEGRATION_ID = "hermes-agent"
NAME = "Nous Research Hermes Agent (nousresearch/hermes-agent, MIT)"
VERSION = "v0.22.2-desktop@sha256:79c98751d8d772ac0f7bfc31a75b123b9cfac254c2e15e4d0ac8762d6b119212"
CHECK = (
    "official Nous Research image, MIT, pinned by digest; runs alone on internal "
    "hermes_agent_net (no internet, no Layer A), no secrets, no Docker socket, "
    "no-new-privileges, 1 CPU and 1.5 GB (D-025)"
)


def record(core) -> IntegrationRecord:
    """Idempotent: a second run returns the record as it stands."""
    existing = core.sync().integrations.get(INTEGRATION_ID)
    if existing is not None:
        return existing
    core.propose_integration(INTEGRATION_ID, IntegrationKind.PACKAGE, NAME, VERSION,
                             RiskLevel.HIGH, "D-025")  # fmt: skip
    core.record_security_check(INTEGRATION_ID, True, CHECK)
    return core.restrict_integration(INTEGRATION_ID, IntegrationStatus.ISOLATED)


def main() -> None:
    from .serve import build_from_env

    rec = record(build_from_env().core)
    print(rec.integration_id, rec.version, rec.status.value, rec.risk.value)


if __name__ == "__main__":
    main()
