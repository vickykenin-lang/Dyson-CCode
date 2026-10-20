"""Receptor supervisor (phase 7, D-026): cheap anomaly detection, bounded closed-playbook repair.

Card E watches and escalates; this adds how Dyson supervises a Receptor without over-reaching. The
research is blunt: LLM root-cause is right only 11-45% of the time, and AI-run shops lose money
without hard limits. So:
  - detection is statistics (a robust z-score), not a model; the model is asked only after an alert;
  - repair is a closed playbook — retry, restart, roll back, cap the budget, pause — each bounded in
    attempts; anything outside the list escalates to the Founder (AMD-5, LA-G-05);
  - a kill switch auto-pauses when a Receptor spends more than it earns or its revenue will not
    reconcile.
Nothing here moves money or self-certifies. PAUSE is bounded repair; everything larger is the
Founder's decision.
"""

from collections.abc import Sequence
from decimal import Decimal
from enum import StrEnum
from statistics import median

from dyson_contracts.common import Contract


def robust_anomaly(history: Sequence[float], latest: float, k: float = 3.5) -> tuple[bool, float]:
    """Flag `latest` against a baseline using the median and MAD (robust to a few wild points).

    Returns (anomalous, score). Cheap enough to run nightly over a Receptor's KPIs; an alert gates
    the expensive LLM triage, so the model is never run on every metric.
    """
    if len(history) < 3:
        return False, 0.0  # not enough baseline to judge
    med = median(history)
    mad = median([abs(x - med) for x in history])
    if mad == 0:
        return (latest != med), (float("inf") if latest != med else 0.0)
    score = abs(latest - med) / (1.4826 * mad)
    return score > k, score


class Remedy(StrEnum):
    """The whole closed playbook. There is no free-form fix, by construction."""

    RETRY = "retry"  # transient failure: try again
    RESTART = "restart"  # restart the Receptor's workers
    ROLLBACK = "rollback"  # roll back the prompt/config to the last good one
    CAP_BUDGET = "cap_budget"  # tighten the spend cap
    PAUSE = "pause"  # stop the Receptor (bounded repair, AMD-5)
    ESCALATE = "escalate"  # out of the playbook: the Founder decides


# How the playbook escalates as attempts fail. PAUSE is the last bounded step before the Founder.
_LADDER = (Remedy.RETRY, Remedy.RESTART, Remedy.ROLLBACK, Remedy.CAP_BUDGET, Remedy.PAUSE)

# Reversible steps are safe at a lower autonomy level; PAUSE is safe (it only stops).
_REVERSIBLE = frozenset({Remedy.RETRY, Remedy.RESTART, Remedy.ROLLBACK, Remedy.CAP_BUDGET})


class Autonomy(StrEnum):
    """Per-Receptor, raised only after clean audits (staged autonomy)."""

    OBSERVED = "observed"  # nothing automatic: every remedy is proposed to the Founder
    GUARDED = "guarded"  # only reversible remedies run automatically
    TRUSTED = "trusted"  # the whole bounded playbook runs automatically


class Supervision(Contract):
    remedy: Remedy
    attempt: int
    automatic: bool  # True only if the Receptor's autonomy allows this remedy without the Founder


def plan_remediation(attempts: int, autonomy: Autonomy, max_attempts: int = 3) -> Supervision:
    """The next step in the closed playbook, bounded by attempts and gated by autonomy.

    attempts is how many remedies this incident has already had. After the ladder or the cap is
    spent, the only step left is to escalate to the Founder.
    """
    if attempts >= max_attempts or attempts >= len(_LADDER):
        return Supervision(remedy=Remedy.ESCALATE, attempt=attempts + 1, automatic=False)
    remedy = _LADDER[attempts]
    if autonomy is Autonomy.TRUSTED:
        automatic = True
    elif autonomy is Autonomy.GUARDED:
        automatic = remedy in _REVERSIBLE
    else:  # OBSERVED
        automatic = False
    return Supervision(remedy=remedy, attempt=attempts + 1, automatic=automatic)


def kill_switch(revenue: Decimal, cost: Decimal, reconciled: bool) -> bool:
    """Auto-pause when a Receptor spends more than it earns, or its revenue will not reconcile."""
    return cost > revenue or not reconciled
