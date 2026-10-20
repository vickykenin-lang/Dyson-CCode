"""The extension contract (D-026): a manifest the Gate can trust only after it checks it."""

from decimal import Decimal

import pytest
from pydantic import ValidationError

from dyson_contracts.capability import (
    Budget,
    CapabilityKind,
    CapabilityManifest,
    IsolationTier,
    Lifecycle,
    Operation,
    Provenance,
    Requests,
    RuleOfTwo,
)
from dyson_contracts.common import Money, RiskLevel

DIGEST = "a" * 64


def _manifest(**over):
    base = dict(
        id="dyson.jarvis.engine",
        version="0.1.0",
        kind=CapabilityKind.AGENT,
        contract_version="1.0.0",
        publisher="Dyson",
        license="MIT",
        summary="The Jarvis engine",
        provenance=Provenance(source_url="https://example.invalid/x", artifact_digest=DIGEST),
        operations=(Operation(name="think", summary="reason over a task"),),
        budget=Budget(cpus=Decimal("1"), memory_mb=512, timeout_s=120, calls_per_minute=30),
        isolation=IsolationTier.GVISOR,
        risk=RiskLevel.MEDIUM,
    )
    base.update(over)
    return CapabilityManifest(**base)


def test_a_plain_capability_validates_and_is_frozen():
    m = _manifest()
    assert m.id == "dyson.jarvis.engine"
    assert not m.needs_founder_admission  # plain medium-risk, no external effect
    with pytest.raises(ValidationError):
        m.risk = RiskLevel.HIGH  # frozen


def test_lifecycle_starts_at_shadow():
    assert Lifecycle.SHADOW.value == "shadow"


def test_a_reverse_dns_id_is_required():
    with pytest.raises(ValidationError):
        _manifest(id="JarvisEngine")  # not reverse-dns, has capitals


def test_a_destructive_operation_must_require_approval():
    with pytest.raises(ValidationError):
        Operation(name="delete", summary="removes data", destructive=True)
    ok = Operation(name="delete", summary="removes data", destructive=True, requires_approval=True)
    assert ok.requires_approval


def test_an_open_world_operation_must_name_its_hosts():
    web = Operation(name="search", summary="web search", open_world=True)
    with pytest.raises(ValidationError):
        _manifest(operations=(web,))  # no egress hosts named
    m = _manifest(
        operations=(web,),
        requests=Requests(egress_hosts=("www.google.com",)),
        risk=RiskLevel.MEDIUM,
    )
    assert m.needs_founder_admission  # open world always goes to the Founder


def test_overall_risk_cannot_be_below_an_operation():
    hot = Operation(name="pay", summary="moves money", risk=RiskLevel.HIGH, requires_approval=True)
    with pytest.raises(ValidationError):
        _manifest(operations=(hot,), risk=RiskLevel.LOW)


def test_wasm_cannot_hold_an_agent_or_process():
    with pytest.raises(ValidationError):
        _manifest(kind=CapabilityKind.PROCESS, isolation=IsolationTier.WASM)


def test_budget_ceilings_match_the_small_server():
    with pytest.raises(ValidationError):
        Budget(cpus=Decimal("4"), memory_mb=512, timeout_s=60, calls_per_minute=10)  # only 2 vCPU
    with pytest.raises(ValidationError):
        Budget(cpus=Decimal("1"), memory_mb=4096, timeout_s=60, calls_per_minute=10)  # over 2 GB


def test_all_three_rule_of_two_flags_force_founder_admission():
    r2 = RuleOfTwo(untrusted_input=True, sensitive_access=True, external_effect=True)
    m = _manifest(rule_of_two=r2)
    assert m.rule_of_two.all_three and m.needs_founder_admission


def test_a_money_moving_capability_declares_a_daily_cap():
    b = Budget(
        cpus=Decimal("0.5"),
        memory_mb=256,
        timeout_s=60,
        calls_per_minute=10,
        spend_per_day=Money(amount=Decimal("100.00"), currency="INR"),
    )
    assert b.spend_per_day.currency == "INR"
