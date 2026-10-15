"""MemoryStore: the Memory & Evidence Layer's only way in and out of the database.

I is a controlled store, not an authority (LA-MEM-08): nothing here grants or checks permission
for actions. It records, isolates and retrieves with citations.
"""

import json
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime
from uuid import UUID

import psycopg
from psycopg.types.json import Jsonb

from dyson_contracts.audit import AuditEvent
from dyson_contracts.evidence import EvidenceRecord, EvidenceStage

from .models import (
    LOCKED_STATUSES,
    ArchivedMessage,
    Citation,
    MemoryItem,
    MessageHit,
    RegisterEntry,
    RegisterView,
    SharedLearning,
    StageStatus,
    Thread,
)
from .secrets import SecretGuard


class MemoryStore:
    def __init__(self, conn: psycopg.Connection, scope: str, guard: SecretGuard):
        if not conn.autocommit:
            raise ValueError("MemoryStore needs an autocommit connection (see db.connect)")
        self._conn = conn
        self.scope = scope
        self._guard = guard

    @contextmanager
    def _tx(self) -> Iterator[psycopg.Connection]:
        with self._conn.transaction():
            self._conn.execute("SELECT set_config('dyson.scope', %s, true)", [self.scope])
            yield self._conn

    # Conversation archive ---------------------------------------------------------------
    def create_thread(self, thread: Thread) -> None:
        self._guard.check(thread.title)
        with self._tx() as c:
            c.execute(
                "INSERT INTO memory.threads (thread_id, receptor_id, title, created_at)"
                " VALUES (%s, %s, %s, %s)",
                [thread.thread_id, thread.receptor_id, thread.title, thread.created_at],
            )

    def append_message(self, m: ArchivedMessage) -> None:
        self._guard.check(m.body, *(a.name for a in m.attachments))
        with self._tx() as c:
            c.execute(
                "INSERT INTO memory.messages (message_id, thread_id, participant, modality, body,"
                " language, transcription_uncertain, raw_transcript_ref, attachments, sent_at)"
                " VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                [
                    m.message_id,
                    m.thread_id,
                    m.participant,
                    m.modality.value,
                    m.body,
                    m.language.value,
                    m.transcription_uncertain,
                    m.raw_transcript_ref,
                    Jsonb([a.model_dump() for a in m.attachments]),
                    m.sent_at,
                ],
            )

    def thread_messages(self, thread_id: UUID) -> list[ArchivedMessage]:
        with self._tx() as c:
            rows = c.execute(
                "SELECT * FROM memory.messages WHERE thread_id = %s ORDER BY sent_at, seq",
                [thread_id],
            ).fetchall()
        return [_message(r) for r in rows]

    def search_messages(self, query: str, limit: int = 20) -> list[MessageHit]:
        with self._tx() as c:
            rows = c.execute(
                "SELECT *, ts_rank(search, q) AS rank"
                " FROM memory.messages, websearch_to_tsquery('simple', %s) q"
                " WHERE search @@ q ORDER BY rank DESC, sent_at DESC LIMIT %s",
                [query, limit],
            ).fetchall()
        return [
            MessageHit(
                message=_message(r),
                citation=Citation(kind="message", ref=str(r["message_id"])),
                uncertain=r["transcription_uncertain"],
            )
            for r in rows
        ]

    # Long-term memory -------------------------------------------------------------------
    def remember(self, item: MemoryItem) -> MemoryItem:
        """Store a memory. It is marked uncertain if any cited message was uncertain speech."""
        self._guard.check(item.content)
        cited = [UUID(s.ref) for s in item.sources if s.kind == "message"]
        with self._tx() as c:
            uncertain = item.uncertain
            if cited and not uncertain:
                row = c.execute(
                    "SELECT bool_or(transcription_uncertain) AS u FROM memory.messages"
                    " WHERE message_id = ANY(%s)",
                    [cited],
                ).fetchone()
                uncertain = bool(row["u"])
            stored = item.model_copy(update={"uncertain": uncertain})
            c.execute(
                "INSERT INTO memory.memory_items (item_id, receptor_id, kind, content, sources,"
                " uncertain, supersedes, created_at) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
                [
                    stored.item_id,
                    stored.receptor_id,
                    stored.kind.value,
                    stored.content,
                    Jsonb([s.model_dump() for s in stored.sources]),
                    stored.uncertain,
                    stored.supersedes,
                    stored.created_at,
                ],
            )
        return stored

    def recall(self, query: str, limit: int = 10) -> list[MemoryItem]:
        """Current (not superseded) memories matching the query, each with its sources."""
        with self._tx() as c:
            rows = c.execute(
                "SELECT m.*, ts_rank(m.search, q) AS rank"
                " FROM memory.memory_items m, websearch_to_tsquery('simple', %s) q"
                " WHERE m.search @@ q AND NOT EXISTS"
                " (SELECT 1 FROM memory.memory_items n WHERE n.supersedes = m.item_id)"
                " ORDER BY rank DESC, m.created_at DESC LIMIT %s",
                [query, limit],
            ).fetchall()
        return [_memory(r) for r in rows]

    def add_shared_learning(self, learning: SharedLearning) -> None:
        self._guard.check(learning.content)
        with self._tx() as c:
            c.execute(
                "INSERT INTO memory.shared_learnings (learning_id, content, origin_receptor_id,"
                " sources, approval_id, verified_evidence_id, created_at)"
                " VALUES (%s, %s, %s, %s, %s, %s, %s)",
                [
                    learning.learning_id,
                    learning.content,
                    learning.origin_receptor_id,
                    Jsonb([s.model_dump() for s in learning.sources]),
                    learning.approval_id,
                    learning.verified_evidence_id,
                    learning.created_at,
                ],
            )

    def shared_learnings(self) -> list[SharedLearning]:
        with self._tx() as c:
            rows = c.execute("SELECT * FROM memory.shared_learnings ORDER BY created_at").fetchall()
        return [SharedLearning(**r) for r in rows]

    # Decision and amendment register ----------------------------------------------------
    def record_register_entry(self, entry: RegisterEntry) -> None:
        self._guard.check(entry.title, entry.body)
        with self._tx() as c:
            c.execute(
                "INSERT INTO memory.register_entries (entry_id, rule_id, version, status, title,"
                " body, decision_date, evidence, founder_approval_ref, recorded_at)"
                " VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                [
                    entry.entry_id,
                    entry.rule_id,
                    entry.version,
                    entry.status.value,
                    entry.title,
                    entry.body,
                    entry.decision_date,
                    Jsonb([e.model_dump() for e in entry.evidence]),
                    entry.founder_approval_ref,
                    entry.recorded_at,
                ],
            )

    def register_history(self, rule_id: str) -> list[RegisterEntry]:
        with self._tx() as c:
            rows = c.execute(
                "SELECT * FROM memory.register_entries WHERE rule_id = %s ORDER BY seq", [rule_id]
            ).fetchall()
        return [_register(r) for r in rows]

    def register_view(self, rule_id: str) -> RegisterView | None:
        """The authoritative status is the latest entry; locked is derived from it."""
        history = self.register_history(rule_id)
        if not history:
            return None
        current = history[-1]
        return RegisterView(
            current=current,
            locked=current.status in LOCKED_STATUSES,
            history_length=len(history),
        )

    # Evidence registry ------------------------------------------------------------------
    def record_evidence(self, rec: EvidenceRecord, receptor_id: str | None = None) -> None:
        self._guard.check(rec.detail, rec.artifact_ref)
        with self._tx() as c:
            c.execute(
                "INSERT INTO memory.evidence (evidence_id, receptor_id, capability, provider,"
                " stage, outcome, environment, scope, recorded_by, recorded_at, expires_at,"
                " artifact_ref, task_id, detail)"
                " VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                [
                    rec.evidence_id,
                    receptor_id,
                    rec.capability,
                    rec.provider,
                    int(rec.stage),
                    rec.outcome.value,
                    rec.environment,
                    rec.scope,
                    rec.recorded_by.value,
                    rec.recorded_at,
                    rec.expires_at,
                    rec.artifact_ref,
                    rec.task_id,
                    rec.detail,
                ],
            )

    def capability_status(
        self, capability: str, provider: str, environment: str, now: datetime
    ) -> dict[EvidenceStage, StageStatus]:
        """Latest record per stage, failed and negative included. Stages are never merged."""
        with self._tx() as c:
            rows = c.execute(
                "SELECT DISTINCT ON (stage) * FROM memory.evidence"
                " WHERE capability = %s AND provider = %s AND environment = %s"
                " ORDER BY stage, seq DESC",
                [capability, provider, environment],
            ).fetchall()
        out = {}
        for r in rows:
            rec = _evidence(r)
            out[rec.stage] = StageStatus(
                record=rec, expired=rec.expires_at is not None and rec.expires_at <= now
            )
        return out

    # Audit log --------------------------------------------------------------------------
    def audit(self, event: AuditEvent) -> None:
        self._guard.check(event.summary, json.dumps(event.data))
        with self._tx() as c:
            c.execute(
                "INSERT INTO memory.audit_log (event_id, kind, actor, at, summary, task_id,"
                " ref_id, data) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
                [
                    event.event_id,
                    event.kind.value,
                    event.actor.value,
                    event.at,
                    event.summary,
                    event.task_id,
                    event.ref_id,
                    Jsonb(event.data),
                ],
            )

    def audit_events(self, limit: int = 100) -> list[AuditEvent]:
        with self._tx() as c:
            rows = c.execute(
                "SELECT event_id, kind, actor, at, summary, task_id, ref_id, data"
                " FROM memory.audit_log ORDER BY seq DESC LIMIT %s",
                [limit],
            ).fetchall()
        return [AuditEvent(**r) for r in reversed(rows)]

    def verify_audit_chain(self) -> int | None:
        """None when the whole chain verifies; otherwise the seq of the first broken link."""
        with self._tx() as c:
            return c.execute("SELECT memory.verify_audit_chain() AS bad").fetchone()["bad"]


def _message(r: dict) -> ArchivedMessage:
    return ArchivedMessage(
        message_id=r["message_id"],
        thread_id=r["thread_id"],
        participant=r["participant"],
        modality=r["modality"],
        body=r["body"],
        language=r["language"],
        transcription_uncertain=r["transcription_uncertain"],
        raw_transcript_ref=r["raw_transcript_ref"],
        attachments=r["attachments"],
        sent_at=r["sent_at"],
    )


def _memory(r: dict) -> MemoryItem:
    fields = MemoryItem.model_fields
    return MemoryItem(**{k: v for k, v in r.items() if k in fields})


def _register(r: dict) -> RegisterEntry:
    fields = RegisterEntry.model_fields
    return RegisterEntry(**{k: v for k, v in r.items() if k in fields})


def _evidence(r: dict) -> EvidenceRecord:
    fields = EvidenceRecord.model_fields
    return EvidenceRecord(**{k: v for k, v in r.items() if k in fields})
