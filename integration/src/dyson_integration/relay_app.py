"""The sandbox panel the Founder sees on the dashboard: a live, view-only window and a STOP.

Read-only, like every dashboard surface (LA-DASH-02): only GET routes, no action path. The live
picture is the sandbox's noVNC stream, carried here by the edge at `novnc_url`; the viewer is loaded
view-only so it can never type or click — the Founder watches, Dyson drives. STOP is not an action
on this page; it links to Direct Founder Controls, the one surface that acts (with the passkey).
"""

from fastapi import FastAPI
from fastapi.responses import HTMLResponse

from .relay import RelaySessions

_PANEL = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Dyson sandbox</title>
<style>
  :root {{ color-scheme: dark; }}
  body {{ margin: 0; background: #0d1014; color: #e6e9ef;
         font: 14px/1.5 ui-sans-serif, system-ui, sans-serif; }}
  .bar {{ display: flex; align-items: center; gap: 10px; padding: 8px 12px;
          background: #151a21; border-bottom: 1px solid #222a35; }}
  .dot {{ width: 8px; height: 8px; border-radius: 50%; background: #3fb950; }}
  .bar b {{ font-weight: 600; }}
  .bar .eye {{ margin-left: auto; color: #8b98a9; font-size: 12px; }}
  .stop {{ color: #fff; background: #b4232a; text-decoration: none; padding: 5px 12px;
           border-radius: 6px; font-weight: 600; }}
  .screen {{ width: 100%; height: calc(100vh - 42px); border: 0; background: #000;
             display: block; }}
  .idle {{ display: grid; place-items: center; height: calc(100vh - 42px); color: #8b98a9; }}
</style></head>
<body>
  <div class="bar">
    <span class="dot"></span><b>Dyson sandbox</b>
    <span class="eye">view-only — Dyson is driving</span>
    <a class="stop" href="{controls_url}">STOP</a>
  </div>
  {body}
</body></html>"""

_LIVE = (
    '<iframe class="screen" src="{novnc_url}" allow="fullscreen" title="Dyson sandbox"></iframe>'
)
_IDLE = '<div class="idle">Sandbox is idle. Ask Dyson to open something.</div>'


def create_relay_app(
    sessions: RelaySessions, novnc_url: str = "", controls_url: str = "/"
) -> FastAPI:
    """novnc_url is the edge path to the sandbox's view-only noVNC stream."""
    app = FastAPI(title="Dyson sandbox panel - read only", docs_url=None, redoc_url=None)

    @app.get("/health")
    def health() -> dict:
        return {"ok": True}

    @app.get("/sandbox")
    def sandbox() -> dict:
        live = sessions.live()
        session = live[0] if live else None
        return {
            "active": session is not None,
            "view_only": True,
            "session_id": str(session.session_id) if session else None,
            "capability_id": session.capability_id if session else None,
            "novnc_url": novnc_url,
        }

    @app.get("/panel", response_class=HTMLResponse)
    def panel() -> str:
        body = _LIVE.format(novnc_url=novnc_url) if sessions.live() and novnc_url else _IDLE
        return _PANEL.format(controls_url=controls_url, body=body)

    return app
