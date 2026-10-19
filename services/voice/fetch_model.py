"""Build step for the voice image: fetch the speech model at a pinned revision and refuse it unless
every file matches its pinned SHA-256 (D-024). Runs once at image build; the running container
has no internet."""

import hashlib
import shutil
import sys
from pathlib import Path

from huggingface_hub import hf_hub_download

REPO = "OpenVoiceOS/ai4bharat-indicconformer-hi-onnx"  # MIT, from ai4bharat IndicConformer (hi)
REVISION = "8960b8611af5b8c375d442d52907360176410c8b"
FILES = {
    "config.json": "4bfb1d53736f8b675b784d6ece61f5b8e7ae73ca2c0ed4c232e9135ac44ab909",
    "vocab.txt": "152e58dc9469feb8f74fb006245616ad7cd91b3f7a5ace72ec53f970db10c981",
    "model.int8.onnx": "c2044177b6d44494fe40be755466845a4c7bd1b5a5d1f6a15b33b2b4ba6011cd",
}

out = Path(sys.argv[1])
out.mkdir(parents=True, exist_ok=True)
for name, want in FILES.items():
    src = hf_hub_download(REPO, name, revision=REVISION)
    got = hashlib.sha256(Path(src).read_bytes()).hexdigest()
    if got != want:
        sys.exit(f"{name}: SHA-256 {got} is not the pinned {want}")
    shutil.copy(src, out / name)
print(f"model {REPO}@{REVISION[:12]} verified", flush=True)
