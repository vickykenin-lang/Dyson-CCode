"""The Founder's sandbox receptor capability: sealed, model-only via C, Founder-admitted."""

from dyson_contracts.capability import CapabilityKind, IsolationTier
from dyson_contracts.common import RiskLevel
from dyson_integration.hermes_agent_record import VERSION
from dyson_integration.sandbox_receptor import CAPABILITY_ID, manifest


def test_the_manifest_validates_and_is_a_sealed_container():
    m = manifest()
    assert m.id == CAPABILITY_ID and m.kind is CapabilityKind.PROCESS
    assert m.isolation is IsolationTier.CONTAINER and m.risk is RiskLevel.HIGH
    assert m.requests.open_web_sealed  # any site, isolated at the network layer
    assert m.requests.secrets == ()  # holds no credential, so nothing can leak out
    assert not m.rule_of_two.sensitive_access  # sealed from the Founder's own data
    assert m.rule_of_two.untrusted_input and m.rule_of_two.external_effect  # two, never the third


def test_it_reaches_a_model_only_through_c():
    assert manifest().requests.models == ("dyson-router",)


def test_it_is_pinned_to_the_exact_hermes_image():
    # A later image swap changes this digest and the Gate auto-disables the capability (rug pull).
    assert manifest().provenance.artifact_digest == VERSION.split("sha256:")[1]


def test_only_sensitive_actions_wait_for_a_founder_approval():
    ops = {op.name: op for op in manifest().operations}
    assert not ops["navigate"].requires_approval  # safe browsing runs on its own
    assert not ops["interact"].requires_approval
    assert ops["act_sensitive"].requires_approval  # login / submit / pay -> Founder approves
    assert ops["act_sensitive"].risk is RiskLevel.HIGH


def test_admission_goes_to_the_founder():
    assert manifest().needs_founder_admission  # high risk and open-world
