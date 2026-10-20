"""The AMD register is complete, locked, and agrees with the frozen contracts."""

import importlib.util
from datetime import date
from pathlib import Path

import yaml

from dyson_contracts.common import Component
from dyson_contracts.evidence import EvidenceStage
from dyson_contracts.tasks import QA_CONSECUTIVE_FAILURE_LIMIT

ROOT = Path(__file__).resolve().parent.parent
REGISTER = yaml.safe_load((ROOT / "policy" / "amd_register.yaml").read_text(encoding="utf-8"))
RULES = {r["id"]: r for r in REGISTER["rules"]}


def _lock_module():
    spec = importlib.util.spec_from_file_location("policy_lock", ROOT / "tools" / "policy_lock.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_all_fourteen_rules_in_order():
    assert list(RULES) == [f"AMD-{i}" for i in range(1, 15)]


def test_every_rule_is_versioned_dated_and_locked():
    for rule in RULES.values():
        assert rule["status"] == "DESIGN LOCKED"
        assert rule["version"]
        date.fromisoformat(rule["effective_from"])
        for field in ("title", "principle", "layer_a_meaning", "carried_by"):
            assert rule[field].strip(), (rule["id"], field)
        assert isinstance(rule["controls"], dict) and rule["controls"]


def test_amd_1_to_13_unchanged():  # LA-AMD-05
    lock = (ROOT / "policy" / "amd_register.lock").read_text(encoding="utf-8").strip()
    assert _lock_module().locked_hash() == lock, "AMD-1..13 changed without a lock update"


def test_amd12_is_the_approved_survival_mode():
    # AMD-12 v1.1 (18 Oct 2026, Founder-approved amendment): 72 hours, Survival Mode.
    assert RULES["AMD-12"]["controls"]["automatic_72h_trigger_enabled"] is True
    assert RULES["AMD-12"]["controls"]["presence_timeout_hours"] == 72
    assert RULES["AMD-12"]["controls"]["nominee_authority"] == "none"
    assert RULES["AMD-12"]["presence"]  # gate 7's open sub-point, now defined


def test_controls_agree_with_contracts():
    assert RULES["AMD-3"]["controls"]["qa_consecutive_failure_limit"] == (
        QA_CONSECUTIVE_FAILURE_LIMIT
    )
    assert RULES["AMD-3"]["controls"]["evidence_stage_count"] == len(EvidenceStage)
    assert RULES["AMD-4"]["controls"]["preapproved_models"] == []
    assert RULES["AMD-5"]["controls"]["stop_requires_llm"] is False
    assert RULES["AMD-5"]["controls"]["auto_resume_after_serious_breach"] is False
    assert RULES["AMD-10"]["controls"]["dashboard_has_action_path"] is False


def test_planes_use_known_components():
    planes = yaml.safe_load((ROOT / "policy" / "planes.yaml").read_text(encoding="utf-8"))
    names = {p["name"] for p in planes["planes"]}
    assert names == {"governance", "intelligence", "execution", "assurance"}
    for plane in planes["planes"]:
        for comp in plane["components"]:
            assert comp in Component.__members__, comp
    by_plane = {p["name"]: set(p["components"]) for p in planes["planes"]}
    # AMD-1: thinking components never sit in the deciding or acting planes.
    assert not by_plane["intelligence"] & (by_plane["governance"] | by_plane["execution"])


def test_founder_decisions_recorded():
    decisions = yaml.safe_load((ROOT / "policy" / "decisions.yaml").read_text(encoding="utf-8"))
    ids = [d["id"] for d in decisions["decisions"]]
    assert ids == [f"D-{i:03d}" for i in range(1, 26)]
