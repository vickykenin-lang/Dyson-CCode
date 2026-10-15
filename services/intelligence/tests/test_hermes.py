"""Isolated Hermes runtime (zone 4)."""

import ast
import sys
from pathlib import Path
from uuid import uuid4

import pytest
import yaml
from fastapi.testclient import TestClient
from intelligence_testkit import NOW, AcceptanceBarFor, FakeGovernance, configure, qual
from pydantic import ValidationError

from dyson_contracts.common import Component
from dyson_contracts.integrations import IntegrationKind
from dyson_intelligence.hermes.gate import may_rely_on_hermes
from dyson_intelligence.hermes.runtime import HermesError, HermesOutput, HermesRuntime
from dyson_intelligence.models import ChatMessage, ModelRequest, RoutedResponse
from dyson_intelligence.router_api import create_app

ROOT = Path(__file__).resolve().parents[1]
HERMES_SRC = ROOT / "src" / "dyson_intelligence" / "hermes"
COMPOSE = ROOT / "deploy" / "hermes.compose.yml"
HERMES_TOKEN = "h" * 40


class ApiRouterClient:
    """Hermes's client for C, speaking HTTP with only its own credential."""

    def __init__(self, http):
        self.http = http

    def complete(self, task_class, request):
        r = self.http.post("/v1/complete", json={"task_class": task_class,
                                                 "request": request.model_dump(mode="json")},
                           headers={"Authorization": f"Bearer {HERMES_TOKEN}"})  # fmt: skip
        r.raise_for_status()
        return RoutedResponse.model_validate(r.json())


class RecordingToolHub:
    def __init__(self):
        self.requests = []

    def call(self, request):
        self.requests.append(request)
        return {"status": "denied", "denied_checks": ["identity_permission"]}


def make(router=None, gov=None):
    gov = gov or FakeGovernance()
    hub = RecordingToolHub()
    client = ApiRouterClient(TestClient(create_app(router, {Component.HERMES: HERMES_TOKEN})))
    return HermesRuntime(client, hub, gov, clock=lambda: NOW), hub, gov


def test_hermes_code_has_no_way_out_but_its_two_ports():  # LA-HER-01, LA-HER-02, LA-HER-03
    allowed_stdlib = {"collections", "datetime", "typing", "uuid"}
    for path in HERMES_SRC.rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.Import):
                mods = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom):
                if node.level == 2:  # ..models only: the provider-neutral shapes
                    assert node.module == "models", f"{path.name} imports ..{node.module}"
                    continue
                if node.level == 1:
                    continue
                mods = [node.module]
            else:
                continue
            for m in mods:
                top = m.split(".")[0]
                assert top in allowed_stdlib | {"dyson_contracts", "pydantic"}, (
                    f"{path.name} imports {m}"
                )
                assert top in sys.stdlib_module_names or top in {"dyson_contracts", "pydantic"}


def test_hermes_container_reaches_only_c_and_g():  # LA-HER-01, LA-HER-02, LA-HER-03
    compose = yaml.safe_load(COMPOSE.read_text())
    services, networks = compose["services"], compose["networks"]
    hermes = services["hermes"]
    assert hermes["networks"] == ["hermes_net"]
    assert networks["hermes_net"]["internal"] is True  # no route to the internet
    members = {name for name, s in services.items() if "hermes_net" in s.get("networks", [])}
    assert members == {"hermes", "model-router", "tool-hub"}
    assert "volumes" not in hermes and "ports" not in hermes and "env_file" not in hermes
    assert hermes["secrets"] == ["hermes_caller_token"]
    assert set(hermes["environment"]) == {"DYSON_ROUTER_URL", "DYSON_TOOLHUB_URL"}
    assert hermes["read_only"] is True and hermes["cap_drop"] == ["ALL"]
    # Only C has a network that leaves Layer A; G is the only other neighbour.
    exits = {n for n, cfg in networks.items() if not (cfg or {}).get("internal")}
    assert {name for name, s in services.items() if set(s.get("networks", [])) & exits} == {
        "model-router"
    }


def test_hermes_thinks_only_through_c(router, gov, providers):  # LA-HER-02
    configure(router, gov, "hermes.research", [("m1", "alpha", {})])
    hermes, _, _ = make(router, gov)
    out = hermes.think("hermes.research", ModelRequest(
        messages=(ChatMessage(role="user", content="Summarise the market"),),
        max_output_tokens=100))  # fmt: skip
    assert out.model_id == "m1"
    row = router._conn.execute(
        "SELECT caller FROM intelligence.calls WHERE status = 'ok'").fetchone()  # fmt: skip
    assert row["caller"] == "hermes"


def test_hermes_cannot_use_a_model_c_has_not_approved_for_it(router, gov):  # LA-HER-02
    hermes, _, _ = make(router, gov)
    with pytest.raises(Exception, match="409"):
        hermes.think("hermes.research", ModelRequest(
            messages=(ChatMessage(role="user", content="hi"),), max_output_tokens=10))  # fmt: skip


def test_hermes_acts_only_through_g_as_itself():  # LA-HER-03
    hermes, hub, _ = make()
    result = hermes.call_tool(uuid4(), "listing.publish", {"sku": "A1"}, "hermes-test-key-0001")
    (req,) = hub.requests
    assert req.requested_by is Component.HERMES and req.approval_id is None
    assert result["status"] == "denied"  # G decides, not Hermes


def test_skills_enter_only_through_the_integration_gate():  # LA-HER-06
    hermes, _, gov = make()
    with pytest.raises(HermesError, match="integration gate"):
        hermes.load_skill("web-research")
    gov.admit("some-model", IntegrationKind.MODEL)
    with pytest.raises(HermesError):
        hermes.load_skill("some-model")  # a model is not a skill
    gov.admit("web-research", IntegrationKind.SKILL)
    gov.admit("crm-plugin", IntegrationKind.PLUGIN)
    hermes.load_skill("web-research")
    hermes.load_skill("crm-plugin")
    assert hermes.skills() == ["crm-plugin", "web-research"]
    gov.revoke("web-research")
    assert hermes.skills() == ["crm-plugin"]


def test_nothing_relies_on_hermes_until_qualified():  # LA-HER-07
    gov = FakeGovernance()
    bar = AcceptanceBarFor("research")
    good = qual("hermes", "research")
    assert not may_rely_on_hermes(gov.registry(), bar, good)  # not admitted
    gov.admit("hermes", IntegrationKind.INTEGRATION)
    assert not may_rely_on_hermes(gov.registry(), bar, None)  # not qualified
    assert not may_rely_on_hermes(gov.registry(), bar, qual("hermes", "research", passed=50))
    assert not may_rely_on_hermes(gov.registry(), bar, qual("hermes", "research", latency=99999))
    assert not may_rely_on_hermes(gov.registry(), bar, qual("hermes", "other"))
    assert not may_rely_on_hermes(gov.registry(), None, good)
    assert may_rely_on_hermes(gov.registry(), bar, good)
    gov.revoke("hermes")
    assert not may_rely_on_hermes(gov.registry(), bar, good)


def test_hermes_cannot_certify_its_own_work():  # LA-HER-08
    hermes, _, _ = make()
    out = hermes.report(uuid4(), {"summary": "All done, verified by me."})
    assert out.verified is False and out.produced_by is Component.HERMES
    with pytest.raises(ValidationError):
        HermesOutput(task_id=uuid4(), output="x", verified=True, produced_at=NOW)
    with pytest.raises(ValidationError):
        HermesOutput(task_id=uuid4(), output="x", produced_by=Component.QA_QC, produced_at=NOW)
    assert not hasattr(hermes, "verify") and not hasattr(hermes, "record_evidence")
