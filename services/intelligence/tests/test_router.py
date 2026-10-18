"""Model Router & Fallback (card C)."""

import ast
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

import psycopg
import pytest
from fastapi.testclient import TestClient
from intelligence_testkit import configure, qual, spec

from dyson_contracts.approvals import ApprovalCategory
from dyson_contracts.common import Component
from dyson_intelligence.models import ChatMessage, ModelRequest
from dyson_intelligence.redaction import Redaction
from dyson_intelligence.router import ModelRouter, RouterError, change_digest
from dyson_intelligence.router_api import create_app

B, HERMES = Component.CONVERSATION_ENGINE, Component.HERMES
SRC = Path(__file__).resolve().parents[1] / "src" / "dyson_intelligence"


def ask(text="hello", max_tokens=100):
    return ModelRequest(messages=(ChatMessage(role="user", content=text),),
                        max_output_tokens=max_tokens)  # fmt: skip


def calls(conn):
    return conn.execute("SELECT * FROM intelligence.calls ORDER BY seq").fetchall()


def test_no_model_is_preapproved(router, providers):  # LA-RTR-03
    assert router.route("chat") == []
    with pytest.raises(RouterError, match="no approved budget"):
        router.complete(B, "chat", ask())
    assert all(not p.requests for p in providers.values())


def test_registration_needs_gate_admission_and_exact_approval(router, gov):  # LA-RTR-06
    s = spec("m1", "alpha")
    digest = change_digest("register_model", s.model_dump(mode="json"))
    approval = gov.approve(digest, ApprovalCategory.INTEGRATION)
    with pytest.raises(RouterError, match="not an admitted model"):
        router.register_model(s, approval)
    gov.admit("m1")
    other = gov.approve(change_digest("register_model", spec("m1", "alpha", inp="0").model_dump(
        mode="json")), ApprovalCategory.INTEGRATION)  # fmt: skip
    with pytest.raises(RouterError, match="Founder approval"):
        router.register_model(s, other)  # approval for a different price
    router.register_model(s, approval)
    with pytest.raises(RouterError, match="Founder approval"):
        router.register_model(s, approval)  # an approval is used once


def test_cheapest_model_that_meets_the_bar_is_chosen(router, gov, providers):  # LA-RTR-02
    configure(router, gov, "chat", [
        ("cheap-but-weak", "alpha", {"passed": 80, "cost": "0.001"}),
        ("cheap-but-slow", "alpha", {"latency": 9000, "cost": "0.002"}),
        ("mid", "beta", {"cost": "0.02"}),
        ("cheapest-good", "alpha", {"cost": "0.01"}),
    ])  # fmt: skip
    assert router.route("chat") == ["cheapest-good", "mid"]
    out = router.complete(B, "chat", ask())
    assert out.model_id == "cheapest-good"
    assert [r["model_id"] for r in calls(router._conn) if r["status"] == "ok"] == ["cheapest-good"]


def test_qualification_alone_admits_nothing(router, gov):  # LA-RTR-03, LA-RTR-06
    configure(router, gov, "chat", [("m1", "alpha", {})])
    router.record_qualification(qual("unregistered", "chat", cost="0"))
    assert router.route("chat") == ["m1"]


def test_revoked_at_the_gate_leaves_the_route(router, gov):  # LA-RTR-06
    configure(router, gov, "chat", [("m1", "alpha", {}), ("m2", "beta", {"cost": "0.5"})])
    gov.revoke("m1")
    assert router.route("chat") == ["m2"]


def test_retiring_a_model_needs_approval(router, gov):  # LA-RTR-06
    configure(router, gov, "chat", [("m1", "alpha", {})])
    with pytest.raises(RouterError, match="Founder approval"):
        router.retire_model("m1", uuid4())
    approval = gov.approve(change_digest("retire_model", {"model_id": "m1"}),
                           ApprovalCategory.INTEGRATION)  # fmt: skip
    router.retire_model("m1", approval)
    assert router.route("chat") == []


def test_falls_back_to_the_tested_alternative(router, gov, providers):  # LA-RTR-04
    configure(router, gov, "chat", [("primary", "alpha", {}), ("backup", "beta", {"cost": "1"})])
    providers["alpha"].down = True
    out = router.complete(B, "chat", ask())
    assert out.model_id == "backup"
    assert [(a.model_id, a.ok) for a in out.attempts] == [("primary", False), ("backup", True)]
    final = [(r["model_id"], r["status"]) for r in calls(router._conn) if r["status"] != "reserved"]
    assert final == [("primary", "failed"), ("backup", "ok")]


def test_untested_model_is_never_a_fallback(router, gov, providers):  # LA-RTR-04
    configure(router, gov, "chat", [("primary", "alpha", {}), ("untested", "beta", {"passed": 10})])
    providers["alpha"].down = True
    with pytest.raises(RouterError, match="every model on the route failed"):
        router.complete(B, "chat", ask())
    assert not providers["beta"].requests


def test_token_limit_is_enforced_before_any_call(router, gov, providers):  # LA-RTR-05
    configure(router, gov, "chat", [("m1", "alpha", {})], max_tokens=500)
    with pytest.raises(RouterError, match="over the approved 500"):
        router.complete(B, "chat", ask(max_tokens=501))
    assert not providers["alpha"].requests


def test_daily_budget_is_enforced_before_the_call(router, gov, providers, clock):  # LA-RTR-05
    # m1 costs 1 + 2 per million tokens; 100 in + 50 out = 0.0002 per call; worst case is higher.
    configure(router, gov, "chat", [("m1", "alpha", {})], max_cost="0.0006")
    router.complete(B, "chat", ask(max_tokens=100))
    assert router.spent_today("chat", "INR") == Decimal("0.0002")
    with pytest.raises(RouterError, match="budget"):
        for _ in range(5):
            router.complete(B, "chat", ask(max_tokens=100))
    sent = len(providers["alpha"].requests)
    assert router.spent_today("chat", "INR") <= Decimal("0.0006")
    clock.advance(days=1)
    router.complete(B, "chat", ask(max_tokens=100))  # a new day, a new budget
    assert len(providers["alpha"].requests) == sent + 1


def test_a_budget_is_never_spent_in_another_currency(router, gov, providers):  # LA-RTR-05
    from dyson_intelligence.models import ModelBudget

    configure(router, gov, "chat", [("m1", "alpha", {})])  # priced in INR
    usd = ModelBudget(task_class="chat", max_cost_per_day=Decimal(5), currency="USD",
                      max_output_tokens_per_call=1000)  # fmt: skip
    router.set_budget(usd, gov.approve(change_digest("set_budget", usd.model_dump(mode="json")),
                                       ApprovalCategory.FINANCIAL))  # fmt: skip
    with pytest.raises(RouterError, match="every model on the route failed"):
        router.complete(B, "chat", ask())
    assert not providers["alpha"].requests


def test_only_b_and_hermes_may_call_a_model(router, gov):  # LA-RTR-01
    configure(router, gov, "chat", [("m1", "alpha", {})])
    for caller in (Component.ORCHESTRATOR, Component.GOVERNANCE_CORE, Component.RECEPTOR,
                   Component.TOOL_HUB, Component.QA_QC):  # fmt: skip
        with pytest.raises(RouterError, match="may not call a model"):
            router.complete(caller, "chat", ask())
    assert router.complete(HERMES, "chat", ask()).model_id == "m1"
    assert {r["caller"] for r in calls(router._conn)} == {"hermes"}


def test_api_identifies_the_caller_by_credential(router, gov):  # LA-RTR-01, LA-HER-02
    configure(router, gov, "chat", [("m1", "alpha", {})])
    tokens = {B: "b" * 40, HERMES: "h" * 40}
    client = TestClient(create_app(router, tokens))
    body = {"task_class": "chat", "request": ask().model_dump(mode="json")}
    assert client.post("/v1/complete", json=body).status_code == 401
    bad = client.post("/v1/complete", json=body, headers={"Authorization": "Bearer " + "x" * 40})
    assert bad.status_code == 401
    smuggled = dict(body, caller="B")
    as_hermes = {"Authorization": "Bearer " + "h" * 40}
    assert client.post("/v1/complete", json=smuggled, headers=as_hermes).status_code == 422
    ok = client.post("/v1/complete", json=body, headers={"Authorization": "Bearer " + "h" * 40})
    assert ok.status_code == 200 and ok.json()["model_id"] == "m1"
    assert calls(router._conn)[-1]["caller"] == "hermes"


def test_api_has_no_way_to_change_configuration(router):  # LA-RTR-06
    app = create_app(router, {B: "b" * 40})
    mutating = {(r.path, m) for r in app.routes for m in getattr(r, "methods", set())
                if m in {"POST", "PUT", "PATCH", "DELETE"}}  # fmt: skip
    assert mutating == {("/v1/complete", "POST")}


def test_routing_records_are_append_only(router, gov, conn):  # LA-RTR-06
    configure(router, gov, "chat", [("m1", "alpha", {})])
    router.complete(B, "chat", ask())
    for table in ("models", "acceptance_bars", "budgets", "qualifications", "calls"):
        for stmt in (f"UPDATE intelligence.{table} SET at = now()",
                     f"DELETE FROM intelligence.{table}"):  # fmt: skip
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                conn.execute(stmt)


def test_no_model_vendor_sdk_or_raw_network_client_anywhere():  # LA-G-06, LA-RTR-01
    forbidden = {"anthropic", "openai", "google", "vertexai", "boto3", "botocore", "cohere",
                 "mistralai", "litellm", "langchain", "requests", "httpx", "urllib", "socket",
                 "http", "aiohttp"}  # fmt: skip
    for path in SRC.rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text())):
            names = (
                [a.name for a in node.names] if isinstance(node, ast.Import)
                else [node.module] if isinstance(node, ast.ImportFrom) and node.level == 0
                else []
            )  # fmt: skip
            for name in names:
                assert name.split(".")[0] not in forbidden, f"{path.name} imports {name}"


PERSONAL = {
    "phone": "+91 98765 43210",
    "email": "vicky.k@example.com",
    "upi": "designinfra@okhdfc",
    "pan": "ABCDE1234F",
    "ifsc": "HDFC0001234",
    "card": "4111 1111 1111 1111",
    "aadhaar": "2345 6789 0123",
    "account": "50100123456789",
}


def test_personal_and_financial_identifiers_never_reach_a_model(router, gov, providers):
    # D-017, LA-RTR-07, LA-SEC-07
    configure(router, gov, "chat", [("m", "alpha", {})])
    text = "Note for T0: " + "; ".join(f"{k} {v}" for k, v in PERSONAL.items()) + "; tally 4 and 15"
    providers["alpha"].answers = ['{"note": "call [PHONE_1], pay [UPI_1]"}']
    out = router.complete(B, "chat", ask(text))
    _, sent = providers["alpha"].requests[-1]
    for value in PERSONAL.values():
        assert value not in sent.messages[0].content
    assert "tally 4 and 15" in sent.messages[0].content  # ordinary numbers still go
    assert "[PHONE_1]" in sent.messages[0].content and "[ACCOUNT" not in sent.messages[0].content
    # The reply gets the real values back inside Layer A.
    assert out.response.text == '{"note": "call +91 98765 43210, pay designinfra@okhdfc"}'


def test_names_and_addresses_never_reach_a_model(conn, gov, providers, clock):
    # D-017, LA-RTR-07, LA-SEC-07: people Layer A knows, names with a cue, and addresses
    router = ModelRouter(conn, gov, providers, clock, personal=lambda: [("NAME", "Neha Gautam")])
    configure(router, gov, "chat", [("m", "alpha", {})])
    text = ("Neha ko batao. Mera naam Arjun Mehta hai. Mr. Ravi Kumar ka address: Flat 4,"
            " Green Park, New Delhi 110016; Sharma ji se milo; श्री राम शर्मा;"
            " tally 4 and 15 on T0")  # fmt: skip
    providers["alpha"].answers = ['{"to": "[NAME_1]", "at": "[ADDRESS_1]"}']
    out = router.complete(B, "chat", ask(text))
    _, sent = providers["alpha"].requests[-1]
    hidden = ["Neha", "Gautam", "Arjun", "Mehta", "Ravi Kumar", "Flat 4", "110016", "Sharma",
              "राम शर्मा"]  # fmt: skip
    for value in hidden:
        assert value not in sent.messages[0].content, value
    assert "tally 4 and 15 on T0" in sent.messages[0].content  # the request itself still goes
    assert (
        "Mr. [NAME_" in sent.messages[0].content
        and "address: [ADDRESS_1]" in sent.messages[0].content
    )
    assert out.response.text == '{"to": "Neha", "at": "Flat 4, Green Park, New Delhi 110016"}'


@pytest.mark.parametrize("text", [
    "Tally 4 and 4 on T0", "T0 par 7 aur 8 jod do", "Aap kaun ho? Tumhara naam kya hai",
    "Haan ji, theek hai", "Survival Mode kab chalu hoga? Dyson ko Hermes se research karwao",
    "I am ready", "Tally 100000 and 5 on T0",
])  # fmt: skip
def test_everyday_text_reaches_the_model_unchanged(text):  # LA-RTR-07: no needless hiding
    assert Redaction().text(text) == text
