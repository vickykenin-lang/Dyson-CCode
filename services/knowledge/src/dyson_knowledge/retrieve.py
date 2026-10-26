"""Search the knowledge index: hybrid (vector + keyword) retrieval over pgvector.

Dense vector search finds meaning; Postgres full-text (the 'simple' tsvector) catches exact terms
and filenames that embeddings blur. The two rankings are merged with Reciprocal Rank Fusion — the
no-tuning default the research recommends — so a query gets the best of both. Returns the top chunks
with their source path and a fused score, for the conversation engine to answer from and cite.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol

import psycopg

RRF_K = 60  # reciprocal-rank-fusion constant; 60 is the standard default
POOL = 20  # how many to pull from each ranker before fusing


class _QueryEmbedder(Protocol):
    def embed_query(self, text: str) -> list[float]: ...


@dataclass(frozen=True)
class Hit:
    source: str
    path: str
    folder: str
    ord: int
    text: str
    score: float  # fused rank score (for ordering)
    similarity: float  # best vector cosine similarity (0..1), for a relevance threshold


def _vec(embedding: Sequence[float]) -> str:
    return "[" + ",".join(repr(float(x)) for x in embedding) + "]"


class Retriever:
    def __init__(self, conn: psycopg.Connection, embedder: _QueryEmbedder):
        self._c = conn
        self._e = embedder

    def search(self, query: str, *, source: str | None = None, k: int = 5) -> list[Hit]:
        qv = _vec(self._e.embed_query(query))
        src = "" if source is None else "AND source = %(src)s"
        sql = f"""
        WITH v AS (
            SELECT chunk_id, source, path, folder, ord, text,
                   1 - (embedding <=> %(q)s::vector) AS vsim,
                   row_number() OVER (ORDER BY embedding <=> %(q)s::vector) AS rk
            FROM knowledge.chunks WHERE true {src}
            ORDER BY embedding <=> %(q)s::vector LIMIT %(pool)s
        ),
        k AS (
            SELECT chunk_id, source, path, folder, ord, text,
                   1 - (embedding <=> %(q)s::vector) AS vsim,
                   row_number() OVER (
                       ORDER BY ts_rank(tsv, plainto_tsquery('simple', %(qt)s)) DESC) AS rk
            FROM knowledge.chunks
            WHERE tsv @@ plainto_tsquery('simple', %(qt)s) {src}
            ORDER BY ts_rank(tsv, plainto_tsquery('simple', %(qt)s)) DESC LIMIT %(pool)s
        ),
        fused AS (
            SELECT source, path, folder, ord, text,
                   sum(1.0 / (%(rrf)s + rk)) AS score, max(vsim) AS similarity
            FROM (SELECT * FROM v UNION ALL SELECT * FROM k) u
            GROUP BY source, path, folder, ord, text
        )
        SELECT source, path, folder, ord, text, score, coalesce(similarity, 0) AS similarity
        FROM fused ORDER BY score DESC LIMIT %(k)s
        """
        params = {"q": qv, "qt": query, "pool": POOL, "rrf": RRF_K, "k": k, "src": source}
        rows = self._c.execute(sql, params).fetchall()
        return [
            Hit(source=r["source"], path=r["path"], folder=r["folder"], ord=r["ord"],
                text=r["text"], score=float(r["score"]), similarity=float(r["similarity"]))
            for r in rows
        ]  # fmt: skip
