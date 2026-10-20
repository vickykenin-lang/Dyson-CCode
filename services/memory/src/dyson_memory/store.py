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
    Fact,
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

    # Founder presence (AMD-12 v1.1): a login, a message, or an action on Direct Founder Controls.
    PRESENCE_EVENTS = ("login", "decision", "control", "resume_requested", "passkey_enrolled")

    def last_founder_presence(self):
        with self._tx() as c:
            row = c.execute(
                "SELECT greatest("
                " (SELECT max(sent_at) FROM memory.messages WHERE participant = 'founder'),"
                " (SELECT max(at) FROM memory.audit_log WHERE summary = ANY(%s))) AS at",
                [list(self.PRESENCE_EVENTS)],
            ).fetchone()
        return row["at"]

    def last_audit_at(self, summary_prefix: str):
        with self._tx() as c:
            row = c.execute(
                "SELECT max(at) AS at FROM memory.audit_log WHERE summary LIKE %s",
                [summary_prefix + "%"],
            ).fetchone()
        return row["at"]

    def thread_summaries(self, limit: int = 200) -> list[dict]:
        """Each thread with its first Founder message and its last activity, newest first."""
        with self._tx() as c:
            return c.execute(
                "SELECT t.thread_id, max(m.sent_at) AS last_at,"
                " (array_agg(m.body ORDER BY m.sent_at, m.seq)"
                "    FILTER (WHERE m.participant = 'founder'))[1] AS first_line"
                " FROM memory.threads t JOIN memory.messages m USING (thread_id)"
                " GROUP BY t.thread_id ORDER BY last_at DESC LIMIT %s",
                [limit],
            ).fetchall()

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

    # Bi-temporal personal facts (phase 2) -----------------------------------------------
    def record_fact(self, fact: Fact) -> Fact:
        """Store a fact. A newer fact may name the one it supersedes; both are kept."""
        self._guard.check(fact.subject, fact.value, fact.statement)
        with self._tx() as c:
            c.execute(
                "INSERT INTO memory.facts (fact_id, receptor_id, subject, attribute, value,"
                " statement, valid_from, valid_to, sources, confidence, supersedes, recorded_at)"
                " VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                [
                    fact.fact_id,
                    fact.receptor_id,
                    fact.subject,
                    fact.attribute,
                    fact.value,
                    fact.statement,
                    fact.valid_from,
                    fact.valid_to,
                    Jsonb([s.model_dump() for s in fact.sources]),
                    fact.confidence,
                    fact.supersedes,
                    fact.recorded_at,
                ],
            )
        return fact

    def current_facts(self, subject: str | None = None, attribute: str | None = None) -> list[Fact]:
        """Facts true now: not superseded, and inside their valid window."""
        with self._tx() as c:
            rows = c.execute(
                "SELECT f.* FROM memory.facts f"
                " WHERE NOT EXISTS (SELECT 1 FROM memory.facts n WHERE n.supersedes = f.fact_id)"
                "   AND f.valid_from <= now() AND (f.valid_to IS NULL OR f.valid_to > now())"
                "   AND (%s::text IS NULL OR f.subject = %s::text)"
                "   AND (%s::text IS NULL OR f.attribute = %s::text)"
                " ORDER BY f.recorded_at DESC",
                [subject, subject, attribute, attribute],
            ).fetchall()
        return [_fact(r) for r in rows]

    def facts_as_of(
        self, when: datetime, subject: str | None = None, attribute: str | None = None
    ) -> list[Fact]:
        """Point in time: what Dyson knew to be true at `when` (bi-temporal query)."""
        with self._tx() as c:
            rows = c.execute(
                "SELECT f.* FROM memory.facts f"
                " WHERE f.recorded_at <= %s"
                "   AND f.valid_from <= %s AND (f.valid_to IS NULL OR f.valid_to > %s)"
                "   AND NOT EXISTS (SELECT 1 FROM memory.facts n"
                "       WHERE n.supersedes = f.fact_id AND n.recorded_at <= %s)"
                "   AND (%s::text IS NULL OR f.subject = %s::text)"
                "   AND (%s::text IS NULL OR f.attribute = %s::text)"
                " ORDER BY f.recorded_at DESC",
                [when, when, when, when, subject, subject, attribute, attribute],
            ).fetchall()
        return [_fact(r) for r in rows]

    def search_facts(self, query: str, limit: int = 10) -> list[Fact]:
        """Current facts matching the query by meaning (full text) or spelling (trigram)."""
        with self._tx() as c:
            rows = c.execute(
                "SELECT f.*,"
                "   ts_rank(f.search, websearch_to_tsquery('simple', %s)) AS r,"
                "   GREATEST(similarity(f.subject, %s), similarity(f.value, %s)) AS sim"
                " FROM memory.facts f"
                " WHERE NOT EXISTS (SELECT 1 FROM memory.facts n WHERE n.supersedes = f.fact_id)"
                "   AND f.valid_from <= now() AND (f.valid_to IS NULL OR f.valid_to > now())"
                "   AND (f.search @@ websearch_to_tsquery('simple', %s)"
                "        OR similarity(f.subject, %s) > 0.2 OR similarity(f.value, %s) > 0.2)"
                " ORDER BY (ts_rank(f.search, websearch_to_tsquery('simple', %s))"
                "           + GREATEST(similarity(f.subject, %s), similarity(f.value, %s))) DESC,"
                "          f.recorded_at DESC LIMIT %s",
                [query, query, query, query, query, query, query, query, query, limit],
            ).fetchall()
        return [_fact(r) for r in rows]

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


def _fact(r: dict) -> Fact:
    fields = Fact.model_fields
    return Fact(**{k: v for k, v in r.items() if k in fields})


def _register(r: dict) -> RegisterEntry:
    fields = RegisterEntry.model_fields
    return RegisterEntry(**{k: v for k, v in r.items() if k in fields})


def _evidence(r: dict) -> EvidenceRecord:
    fields = EvidenceRecord.model_fields
    return EvidenceRecord(**{k: v for k, v in r.items() if k in fields})
