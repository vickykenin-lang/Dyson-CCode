"""Every PRD requirement is owned by exactly one execution-plan step."""

import re
from collections import Counter
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
REQS = yaml.safe_load(
    (ROOT / "docs" / "traceability" / "requirements.yaml").read_text(encoding="utf-8")
)["requirements"]

# Requirement counts per prefix in the PRD (sections 2, 7, 8, 10, 12).
EXPECTED = {
    "LA-G": 9, "LA-APP": 9, "LA-GW": 5, "LA-DFC": 6, "LA-VLT": 4, "LA-GOV": 10, "LA-CONV": 7,
    "LA-RTR": 7, "LA-ORC": 7, "LA-MON": 6, "LA-QA": 6, "LA-TOOL": 7, "LA-FIN": 8, "LA-MEM": 10,
    "LA-DASH": 5, "LA-HER": 8, "LA-RD": 5, "LA-AMD": 5, "LA-IF": 12, "LA-SEC": 7, "LA-SAF": 5,
    "LA-EVD": 5, "LA-REL": 6, "LA-COST": 4, "LA-PERF": 3, "LA-PRIV": 3, "LA-DEP": 5,
}  # fmt: skip


def test_ids_are_unique_and_well_formed():
    ids = [r["id"] for r in REQS]
    assert len(ids) == len(set(ids))
    assert all(re.fullmatch(r"LA-[A-Z]+-\d{2}", i) for i in ids)


def test_counts_match_prd():
    counts = Counter(r["id"].rsplit("-", 1)[0] for r in REQS)
    assert dict(counts) == EXPECTED
    assert len(REQS) == sum(EXPECTED.values()) == 174


def test_numbering_has_no_gaps():
    by_prefix = {}
    for r in REQS:
        prefix, num = r["id"].rsplit("-", 1)
        by_prefix.setdefault(prefix, []).append(int(num))
    for prefix, nums in by_prefix.items():
        assert sorted(nums) == list(range(1, len(nums) + 1)), prefix


def test_every_requirement_has_one_step_text_and_basis():
    for r in REQS:
        assert r["step"] in range(1, 11), r["id"]
        assert r["text"].strip() and r["basis"].strip(), r["id"]


def test_every_step_owns_something():
    assert {r["step"] for r in REQS} == set(range(1, 11))
