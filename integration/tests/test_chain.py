"""The end-to-end chain: command -> policy -> G -> T0 -> F verifies -> answer (Step 9 done-when)."""

import json
import threading
import time
from uuid import UUID, uuid4

from fastapi.testclient import TestClient
from integration_testkit import say, status, task_of

from dyson_contracts.audit import AuditKind
from dyson_contracts.evidence import EvidenceStage
from dyson_contracts.tasks import TaskState


def audit(layer, kind=None, task_id=None):
    events = layer.memory.audit_events(limit=5000)
    return [
        e
        for e in events
        if (kind is None or e.kind is kind) and (task_id is None or e.task_id == task_id)
    ]


def test_command_to_verified_answer(layer, gateway, founder, t0):
    # LA-G-04, LA-EVD-01, LA-ORC-07, LA-IF-02, LA-CONV-06
    out = say(gateway, founder, "Please tally 2, 3 and 4 on T0")
    assert out["acknowledgment"]["state"] == "accepted"
    assert "not done" in out["reply"]["text"]
    task_id = task_of(out)
    layer.tick(rounds=3)
    s = status(gateway, founder, task_id)
    assert s["state"] == "completed-verified" and len(s["verified_evidence_ids"]) == 1
    assert t0.published[task_id]["total"] == "9"

    # T0 got the work only through G, with the task ID and idempotency key (LA-IF-02).
    (assignment,) = t0.assignments
    assert assignment.task_id == task_id and assignment.idempotency_key == f"{task_id}:a1"
    assert assignment.issued_via.value == "G"

    # F's evidence is in I at stage 7, passed by F itself (LA-EVD-01).
    (evidence_id,) = s["verified_evidence_ids"]
    with layer.memory_conn.transaction():
        layer.memory_conn.execute("SELECT set_config('dyson.scope', 'core', true)")
        row = layer.memory_conn.execute(
            "SELECT stage, outcome, recorded_by FROM memory.evidence WHERE evidence_id = %s",
            [evidence_id],
        ).fetchone()
    assert row == {
        "stage": int(EvidenceStage.REAL_OUTPUT_VERIFIED),
        "outcome": "passed",
        "recorded_by": "F",
    }

    # D wrote every state and the evidence reference into I (LA-ORC-07).
    moves = [e.data["to"] for e in audit(layer, AuditKind.TASK_TRANSITION, task_id)]
    assert moves == ["accepted", "running", "completed-verified"]
    last = audit(layer, AuditKind.TASK_TRANSITION, task_id)[-1]
    assert last.data["evidence_ids"] == [str(evidence_id)]
    # G's decision on the call is audited in I too.
    assert any(e.kind is AuditKind.TOOL_CALL for e in audit(layer, task_id=task_id))
    assert layer.memory.verify_audit_chain() is None


def test_planted_fault_is_caught_and_held(layer, gateway, founder, t0):
    # LA-IF-04, LA-IF-12, LA-QA-03 / LA-ORC-04 via the real chain, LA-AMD-03
    task_id = task_of(say(gateway, founder, "Tally 1, 2, 3, 4, 5, 6 on T0"))
    layer.tick(rounds=12)
    s = status(gateway, founder, task_id)
    assert s["state"] == "held" and s["verified_evidence_ids"] == []
    assert len(t0.claims) == 3 and all(c.claim.value == "done" for c in t0.claims)
    verdicts = layer.qa.audit_task(task_id)
    assert [v["fit_for_purpose"] for v in verdicts] == [False, False, False]
    assert all(v["technical_success"] for v in verdicts)  # the receipt looked fine every time
    told = [m for m in layer.inbox.messages if m[3] == task_id]
    assert {m[0] for m in told} >= {"human_reviewer", "founder"}


def test_app_never_shows_a_failed_verification_as_done(layer, founder, t0):
    # LA-APP-04, LA-EVD-01
    from dyson_founder_app.app import create_app
    from dyson_founder_app.gateway_client import GatewayClient
    from dyson_founder_app.voice import NoVoice

    app = TestClient(
        create_app(GatewayClient(TestClient(layer.gateway)), NoVoice(), secure_cookies=False)
    )
    app.post(
        "/login",
        data={
            "username": layer.settings.founder_username,
            "password": layer.settings.founder_password,
        },
    )
    app.get("/")
    app.post("/send", data={"text": "Tally 1, 2, 3, 4, 5, 6 on T0"})
    layer.tick(rounds=12)
    page = app.get("/").text
    assert "Held for review" in page and "Done and verified" not in page


def test_approval_pending_then_founder_approves_once(layer, gateway, founder, t0):
    # LA-REL-04 (approval pending), LA-DFC-05 through the real chain
    task_id = task_of(say(gateway, founder, "Publish on T0: weekly summary ready"))
    layer.tick(rounds=3)
    assert status(gateway, founder, task_id)["state"] == "approval-needed"
    assert t0.assignments == []  # nothing ran while the approval was pending
    device = layer.founder_device()
    (pending,) = [p for p in device.pending() if p["task_id"] == str(task_id)]
    assert "weekly summary ready" in pending["action_summary"]
    device.decide(pending["approval_id"], pending["action_digest"], "approve")
    layer.tick(rounds=3)
    assert status(gateway, founder, task_id)["state"] == "completed-verified"
    assert len(t0.assignments) == 1
    assert layer.core.approval_status(UUID(pending["approval_id"])).value == "consumed"


def test_rejected_approval_never_runs(layer, gateway, founder, t0):
    task_id = task_of(say(gateway, founder, "Publish on T0: draft"))
    layer.tick()
    device = layer.founder_device()
    (p,) = [p for p in device.pending() if p["task_id"] == str(task_id)]
    device.decide(p["approval_id"], p["action_digest"], "reject")
    layer.tick(rounds=3)
    assert status(gateway, founder, task_id)["state"] == "rejected" and t0.assignments == []


def test_status_streams_while_the_task_runs(layer, gateway, founder, clock):
    # LA-PERF-03, LA-G-09. The test client hands over a stream only when it ends, so the worker
    # runs first in the background; the events still arrive one per state change.
    task_id = task_of(say(gateway, founder, "Tally 5 and 6 on T0"))
    stop, errors = threading.Event(), []

    def worker():
        while not stop.is_set():
            try:
                layer.tick()
            except Exception as exc:  # surfaced below instead of hanging the stream
                errors.append(exc)
            clock.advance(seconds=1)  # the stream gives up after its deadline, never hangs
            time.sleep(0.05)

    t = threading.Thread(target=worker, daemon=True)
    t.start()
    with gateway.stream("GET", f"/tasks/{task_id}/events", headers=founder) as s:
        states = [
            json.loads(line[6:])["state"] for line in s.iter_lines() if line.startswith("data: ")
        ]
    stop.set()
    t.join()
    assert errors == []
    assert states[-1] == "completed-verified" and len(states) >= 2
    assert states == sorted(set(states), key=states.index)  # each state once, in order


def test_b_offers_only_what_a_permits(layer, gateway, founder):  # LA-CONV-06
    from dyson_contracts.integrations import IntegrationStatus

    tools = layer.b._catalog.tools()
    assert set(tools) == {"t0.tally", "t0.publish"}
    assert tools["t0.tally"]["receptors"] == ["T0"]
    layer.core.restrict_integration("t0.tally", IntegrationStatus.REVOKED)
    out = say(gateway, founder, "Tally 1 and 2 on T0")
    assert out["acknowledgment"] is None and out["reply"]["kind"] == "clarify"


def test_recalls_a_previous_session_and_an_approved_rule(layer, gateway, founder, settings):
    # PRD §13 stream B milestone; LA-APP-05
    thread = uuid4()
    say(gateway, founder, "Remember the T0 fault plan", thread)
    gateway.delete("/session", headers=founder)  # the session ends
    again = gateway.post(
        "/session",
        json={"username": settings.founder_username, "secret": settings.founder_password},
    ).json()
    headers = {"Authorization": f"Bearer {again['token']}"}
    out = say(gateway, headers, "What did I say earlier?", thread)
    assert out["reply"]["text"] == 'Earlier you said: "Remember the T0 fault plan".'
    out = say(gateway, headers, "What is AMD-4?", thread)
    view = layer.memory.register_view("AMD-4")
    assert view.current.title in out["reply"]["text"]


def test_hindi_and_hinglish_commands_reach_the_same_chain(layer, gateway, founder):
    # PRD §13 stream E milestone (text path; voice waits for gate 5)
    hinglish = say(gateway, founder, "T0 par 4 aur 6 tally kar do")
    assert hinglish["reply"]["language"] == "hinglish"
    layer.tick(rounds=3)
    assert status(gateway, founder, task_of(hinglish))["state"] == "completed-verified"
    hindi = say(gateway, founder, "T0 पर 1 और 2 tally करें")
    assert hindi["reply"]["language"] == "hi" and hindi["acknowledgment"] is not None
    assert TaskState.ACCEPTED.value == hindi["acknowledgment"]["state"]
