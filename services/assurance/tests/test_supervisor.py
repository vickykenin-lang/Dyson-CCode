"""Receptor supervisor (phase 7): statistical alerts, closed-playbook repair, kill switch."""

from decimal import Decimal

from dyson_assurance.supervisor import (
    Autonomy,
    Remedy,
    kill_switch,
    plan_remediation,
    robust_anomaly,
)


def test_a_steady_series_is_not_flagged_but_a_spike_is():
    steady = [100, 102, 98, 101, 99, 100]
    assert not robust_anomaly(steady, 103)[0]  # within normal variation
    flagged, score = robust_anomaly(steady, 400)  # a real spike
    assert flagged and score > 3.5


def test_too_little_history_never_flags():
    assert robust_anomaly([100, 102], 500) == (False, 0.0)


def test_the_playbook_escalates_step_by_step_then_hands_to_the_founder():
    order = [plan_remediation(i, Autonomy.TRUSTED).remedy for i in range(5)]
    assert order == [
        Remedy.RETRY,
        Remedy.RESTART,
        Remedy.ROLLBACK,
        Remedy.ESCALATE,
        Remedy.ESCALATE,
    ]
    # With a higher cap, PAUSE is the last bounded step before the Founder.
    assert plan_remediation(4, Autonomy.TRUSTED, max_attempts=6).remedy is Remedy.PAUSE


def test_observed_autonomy_proposes_everything_to_the_founder():
    s = plan_remediation(0, Autonomy.OBSERVED)
    assert s.remedy is Remedy.RETRY and not s.automatic


def test_guarded_autonomy_runs_only_reversible_steps_automatically():
    assert plan_remediation(0, Autonomy.GUARDED).automatic  # retry is reversible
    # cap_budget is reversible too; pause is not auto under guarded even with a higher cap.
    pause = plan_remediation(4, Autonomy.GUARDED, max_attempts=6)
    assert pause.remedy is Remedy.PAUSE and not pause.automatic


def test_there_is_no_remedy_outside_the_closed_playbook():
    allowed = {Remedy.RETRY, Remedy.RESTART, Remedy.ROLLBACK, Remedy.CAP_BUDGET, Remedy.PAUSE}
    seen = {plan_remediation(i, Autonomy.TRUSTED, max_attempts=6).remedy for i in range(5)}
    assert seen <= allowed | {Remedy.ESCALATE}


def test_kill_switch_pauses_a_loss_making_or_unreconciled_receptor():
    assert kill_switch(Decimal("100"), Decimal("150"), reconciled=True)  # cost > revenue
    assert kill_switch(Decimal("100"), Decimal("50"), reconciled=False)  # will not reconcile
    assert not kill_switch(Decimal("100"), Decimal("50"), reconciled=True)  # healthy
