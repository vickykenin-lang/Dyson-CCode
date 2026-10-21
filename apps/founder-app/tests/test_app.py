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


def test_without_voice_connected_nothing_is_sent(make, backend):  # LA-APP-01
    app = make()  # NoVoice
    app.post("/login", data={"username": "founder", "password": PASSWORD})
    page = app.post("/voice", files={"audio": ("a.wav", b"...", "audio/wav")}).text
    assert "voice is not connected yet" in page and backend.messages == []


class FakeVoiceService:  # stands in for the voice container's HTTP API
    def __init__(self, answer, status=200):
        self.answer, self.status, self.sent = answer, status, []

    def post(self, url, content, headers):
        import httpx

        self.sent.append((url, headers["content-type"], content))
        return httpx.Response(self.status, json=self.answer)


def test_spoken_words_reach_dyson_through_the_voice_container(make, backend):  # D-024
    from dyson_founder_app.voice import RemoteVoice

    service = FakeVoiceService({"text": "T0 par 7 aur 8 jod do", "uncertain": False})
    app = make(RemoteVoice("http://172.32.0.10:8096", http=service))
    app.post("/login", data={"username": "founder", "password": PASSWORD})
    app.post("/voice", files={"audio": ("voice.wav", b"RIFF-wav", "audio/wav")})
    assert service.sent == [("http://172.32.0.10:8096/transcribe", "audio/wav", b"RIFF-wav")]
    assert backend.messages[-1].text == "T0 par 7 aur 8 jod do"
    assert backend.messages[-1].modality.value == "voice"
    # anything but the app's own WAV recording is refused before it leaves the app
    page = app.post("/voice", files={"audio": ("a.webm", b"...", "audio/webm")}).text
    assert "use the microphone button" in page and len(service.sent) == 1


def test_an_unsure_hearing_from_the_voice_container_waits_for_the_founder(make, backend):
    from dyson_founder_app.voice import RemoteVoice  # LA-APP-07

    service = FakeVoiceService({"text": "pachas hazaar bhejo", "uncertain": True})
    app = make(RemoteVoice("http://voice", http=service))
    app.post("/login", data={"username": "founder", "password": PASSWORD})
    page = app.post("/voice", files={"audio": ("voice.wav", b"RIFF", "audio/wav")}).text
    assert "Please check what I heard" in page and backend.messages == []


class Speech:
    def __init__(self):
        self.said = []

    def speak(self, text):
        self.said.append(text)
        return b"ID3-mp3"


def test_a_spoken_command_gets_a_spoken_answer_a_typed_one_does_not(make, voice):  # D-024
    speech = Speech()
    app = make(voice, speech)
    app.post("/login", data={"username": "founder", "password": PASSWORD})
    typed = app.post("/send", data={"text": "How are sales?"}).text
    assert "id='answer'" not in typed and "Hear this reply" in typed
    spoken = app.post("/voice", files={"audio": ("voice.wav", b"RIFF", "audio/wav")}).text
    assert "<audio id='answer' autoplay src='/speak/-1'>" in spoken
    r = app.get("/speak/-1")
    assert r.status_code == 200 and r.headers["content-type"] == "audio/mpeg"
    assert speech.said == ["I will report when verified."]  # only Dyson's own reply is spoken
    assert app.get("/speak/0").content == b"ID3-mp3" and app.get("/speak/9").status_code == 404
    app.post("/logout")
    assert app.get("/speak/-1").status_code == 401


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

    # Only Dyson's own surfaces: the gateway, voice, speech, cookies, and the governed sandbox
    # panel's display URLs (the sandbox is Dyson's, reached through G). No other channel.
    assert list(inspect.signature(app.create_app).parameters) == [
        "gateway", "voice", "speech", "secure_cookies", "sandbox_novnc_url", "controls_url",
    ]  # fmt: skip
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


def test_dashboard_holds_the_conversation_but_no_control(founder):  # gate 8, D-024
    page = founder.get("/").text
    assert "href='/dashboard'" in page
    html = founder.get("/dashboard").text
    assert '["A", 660, 210' in html and '["hermes", 860, 345' in html  # every part is on the board
    assert '"G>T0":' in html and "What just happened" in html  # and every wire
    js = founder.get("/static/three.module.min.js")  # the 3D star needs no outside CDN
    assert js.status_code == 200 and js.headers["content-type"].startswith("text/javascript")
    assert b"Three.js Authors" in js.content[:200]
    # the only things it can post are the conversation's own calls; approvals, STOP and PAUSE
    # stay on Direct Founder Controls
    import re

    posted = set(re.findall(r'post\("(/api/[a-z/]*)', html))
    assert posted == {"/api/send", "/api/voice", "/api/thread/", "/api/statement"}
    for control in ("/decisions", "/controls", "/approve", "/stop", "/pause", "/proposals"):
        assert control not in html.lower()
    r = founder.get("/dashboard/data")
    assert r.status_code == 503  # this test gateway has no dashboard connected


def test_the_observatory_talks_through_the_same_gateway_calls(make, backend, voice):  # D-024
    speech = Speech()
    app = make(voice, speech)
    assert app.get("/api/state").status_code == 401  # Founder session only
    app.post("/login", data={"username": "founder", "password": PASSWORD})
    out = app.post("/api/send", data={"text": "How are sales?", "message_id": str(uuid4())}).json()
    assert out["sent"] and "Sales are up" in out["notice"]
    state = app.get("/api/state").json()
    assert [m["content"] for m in state["messages"]] == ["How are sales?", "Sales are up 4%."]
    assert state["speech"] is True and state["notices"] == []
    heard = app.post("/api/voice", files={"audio": ("voice.wav", b"RIFF", "audio/wav")}).json()
    assert heard["sent"] and backend.messages[-1].modality.value == "voice"
    thread = state["thread"]
    app.post("/api/thread/new")
    assert app.get("/api/state").json()["thread"] != thread  # a fresh conversation
    assert app.post("/api/thread/open", data={"thread_id": thread}).json()["thread"] == thread
    assert app.get("/api/state").json()["thread"] == thread
    assert app.post("/api/thread/delete", data={"thread_id": thread}).status_code == 404  # D-023


def test_an_unsure_voice_in_the_observatory_waits_for_the_founder(make, backend):  # LA-APP-07
    from app_testkit import ScriptedVoice

    app = make(ScriptedVoice("pachas hazaar bhejo", uncertain=True))
    app.post("/login", data={"username": "founder", "password": PASSWORD})
    out = app.post("/api/voice", files={"audio": ("voice.wav", b"RIFF", "audio/wav")}).json()
    assert out == {"sent": False, "heard": "pachas hazaar bhejo", "uncertain": True}
    assert backend.messages == []
