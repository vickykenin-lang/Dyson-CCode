"""The Founder app, served from Python as plain HTML with a little JavaScript for live status.

What the Founder sees about a task comes from `status_label`: only a task that is
completed-verified with cited evidence is shown as done. An acknowledgment is shown as
"accepted, not done yet" or "waiting for your approval", never as completion (LA-APP-04).
"""

from datetime import date
from html import escape
from typing import Annotated
from uuid import UUID, uuid4

from fastapi import FastAPI, File, Form, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response

from dyson_contracts.interface import TaskStatusUpdate
from dyson_contracts.tasks import TaskState

from .gateway_client import GatewayClient, NotLoggedIn, Refused
from .voice import VoicePort, VoiceUnavailable

SESSION, THREAD = "dyson_session", "dyson_thread"
SETTLED = {TaskState.COMPLETED_VERIFIED, TaskState.FAILED, TaskState.REJECTED, TaskState.CLOSED}

LABELS = {
    TaskState.ACCEPTED: "Accepted, not done yet",
    TaskState.APPROVAL_NEEDED: "Waiting for your approval on Direct Founder Controls",
    TaskState.RUNNING: "Running, not done until it is verified",
    TaskState.HELD: "Held for review",
    TaskState.STOPPED: "Stopped",
    TaskState.FAILED: "Failed",
    TaskState.REJECTED: "Rejected",
    TaskState.CLOSED: "Closed",
}


def status_label(update: TaskStatusUpdate) -> tuple[str, bool]:
    """(text, done). Done only with verified evidence; nothing a tool said counts."""
    if update.state is TaskState.COMPLETED_VERIFIED and update.verified_evidence_ids:
        n = len(update.verified_evidence_ids)
        return f"Done and verified ({n} evidence record{'s' if n > 1 else ''})", True
    return LABELS.get(update.state, "Not done"), False


def create_app(gateway: GatewayClient, voice: VoicePort, *, secure_cookies: bool = True) -> FastAPI:
    app = FastAPI(title="Dyson")

    def cookie(resp: Response, name: str, value: str) -> None:
        resp.set_cookie(name, value, httponly=True, samesite="strict", secure=secure_cookies)

    def thread_of(request: Request) -> UUID:
        try:
            return UUID(request.cookies.get(THREAD, ""))
        except ValueError:
            return uuid4()

    def page(request: Request, notice: str = "", body: str | None = None) -> Response:
        token = request.cookies.get(SESSION)
        if not token:
            return HTMLResponse(_shell(_login_form(notice)))
        thread = thread_of(request)
        try:
            history = gateway.thread(token, thread)
            tasks = gateway.tasks(token, thread)
            waiting = gateway.notices(token)
            open_threads = gateway.threads(token)
            archived = gateway.threads(token, archived=True)
        except NotLoggedIn:
            resp = HTMLResponse(_shell(_login_form("Your session ended. Please log in again.")))
            resp.delete_cookie(SESSION)
            return resp
        html = (
            body
            if body is not None
            else (
                _notices(waiting)
                + _conversation(history, tasks, notice)
                + _threads(open_threads, archived, thread)
            )
        )
        resp = HTMLResponse(_shell(html, logged_in=True))
        cookie(resp, THREAD, str(thread))
        return resp

    @app.get("/", response_class=HTMLResponse)
    def home(request: Request, notice: str = "") -> Response:
        if notice == "archived":
            return page(
                request,
                notice="Conversation archived. Nothing was deleted; it is under "
                "Archived conversations.",
            )
        return page(request)

    @app.post("/login")
    def login(request: Request, username: str = Form(), password: str = Form()) -> Response:
        try:
            token = gateway.login(username, password)
        except NotLoggedIn:
            return HTMLResponse(_shell(_login_form("Login failed.")), status_code=401)
        except Exception:
            return HTMLResponse(_shell(_login_form("Login is unavailable right now.")), 503)
        resp = RedirectResponse("/", status_code=303)
        cookie(resp, SESSION, token)
        return resp

    @app.post("/logout")
    def logout(request: Request) -> Response:
        token = request.cookies.get(SESSION)
        if token:
            try:
                gateway.logout(token)
            except NotLoggedIn:
                pass
        resp = RedirectResponse("/", status_code=303)
        resp.delete_cookie(SESSION)
        return resp

    def send(request: Request, text: str, voice_msg: bool, message_id: str = "") -> Response:
        token = request.cookies.get(SESSION)
        if not token:
            return RedirectResponse("/", status_code=303)
        try:
            mid = UUID(message_id) if message_id else None
        except ValueError:
            mid = None
        try:
            out = gateway.send(token, thread_of(request), text, voice=voice_msg, message_id=mid)
        except NotLoggedIn:
            return page(request)
        return page(request, notice=_ack_notice(out))

    @app.post("/send")
    def send_text(request: Request, text: str = Form(), message_id: str = Form("")) -> Response:
        # message_id is fixed when the form is drawn, so resubmitting it is the same command.
        return send(request, text, voice_msg=False, message_id=message_id)

    @app.post("/voice")
    async def voice_in(request: Request, audio: Annotated[UploadFile, File()]) -> Response:
        if not request.cookies.get(SESSION):
            return RedirectResponse("/", status_code=303)
        try:
            heard = voice.transcribe(await audio.read(), audio.content_type or "")
        except VoiceUnavailable:
            return page(request, notice="Voice is not available yet. Please type instead.")
        if heard.uncertain or not heard.text.strip():
            return page(request, body=_confirm_voice(heard.text))  # never sent on its own
        return send(request, heard.text, voice_msg=True)

    @app.post("/voice/confirm")
    def voice_confirm(request: Request, text: str = Form(), message_id: str = Form("")) -> Response:
        # the Founder confirmed what was heard
        return send(request, text, voice_msg=True, message_id=message_id)

    def switch(thread: UUID, notice: str = "") -> Response:
        resp = RedirectResponse("/" + (f"?notice={notice}" if notice else ""), status_code=303)
        cookie(resp, THREAD, str(thread))
        return resp

    @app.post("/new")
    def new_conversation(request: Request) -> Response:
        return switch(uuid4())

    @app.post("/archive")
    def archive(request: Request) -> Response:
        token = request.cookies.get(SESSION)
        if not token:
            return RedirectResponse("/", status_code=303)
        try:
            gateway.archive(token, thread_of(request))
        except NotLoggedIn:
            return page(request)
        return switch(uuid4(), "archived")

    @app.post("/open/{thread_id}")
    def open_thread(thread_id: UUID, request: Request) -> Response:
        return switch(thread_id)

    @app.post("/restore/{thread_id}")
    def restore(thread_id: UUID, request: Request) -> Response:
        token = request.cookies.get(SESSION)
        if not token:
            return RedirectResponse("/", status_code=303)
        try:
            gateway.restore(token, thread_id)
        except NotLoggedIn:
            return page(request)
        return switch(thread_id)

    @app.post("/statement")
    async def statement(
        request: Request,
        file: Annotated[UploadFile, File()],
        period_start: Annotated[date, Form()],
        period_end: Annotated[date, Form()],
    ) -> Response:
        token = request.cookies.get(SESSION)
        if not token:
            return RedirectResponse("/", status_code=303)
        try:
            name, content = file.filename or "statement.csv", await file.read()
            kept = gateway.upload_statement(token, name, period_start, period_end, content)
        except NotLoggedIn:
            return page(request)
        except Refused as exc:
            return page(request, notice=f"Statement not accepted: {exc}")
        return page(
            request,
            notice=f"Statement received: {kept} lines kept (date, amount, "
            "direction and masked reference only). The file is not kept.",
        )

    @app.get("/tasks/{task_id}/status")
    def task_status(task_id: UUID, request: Request) -> Response:
        token = request.cookies.get(SESSION)
        if not token:
            return JSONResponse({"detail": "log in"}, status_code=401)
        try:
            update = gateway.task(token, task_id)
        except NotLoggedIn:
            return JSONResponse({"detail": "log in"}, status_code=401)
        label, done = status_label(update)
        return JSONResponse(
            {
                "state": update.state.value,
                "label": label,
                "done": done,
                "settled": update.state in SETTLED,
            }
        )

    return app


def _ack_notice(out: dict) -> str:
    ack, reply = out.get("acknowledgment"), out["reply"]
    if ack is None:
        return reply["text"]
    state = TaskState(ack["state"])
    return f"{LABELS[state]} (task {ack['task_id']}). {reply['text']}"


CSS = """
:root{--bg:#0f1220;--panel:#181c2e;--text:#e8eaf2;--muted:#9aa0b8;--accent:#f2b84b;
--ok:#4cc38a;--wait:#f2b84b}
*{box-sizing:border-box}body{margin:0;font:16px/1.5 system-ui,sans-serif;background:var(--bg);
color:var(--text)}header{padding:12px 16px;border-bottom:1px solid #262b44;display:flex;
justify-content:space-between;align-items:center}header b{color:var(--accent);letter-spacing:.08em}
main{max-width:760px;margin:0 auto;padding:16px}section{background:var(--panel);border-radius:10px;
padding:12px 16px;margin-bottom:16px}.msg{margin:6px 0}.user{color:var(--accent)}
.notice{border-left:3px solid var(--accent);padding-left:10px}.task{display:flex;
justify-content:space-between;gap:8px;border-bottom:1px solid #262b44;padding:6px 0}
.done{color:var(--ok)}.wait{color:var(--wait)}textarea,input{width:100%;padding:8px;
border-radius:6px;border:1px solid #33395a;background:#0f1220;color:var(--text)}
button{margin-top:8px;padding:8px 14px;border:0;border-radius:6px;background:var(--accent);
color:#111;font-weight:600}
"""

POLL = """
for (const el of document.querySelectorAll('[data-task]')) {
  const tick = async () => {
    const r = await fetch('/tasks/' + el.dataset.task + '/status');
    if (!r.ok) return;
    const s = await r.json();
    el.textContent = s.label;
    el.className = s.done ? 'done' : 'wait';
    if (!s.settled) setTimeout(tick, 2000);
  };
  setTimeout(tick, 2000);
}
"""


def _shell(content: str, logged_in: bool = False) -> str:
    out = (
        '<form method="post" action="/logout"><button>Log out</button></form>' if logged_in else ""
    )
    return (
        "<!doctype html><html lang='en'><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width,initial-scale=1'>"
        f"<title>Dyson</title><style>{CSS}</style></head><body>"
        f"<header><b>DYSON</b>{out}</header><main>{content}</main>"
        f"<script>{POLL}</script></body></html>"
    )


def _login_form(notice: str) -> str:
    n = f"<p class='notice'>{escape(notice)}</p>" if notice else ""
    return (
        f"<section><h1>Founder login</h1>{n}<form method='post' action='/login'>"
        "<label>Username<input name='username' autocomplete='username'></label>"
        "<label>Password<input name='password' type='password' "
        "autocomplete='current-password'></label><button>Log in</button></form></section>"
    )


def _conversation(history: list[dict], tasks: list[TaskStatusUpdate], notice: str) -> str:
    msgs = "".join(
        f"<p class='msg {'user' if m['role'] == 'user' else ''}'>"
        f"{'You' if m['role'] == 'user' else 'Dyson'}"
        f"{' (voice)' if m.get('modality') == 'voice' else ''}: {escape(m['content'])}</p>"
        for m in history
    )
    rows = ""
    for t in tasks:
        label, done = status_label(t)
        live = "" if t.state in SETTLED else f" data-task='{t.task_id}'"
        rows += (
            f"<div class='task'><span>Task {t.task_id}</span>"
            f"<span class='{'done' if done else 'wait'}'{live}>{escape(label)}</span></div>"
        )
    n = f"<p class='notice'>{escape(notice)}</p>" if notice else ""
    return (
        f"{n}<section><h2>Conversation</h2>{msgs or '<p>Say what you need.</p>'}"
        "<form method='post' action='/send'><textarea name='text' rows='3' required></textarea>"
        f"<input type='hidden' name='message_id' value='{uuid4()}'>"
        "<button>Send</button></form>"
        "<form method='post' action='/voice' enctype='multipart/form-data'>"
        "<input type='file' name='audio' accept='audio/*'><button>Send voice</button></form>"
        f"</section><section><h2>Tasks</h2>{rows or '<p>No tasks yet.</p>'}</section>"
        "<section><h2>Bank statement</h2><p>CSV or delimited export from netbanking, not PDF. "
        "Only date, amount, debit or credit and a masked reference are kept.</p>"
        "<form method='post' action='/statement' enctype='multipart/form-data'>"
        "<input type='file' name='file' accept='.csv,.txt,text/csv' required>"
        "<label>From<input type='date' name='period_start' required></label>"
        "<label>To<input type='date' name='period_end' required></label>"
        "<button>Upload statement</button></form></section>"
        "<p>Approvals, STOP and PAUSE are on Direct Founder Controls, not in this app.</p>"
    )


def _threads(open_threads: list[dict], archived: list[dict], current: UUID) -> str:
    """Conversations: open ones and the archive. There is no delete (D-023)."""

    def row(t: dict, action: str, label: str) -> str:
        here = " (this one)" if t["thread_id"] == str(current) else ""
        return (
            f"<div class='task'><span>{escape(t['title'])}{here}</span>"
            f"<form method='post' action='/{action}/{t['thread_id']}'><button>{label}</button>"
            "</form></div>"
        )

    opened = "".join(row(t, "open", "Open") for t in open_threads)
    stored = "".join(row(t, "restore", "Restore") for t in archived)
    return (
        "<section><h2>Conversations</h2>"
        "<form method='post' action='/new'><button>New conversation</button></form>"
        "<form method='post' action='/archive'><button>Archive this conversation</button></form>"
        f"{opened or '<p>No other conversations.</p>'}"
        f"<h3>Archived conversations</h3>{stored or '<p>None archived.</p>'}"
        "<p>Nothing is ever deleted; archived conversations can be restored.</p></section>"
    )


def _notices(items: list[dict]) -> str:
    """What waits on the Founder. Acting on it happens on Direct Founder Controls only."""
    if not items:
        return ""
    rows = "".join(f"<p class='msg'>{escape(i['text'])}</p>" for i in items)
    return (
        f"<section class='notice'><h2>Waiting for you ({len(items)})</h2>{rows}"
        "<p>Open Direct Founder Controls to approve or reject.</p></section>"
    )


def _confirm_voice(text: str) -> str:
    heard = escape(text) if text.strip() else "(nothing clear)"
    form = (
        "<form method='post' action='/voice/confirm'>"
        f"<input type='hidden' name='message_id' value='{uuid4()}'>"
        f"<textarea name='text' rows='3' required>{escape(text)}</textarea>"
        "<button>Send as corrected</button></form>"
        if text.strip()
        else ""
    )
    return (
        "<section><h2>Please check what I heard</h2>"
        f"<p class='notice'>I may have misheard: “{heard}”. Nothing was sent.</p>"
        f"{form}<form method='get' action='/'><button>Discard</button></form></section>"
    )
