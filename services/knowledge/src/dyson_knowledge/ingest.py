"""Ingest one source document into the index, idempotently and safely.

The record-manager logic lives here: hash the text, skip if unchanged (no wasted embedding), else
chunk → embed → upsert under a new generation so a changed file never leaves stale vectors, and
tombstone on delete. A document that trips the secret scan is quarantined, never embedded. A
reconcile sweep tombstones anything in the store that is no longer present at the source — the trap
that silently rots naive indexes (incremental pipelines do not delete source-removed docs).
"""

import hashlib
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from enum import StrEnum

from .chunk import chunk_text
from .model import Chunk, SourceDoc
from .ports import Embedder, Store
from .secrets_scan import has_secret


class IngestOutcome(StrEnum):
    INDEXED = "indexed"  # chunked, embedded and stored (new or changed)
    UNCHANGED = "unchanged"  # same content hash as what's already indexed; nothing done
    QUARANTINED = "quarantined"  # contained a credential; refused, not indexed
    EMPTY = "empty"  # no text to index


def content_hash(text: str) -> str:
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()


@dataclass
class Ingestor:
    store: Store
    embedder: Embedder
    chunker: Callable[[str], list[str]] = chunk_text

    def ingest(self, doc: SourceDoc) -> IngestOutcome:
        if has_secret(doc.text):
            self.store.delete(doc.source, doc.path)  # if it was indexed before, pull it now
            return IngestOutcome.QUARANTINED
        pieces = self.chunker(doc.text)
        if not pieces:
            return IngestOutcome.EMPTY
        digest = content_hash(doc.text)
        state = self.store.document_state(doc.source, doc.path)
        if state is not None and state[0] == digest:
            return IngestOutcome.UNCHANGED
        generation = (state[1] + 1) if state is not None else 1
        vectors = self.embedder.embed(pieces)
        pairs = zip(pieces, vectors, strict=True)
        chunks = [Chunk(ord=i, text=t, embedding=v) for i, (t, v) in enumerate(pairs)]
        self.store.upsert(
            source=doc.source,
            path=doc.path,
            content_hash=digest,
            generation=generation,
            mime=doc.mime,
            tags=doc.tags,
            embedding_model=self.embedder.model_id,
            chunks=chunks,
        )
        return IngestOutcome.INDEXED

    def delete(self, source: str, path: str) -> None:
        self.store.delete(source, path)

    def reconcile(self, source: str, present: Iterable[str]) -> list[str]:
        """Tombstone every live path in the store that is no longer present at the source.
        Returns the paths removed. Run as a periodic sweep behind the change-driven ingest."""
        present_set = set(present)
        gone = sorted(self.store.known_paths(source) - present_set)
        for path in gone:
            self.store.delete(source, path)
        return gone

    def ingest_all(self, docs: Sequence[SourceDoc]) -> dict[IngestOutcome, int]:
        counts: dict[IngestOutcome, int] = {}
        for doc in docs:
            outcome = self.ingest(doc)
            counts[outcome] = counts.get(outcome, 0) + 1
        return counts
