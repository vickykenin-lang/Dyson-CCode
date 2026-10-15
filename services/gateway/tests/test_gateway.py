"""Entry Gateway (identity, session, rate limiting)."""

import ast
import json
from datetime import timedelta
from pathlib import Path
from uuid import UUID, uuid4

from gateway_testkit import NOW, PASSWORD

from dyson_contracts.interface import Language, TaskStatusUpdate
from dyson_contracts.tasks import TaskState
from dyson_gateway.ports import ConversationReply, ReplyKind

SRC = Path(__file__).resolve().parents[1] / "src" / "dyson_gateway"


def send(client, auth, text, thread=None, **kw):
    body = {"thread_id": str(thread or uuid4()), "text": text, **kw}
    return client.post("/messages", json=body, headers=auth)


def test_every_session_is_authenticated(client, backend):  # LA-GW-01, LA-SEC-03
    assert send(client, {}, "do it").status_code == 401
    assert send(client, {"Authorization": "Bearer made-up"}, "do it").status_code == 401
    bad = client.post("/session", json={"username": "founder", "secret": "wrong"})
    assert bad.status_code == 401
    assert (
        client.post("/session", json={"username": "someone", "secret": PASSWORD}).status_code == 401
    )
    assert backend.messages == []


def test_sessions_expire_and_end(client, clock):  # LA-GW-01
    token = client.post("/session", json={"username": "founder", "secret": PASSWORD}).json()
    auth = {"Authorization": f"Bearer {token['token']}"}
    assert send(client, auth, "hello?").status_code == 200
    clock.advance(hours=1, seconds=1)  # idle too long
    assert send(client, auth, "hello?").status_code == 401
    token = client.post("/session", json={"username": "founder", "secret": PASSWORD}).json()
    auth = {"Authorization": f"Bearer {token['token']}"}
    assert client.delete("/session", headers=auth).status_code == 204
    assert send(client, auth, "hello?").status_code == 401


def test_failed_logins_lock_the_address_out(client, clock, audit):  # LA-GW-02
    for _ in range(3):
        client.post("/session", json={"username": "founder", "secret": "guess"})
    locked = client.post("/session", json={"username": "founder", "secret": PASSWORD})
    assert locked.status_code == 429  # even the right password, until the lockout ends
    clock.advance(minutes=15)
    assert (
        client.post("/session", json={"username": "founder", "secret": PASSWORD}).status_code == 200
    )
    assert [e for e, _ in audit].count("login_failed") == 3


def test_all_traffic_is_rate_limited(make, limits, audit):  # LA-GW-02
    client = make(limits.model_copy(update={"requests_per_minute": 60, "burst": 5}))
    codes = [client.post("/session", json={"username": "x", "secret": "y"}).status_code
             for _ in range(8)]  # fmt: skip
    assert 429 in codes and codes.count(429) >= 3
    assert any(e == "rate_limited" for e, _ in audit)


def test_authenticated_requests_go_to_b_only(client, auth, backend):  # LA-GW-03, LA-HER-04
    thread = uuid4()
    r = send(client, auth, "Send the weekly report", thread)
    assert r.status_code == 200
    (m,) = backend.messages
    assert m.thread_id == thread and m.text == "Send the weekly report"
    paths = {route.path for route in client.app.routes}
    assert not [p for p in paths if "hermes" in p.lower()]


def test_gateway_has_no_approval_or_control_endpoint(client):  # LA-DFC-01
    words = ("approv", "reject", "decision", "stop", "pause", "resume", "control")
    for route in client.app.routes:
        assert not any(w in route.path.lower() for w in words), route.path
    tree = ast.parse("\n".join(p.read_text() for p in SRC.rglob("*.py")))
    imported = {n.module.split(".")[0] for n in ast.walk(tree)
                if isinstance(n, ast.ImportFrom) and n.module and n.level == 0}  # fmt: skip
    assert not imported & {"dyson_governance", "dyson_founder_controls", "dyson_intelligence",
                           "psycopg"}  # fmt: skip


def test_acknowledgment_is_immediate_and_never_completion(client, auth, backend):
    # LA-APP-04, LA-G-09, LA-PERF-01
    r = send(client, auth, "Publish the listing").json()
    assert r["acknowledgment"]["state"] == "accepted"
    backend.next_state = TaskState.APPROVAL_NEEDED
    r = send(client, auth, "Pay the supplier").json()
    assert r["acknowledgment"]["state"] == "approval-needed"
    claimed = uuid4()
    backend.handle = lambda m: ConversationReply(  # a backend that over-claims
        kind=ReplyKind.ACCEPTED, text="Done!", language=Language.ENGLISH, task_id=claimed,
        task_state=TaskState.COMPLETED_VERIFIED)  # fmt: skip
    r = send(client, auth, "Claim it is done").json()
    assert r["acknowledgment"] is None  # an acknowledgment can never carry completion
    r = send(client, auth, "What is the time?").json()
    assert r["acknowledgment"] is None  # a question creates no task


def test_status_streams_until_verified(client, auth, backend):  # LA-G-09, LA-APP-04
    r = send(client, auth, "Send the report").json()
    task_id = r["reply"]["task_id"]
    tid = UUID(task_id)
    evidence = uuid4()
    backend.updates[tid] = TaskStatusUpdate(task_id=tid, state=TaskState.COMPLETED_VERIFIED,
                                            verified_evidence_ids=(evidence,), at=NOW)  # fmt: skip
    with client.stream("GET", f"/tasks/{task_id}/events", headers=auth) as s:
        events = [json.loads(line[6:]) for line in s.iter_lines() if line.startswith("data: ")]
    assert events[-1]["state"] == "completed-verified"
    assert events[-1]["verified_evidence_ids"] == [str(evidence)]


def test_reconnect_gets_tasks_and_context_back(client, auth, backend):  # LA-APP-05
    thread = uuid4()
    send(client, auth, "Send the report", thread)
    send(client, auth, "How are sales?", thread)
    token = client.post("/session", json={"username": "founder", "secret": PASSWORD}).json()
    again = {"Authorization": f"Bearer {token['token']}"}  # a new session after a dropped call
    history = client.get(f"/threads/{thread}", headers=again).json()
    assert [m["content"] for m in history if m["role"] == "user"] == [
        "Send the report", "How are sales?"]  # fmt: skip
    tasks = client.get(f"/threads/{thread}/tasks", headers=again).json()
    assert [t["state"] for t in tasks] == ["accepted"]


def test_uncertain_speech_is_passed_on_flagged(client, auth, backend):  # LA-APP-07
    send(client, auth, "send fifty thousand", modality="voice", transcription_uncertain=True)
    assert backend.messages[-1].transcription_uncertain is True


def test_session_token_is_not_stored_in_clear(clock):  # LA-GW-01
    from dyson_gateway.auth import SessionStore

    store = SessionStore(clock, max_age=timedelta(hours=1), idle_timeout=timedelta(hours=1))
    token = store.issue()
    assert token not in repr(store.__dict__)


def test_a_retried_message_keeps_its_id(client, auth, backend):  # LA-REL-02
    mid = str(uuid4())
    thread = uuid4()
    send(client, auth, "Send the report", thread, client_message_id=mid)
    send(client, auth, "Send the report", thread, client_message_id=mid)  # network retry
    first, second = backend.messages
    assert first.message_id == second.message_id == UUID(mid)
    send(client, auth, "Send the report", thread)
    assert backend.messages[-1].message_id != first.message_id  # no id: a new message
