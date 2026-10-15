"""Conversation archive, long-term memory and Receptor isolation."""

import os
import subprocess
from datetime import timedelta
from uuid import uuid4

import psycopg
import pytest
from memory_testkit import NOW
from pydantic import ValidationError

from dyson_contracts.interface import Language, Modality
from dyson_memory.db import connect
from dyson_memory.models import (
    ArchivedMessage,
    Citation,
    MemoryItem,
    MemoryKind,
    SharedLearning,
    Thread,
)


def _thread(store, receptor=None):
    t = Thread(thread_id=uuid4(), receptor_id=receptor, title="ops", created_at=NOW)
    store.create_thread(t)
    return t


def _msg(thread, body, minutes=0, voice=False, uncertain=False, who="founder"):
    return ArchivedMessage(
        message_id=uuid4(),
        thread_id=thread.thread_id,
        participant=who,
        modality=Modality.VOICE if voice else Modality.TEXT,
        body=body,
        language=Language.HINGLISH,
        transcription_uncertain=uncertain,
        sent_at=NOW + timedelta(minutes=minutes),
    )


def test_voice_and_text_share_one_history(store_for):
    core = store_for("core")
    t = _thread(core)
    core.append_message(_msg(t, "Receptor 3 ka status batao", voice=True))
    core.append_message(_msg(t, "Receptor 3 is healthy", minutes=1, who="dyson"))
    core.append_message(_msg(t, "thanks", minutes=2))
    history = core.thread_messages(t.thread_id)
    assert [m.body for m in history] == [
        "Receptor 3 ka status batao",
        "Receptor 3 is healthy",
        "thanks",
    ]
    assert [m.modality for m in history] == [Modality.VOICE, Modality.TEXT, Modality.TEXT]


def test_transcript_survives_reconnect(db, store_for, guard):
    core = store_for("core")
    t = _thread(core)
    m = _msg(t, "remember the T0 fault plan", voice=True)
    core.append_message(m)
    from dyson_memory.store import MemoryStore

    with connect(db["app"]) as fresh:
        assert MemoryStore(fresh, "core", guard).thread_messages(t.thread_id) == [m]


@pytest.mark.skipif(
    not os.environ.get("DYSON_TEST_RESTART_CMD"),
    reason="set DYSON_TEST_RESTART_CMD to restart Postgres",
)
def test_transcript_survives_server_restart(db, store_for, guard):
    from dyson_memory.store import MemoryStore

    core = store_for("core")
    t = _thread(core)
    m = _msg(t, "survive a restart", voice=True)
    core.append_message(m)
    subprocess.run(os.environ["DYSON_TEST_RESTART_CMD"], shell=True, check=True)
    with connect(db["app"]) as fresh:
        assert MemoryStore(fresh, "core", guard).thread_messages(t.thread_id) == [m]


def test_search_cites_records_and_flags_uncertain_speech(store_for):
    core = store_for("core")
    t = _thread(core)
    sure = _msg(t, "budget for R11 is approved", voice=True)
    unsure = _msg(t, "budget for R12 maybe", minutes=1, voice=True, uncertain=True)
    core.append_message(sure)
    core.append_message(unsure)
    hits = {h.message.message_id: h for h in core.search_messages("budget")}
    assert hits[sure.message_id].citation.ref == str(sure.message_id)
    assert hits[sure.message_id].uncertain is False
    assert hits[unsure.message_id].uncertain is True


def test_typed_text_cannot_be_marked_uncertain(store_for):
    with pytest.raises(ValidationError):
        _msg(_thread(store_for("core")), "x", uncertain=True)


def test_messages_are_append_only(store_for, admin):
    core = store_for("core")
    t = _thread(core)
    core.append_message(_msg(t, "original"))
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        admin.execute("UPDATE memory.messages SET body = 'rewritten'")
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        admin.execute("DELETE FROM memory.messages")


def test_no_automatic_chatgpt_import(store_for, admin):  # LA-PRIV-03
    t = _thread(store_for("core"))
    with pytest.raises(psycopg.errors.CheckViolation):
        admin.execute(
            "INSERT INTO memory.messages (message_id, thread_id, participant, modality, body,"
            " language, source, sent_at) VALUES (%s, %s, 'founder', 'text', 'old chat', 'en',"
            " 'chatgpt', now())",
            [uuid4(), t.thread_id],
        )


def test_receptors_are_isolated(store_for):
    t0, r11, core = store_for("T0"), store_for("R11"), store_for("core")
    t = _thread(t0, receptor="T0")
    t0.append_message(_msg(t, "T0 private note"))
    assert r11.thread_messages(t.thread_id) == []
    assert r11.search_messages("private") == []
    assert len(core.thread_messages(t.thread_id)) == 1
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        r11.append_message(_msg(t, "R11 writing into T0's thread"))
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        _thread(r11, receptor="T0")  # cannot create rows for another Receptor
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        _thread(r11)  # nor central rows


def test_no_scope_sees_nothing(db, store_for):
    core = store_for("core")
    t = _thread(core)
    core.append_message(_msg(t, "central"))
    with psycopg.connect(db["app"]) as c:
        assert c.execute("SELECT count(*) FROM memory.messages").fetchone()[0] == 0


def test_recall_with_provenance_and_uncertainty(store_for):
    core = store_for("core")
    t = _thread(core)
    unsure = _msg(t, "launch date maybe Friday", voice=True, uncertain=True)
    core.append_message(unsure)
    stored = core.remember(
        MemoryItem(
            item_id=uuid4(),
            kind=MemoryKind.PROJECT_STATUS,
            content="Launch date is Friday",
            sources=(Citation(kind="message", ref=str(unsure.message_id)),),
            created_at=NOW,
        )
    )
    assert stored.uncertain is True  # inherited from the uncertain transcript
    [hit] = core.recall("launch")
    assert hit.sources[0].ref == str(unsure.message_id) and hit.uncertain


def test_superseded_memory_is_not_recalled(store_for):
    core = store_for("core")
    src = (Citation(kind="document", ref="plan-v1"),)
    old = MemoryItem(
        item_id=uuid4(),
        kind=MemoryKind.FACT,
        content="prototype disk 50 GB",
        sources=src,
        created_at=NOW,
    )
    core.remember(old)
    new = MemoryItem(
        item_id=uuid4(),
        kind=MemoryKind.FACT,
        content="prototype disk 80 GB",
        sources=src,
        supersedes=old.item_id,
        created_at=NOW + timedelta(minutes=1),
    )
    core.remember(new)
    assert [m.item_id for m in core.recall("prototype disk")] == [new.item_id]


def test_memory_needs_a_source():
    with pytest.raises(ValidationError):
        MemoryItem(item_id=uuid4(), kind=MemoryKind.FACT, content="x", sources=(), created_at=NOW)


def test_shared_learning_needs_core_and_is_readable_by_receptors(store_for):
    learning = SharedLearning(
        learning_id=uuid4(),
        content="Retry T0 inspections once after a timeout",
        origin_receptor_id="T0",
        sources=(Citation(kind="evidence", ref=str(uuid4())),),
        approval_id=uuid4(),
        verified_evidence_id=uuid4(),
        created_at=NOW,
    )
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        store_for("T0").add_shared_learning(learning)
    store_for("core").add_shared_learning(learning)
    assert store_for("R11").shared_learnings() == [learning]
