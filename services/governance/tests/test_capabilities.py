"""Extension contract through the Gate (D-026): propose, check, admit, pin, rug-pull."""

from decimal import Decimal

import pytest

from dyson_contracts.capability import (
    Budget,
    CapabilityKind,
    CapabilityManifest,
    IsolationTier,
    Lifecycle,
    Operation,
    Provenance,
    Requests,
)
from dyson_contracts.common import RiskLevel
from dyson_governance.core import GovernanceError

DIGEST = "b" * 64


def _manifest(cid="dyson.jarvis.engine", ops=None, risk=RiskLevel.MEDIUM, **over):
    base = dict(
        id=cid,
        version="0.1.0",
        kind=CapabilityKind.AGENT,
        contract_version="1.0.0",
        publisher="Dyson",
        license="MIT",
        summary="a capability",
        provenance=Provenance(source_url="https://example.invalid/x", artifact_digest=DIGEST),
        operations=ops or (Operation(name="think", summary="reason over a task"),),
        budget=Budget(cpus=Decimal("1"), memory_mb=512, timeout_s=120, calls_per_minute=30),
        isolation=IsolationTier.GVISOR,
        risk=risk,
    )
    base.update(over)
    return CapabilityManifest(**base)


def test_a_capability_starts_shadow_and_not_live(core):
    core.propose_capability(_manifest(), "gate-1")
    rec = core.capabilities()["dyson.jarvis.engine"]
    assert rec.lifecycle is Lifecycle.SHADOW and not rec.admitted and not rec.live


def test_nothing_is_admitted_before_a_check(core):
    core.propose_capability(_manifest(), "gate-1")
    with pytest.raises(GovernanceError):
        core.admit_capability("dyson.jarvis.engine")


def test_a_failed_check_disables(core):
    core.propose_capability(_manifest(), "gate-1")
    rec = core.check_capability("dyson.jarvis.engine", False, "scan-bad")
    assert rec.lifecycle is Lifecycle.DISABLED and not rec.live


def test_plain_capability_admits_without_the_founder(core):
    core.propose_capability(_manifest(), "gate-1")
    core.check_capability("dyson.jarvis.engine", True, "scan-ok")
    rec = core.admit_capability("dyson.jarvis.engine")
    assert rec.admitted and rec.live and rec.lifecycle is Lifecycle.SHADOW


def test_high_risk_capability_needs_a_founder_approval(core, founder):
    core.propose_capability(_manifest(risk=RiskLevel.HIGH), "gate-1")
    core.check_capability("dyson.jarvis.engine", True, "scan-ok")
    req = core.admit_capability("dyson.jarvis.engine")
    assert not core.capabilities()["dyson.jarvis.engine"].admitted  # waits on the Founder
    founder.decide(core, req)
    rec = core.capabilities()["dyson.jarvis.engine"]
    assert rec.admitted and rec.founder_approval_id == str(req.approval_id)


def test_an_external_operation_needs_the_founder(core, founder):
    web = Operation(name="search", summary="web", open_world=True)
    m = _manifest(ops=(web,), requests=Requests(egress_hosts=("www.google.com",)))
    core.propose_capability(m, "gate-1")
    core.check_capability(m.id, True, "scan-ok")
    req = core.admit_capability(m.id)
    founder.decide(core, req)
    assert core.capabilities()[m.id].admitted


def test_promotion_moves_to_enabled(core):
    core.propose_capability(_manifest(), "gate-1")
    core.check_capability("dyson.jarvis.engine", True, "scan-ok")
    core.admit_capability("dyson.jarvis.engine")
    rec = core.promote_capability("dyson.jarvis.engine", Lifecycle.ENABLED)
    assert rec.lifecycle is Lifecycle.ENABLED and rec.live


def test_a_changed_operation_hash_disables_the_capability(core):
    m = _manifest()
    core.propose_capability(m, "gate-1")
    core.check_capability(m.id, True, "scan-ok")
    core.admit_capability(m.id)
    # Same operation, unchanged: integrity holds.
    assert core.check_capability_integrity(m.id, m.operations).live
    # A quietly swapped operation (a rug pull): the Gate disables it.
    swapped = (Operation(name="think", summary="now also emails the founder", open_world=True),)
    rec = core.check_capability_integrity(m.id, swapped)
    assert rec.lifecycle is Lifecycle.DISABLED and not rec.admitted and not rec.live


def test_disable_is_immediate_and_needs_no_approval(core):
    core.propose_capability(_manifest(), "gate-1")
    core.check_capability("dyson.jarvis.engine", True, "scan-ok")
    core.admit_capability("dyson.jarvis.engine")
    assert not core.disable_capability("dyson.jarvis.engine").live
