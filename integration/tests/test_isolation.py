"""Layer A as it runs on AWS: Direct Founder Controls and Hermes in their own processes
(LA-DEP-01, LA-DEP-02, LA-DEP-03, LA-TOOL-02). Each piece is built exactly as its container
builds it; only the network between them is in-process here."""

from uuid import uuid4

from fastapi.testclient import TestClient
from integration_testkit import NOW, say, status, task_of

from dyson_contracts.common import Component, RiskLevel
from dyson_contracts.control import ControlMode
from dyson_contracts.toolcalls import ToolCallRequest
from dyson_founder_controls.client import ControlsClient
from dyson_integration.hermes_service import (
    RemoteHermes,
    build_hermes,
    create_hermes_app,
    write_hermes_secrets,
)
from dyson_integration.system import controls_app


def test_stop_from_the_separate_controls_process_reaches_d_and_t0(
    layer, gateway, founder, t0, dsns, settings, clock
):
    # LA-DEP-02: DFC holds only A and I; B, C and Hermes are not in its process at all.
    running = task_of(say(gateway, founder, "Tally 3 and 4 on T0"))
    for model in layer.models.values():
        model.down = True
    device = ControlsClient(TestClient(controls_app(dsns, settings, clock)),
                            layer.secrets.get("core", "device_key").encode())  # fmt: skip
    assert device.control("stop", reason="drill")["mode"] == "stopped"
    layer.tick()
    assert t0.mode is ControlMode.STOPPED
    assert status(gateway, founder, running)["state"] == "stopped"
    for model in layer.models.values():
        model.down = False
    request = device.resume_request()
    device.decide(request["approval_id"], request["action_digest"], "approve")
    layer.tick(rounds=3)
    assert t0.mode is ControlMode.RUNNING
    assert status(gateway, founder, running)["state"] == "completed-verified"


def _remote_hermes(layer, tmp_path):
    secrets_file = tmp_path / "hermes.json"
    write_hermes_secrets(layer.secrets, secrets_file)
    import json

    creds = json.loads(secrets_file.read_text())
    assert sorted(creds) == ["hermes_job_token", "hermes_router_token", "hermes_token"]
    edge = layer.hermes_edge
    hermes = build_hermes(
        "http://edge", creds, lambda prefix: TestClient(edge, base_url=f"http://edge{prefix}")
    )
    app = TestClient(create_hermes_app(hermes, creds["hermes_job_token"]))
    layer.hermes, layer.remote_hermes = (
        None,
        RemoteHermes("http://hermes", creds["hermes_job_token"], app),
    )
    return hermes, app


def test_hermes_in_its_own_process_reaches_only_c_and_g(layer, tmp_path):
    # LA-DEP-01, LA-TOOL-02: Hermes knows only its three credentials and the edge.
    hermes, app = _remote_hermes(layer, tmp_path)
    request = ToolCallRequest(call_id=uuid4(), task_id=uuid4(), idempotency_key=f"h-{uuid4().hex}",
                              tool_id="hermes.research", requested_by=Component.ORCHESTRATOR,
                              arguments={"question": "What sells best?"}, risk=RiskLevel.LOW,
                              requested_at=NOW)  # fmt: skip
    out = layer.hub.call(request, layer.tokens[Component.ORCHESTRATOR])
    assert out.status == "executed" and out.result["verified"] is False
    # Through G, Hermes is still only Hermes: a tool outside its scope is denied.
    assert hermes.call_tool(uuid4(), "t0.tally", {"numbers": [1]}, f"h-{uuid4().hex}",
                            receptor_id="T0")["status"] == "denied"  # fmt: skip
    edge = TestClient(layer.hermes_edge)
    assert edge.get("/registry").status_code == 401  # the registry needs Hermes's credential
    for path in ("/messages", "/login", "/approvals", "/control", "/finance/ledger"):
        assert edge.get(path).status_code == 404  # no Gateway, app, DFC or J on the edge
    assert app.post("/jobs", json=request.model_dump(mode="json")).status_code == 401


def test_founder_sees_waiting_approvals_and_uploads_a_statement(layer, gateway, founder):
    # LA-VLT-01, D-014, D-017: notices are read-only; the statement keeps parsed fields only.
    say(gateway, founder, "Publish on T0: launch moved to Monday")  # needs an approval
    layer.tick()
    notices = gateway.get("/notices", headers=founder).json()
    assert any(
        n["kind"] == "approval" and n["text"].startswith("Approval waiting") for n in notices
    )
    assert gateway.get("/notices").status_code == 401  # Founder session only
    import base64

    csv = (
        "Date,Narration,Chq./Ref.No.,Value Dt,Withdrawal Amt.,Deposit Amt.,Closing Balance\n"
        '05/10/26,UPI-ACME-acme@okhdfc,0000345771173416,05/10/26,,"1,500.00","9,999.00"\n'
    )
    body = {"filename": "oct.csv", "period_start": "2026-10-01", "period_end": "2026-10-31",
            "content_base64": base64.b64encode(csv.encode()).decode()}  # fmt: skip
    r = gateway.post("/statements", json=body, headers=founder)
    assert r.status_code == 200 and r.json() == {"lines_kept": 1}
    bad = dict(body, period_end="2026-10-02")  # a line outside the stated period
    assert gateway.post("/statements", json=bad, headers=founder).status_code == 422
