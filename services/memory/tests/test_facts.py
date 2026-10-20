"""Bi-temporal personal facts (phase 2): point-in-time truth, supersession, search, isolation."""

from datetime import UTC, datetime
from uuid import uuid4

import psycopg
import pytest

from dyson_memory.models import Citation, Fact

T0 = datetime(2026, 1, 1, tzinfo=UTC)


def _fact(subject, attribute, value, statement, valid_from, recorded_at, **over):
    base = dict(
        fact_id=uuid4(),
        subject=subject,
        attribute=attribute,
        value=value,
        statement=statement,
        valid_from=valid_from,
        sources=(Citation(kind="message", ref=str(uuid4())),),
        recorded_at=recorded_at,
    )
    base.update(over)
    return Fact(**base)


def test_a_fact_is_stored_and_found_as_current(store_for):
    store = store_for("core")
    f = _fact("founder", "bank", "HDFC", "The Founder banks with HDFC.", T0, T0)
    store.record_fact(f)
    current = store.current_facts("founder", "bank")
    assert [c.value for c in current] == ["HDFC"]


def test_a_newer_fact_supersedes_but_history_survives(store_for):
    store = store_for("core")
    old = _fact("founder", "bank", "HDFC", "Banks with HDFC.", T0, T0)
    store.record_fact(old)
    jun = datetime(2026, 6, 1, tzinfo=UTC)
    new = _fact(
        "founder", "bank", "ICICI", "Now banks with ICICI.", jun, jun, supersedes=old.fact_id
    )
    store.record_fact(new)
    # Now: only the current fact.
    assert [c.value for c in store.current_facts("founder", "bank")] == ["ICICI"]
    # As of before the change: the old truth is still answerable.
    march = datetime(2026, 3, 1, tzinfo=UTC)
    assert [c.value for c in store.facts_as_of(march, "founder", "bank")] == ["HDFC"]
    # As of after: the new one.
    assert [c.value for c in store.facts_as_of(jun, "founder", "bank")] == ["ICICI"]


def test_facts_are_append_only_even_for_the_app_role(store_for):
    store = store_for("core")
    f = _fact("founder", "city", "Delhi", "Lives in Delhi.", T0, T0)
    store.record_fact(f)
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        with store._tx() as c:
            c.execute("UPDATE memory.facts SET value = 'Mumbai' WHERE fact_id = %s", [f.fact_id])


def test_search_finds_by_meaning_and_by_spelling(store_for):
    store = store_for("core")
    store.record_fact(
        _fact("founder", "car", "Tata Nexon", "The Founder drives a Tata Nexon.", T0, T0)
    )
    store.record_fact(_fact("project:dyson", "stack", "FastAPI", "Dyson runs on FastAPI.", T0, T0))
    by_meaning = store.search_facts("what does the founder drive")
    assert any("Nexon" in f.value for f in by_meaning)
    by_spelling = store.search_facts("Nexonn")  # misspelt; trigram still catches it
    assert any("Nexon" in f.value for f in by_spelling)


def test_a_receptor_cannot_see_core_personal_facts(store_for):
    core = store_for("core")
    core.record_fact(_fact("founder", "email", "x@y.z", "Founder email on file.", T0, T0))
    t0 = store_for("T0")
    assert t0.current_facts("founder", "email") == []  # isolation holds


def test_a_closed_fact_is_not_current_after_its_validity_ends(store_for):
    store = store_for("core")
    ended = _fact(
        "founder",
        "job",
        "Acme",
        "Worked at Acme.",
        T0,
        T0,
        valid_to=datetime(2026, 5, 1, tzinfo=UTC),
    )
    store.record_fact(ended)
    assert store.current_facts("founder", "job") == []  # validity has ended
    assert [
        f.value for f in store.facts_as_of(datetime(2026, 3, 1, tzinfo=UTC), "founder", "job")
    ] == ["Acme"]
