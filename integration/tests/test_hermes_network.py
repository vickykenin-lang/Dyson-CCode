"""Hermes's network isolation, in real containers (LA-HER-01, LA-HER-02, LA-HER-03).

Runs the deploy/hermes.compose.yml topology with stub services. Needs Docker; skipped without it
unless DYSON_TEST_REQUIRE_DOCKER=1 (set in CI).
"""

import json
import os
import shutil
import subprocess
import uuid
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
BASE = ROOT / "services" / "intelligence" / "deploy" / "hermes.compose.yml"
OVERLAY = ROOT / "integration" / "docker" / "hermes-network-test.override.yml"

PROBE = (
    "import json,socket,urllib.request,os\n"
    "def http(u):\n"
    "    try:\n"
    "        urllib.request.urlopen(u, timeout=3); return 'reached'\n"
    "    except Exception as e: return 'blocked: ' + type(e).__name__\n"
    "def tcp(h,p):\n"
    "    try:\n"
    "        socket.create_connection((h,p), timeout=3).close(); return 'reached'\n"
    "    except Exception as e: return 'blocked: ' + type(e).__name__\n"
    "out = {'model_router': http(os.environ['DYSON_ROUTER_URL']),\n"
    "       'tool_hub': http(os.environ['DYSON_TOOLHUB_URL']),\n"
    "       'governance': http('http://governance:8000'),\n"
    "       'internet_ip': tcp('1.1.1.1', 443),\n"
    "       'internet_dns': tcp('api.anthropic.com', 443),\n"
    "       'can_write_disk': os.access('/', os.W_OK),\n"
    "       'secret_files': sorted(os.listdir('/run/secrets'))}\n"
    "print('PROBE ' + json.dumps(out))\n"
)


def _docker_ok() -> bool:
    if not shutil.which("docker"):
        return False
    return subprocess.run(["docker", "info"], capture_output=True).returncode == 0


@pytest.fixture
def compose(tmp_path):
    if not _docker_ok():
        if os.environ.get("DYSON_TEST_REQUIRE_DOCKER") == "1":
            pytest.fail("Docker is required for this test")
        pytest.skip("Docker is not available")
    token = tmp_path / "hermes_caller_token"
    token.write_text(uuid.uuid4().hex)
    project = f"hermes-net-{uuid.uuid4().hex[:8]}"
    env = {**os.environ, "HERMES_TOKEN_FILE": str(token), "HERMES_PROBE": PROBE.replace("$", "$$")}
    base = ["docker", "compose", "-p", project, "-f", str(BASE), "-f", str(OVERLAY)]
    yield base, env
    subprocess.run([*base, "down", "-v", "--remove-orphans"], env=env, capture_output=True)


def test_hermes_reaches_only_c_and_g(compose):
    base, env = compose
    up = subprocess.run(
        [*base, "up", "-d", "model-router", "tool-hub", "governance"],
        env=env,
        capture_output=True,
        text=True,
        timeout=300,
    )
    assert up.returncode == 0, up.stderr
    run = subprocess.run(
        [*base, "run", "--rm", "hermes"], env=env, capture_output=True, text=True, timeout=300
    )
    assert run.returncode == 0, run.stderr
    line = next(ln for ln in run.stdout.splitlines() if ln.startswith("PROBE "))
    seen = json.loads(line[len("PROBE ") :])
    assert seen["model_router"] == "reached" and seen["tool_hub"] == "reached"
    assert seen["governance"].startswith("blocked")  # not even the Governance Core
    assert seen["internet_ip"].startswith("blocked")  # no direct model call
    assert seen["internet_dns"].startswith("blocked")
    assert seen["can_write_disk"] is False
    assert seen["secret_files"] == ["hermes_caller_token"]
