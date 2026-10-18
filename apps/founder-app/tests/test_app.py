"""Dyson Founder app."""

import ast
import re
import sys
import time
from pathlib import Path
from uuid import uuid4

from app_testkit import NOW, PASSWORD

from dyson_contracts.interface import TaskStatusUpdate
from dyson_contracts.tasks import TaskState
from dyson_founder_app.app import status_label

SRC = Path(__file__).resolve().parents[1] / "src" / "dyson_founder_app"


def test_founder_only_through_the_gateway(app, backend):  # LA-APP-06, LA-SEC-03
    assert "Founder login" in app.get("/").text
    assert "Founder login" in app.post("/send", data={"text": "Pay everyone"}).text
    r = app.post("/login", data={"username": "founder", "password": "guess"})
    assert r.status_code == 401 and "Login failed" in r.text
    assert backend.messages == []


def test_branded_dyson_text_first_page(founder):  # LA-APP-01
    page = founder.get("/").text
    assert "<title>Dyson</title>" in page and "DYSON" in page
    assert "name='viewport'" in page and "<textarea name='text'" in page


def test_acknowledgment_is_honest_and_immediate(founder, backend):
    # LA-APP-04, LA-G-09, LA-PERF-01
    start = time.monotonic()
    page = founder.post("/send", data={"text": "Publish the R11 listing"}).text
    assert time.monotonic() - start < 1.0
    assert "Accepted, not done yet" in page
    assert not re.search(r"\b(done and verified|completed)\b", page, re.I)
    backend.next_state = TaskState.APPROVAL_NEEDED
    page = founder.post("/send", data={"text": "Pay the supplier"}).text
    assert "Waiting for your approval on Direct Founder Controls" in page


def test_live_status_says_done_only_with_verified_evidence(founder, backend):  # LA-APP-04
    founder.post("/send", data={"text": "Send the report"})
    (tid,) = backend.updates
    assert founder.get(f"/tasks/{tid}/status").json()["done"] is False
    backend.updates[tid] = TaskStatusUpdate(task_id=tid, state=TaskState.RUNNING,
                                            message="tool said 200 OK", at=NOW)  # fmt: skip
    s = founder.get(f"/tasks/{tid}/status").json()
    assert s["done"] is False and s["label"] == "Running, not done until it is verified"
    backend.updates[tid] = TaskStatusUpdate(task_id=tid, state=TaskState.COMPLETED_VERIFIED,
                                            verified_evidence_ids=(uuid4(),), at=NOW)  # fmt: skip
    s = founder.get(f"/tasks/{tid}/status").json()
    assert s["done"] is True and s["settled"] is True
    assert "Done and verified" in founder.get("/").text


def test_status_label_never_calls_anything_else_done():  # LA-APP-04
    for state in TaskState:
        if state is TaskState.COMPLETED_VERIFIED:
            continue
        label, done = status_label(TaskStatusUpdate(task_id=uuid4(), state=state, at=NOW))
        assert done is False and "verified" not in label.replace("until it is verified", "")


def test_voice_and_text_share_one_thread(founder, backend):  # LA-APP-03
    founder.post("/send", data={"text": "Track R11 sales"})
    founder.post("/voice", files={"audio": ("a.webm", b"...", "audio/webm")})
    text_msg, voice_msg = backend.messages
    assert text_msg.thread_id == voice_msg.thread_id
    assert voice_msg.modality.value == "voice"
    page = founder.get("/").text
    assert "You: Track R11 sales" in page and "You (voice): Send the weekly report" in page


def test_uncertain_speech_is_confirmed_never_sent_silently(make, backend):  # LA-APP-07
    from app_testkit import ScriptedVoice

    app = make(ScriptedVoice("send fifty thousand", uncertain=True))
    app.post("/login", data={"username": "founder", "password": PASSWORD})
    page = app.post("/voice", files={"audio": ("a.webm", b"...", "audio/webm")}).text
    assert "I may have misheard" in page and "Nothing was sent" in page
    assert backend.messages == []
    app.post("/voice/confirm", data={"text": "send fifteen thousand"})
    assert backend.messages[-1].text == "send fifteen thousand"


def test_voice_is_a_slot_until_gate_5(make, backend):  # LA-APP-01
    app = make()  # NoVoice
    app.post("/login", data={"username": "founder", "password": PASSWORD})
    page = app.post("/voice", files={"audio": ("a.webm", b"...", "audio/webm")}).text
    assert "Voice is not available yet" in page and backend.messages == []


def test_reconnect_restores_tasks_and_context(founder, make, backend):  # LA-APP-05
    founder.post("/send", data={"text": "Send the report"})
    founder.post("/send", data={"text": "How are sales?"})
    fresh = make()  # the app restarted; the Founder's browser keeps its cookies
    fresh.cookies = founder.cookies
    page = fresh.get("/").text
    assert "You: Send the report" in page and "Dyson: Sales are up 4%." in page
    assert "Accepted, not done yet" in page


def test_app_holds_no_authority_and_no_records(founder):  # LA-APP-09, LA-APP-06, LA-DFC-01
    words = ("approv", "reject", "decision", "stop", "pause", "resume", "control")
    for route in founder.app.routes:
        assert not any(w in route.path.lower() for w in words), route.path
    allowed = {"dyson_contracts", "fastapi", "httpx", "pydantic"}
    for path in SRC.rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.Import):
                mods = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.level == 0:
                mods = [node.module]
            else:
                continue
            for m in mods:
                top = m.split(".")[0]
                assert top in allowed or top in sys.stdlib_module_names, f"{path.name}: {m}"
                assert top not in {"sqlite3", "shelve", "dbm", "pickle"}, f"{path.name}: {m}"
    assert set(founder.cookies.keys()) == {"dyson_session", "dyson_thread"}


def test_founder_talks_only_to_dyson(founder):  # LA-HER-04, LA-G-08
    import inspect

    from dyson_founder_app import app

    assert list(inspect.signature(app.create_app).parameters) == ["gateway", "voice",
                                                                  "secure_cookies"]  # fmt: skip
    assert "hermes" not in (SRC / "app.py").read_text().lower()
    page = founder.get("/").text
    assert "Conversation" in page and "Tasks" in page  # one place for routine operations


def test_session_cookie_is_protected(app):  # LA-APP-06
    r = app.post("/login", data={"username": "founder", "password": PASSWORD},
                 follow_redirects=False)  # fmt: skip
    set_cookie = r.headers["set-cookie"].lower()
    assert "httponly" in set_cookie and "samesite=strict" in set_cookie


def test_resubmitting_the_same_form_is_the_same_command(founder, backend):  # LA-REL-02
    page = founder.get("/").text
    mid = re.search(r"name='message_id' value='([0-9a-f-]{36})'", page).group(1)
    founder.post("/send", data={"text": "Publish it", "message_id": mid})
    founder.post("/send", data={"text": "Publish it", "message_id": mid})  # retry
    a, b = backend.messages
    assert str(a.message_id) == str(b.message_id) == mid
    fresh = re.search(r"name='message_id' value='([0-9a-f-]{36})'", founder.get("/").text).group(1)
    assert fresh != mid  # each newly drawn form is a new command


def test_statement_upload_form_is_shown_and_refusals_are_explained(founder):  # LA-VLT-01
    page = founder.get("/").text
    assert "action='/statement'" in page and "not PDF" in page
    files = {"file": ("oct.csv", b"date,amount\n", "text/csv")}
    r = founder.post("/statement", files=files,
                     data={"period_start": "2026-10-01", "period_end": "2026-10-31"})  # fmt: skip
    assert "Statement not accepted" in r.text  # nothing is connected behind this gateway


def test_conversations_can_be_archived_never_deleted(founder):  # D-023
    page = founder.get("/").text
    assert "Archive this conversation" in page and "Nothing is ever deleted" in page
    assert "delete" not in page.lower().replace("nothing was deleted", "").replace(
        "nothing is ever deleted", "")  # fmt: skip


def test_dashboard_page_is_read_only_and_explains_when_unavailable(founder):  # gate 8
    page = founder.get("/").text
    assert "href='/dashboard'" in page
    html = founder.get("/dashboard").text
    assert '["A", 500, 62' in html and '["hermes", 150, 350' in html  # every part is on the page
    assert "WHAT JUST HAPPENED" in html and "WAITING FOR YOU" in html
    assert "<form" not in html and "method:" not in html  # nothing on the dashboard can act
    r = founder.get("/dashboard/data")
    assert r.status_code == 503  # this test gateway has no dashboard connected
