"""Load the authoritative register from policy/ into memory.register_entries.

AMD-1..AMD-14 enter as DESIGN LOCKED; Founder decisions D-xxx enter as APPROVED. Re-running is
safe: an entry is skipped when the latest one for that rule already has the same version, status
and text.
"""

from datetime import UTC, date, datetime
from pathlib import Path
from uuid import uuid4

import yaml

from .models import RegisterEntry, RegisterStatus
from .store import MemoryStore


def policy_entries(policy_dir: Path) -> list[RegisterEntry]:
    reg = yaml.safe_load((policy_dir / "amd_register.yaml").read_text("utf-8"))
    dec = yaml.safe_load((policy_dir / "decisions.yaml").read_text("utf-8"))
    now = datetime.now(UTC)
    entries = []
    approval_ref = "; ".join(reg["register"]["source"][:2])
    for r in reg["rules"]:
        entries.append(
            RegisterEntry(
                entry_id=uuid4(),
                rule_id=r["id"],
                version=r["version"],
                status=RegisterStatus(r["status"]),
                title=r["title"],
                body=r["principle"],
                decision_date=date.fromisoformat(r["effective_from"]),
                founder_approval_ref=approval_ref,
                recorded_at=now,
            )
        )
    for d in dec["decisions"]:
        entries.append(
            RegisterEntry(
                entry_id=uuid4(),
                rule_id=d["id"],
                version="1",
                status=RegisterStatus.APPROVED,
                title=d["topic"],
                body=d["decision"],
                decision_date=date.fromisoformat(d["date"]),
                founder_approval_ref=f"Founder decision {d['id']}, policy/decisions.yaml",
                recorded_at=now,
            )
        )
    return entries


def seed_register(store: MemoryStore, policy_dir: Path) -> int:
    added = 0
    for entry in policy_entries(policy_dir):
        view = store.register_view(entry.rule_id)
        if view and (view.current.version, view.current.status, view.current.body) == (
            entry.version,
            entry.status,
            entry.body,
        ):
            continue
        store.record_register_entry(entry)
        added += 1
    return added
