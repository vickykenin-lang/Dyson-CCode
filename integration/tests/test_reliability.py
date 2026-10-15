"""LA-REL-04 failure modes, provider switch and restart, on the connected system."""

from uuid import uuid4

import psycopg
from fastapi.testclient import TestClient
from integration_testkit import say, status, task_of

from dyson_contracts.approvals import ApprovalCategory
from dyson_contracts.common import Component
from dyson_contracts.integrations import IntegrationStatus
from dyson_governance.events import ProposalKind
from dyson_integration.rules_model import MODEL_ID
from dyson_integration.system import BACKUP_MODEL_ID
from dyson_intelligence.router import change_digest


def test_receptor_down_fails_safely_and_is_reported(layer, gateway, founder, t0, clock):
    layer.tick()  # T0 reports healthy once
    t0.reachable = False
    task_id = task_of(say(gateway, founder, "Tally 1 and 2 on T0"))
    layer.tick(rounds=3)
    s = status(gateway, founder, task_id)
    assert s["state"] == "failed" and "T0 is unreachable" in s["message"]
    assert any(m[3] == task_id for m in layer.inbox.messages)  # the Founder is told
    clock.advance(days=3)
    layer.tick()
    assert not any("unverified" in m[2] for m in layer.inbox.messages)  # 3 days is allowed
    clock.advance(seconds=1)  # silent past stale_after (D-011)
    layer.tick()
    assert any("unverified" in m[2] and m[0] == "founder" for m in layer.inbox.messages)
    clock.advance(hours=1)
    layer.tick()
    assert any(m[2].startswith("Reminder:") for m in layer.inbox.messages)  # D-009


def test_model_outage_falls_back_and_total_outage_starts_nothing(layer, gateway, founder):
    # LA-RTR-04 on the real chain
    layer.models["local-rules"].down = True
    out = say(gateway, founder, "Tally 4 and 4 on T0")
    assert out["acknowledgment"] is not None  # the backup model answered
    calls = layer.router._conn.execute(
        "SELECT model_id, status FROM intelligence.calls WHERE status <> 'reserved' ORDER BY seq"
    ).fetchall()
    assert [(c["model_id"], c["status"]) for c in calls][-2:] == [
        (MODEL_ID, "failed"),
        (BACKUP_MODEL_ID, "ok"),
    ]
    layer.models["local-rules-b"].down = True
    before = layer.orch._conn.execute("SELECT count(*) AS n FROM orchestrator.tasks").fetchone()
    assert say(gateway, founder, "Tally 9 on T0")["reply"]["kind"] == "unavailable"
    after = layer.orch._conn.execute("SELECT count(*) AS n FROM orchestrator.tasks").fetchone()
    assert before == after


def test_tool_compromise_is_contained_at_once(layer, gateway, founder, t0):
    task_id = task_of(say(gateway, founder, "Tally 2 and 2 on T0"))
    layer.core.restrict_integration("t0.tally", IntegrationStatus.ISOLATED)  # compromised
    layer.tick(rounds=3)
    s = status(gateway, founder, task_id)
    assert s["state"] == "failed" and "registry" in s["message"]
    assert t0.assignments == []
    assert "t0.tally" not in layer.b._catalog.tools()


def test_founder_disconnected_and_session_lost_lose_nothing(layer, gateway, founder, settings):
    thread = uuid4()
    task_id = task_of(say(gateway, founder, "Tally 3 and 3 on T0", thread))
    gateway.delete("/session", headers=founder)  # the session is gone
    layer.tick(rounds=3)  # work continues with nobody connected
    fresh = TestClient(layer.gateway)  # a new device
    token = fresh.post(
        "/session",
        json={"username": settings.founder_username, "secret": settings.founder_password},
    ).json()["token"]
    headers = {"Authorization": f"Bearer {token}"}
    tasks = fresh.get(f"/threads/{thread}/tasks", headers=headers).json()
    assert [(t["task_id"], t["state"]) for t in tasks] == [(str(task_id), "completed-verified")]
    history = fresh.get(f"/threads/{thread}", headers=headers).json()
    assert history[0]["content"] == "Tally 3 and 3 on T0"


def test_central_server_restart_resumes_from_the_database(layer, make, t0, gateway, founder):
    task_id = task_of(say(gateway, founder, "Tally 6 and 1 on T0"))
    layer.tick()  # accepted -> running, then the server dies
    restarted = make(t0)  # a new process on the same database; no bootstrap
    restarted.tick(rounds=3)
    view = restarted.orch.get(task_id)
    assert view.state.value == "completed-verified"
    assert len(t0.assignments) == 1  # nothing ran twice across the restart
    assert restarted.core.limits("T0") is not None  # A's state came back from its event log


def test_switching_the_model_keeps_history_tasks_and_register(layer, gateway, founder):
    # LA-RTR-04, LA-MEM-10, LA-REL-06
    thread = uuid4()
    task_id = task_of(say(gateway, founder, "Tally 1 and 1 on T0", thread))
    layer.tick(rounds=3)
    rules = [layer.memory.register_view(r) for r in ("AMD-1", "AMD-4", "D-009", "D-011")]
    history = gateway.get(f"/threads/{thread}", headers=founder).json()

    payload = {"component": "C", "op": "retire_model", "value": {"model_id": MODEL_ID}}
    request = layer.core.propose(
        ProposalKind.EXTERNAL_ACTION,
        payload,
        "Retire model",
        Component.CORE_RD,
        ApprovalCategory.INTEGRATION,
    )
    assert request.action_digest == change_digest("retire_model", {"model_id": MODEL_ID})
    layer.approve(request)
    layer.router.retire_model(MODEL_ID, request.approval_id)
    assert layer.router.route("conversation.interpret") == [BACKUP_MODEL_ID]

    out = say(gateway, founder, "What did I say earlier?", thread)
    assert "Tally 1 and 1 on T0" in out["reply"]["text"]  # served by the other model
    assert [layer.memory.register_view(r) for r in ("AMD-1", "AMD-4", "D-009", "D-011")] == rules
    assert gateway.get(f"/threads/{thread}", headers=founder).json()[: len(history)] == history
    assert status(gateway, founder, task_id)["state"] == "completed-verified"


def test_host_restart_and_backup_restore_bring_the_transcript_back(
    layer, gateway, founder, dsns, make, t0, tmp_path
):
    # LA-MEM-05 on the connected system
    from dyson_memory.backup import backup, restore

    thread = uuid4()
    say(gateway, founder, "Keep this for after the restore", thread)
    dump = backup(dsns["backup"], tmp_path / "memory.dump")
    with psycopg.connect(dsns["admin"], autocommit=True) as admin:
        admin.execute("DROP SCHEMA memory CASCADE")  # the host's data is lost
    restore(dsns["admin"], dump)
    restarted = make(t0)
    token = (
        TestClient(restarted.gateway)
        .post(
            "/session",
            json={
                "username": restarted.settings.founder_username,
                "secret": restarted.settings.founder_password,
            },
        )
        .json()["token"]
    )
    history = (
        TestClient(restarted.gateway)
        .get(f"/threads/{thread}", headers={"Authorization": f"Bearer {token}"})
        .json()
    )
    assert history[0]["content"] == "Keep this for after the restore"
    assert restarted.memory.verify_audit_chain() is None
