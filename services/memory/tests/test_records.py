"""Register, evidence registry, audit log, secrets and backup / restore."""

from datetime import date, timedelta
from pathlib import Path
from uuid import uuid4

import psycopg
import pytest
from memory_testkit import CANARY, NOW

from dyson_contracts.audit import AuditEvent, AuditKind
from dyson_contracts.common import Component
from dyson_contracts.evidence import EvidenceOutcome, EvidenceRecord, EvidenceStage
from dyson_memory.backup import backup, restore
from dyson_memory.db import connect
from dyson_memory.models import (
    ArchivedMessage,
    Citation,
    MemoryItem,
    MemoryKind,
    RegisterEntry,
    RegisterStatus,
    Thread,
)
from dyson_memory.register_seed import seed_register
from dyson_memory.secrets import LocalSecretStore, SecretLeak
from dyson_memory.store import MemoryStore

POLICY = Path(__file__).resolve().parents[3] / "policy"


# Register -------------------------------------------------------------------------------
def test_seed_loads_all_rules_and_decisions_once(store_for):
    core = store_for("core")
    first = seed_register(core, POLICY)
    assert first >= 14 + 7
    assert seed_register(core, POLICY) == 0  # idempotent
    view = core.register_view("AMD-3")
    assert view.locked and view.current.status is RegisterStatus.DESIGN_LOCKED
    assert view.current.decision_date == date(2026, 10, 10)
    assert core.register_view("D-007").current.status is RegisterStatus.APPROVED


def test_register_history_is_immutable_and_status_is_latest(store_for, admin):
    core = store_for("core")
    seed_register(core, POLICY)
    core.record_register_entry(
        RegisterEntry(
            entry_id=uuid4(),
            rule_id="D-001",
            version="2",
            status=RegisterStatus.SUPERSEDED,
            title="Task state names",
            body="Superseded for test",
            recorded_at=NOW,
        )
    )
    view = core.register_view("D-001")
    assert view.current.status is RegisterStatus.SUPERSEDED and view.locked is False
    assert [e.version for e in core.register_history("D-001")] == ["1", "2"]
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        admin.execute("UPDATE memory.register_entries SET status = 'APPROVED'")


def test_unlocked_rule_is_never_presented_as_locked(store_for):
    core = store_for("core")
    core.record_register_entry(
        RegisterEntry(
            entry_id=uuid4(),
            rule_id="D-099",
            version="1",
            status=RegisterStatus.PROPOSED,
            title="Proposal",
            body="A proposed rule",
            recorded_at=NOW,
        )
    )
    assert core.register_view("D-099").locked is False


def test_locked_entry_needs_founder_approval(store_for):
    with pytest.raises(psycopg.errors.CheckViolation):
        store_for("core").record_register_entry(
            RegisterEntry(
                entry_id=uuid4(),
                rule_id="D-098",
                version="1",
                status=RegisterStatus.APPROVED,
                title="No approval",
                body="Missing approval",
                decision_date=date(2026, 10, 15),
                recorded_at=NOW,
            )
        )


def test_only_core_writes_the_register(store_for):
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        seed_register(store_for("T0"), POLICY)


# Evidence -------------------------------------------------------------------------------
def _ev(stage, outcome=EvidenceOutcome.PASSED, by=Component.QA_QC, minutes=0, expires=None):
    return EvidenceRecord(
        evidence_id=uuid4(),
        capability="t0.inspect",
        provider="test-t0",
        stage=stage,
        outcome=outcome,
        environment="local",
        scope="T0",
        recorded_by=by,
        recorded_at=NOW + timedelta(minutes=minutes),
        expires_at=expires,
        artifact_ref=f"artifact-{uuid4()}",
    )


def test_stages_are_separate_and_failures_are_kept(store_for):
    core = store_for("core")
    core.record_evidence(_ev(EvidenceStage.SOURCE_IMPLEMENTED, by=Component.ORCHESTRATOR))
    core.record_evidence(
        _ev(EvidenceStage.TEST_PASSED, EvidenceOutcome.FAILED, Component.ORCHESTRATOR)
    )
    core.record_evidence(_ev(EvidenceStage.TEST_PASSED, minutes=1, by=Component.ORCHESTRATOR))
    status = core.capability_status("t0.inspect", "test-t0", "local", NOW + timedelta(hours=1))
    assert set(status) == {EvidenceStage.SOURCE_IMPLEMENTED, EvidenceStage.TEST_PASSED}
    assert status[EvidenceStage.TEST_PASSED].record.outcome is EvidenceOutcome.PASSED
    with core._tx() as c:  # the failed attempt stays on record
        failed = c.execute("SELECT count(*) AS n FROM memory.evidence WHERE outcome = 'failed'")
        assert failed.fetchone()["n"] == 1


def test_expired_evidence_is_flagged(store_for):
    core = store_for("core")
    core.record_evidence(
        _ev(
            EvidenceStage.CREDENTIAL_AVAILABLE,
            by=Component.TOOL_HUB,
            expires=NOW + timedelta(days=1),
        )
    )
    status = core.capability_status("t0.inspect", "test-t0", "local", NOW + timedelta(days=2))
    assert status[EvidenceStage.CREDENTIAL_AVAILABLE].expired


def test_live_stages_cannot_be_self_certified_even_in_sql(store_for, admin):
    with pytest.raises(psycopg.errors.CheckViolation):
        admin.execute(
            "INSERT INTO memory.evidence (evidence_id, capability, provider, stage, outcome,"
            " environment, scope, recorded_by, recorded_at, artifact_ref)"
            " VALUES (%s, 'c', 'p', 7, 'passed', 'local', 'T0', 'receptor', now(), 'x')",
            [uuid4()],
        )


def test_receptor_evidence_is_isolated(store_for):
    store_for("T0").record_evidence(
        _ev(EvidenceStage.TEST_PASSED, by=Component.RECEPTOR), receptor_id="T0"
    )
    assert store_for("R11").capability_status("t0.inspect", "test-t0", "local", NOW) == {}
    assert store_for("core").capability_status("t0.inspect", "test-t0", "local", NOW)


# Audit log ------------------------------------------------------------------------------
def _audit(summary="tool call denied", **data):
    return AuditEvent(
        event_id=uuid4(),
        kind=AuditKind.TOOL_CALL_DENIED,
        actor=Component.TOOL_HUB,
        at=NOW,
        summary=summary,
        data=data,
    )


def test_audit_chain_verifies(store_for):
    core = store_for("core")
    for i in range(3):
        core.audit(_audit(f"event {i}", n=i))
    assert core.verify_audit_chain() is None
    assert [e.summary for e in core.audit_events()] == ["event 0", "event 1", "event 2"]


def test_app_role_cannot_alter_audit(db, store_for):
    store_for("core").audit(_audit())
    with psycopg.connect(db["app"], autocommit=True) as c:
        c.execute("SELECT set_config('dyson.scope', 'core', false)")
        for stmt in (
            "UPDATE memory.audit_log SET summary = 'x'",
            "DELETE FROM memory.audit_log",
            "TRUNCATE memory.audit_log",
        ):
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                c.execute(stmt)


def test_owner_cannot_alter_audit_either(db, store_for):
    core = store_for("core")
    core.audit(_audit("original"))
    with psycopg.connect(db["owner"], autocommit=True) as c:
        c.execute("SELECT set_config('dyson.scope', 'core', false)")
        # No UPDATE or DELETE policy exists, so even the owner touches zero rows.
        assert c.execute("UPDATE memory.audit_log SET summary = 'x'").rowcount == 0
        assert c.execute("DELETE FROM memory.audit_log").rowcount == 0
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            c.execute("TRUNCATE memory.audit_log")
    assert [e.summary for e in core.audit_events()] == ["original"]


def test_tampering_by_superuser_is_detected(store_for, admin):
    core = store_for("core")
    for i in range(3):
        core.audit(_audit(f"event {i}"))
    admin.execute("ALTER TABLE memory.audit_log DISABLE TRIGGER audit_log_append_only")
    admin.execute("UPDATE memory.audit_log SET summary = 'forged' WHERE seq = 2")
    admin.execute("ALTER TABLE memory.audit_log ENABLE TRIGGER audit_log_append_only")
    assert core.verify_audit_chain() == 2


def test_caller_cannot_supply_its_own_hash(store_for):
    core = store_for("core")
    with core._tx() as c:
        c.execute(
            "INSERT INTO memory.audit_log (event_id, kind, actor, at, summary, prev_hash, hash)"
            " VALUES (%s, 'config_change', 'A', now(), 'x', 'forged', 'forged')",
            [uuid4()],
        )
    assert core.verify_audit_chain() is None


def test_receptors_cannot_read_or_write_audit(store_for):
    store_for("core").audit(_audit())
    t0 = store_for("T0")
    assert t0.audit_events() == []
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        t0.audit(_audit())


# Secrets --------------------------------------------------------------------------------
def test_canary_credential_never_reaches_memory(store_for, admin):
    core = store_for("core")
    t = Thread(thread_id=uuid4(), title="x", created_at=NOW)
    core.create_thread(t)
    leaks = [
        lambda: core.append_message(
            ArchivedMessage(
                message_id=uuid4(),
                thread_id=t.thread_id,
                participant="founder",
                modality="text",
                body=f"my key is {CANARY}",
                sent_at=NOW,
            )
        ),
        lambda: core.remember(
            MemoryItem(
                item_id=uuid4(),
                kind=MemoryKind.FACT,
                content=f"key={CANARY}",
                sources=(Citation(kind="document", ref="x"),),
                created_at=NOW,
            )
        ),
        lambda: core.audit(_audit(token=CANARY)),
        lambda: core.audit(_audit("aws key AKIAABCDEFGHIJKLMNOP")),
    ]
    for leak in leaks:
        with pytest.raises(SecretLeak):
            leak()
    tables = [
        r[0]
        for r in admin.execute(
            "SELECT tablename FROM pg_tables WHERE schemaname = 'memory'"
        ).fetchall()
    ]
    for table in tables:
        hit = admin.execute(
            f"SELECT count(*) FROM memory.{table} x WHERE x::text LIKE %s", [f"%{CANARY}%"]
        ).fetchone()[0]
        assert hit == 0, table


def test_secret_store_scopes_and_file_permissions(secret_file):
    store = LocalSecretStore(secret_file)
    assert store.get("core", "model_api_key") == CANARY
    with pytest.raises(KeyError):
        store.get("T0", "model_api_key")  # a Receptor cannot read core credentials
    secret_file.chmod(0o644)
    with pytest.raises(PermissionError):
        LocalSecretStore(secret_file)


# Backup and restore ---------------------------------------------------------------------
def test_backup_and_restore(db, store_for, guard, admin, tmp_path):
    core = store_for("core")
    t = Thread(thread_id=uuid4(), title="backup", created_at=NOW)
    core.create_thread(t)
    m = ArchivedMessage(
        message_id=uuid4(),
        thread_id=t.thread_id,
        participant="founder",
        modality="voice",
        body="restore me",
        sent_at=NOW,
    )
    core.append_message(m)
    core.audit(_audit())
    dump = backup(db["backup"], tmp_path / "memory.dump")
    assert dump.stat().st_mode & 0o077 == 0
    admin.execute("DROP SCHEMA memory CASCADE")
    restore(db["admin"], dump)
    with connect(db["app"]) as fresh:
        restored = MemoryStore(fresh, "core", guard)
        assert restored.thread_messages(t.thread_id) == [m]
        assert restored.verify_audit_chain() is None
        assert MemoryStore(fresh, "T0", guard).thread_messages(t.thread_id) == []
