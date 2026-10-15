"""Policy Engine (LA-GOV-01): the AMD register in machine-checkable form, version and date per rule.

The register is loaded from policy/amd_register.yaml and refused if AMD-1..AMD-13 no longer match
policy/amd_register.lock (LA-AMD-05). Policy is read-only at runtime; changing it is a core
amendment (see GovernanceCore.propose_amendment), never an operational parameter.
"""

import hashlib
import json
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

import yaml

LOCKED_IDS = [f"AMD-{i}" for i in range(1, 14)]


class PolicyIntegrityError(RuntimeError):
    pass


@dataclass(frozen=True)
class Rule:
    id: str
    title: str
    status: str
    version: str
    effective_from: date
    controls: dict[str, Any]


class PolicyEngine:
    def __init__(self, rules: dict[str, Rule], register_version: str):
        self._rules = rules
        self.register_version = register_version

    @classmethod
    def load(cls, policy_dir: Path) -> "PolicyEngine":
        raw = yaml.safe_load((policy_dir / "amd_register.yaml").read_text("utf-8"))
        lock = (policy_dir / "amd_register.lock").read_text("utf-8").strip()
        locked = [r for r in raw["rules"] if r["id"] in LOCKED_IDS]
        blob = json.dumps(locked, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
        if hashlib.sha256(blob.encode("utf-8")).hexdigest() != lock:
            raise PolicyIntegrityError("AMD-1..AMD-13 do not match amd_register.lock")
        rules = {
            r["id"]: Rule(
                id=r["id"],
                title=r["title"],
                status=r["status"],
                version=str(r["version"]),
                effective_from=date.fromisoformat(r["effective_from"]),
                controls=dict(r["controls"]),
            )
            for r in raw["rules"]
        }
        return cls(rules, str(raw["register"]["version"]))

    def rule(self, amd_id: str) -> Rule:
        return self._rules[amd_id]

    def control(self, amd_id: str, key: str, on: date | None = None) -> Any:
        """A control value, only if the rule is in effect on the given date."""
        rule = self._rules[amd_id]
        if on is not None and on < rule.effective_from:
            raise LookupError(f"{amd_id} is not in effect on {on}")
        return rule.controls[key]

    def all_control_keys(self) -> set[str]:
        return {f"{r.id}.{k}" for r in self._rules.values() for k in r.controls}
