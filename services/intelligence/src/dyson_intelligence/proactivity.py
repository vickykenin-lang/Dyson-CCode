"""Deciding when to interrupt, building the morning briefing, and learning from the reply (phase 4).

Pure logic, no I/O. B uses it to prepare what the Founder sees; nothing here acts or approves.
"""

from collections import Counter
from datetime import datetime, timedelta
from uuid import UUID, uuid4

from dyson_contracts.proactive import (
    Briefing,
    BriefingSection,
    ClassTuning,
    Disposition,
    Feedback,
    InboxItem,
    InboxKind,
    Urgency,
    UrgentClass,
)

# The classes that interrupt. A class not here always waits for a digest.
INTERRUPTS: frozenset[UrgentClass] = frozenset(
    {
        UrgentClass.MONEY_OUT,
        UrgentClass.DEADLINE_24H,
        UrgentClass.RECEPTOR_FAILING,
        UrgentClass.SECURITY,
    }
)


def classify(
    urgent_class: UrgentClass | None, demoted: frozenset[UrgentClass] = frozenset()
) -> Urgency:
    """Interrupt only for an interrupting class the Founder has not asked to quieten."""
    if urgent_class is not None and urgent_class in INTERRUPTS and urgent_class not in demoted:
        return Urgency.NOW
    return Urgency.DIGEST


def build_briefing(
    for_date: datetime,
    *,
    schedule: tuple[str, ...] = (),
    waiting_mail: tuple[str, ...] = (),
    tasks: tuple[str, ...] = (),
    receptors: tuple[str, ...] = (),
    digest_items: tuple[InboxItem, ...] = (),
) -> Briefing:
    """Assemble the one morning artifact. Empty parts are left out, so a quiet day reads quiet."""
    sections: list[BriefingSection] = []
    if schedule:
        sections.append(BriefingSection(heading="Today", lines=schedule))
    if receptors:
        sections.append(BriefingSection(heading="Your businesses", lines=receptors))
    if waiting_mail:
        sections.append(BriefingSection(heading="Waiting for you", lines=waiting_mail))
    if tasks:
        sections.append(BriefingSection(heading="In progress", lines=tasks))
    if digest_items:
        lines = tuple(f"[{i.kind.value}] {i.subject}" for i in digest_items)
        sections.append(BriefingSection(heading="Also", lines=lines))
    return Briefing(
        briefing_id=uuid4(),
        for_date=for_date,
        sections=tuple(sections),
        item_ids=tuple(i.item_id for i in digest_items),
    )


def due_for_digest(last_digest_at: datetime, now: datetime, times_per_day: int = 2) -> bool:
    """True when enough time has passed for the next batch (default twice a day)."""
    gap = timedelta(hours=24 / max(1, times_per_day))
    return now - last_digest_at >= gap


def unanswered_review(
    items: tuple[InboxItem, ...], feedback: tuple[Feedback, ...]
) -> tuple[UUID, ...]:
    """Review items the Founder has not acted on yet, so nothing silently ships."""
    answered = {f.item_id for f in feedback}
    return tuple(
        i.item_id for i in items if i.kind is InboxKind.REVIEW and i.item_id not in answered
    )


def tune(items: tuple[InboxItem, ...], feedback: tuple[Feedback, ...]) -> tuple[ClassTuning, ...]:
    """Per urgent class: how often the Founder acted vs dismissed, and whether to quieten it.

    A suggestion only (LA-CONV-05): Dyson never changes what interrupts on its own.
    """
    by_item = {i.item_id: i for i in items}
    acted: Counter[UrgentClass] = Counter()
    dismissed: Counter[UrgentClass] = Counter()
    for f in feedback:
        item = by_item.get(f.item_id)
        if item is None or item.urgent_class is None:
            continue
        if f.disposition is Disposition.ACTED:
            acted[item.urgent_class] += 1
        elif f.disposition is Disposition.DISMISSED:
            dismissed[item.urgent_class] += 1
    out: list[ClassTuning] = []
    for uc in sorted(set(acted) | set(dismissed), key=lambda c: c.value):
        a, d = acted[uc], dismissed[uc]
        # Security never gets quietened automatically, however often it is dismissed.
        demote = uc is not UrgentClass.SECURITY and d >= 5 and d >= 3 * max(a, 1)
        out.append(ClassTuning(urgent_class=uc, acted=a, dismissed=d, suggest_demote=demote))
    return out
