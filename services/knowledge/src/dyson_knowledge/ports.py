"""The two things the ingestor depends on, as narrow interfaces so they can be swapped.

Embedder: turns text into vectors. The real one is a local open model (EmbeddingGemma) run on the
box, so sensitive text and its vectors never leave; tests use a deterministic fake.

Store: the record manager + vector index. The real one is pgvector in the existing Postgres (keyed
by source+path with a content hash and a generation, tombstoning deletes); tests use an in-memory
one. upsert replaces a document's chunks atomically so a changed file never leaves stale vectors.
"""

from collections.abc import Sequence
from typing import Protocol

from .model import Chunk


class Embedder(Protocol):
    model_id: str  # recorded with each vector; a model change invalidates old vectors
    dim: int

    def embed(self, texts: Sequence[str]) -> list[list[float]]: ...


class Store(Protocol):
    def document_state(self, source: str, path: str) -> tuple[str, int] | None:
        """(content_hash, generation) for a live document, or None if unknown/tombstoned."""
        ...

    def upsert(
        self,
        *,
        source: str,
        path: str,
        content_hash: str,
        generation: int,
        mime: str,
        tags: Sequence[str],
        embedding_model: str,
        chunks: Sequence[Chunk],
    ) -> None:
        """Replace the document's chunks atomically and record its new hash/generation."""
        ...

    def delete(self, source: str, path: str) -> None:
        """Tombstone a document so it stops being retrieved; chunks go too."""
        ...

    def known_paths(self, source: str) -> set[str]:
        """Live (non-tombstoned) paths in a source, for reconciliation sweeps."""
        ...
