"""The self-test receptor capability: sealed, no secrets, no web, no model, Founder-admitted."""

from dyson_contracts.capability import CapabilityKind, IsolationTier
from dyson_integration.selftest_receptor import CAPABILITY_ID, TOOL_IDS, manifest


def test_the_manifest_validates_and_is_a_sealed_container():
    m = manifest()
    assert m.id == CAPABILITY_ID and m.kind is CapabilityKind.PROCESS
    assert m.isolation is IsolationTier.CONTAINER


def test_it_is_sealed_with_no_web_no_secrets_and_no_model():
    m = manifest()
    assert not m.requests.open_web_sealed  # no web at all — the tests are hermetic
    assert m.requests.secrets == ()  # holds no credential
    assert m.requests.models == ()  # no model: it only runs the repo's own checks
    assert not m.rule_of_two.sensitive_access  # sealed from the Founder's data
    assert not m.rule_of_two.external_effect  # no outward effect
    assert m.rule_of_two.untrusted_input  # it may run model-written code later


def test_the_founder_admits_it_deliberately():
    assert manifest().needs_founder_admission  # high risk -> the Founder's passkey on DFC


def test_it_is_dyson_native():
    prov = manifest().provenance
    assert prov.source_url == "dyson://receptors/selftest"
    assert prov.artifact_digest == "0" * 64  # pending the image build, then pinned


def test_run_is_the_only_tool():
    assert TOOL_IDS == ("selftest.run",)
