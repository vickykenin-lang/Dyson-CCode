"""The voice container's only door: Layer A posts a WAV and gets text back (D-024).

It runs on its own network that only Layer A joins, holds no secrets and no database, and has no
route to the internet. Nothing it hears is stored or logged.
"""

from fastapi import FastAPI, HTTPException, Request

from .listen import MAX_SECONDS, RATE, BadAudio, Listener

MAX_BYTES = 44 + RATE * 2 * MAX_SECONDS


def create_app(listener: Listener) -> FastAPI:
    app = FastAPI(title="Dyson voice", docs_url=None, redoc_url=None, openapi_url=None)

    @app.get("/health")
    def health() -> dict:
        return {"ok": True}

    @app.post("/transcribe")
    async def transcribe(request: Request) -> dict:
        if request.headers.get("content-type", "").split(";")[0].strip() != "audio/wav":
            raise HTTPException(415, "send audio/wav")
        body = await request.body()
        if len(body) > MAX_BYTES:
            raise HTTPException(413, f"at most {MAX_SECONDS} seconds at a time")
        try:
            heard = listener.hear(body)
        except BadAudio as exc:
            raise HTTPException(422, str(exc)) from None
        return {
            "text": heard.text,
            "uncertain": heard.uncertain,
            "confidence": heard.confidence,
            "seconds": heard.seconds,
        }

    return app
