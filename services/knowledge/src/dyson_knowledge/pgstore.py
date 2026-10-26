"""The real Store: pgvector in the existing Postgres.

Keyed by (source, path) with a content hash and a generation. upsert replaces a document's chunks
inside one transaction, so a changed file never leaves stale vectors; delete tombstones the document
and drops its chunks so it stops being retrieved. The embedding is sent as a pgvector literal, so
there is no extra driver dependency.
"""

import posixpath
from collections.abc import Sequence

import psycopg

from .model import Chunk


def _vec(embedding: Sequence[float]) -> str:
    return "[" + ",".join(repr(float(x)) for x in embedding) + "]"


class PgStore:
    """Implements the Store port against the knowledge schema. Takes an autocommit connection."""

    def __init__(self, conn: psycopg.Connection):
        self._c = conn

    def document_state(self, source: str, path: str) -> tuple[str, int] | None:
        row = self._c.execute(
            "SELECT content_hash, generation FROM knowledge.documents "
            "WHERE source = %s AND path = %s AND NOT deleted",
            [source, path],
        ).fetchone()
        return (row["content_hash"], row["generation"]) if row else None

    def upsert(self, *, source, path, content_hash, generation, mime, tags,
               embedding_model, chunks):  # fmt: skip
        folder, filename = posixpath.dirname(path), posixpath.basename(path)
        tag_list = list(tags)
        with self._c.transaction():
            doc_id = self._c.execute(
                "INSERT INTO knowledge.documents "
                "(source, path, content_hash, generation, mime, tags, embedding_model, folder, "
                " filename, deleted, updated_at) "
                "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,false,now()) "
                "ON CONFLICT (source, path) DO UPDATE SET "
                "  content_hash=EXCLUDED.content_hash, generation=EXCLUDED.generation, "
                "  mime=EXCLUDED.mime, tags=EXCLUDED.tags, "
                "  embedding_model=EXCLUDED.embedding_model, "
                "  folder=EXCLUDED.folder, filename=EXCLUDED.filename, deleted=false, "
                "  updated_at=now() "
                "RETURNING doc_id",
                [source, path, content_hash, generation, mime, tag_list, embedding_model, folder,
                 filename],  # fmt: skip
            ).fetchone()["doc_id"]
            self._c.execute("DELETE FROM knowledge.chunks WHERE doc_id = %s", [doc_id])
            for ch in chunks:
                self._c.execute(
                    "INSERT INTO knowledge.chunks "
                    "(doc_id, source, path, folder, ord, text, tags, embedding) "
                    "VALUES (%s,%s,%s,%s,%s,%s,%s,%s::vector)",
                    [doc_id, source, path, folder, ch.ord, ch.text, tag_list, _vec(ch.embedding)],
                )

    def delete(self, source: str, path: str) -> None:
        with self._c.transaction():
            row = self._c.execute(
                "UPDATE knowledge.documents SET deleted=true, updated_at=now() "
                "WHERE source = %s AND path = %s AND NOT deleted RETURNING doc_id",
                [source, path],
            ).fetchone()
            if row:
                self._c.execute("DELETE FROM knowledge.chunks WHERE doc_id = %s", [row["doc_id"]])

    def known_paths(self, source: str) -> set[str]:
        rows = self._c.execute(
            "SELECT path FROM knowledge.documents WHERE source = %s AND NOT deleted", [source]
        )
        return {r["path"] for r in rows}

    def _chunk_rows(self, source: str, path: str) -> list[Chunk]:
        """Test helper: the chunks currently stored for a document, in order."""
        rows = self._c.execute(
            "SELECT ord, text FROM knowledge.chunks WHERE source = %s AND path = %s ORDER BY ord",
            [source, path],
        )
        return [Chunk(ord=r["ord"], text=r["text"]) for r in rows]
