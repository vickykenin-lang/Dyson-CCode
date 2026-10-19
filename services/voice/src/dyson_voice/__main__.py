"""`python -m dyson_voice`: the voice container (D-024). Model files are baked into the image."""

import os

import uvicorn

from .app import create_app
from .listen import model_listener

if __name__ == "__main__":
    app = create_app(model_listener(os.environ.get("DYSON_VOICE_MODEL", "/model")))
    print("Voice is up: 8096", flush=True)
    uvicorn.run(
        app, host=os.environ.get("DYSON_VOICE_BIND", "0.0.0.0"), port=8096, log_level="warning"
    )
