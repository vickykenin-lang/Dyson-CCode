"""Run the repository's own checks — ruff and pytest — and report pass/fail.

This is exactly what CI runs, carried out inside Dyson's sealed self-test sandbox instead of on
GitHub (GitHub is CI for people; it is never part of Dyson's runtime). The runner only reads the
repo and runs the two commands; it holds no secret and reaches nothing but its throwaway Postgres.
Each check is bounded by a timeout so a hang can never wedge the sandbox.
"""

import os
import subprocess
from collections.abc import Sequence
from dataclasses import dataclass

TAIL_CHARS = 4000  # how much of each command's output to keep for the Founder to read


@dataclass(frozen=True)
class CheckResult:
    name: str
    ok: bool
    summary: str  # one line: the last meaningful line of output, or the timeout/err note
    tail: str  # the end of stdout+stderr, for debugging a failure


def _last_line(text: str) -> str:
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    return lines[-1] if lines else ""


def _run_one(name: str, cmd: Sequence[str], cwd: str, env: dict, timeout: float) -> CheckResult:
    try:
        proc = subprocess.run(
            list(cmd), cwd=cwd, env=env, capture_output=True, text=True, timeout=timeout
        )
    except subprocess.TimeoutExpired:
        return CheckResult(name, False, f"timed out after {int(timeout)}s", "")
    except OSError as exc:  # the command is missing or could not start
        return CheckResult(name, False, f"could not run: {exc}", "")
    out = (proc.stdout or "") + (proc.stderr or "")
    return CheckResult(
        name, proc.returncode == 0, _last_line(out) or "(no output)", out[-TAIL_CHARS:]
    )


def run_checks(
    repo: str, pg_dsn: str, *, lint_timeout: float = 300.0, test_timeout: float = 1200.0
) -> dict:
    """Run ruff (lint + format) and pytest against the repo at `repo`, with the test database at
    `pg_dsn`. Returns a small JSON-able dict: overall ok, and one entry per check."""
    env = {
        "PATH": os.environ.get("PATH", "/usr/local/bin:/usr/bin:/bin"),
        "HOME": "/tmp",
        "DYSON_TEST_PG_ADMIN": pg_dsn,
        "DYSON_TEST_REQUIRE_DB": "1",  # a missing DB is a failure here, never a silent skip
        "PYTHONDONTWRITEBYTECODE": "1",
    }
    checks = [
        _run_one("ruff-check", ["ruff", "check", "."], repo, env, lint_timeout),
        _run_one("ruff-format", ["ruff", "format", "--check", "."], repo, env, lint_timeout),
        _run_one("pytest", ["pytest", "-q"], repo, env, test_timeout),
    ]
    return {
        "ok": all(c.ok for c in checks),
        "checks": [
            {"name": c.name, "ok": c.ok, "summary": c.summary, "tail": c.tail} for c in checks
        ],
    }
