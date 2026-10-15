"""Compute or check the hash that locks AMD-1..AMD-13 (LA-AMD-05).

    python tools/policy_lock.py          # print the current hash
    python tools/policy_lock.py --write  # rewrite policy/amd_register.lock

Rewriting the lock is a constitutional change: it needs explicit Founder approval (AMD-14).
"""

import hashlib
import json
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
REGISTER = ROOT / "policy" / "amd_register.yaml"
LOCK = ROOT / "policy" / "amd_register.lock"
LOCKED_IDS = [f"AMD-{i}" for i in range(1, 14)]


def locked_hash() -> str:
    rules = yaml.safe_load(REGISTER.read_text(encoding="utf-8"))["rules"]
    locked = [r for r in rules if r["id"] in LOCKED_IDS]
    blob = json.dumps(locked, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


if __name__ == "__main__":
    h = locked_hash()
    if "--write" in sys.argv:
        LOCK.write_text(h + "\n", encoding="utf-8")
    print(h)
