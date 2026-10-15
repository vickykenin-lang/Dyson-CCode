"""The Founder's own client for Direct Founder Controls: works with the app and every model down.

    dyson-control --url URL --key-file PATH stop [--receptor R11] [--reason TEXT]
    dyson-control --url URL --key-file PATH pause [--receptor R11]
    dyson-control --url URL --key-file PATH pending
    dyson-control --url URL --key-file PATH approve APPROVAL_ID
    dyson-control --url URL --key-file PATH reject APPROVAL_ID
    dyson-control --url URL --key-file PATH resume-request [--receptor R11]

The device key is read from the file and used only to answer challenges; it is never printed or
sent. Gate 3 replaces this with the chosen step-up method.
"""

import argparse
import sys
from pathlib import Path
from typing import Any
from uuid import UUID

import httpx

from .app import (
    purpose_for_control,
    purpose_for_decision,
    purpose_for_list,
    purpose_for_resume_request,
)
from .stepup import device_assertion


class ControlsClient:
    def __init__(self, http: httpx.Client, device_key: bytes):
        self._http, self._key = http, device_key

    def _confirm(self, purpose: str) -> dict[str, str]:
        r = self._http.post("/challenges", json={"purpose": purpose})
        r.raise_for_status()
        c = r.json()
        return {
            "challenge_id": c["challenge_id"],
            "assertion": device_assertion(self._key, c["nonce"], purpose),
        }

    def pending(self) -> list[dict[str, Any]]:
        c = self._confirm(purpose_for_list())
        r = self._http.get(
            "/approvals", headers={"X-Challenge": c["challenge_id"], "X-Assertion": c["assertion"]}
        )
        r.raise_for_status()
        return r.json()

    def control(self, command: str, receptor_id: str | None = None, reason: str = "") -> dict:
        scope = "receptor" if receptor_id else "master"
        body = {
            "command": command,
            "scope": scope,
            "receptor_id": receptor_id,
            "reason": reason,
            **self._confirm(purpose_for_control(command, scope, receptor_id)),
        }
        r = self._http.post("/control", json=body)
        r.raise_for_status()
        return r.json()

    def decide(self, approval_id: UUID, action_digest: str, decision: str) -> dict:
        body = {
            "approval_id": str(approval_id),
            "action_digest": action_digest,
            "decision": decision,
            **self._confirm(purpose_for_decision(approval_id, action_digest, decision)),
        }
        r = self._http.post("/decisions", json=body)
        r.raise_for_status()
        return r.json()

    def resume_request(self, receptor_id: str | None = None) -> dict:
        scope = "receptor" if receptor_id else "master"
        body = {
            "scope": scope,
            "receptor_id": receptor_id,
            **self._confirm(purpose_for_resume_request(scope, receptor_id)),
        }
        r = self._http.post("/resume-requests", json=body)
        r.raise_for_status()
        return r.json()


def main(argv: list[str] | None = None, http: httpx.Client | None = None) -> int:
    p = argparse.ArgumentParser(prog="dyson-control")
    p.add_argument("--url", required=http is None)
    p.add_argument("--key-file", required=True, type=Path)
    p.add_argument("--yes", action="store_true", help="skip the typed confirmation")
    p.add_argument(
        "action", choices=["stop", "pause", "pending", "approve", "reject", "resume-request"]
    )
    p.add_argument("approval_id", nargs="?", type=UUID)
    p.add_argument("--receptor")
    p.add_argument("--reason", default="")
    a = p.parse_args(argv)
    client = ControlsClient(
        http or httpx.Client(base_url=a.url, timeout=10), a.key_file.read_bytes().strip()
    )
    if a.action in ("stop", "pause"):
        state = client.control(a.action, a.receptor, a.reason)
        print(f"{state['scope']} {state.get('receptor_id') or ''} is now {state['mode']}")
    elif a.action == "pending":
        for r in client.pending():
            print(
                f"{r['approval_id']}  {r['category']}  {r['action_summary']}"
                f"  digest {r['action_digest']}"
            )
    elif a.action in ("approve", "reject"):
        if a.approval_id is None:
            p.error("approve and reject need an approval id")
        shown = {r["approval_id"]: r for r in client.pending()}.get(str(a.approval_id))
        if shown is None:
            print("no such approval is waiting", file=sys.stderr)
            return 1
        print(f"{a.action.upper()}: {shown['action_summary']}\ndigest {shown['action_digest']}")
        if not a.yes and input(f"Type {a.action} to confirm: ").strip() != a.action:
            print("nothing was decided")
            return 1
        kind = "approve" if a.action == "approve" else "reject"
        out = client.decide(a.approval_id, shown["action_digest"], kind)
        print(f"{out['approval_id']} is {out['status']}")
    else:
        r = client.resume_request(a.receptor)
        print(f"resume needs your approval: {r['approval_id']}  {r['action_summary']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
