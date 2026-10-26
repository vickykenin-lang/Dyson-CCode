"""PgStore against a real pgvector Postgres. Skipped unless DYSON_TEST_DSN points at one.

The CI-independent verification of the same behaviour runs live on the server; these exercise the
SQL itself (upsert replace, tombstone, reconcile, unchanged-skip) when a test database is available.
"""

import os

import pytest

pytestmark = pytest.mark.skipif(
    not os.environ.get("DYSON_TEST_DSN"), reason="set DYSON_TEST_DSN to a pgvector Postgres"
)


class _Embedder768:
    model_id = "fake-768"
    dim = 768

    def embed(self, texts):
        return [[float(len(t) % 7)] + [0.0] * 767 for t in texts]


@pytest.fixture
def ing():
    from dyson_knowledge.db import connect, migrate
    from dyson_knowledge.ingest import Ingestor
    from dyson_knowledge.pgstore import PgStore

    conn = connect(os.environ["DYSON_TEST_DSN"])
    conn.execute("DROP SCHEMA IF EXISTS knowledge CASCADE")
    migrate(conn)
    store = PgStore(conn)
    yield Ingestor(store=store, embedder=_Embedder768()), store
    conn.execute("DROP SCHEMA IF EXISTS knowledge CASCADE")
    conn.close()


def _doc(text, path="projects/x/notes.md"):
    from dyson_knowledge.model import SourceDoc

    return SourceDoc(source="vault", path=path, text=text)


def test_ingest_unchanged_change_delete_reconcile(ing):
    from dyson_knowledge.ingest import IngestOutcome

    ingestor, store = ing
    assert ingestor.ingest(_doc("hello world")) is IngestOutcome.INDEXED
    assert store.document_state("vault", "projects/x/notes.md")[1] == 1
    assert len(store._chunk_rows("vault", "projects/x/notes.md")) >= 1

    assert ingestor.ingest(_doc("hello world")) is IngestOutcome.UNCHANGED
    assert ingestor.ingest(_doc("a brand new body")) is IngestOutcome.INDEXED
    assert store.document_state("vault", "projects/x/notes.md")[1] == 2  # generation bumped

    ingestor.ingest(_doc("second file", path="projects/y/plan.md"))
    assert store.known_paths("vault") == {"projects/x/notes.md", "projects/y/plan.md"}
    gone = ingestor.reconcile("vault", present=["projects/x/notes.md"])
    assert gone == ["projects/y/plan.md"]
    assert store.known_paths("vault") == {"projects/x/notes.md"}


def test_knn_search_returns_nearest(ing):
    ingestor, store = ing
    ingestor.ingest(_doc("alpha"))
    rows = store._c.execute(
        "SELECT path FROM knowledge.chunks ORDER BY embedding <-> %s::vector LIMIT 1",
        ["[" + ",".join(["0.0"] * 768) + "]"],
    ).fetchall()
    assert rows and rows[0]["path"] == "projects/x/notes.md"
