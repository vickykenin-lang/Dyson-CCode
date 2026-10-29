"""The Founder app, served from Python as plain HTML with a little JavaScript for live status.

What the Founder sees about a task comes from `status_label`: only a task that is
completed-verified with cited evidence is shown as done. An acknowledgment is shown as
"accepted, not done yet" or "waiting for your approval", never as completion (LA-APP-04).
"""

import asyncio
import os
from datetime import date
from html import escape
from importlib.resources import files
from typing import Annotated
from uuid import UUID, uuid4

from fastapi import FastAPI, File, Form, Request, UploadFile, WebSocket
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles

from dyson_contracts.interface import TaskStatusUpdate
from dyson_contracts.tasks import TaskState

from .brain_page import PAGE as BRAIN_PAGE
from .dashboard_page import PAGE
from .gateway_client import GatewayClient, NotLoggedIn, Refused
from .voice import (
    NoSpeech,
    SpeechPort,
    SpeechUnavailable,
    VoicePort,
    VoiceUnavailable,
    speech_parts,
)

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


def create_app(
    gateway: GatewayClient,
    voice: VoicePort,
    *,
    speech: SpeechPort | None = None,
    secure_cookies: bool = True,
    controls_url: str = "/",
    novnc_dir: str = "/usr/share/novnc",
    sandbox_vnc: str = "",
) -> FastAPI:
    speech = speech or NoSpeech()
    app = FastAPI(title="Dyson")

    @app.middleware("http")
    async def no_store_html(request, call_next):
        # The app's HTML must always be fresh (every deploy takes effect at once; no stale page
        # cached by the browser or the edge). Static assets (JS, noVNC) keep their own caching.
        resp = await call_next(request)
        if resp.headers.get("content-type", "").startswith("text/html"):
            resp.headers["Cache-Control"] = "no-store"
        return resp

    # The observatory's sandbox panel embeds the sandbox's live screen (served same-origin, below)
    # and a STOP that opens Direct Founder Controls.
    observatory = PAGE.replace("__CONTROLS_URL__", controls_url)
    brain_page = BRAIN_PAGE.replace("__CONTROLS_URL__", controls_url)
    # Serve noVNC's client same-origin, so the sandbox panel needs no second hostname and the one
    # login to this app covers it — no cross-origin iframe, no second Access prompt (D-028).
    if os.path.isdir(novnc_dir):
        app.mount("/sandbox-screen", StaticFiles(directory=novnc_dir, html=True), name="sandbox")

    def cookie(resp: Response, name: str, value: str) -> None:
        resp.set_cookie(name, value, httponly=True, samesite="strict", secure=secure_cookies)

    def thread_of(request: Request) -> UUID:
        try:
            return UUID(request.cookies.get(THREAD, ""))
        except ValueError:
            return uuid4()

    def page(
        request: Request, notice: str = "", body: str | None = None, speak: bool = False
    ) -> Response:
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
                + _conversation(history, tasks, notice, speak)
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
        resp = RedirectResponse("/dashboard", status_code=303)  # the observatory is home (D-024)
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
        # a spoken command gets a spoken answer; a typed one does not
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
        return page(request, notice=_ack_notice(out), speak=voice_msg)

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
        except VoiceUnavailable as exc:
            return page(request, notice=f"Voice: {exc}. You can also type.")
        if heard.uncertain or not heard.text.strip():
            return page(request, body=_confirm_voice(heard.text))  # never sent on its own
        return send(request, heard.text, voice_msg=True)

    @app.post("/voice/confirm")
    def voice_confirm(request: Request, text: str = Form(), message_id: str = Form("")) -> Response:
        # the Founder confirmed what was heard
        return send(request, text, voice_msg=True, message_id=message_id)

    @app.get("/speak/{n}")
    def speak_reply(request: Request, n: int, part: int | None = None) -> Response:
        """Dyson's n-th reply in this conversation, spoken (-1: the latest). Read only.
        With ?part=k only the k-th piece is spoken (X-Parts says how many), so the app can
        start playing the first sentence while the rest is still being made."""
        token = request.cookies.get(SESSION)
        if not token:
            return Response(status_code=401)
        headers = {"Cache-Control": "no-store"}
        try:
            replies = [m for m in gateway.thread(token, thread_of(request)) if m["role"] != "user"]
            text = replies[n]["content"]
            if part is not None:
                pieces = speech_parts(text)
                text = pieces[part] if 0 <= part < len(pieces) else pieces[len(pieces)]
                headers["X-Parts"] = str(len(pieces))
            audio = speech.speak(text)
        except NotLoggedIn:
            return Response(status_code=401)
        except IndexError:
            return Response(status_code=404)
        except SpeechUnavailable:
            return Response(status_code=503)
        return Response(audio, media_type="audio/mpeg", headers=headers)

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

    three = files(__package__).joinpath("static/three.module.min.js").read_bytes()

    @app.get("/static/three.module.min.js")
    def three_js() -> Response:
        """three.js r160 (MIT), served from here so the live map needs no outside CDN."""
        return Response(
            three,
            media_type="text/javascript",
            headers={"Cache-Control": "public, max-age=31536000, immutable"},
        )

    @app.get("/dashboard", response_class=HTMLResponse)
    def dashboard(request: Request) -> Response:
        """Gate 8: the architecture, block by block, with live status. Read only."""
        if not request.cookies.get(SESSION):
            return RedirectResponse("/", status_code=303)
        resp = HTMLResponse(observatory)
        cookie(resp, THREAD, str(thread_of(request)))  # the conversation it talks in
        return resp

    @app.websocket("/sandbox-ws")
    async def sandbox_ws(ws: WebSocket) -> None:
        # Bridge the browser's noVNC websocket to the sandbox's VNC over sandbox_net. Same origin
        # as this app, so the one login covers it. Only the logged-in Founder may reach it, and the
        # sandbox is sealed from the core; input reaches only the sandbox.
        if not ws.cookies.get(SESSION) or not sandbox_vnc:
            await ws.close(code=1008)
            return
        host, _, port = sandbox_vnc.partition(":")
        try:
            reader, writer = await asyncio.open_connection(host, int(port or "5900"))
        except OSError:
            await ws.close(code=1011)
            return
        await ws.accept()

        async def to_vnc() -> None:
            try:
                while True:
                    writer.write(await ws.receive_bytes())
                    await writer.drain()
            except Exception:
                pass

        async def to_browser() -> None:
            try:
                while True:
                    chunk = await reader.read(65536)
                    if not chunk:
                        break
                    await ws.send_bytes(chunk)
            except Exception:
                pass

        tasks = [asyncio.create_task(to_vnc()), asyncio.create_task(to_browser())]
        try:
            await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        finally:
            for t in tasks:
                t.cancel()
            writer.close()
            try:
                await ws.close()
            except Exception:
                pass

    @app.get("/dashboard/data")
    def dashboard_data(request: Request) -> Response:
        token = request.cookies.get(SESSION)
        if not token:
            return JSONResponse({"detail": "log in"}, status_code=401)
        try:
            return JSONResponse(gateway.dashboard(token))
        except NotLoggedIn:
            return JSONResponse({"detail": "log in"}, status_code=401)
        except Refused as exc:
            return JSONResponse({"detail": str(exc)}, status_code=503)

    @app.get("/brain", response_class=HTMLResponse)
    def brain(request: Request) -> Response:
        """The second brain as a galaxy: every note a star, links reasoned. Read only."""
        if not request.cookies.get(SESSION):
            return RedirectResponse("/", status_code=303)
        resp = HTMLResponse(brain_page)
        cookie(resp, THREAD, str(thread_of(request)))
        return resp

    @app.get("/brain/data")
    def brain_data(request: Request) -> Response:
        token = request.cookies.get(SESSION)
        if not token:
            return JSONResponse({"detail": "log in"}, status_code=401)
        try:
            return JSONResponse(gateway.brain(token))
        except NotLoggedIn:
            return JSONResponse({"detail": "log in"}, status_code=401)
        except Refused as exc:
            return JSONResponse({"detail": str(exc)}, status_code=503)

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

    # --- the same conversation as JSON, for the observatory (D-024) -------------------------
    # Exactly what the Conversation page does, through the same Entry Gateway calls; nothing
    # here approves, stops or pauses anything (that stays on Direct Founder Controls).
    def api(request: Request):
        token = request.cookies.get(SESSION)
        if not token:
            raise NotLoggedIn
        return token

    def json_out(body: dict, request: Request, thread: UUID | None = None) -> Response:
        resp = JSONResponse(body)
        cookie(resp, THREAD, str(thread or thread_of(request)))
        return resp

    def login_needed() -> Response:
        return JSONResponse({"detail": "log in"}, status_code=401)

    @app.get("/api/state")
    def api_state(request: Request) -> Response:
        try:
            token, thread = api(request), thread_of(request)
            tasks = []
            for t in gateway.tasks(token, thread):
                label, done = status_label(t)
                tasks.append({"task_id": str(t.task_id), "label": label, "done": done,
                              "settled": t.state in SETTLED})  # fmt: skip
            return json_out(
                {
                    "thread": str(thread),
                    "messages": gateway.thread(token, thread),
                    "tasks": tasks,
                    "notices": gateway.notices(token),
                    "threads": gateway.threads(token),
                    "archived": gateway.threads(token, archived=True),
                    "speech": not isinstance(speech, NoSpeech),
                },
                request,
                thread,
            )
        except NotLoggedIn:
            return login_needed()

    def api_send(request: Request, text: str, voice_msg: bool, message_id: str) -> Response:
        try:
            mid = UUID(message_id) if message_id else None
        except ValueError:
            mid = None
        thread = thread_of(request)
        try:
            out = gateway.send(api(request), thread, text, voice=voice_msg, message_id=mid)
        except NotLoggedIn:
            return login_needed()
        return json_out({"sent": True, "notice": _ack_notice(out)}, request, thread)

    @app.post("/api/send")
    def api_send_text(
        request: Request, text: str = Form(), message_id: str = Form(""), voice: str = Form("")
    ) -> Response:
        # voice=1 when the Founder confirmed or corrected what was heard
        return api_send(request, text, voice == "1", message_id)

    @app.post("/api/voice")
    async def api_voice(request: Request, audio: Annotated[UploadFile, File()]) -> Response:
        try:
            api(request)
            heard = voice.transcribe(await audio.read(), audio.content_type or "")
        except NotLoggedIn:
            return login_needed()
        except VoiceUnavailable as exc:
            return json_out({"sent": False, "notice": f"Voice: {exc}."}, request)
        if heard.uncertain or not heard.text.strip():
            # never sent on its own (LA-APP-07): the Founder confirms or corrects it first
            return json_out({"sent": False, "heard": heard.text, "uncertain": True}, request)
        out = api_send(request, heard.text, True, str(uuid4()))
        return out

    @app.post("/api/thread/{action}")
    def api_thread(request: Request, action: str, thread_id: str = Form("")) -> Response:
        try:
            token = api(request)
            if action == "new":
                return json_out({"thread": None}, request, uuid4())
            if action == "archive":
                gateway.archive(token, thread_of(request))
                return json_out({"notice": "Archived. Nothing was deleted."}, request, uuid4())
            target = UUID(thread_id)
            if action == "restore":
                gateway.restore(token, target)
            elif action != "open":
                return JSONResponse({"detail": "unknown"}, status_code=404)
            return json_out({"thread": str(target)}, request, target)
        except NotLoggedIn:
            return login_needed()
        except Refused as exc:
            return JSONResponse({"notice": f"Not done: {exc}"}, status_code=503)
        except ValueError:
            return JSONResponse({"detail": "bad thread"}, status_code=422)

    @app.post("/api/statement")
    async def api_statement(
        request: Request,
        file: Annotated[UploadFile, File()],
        period_start: Annotated[date, Form()],
        period_end: Annotated[date, Form()],
    ) -> Response:
        try:
            name, content = file.filename or "statement.csv", await file.read()
            kept = gateway.upload_statement(api(request), name, period_start, period_end, content)
        except NotLoggedIn:
            return login_needed()
        except Refused as exc:
            return json_out({"ok": False, "notice": f"Statement not accepted: {exc}"}, request)
        return json_out(
            {"ok": True, "notice": f"Statement received: {kept} lines kept (date, amount, "
             "direction and masked reference only). The file is not kept."},
            request,
        )  # fmt: skip

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
color:#111;font-weight:600}nav a{color:var(--text);margin-right:8px}.scroll{overflow-x:auto}
.muted{color:var(--muted)}
"""

POLL = """
// Voice (D-024): record 16 kHz mono WAV here and send it; Dyson's server turns it into text.
(() => {
  const mic = document.getElementById('mic'), form = document.getElementById('voiceform');
  if (!mic || !form) return;
  const note = document.getElementById('micnote');
  let ctx = null, stream = null, proc = null, parts = [], timer = null;
  const wav = (pcm, rate) => {
    const v = new DataView(new ArrayBuffer(44 + pcm.length * 2)), s = (o, t) => [...t].forEach(
      (c, i) => v.setUint8(o + i, c.charCodeAt(0)));
    s(0, 'RIFF'); v.setUint32(4, 36 + pcm.length * 2, true); s(8, 'WAVEfmt ');
    v.setUint32(16, 16, true); v.setUint16(20, 1, true); v.setUint16(22, 1, true);
    v.setUint32(24, rate, true); v.setUint32(28, rate * 2, true); v.setUint16(32, 2, true);
    v.setUint16(34, 16, true); s(36, 'data'); v.setUint32(40, pcm.length * 2, true);
    pcm.forEach((x, i) => v.setInt16(44 + i * 2, Math.max(-1, Math.min(1, x)) * 32767, true));
    return new Blob([v], {type: 'audio/wav'});
  };
  const to16k = (x, rate) => {
    if (rate === 16000) return x;
    const out = new Float32Array(Math.floor(x.length * 16000 / rate));
    for (let i = 0; i < out.length; i++) out[i] = x[Math.floor(i * rate / 16000)];
    return out;
  };
  const stop = () => {
    clearTimeout(timer); proc.disconnect(); stream.getTracks().forEach(t => t.stop());
    const rate = ctx.sampleRate; ctx.close(); ctx = null;
    const all = new Float32Array(parts.reduce((n, p) => n + p.length, 0));
    let o = 0; for (const p of parts) { all.set(p, o); o += p.length; }
    const dt = new DataTransfer();
    dt.items.add(new File([wav(to16k(all, rate), 16000)], 'voice.wav', {type: 'audio/wav'}));
    form.querySelector('input[name=audio]').files = dt.files;
    mic.disabled = true; mic.textContent = 'Sending…'; form.submit();
  };
  mic.onclick = async () => {
    if (ctx) return stop();
    try {
      stream = await navigator.mediaDevices.getUserMedia({audio: {channelCount: 1,
        echoCancellation: true, noiseSuppression: true}});
    } catch (e) {
      note.textContent = 'The microphone is blocked. Allow it, or type instead.'; return;
    }
    try { ctx = new AudioContext({sampleRate: 16000}); } catch (e) { ctx = new AudioContext(); }
    parts = [];
    proc = ctx.createScriptProcessor(4096, 1, 1);
    proc.onaudioprocess = e => parts.push(new Float32Array(e.inputBuffer.getChannelData(0)));
    ctx.createMediaStreamSource(stream).connect(proc); proc.connect(ctx.destination);
    mic.textContent = '⏹ Listening… tap to send'; timer = setTimeout(stop, 30000);
  };
})();
for (const b of document.querySelectorAll('button.say')) {
  b.onclick = () => new Audio('/speak/' + b.dataset.n).play();
}
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


def _shell(content: str, logged_in: bool = False, script: str = "") -> str:
    out = (
        "<nav><a href='/'>Conversation</a> · <a href='/dashboard'>Live map</a>"
        " · <a href='/brain'>Brain</a></nav>"
        '<form method="post" action="/logout"><button>Log out</button></form>'
        if logged_in
        else ""
    )
    return (
        "<!doctype html><html lang='en'><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width,initial-scale=1'>"
        f"<title>Dyson</title><style>{CSS}</style></head><body>"
        f"<header><b>DYSON</b>{out}</header><main>{content}</main>"
        f"<script>{script or POLL}</script></body></html>"
    )


def _login_form(notice: str) -> str:
    n = f"<p class='notice'>{escape(notice)}</p>" if notice else ""
    return (
        f"<section><h1>Founder login</h1>{n}<form method='post' action='/login'>"
        "<label>Username<input name='username' autocomplete='username'></label>"
        "<label>Password<input name='password' type='password' "
        "autocomplete='current-password'></label><button>Log in</button></form></section>"
    )


def _conversation(
    history: list[dict], tasks: list[TaskStatusUpdate], notice: str, speak: bool = False
) -> str:
    msgs, said = "", 0
    for m in history:
        mine = m["role"] == "user"
        listen = (
            ""
            if mine
            else f" <button type='button' class='say' data-n='{said}' "
            "aria-label='Hear this reply'>🔊</button>"
        )
        said += 0 if mine else 1
        msgs += (
            f"<p class='msg {'user' if mine else ''}'>{'You' if mine else 'Dyson'}"
            f"{' (voice)' if m.get('modality') == 'voice' else ''}: {escape(m['content'])}"
            f"{listen}</p>"
        )
    if speak and said:  # the answer to a spoken command is spoken too
        msgs += "<audio id='answer' autoplay src='/speak/-1'></audio>"
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
        "<form method='post' action='/voice' enctype='multipart/form-data' id='voiceform'>"
        "<input type='file' name='audio' accept='audio/wav' hidden>"
        "<button type='button' id='mic'>🎙 Tap to speak</button> "
        "<span id='micnote' class='muted'>Tap again to send. Up to 30 seconds. Your voice is "
        "heard on Dyson's server and not kept.</span></form>"
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
