"""Retriever against a real pgvector Postgres. Skipped unless DYSON_TEST_DSN points at one.

Proves the two halves of hybrid search: a meaning match the embedding carries, and an exact-term
match only the full-text index catches. The live server runs the same path end to end.
"""

import os

import pytest

pytestmark = pytest.mark.skipif(
    not os.environ.get("DYSON_TEST_DSN"), reason="set DYSON_TEST_DSN to a pgvector Postgres"
)

# A deterministic stand-in for EmbeddingGemma: each topic word owns one dimension, plus a constant
# baseline dimension so a query with no topic word still has a defined (non-zero) cosine.
_TOPICS = {"social": 0, "finance": 1, "sandbox": 2}


def _vec(text: str) -> list[float]:
    v = [0.0] * 768
    v[767] = 1.0  # baseline, so an all-miss query is never the zero vector
    for word, i in _TOPICS.items():
        if word in text.lower():
            v[i] = 1.0
    return v


class _Embedder:
    model_id = "fake-768"
    dim = 768

    def embed(self, texts):
        return [_vec(t) for t in texts]

    def embed_query(self, text):
        return _vec(text)


@pytest.fixture
def retr():
    from dyson_knowledge.db import connect, migrate
    from dyson_knowledge.ingest import Ingestor
    from dyson_knowledge.pgstore import PgStore
    from dyson_knowledge.retrieve import Retriever

    conn = connect(os.environ["DYSON_TEST_DSN"])
    conn.execute("DROP SCHEMA IF EXISTS knowledge CASCADE")
    migrate(conn)
    store = PgStore(conn)
    yield Ingestor(store=store, embedder=_Embedder()), Retriever(conn, _Embedder())
    conn.execute("DROP SCHEMA IF EXISTS knowledge CASCADE")
    conn.close()


def _doc(text, path):
    from dyson_knowledge.model import SourceDoc

    return SourceDoc(source="vault", path=path, text=text)


def test_hybrid_retriever_finds_by_meaning_and_by_exact_term(retr):
    ingestor, retriever = retr
    ingestor.ingest(_doc("social media reels plan teen baar a week", "social-media/plan.md"))
    ingestor.ingest(_doc("finance GST invoice number and ledger", "finance/invoices.md"))

    # meaning: the query shares the social dimension, so that doc is nearest with high similarity
    by_meaning = retriever.search("social media plan")
    assert by_meaning and by_meaning[0].path == "social-media/plan.md"
    assert by_meaning[0].similarity > 0.5

    # exact term: 'invoice' is a word the embedding dimension does not carry; full-text catches it
    by_term = retriever.search("invoice")
    assert by_term and by_term[0].path == "finance/invoices.md"


def test_search_can_be_scoped_to_one_source(retr):
    ingestor, retriever = retr
    ingestor.ingest(_doc("social plan", "social-media/plan.md"))
    assert retriever.search("social", source="vault")  # the source it lives in
    assert retriever.search("social", source="other") == []  # a source with nothing in it
