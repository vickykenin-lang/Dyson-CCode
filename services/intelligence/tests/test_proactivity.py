"""Proactive inbox and briefing (phase 4): interrupt rules, the morning artifact, learning."""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

from dyson_contracts.proactive import (
    Disposition,
    Feedback,
    InboxItem,
    InboxKind,
    Urgency,
    UrgentClass,
)
from dyson_intelligence.proactivity import (
    build_briefing,
    classify,
    due_for_digest,
    tune,
    unanswered_review,
)

DAY = datetime(2026, 10, 20, 8, 0, tzinfo=UTC)


def _item(kind=InboxKind.NOTIFY, urgency=Urgency.DIGEST, uc=None, subject="x", review_ref=""):
    return InboxItem(
        item_id=uuid4(),
        kind=kind,
        subject=subject,
        urgency=urgency,
        urgent_class=uc,
        review_ref=review_ref,
        created_at=DAY,
    )


def test_only_defined_classes_interrupt():
    assert classify(UrgentClass.MONEY_OUT) is Urgency.NOW
    assert classify(UrgentClass.RECEPTOR_FAILING) is Urgency.NOW
    assert classify(None) is Urgency.DIGEST  # ordinary news waits


def test_a_quietened_class_stops_interrupting():
    demoted = frozenset({UrgentClass.DEADLINE_24H})
    assert classify(UrgentClass.DEADLINE_24H, demoted) is Urgency.DIGEST
    assert classify(UrgentClass.MONEY_OUT, demoted) is Urgency.NOW  # others still interrupt


def test_the_briefing_leaves_out_empty_parts():
    quiet = build_briefing(DAY)
    assert quiet.sections == ()  # a quiet day reads quiet
    full = build_briefing(
        DAY,
        schedule=("9:00 call with Ravi",),
        receptors=("R11 healthy, revenue 1,250",),
        digest_items=(_item(subject="newsletter idea"),),
    )
    headings = [s.heading for s in full.sections]
    assert headings == ["Today", "Your businesses", "Also"]
    assert full.item_ids  # it gathered the digest item


def test_digest_fires_twice_a_day_not_hourly():
    assert not due_for_digest(DAY, DAY + timedelta(hours=1))
    assert due_for_digest(DAY, DAY + timedelta(hours=12))


def test_an_unanswered_review_is_surfaced_so_nothing_ships_silently():
    draft = _item(kind=InboxKind.REVIEW, subject="email to Ravi", review_ref="draft:1")
    note = _item(kind=InboxKind.NOTIFY, subject="fyi")
    assert unanswered_review((draft, note), ()) == (draft.item_id,)
    done = (Feedback(item_id=draft.item_id, disposition=Disposition.ACTED, at=DAY),)
    assert unanswered_review((draft, note), done) == ()


def test_the_tuner_suggests_quietening_a_class_the_founder_keeps_dismissing():
    items = [_item(urgency=Urgency.NOW, uc=UrgentClass.DEADLINE_24H) for _ in range(6)]
    fb = tuple(
        Feedback(item_id=i.item_id, disposition=Disposition.DISMISSED, at=DAY) for i in items
    )
    tunings = {t.urgent_class: t for t in tune(tuple(items), fb)}
    assert tunings[UrgentClass.DEADLINE_24H].suggest_demote


def test_security_is_never_quietened_automatically():
    items = [_item(urgency=Urgency.NOW, uc=UrgentClass.SECURITY) for _ in range(10)]
    fb = tuple(
        Feedback(item_id=i.item_id, disposition=Disposition.DISMISSED, at=DAY) for i in items
    )
    tunings = {t.urgent_class: t for t in tune(tuple(items), fb)}
    assert not tunings[UrgentClass.SECURITY].suggest_demote
