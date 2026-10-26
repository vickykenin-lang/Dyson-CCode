"""The ingestor: idempotent, generation-tracked, secret-safe, reconciling."""

from dyson_knowledge.ingest import Ingestor, IngestOutcome
from dyson_knowledge.model import SourceDoc
from fakes import FakeEmbedder, FakeStore


def _ing():
    store, emb = FakeStore(), FakeEmbedder()
    return Ingestor(store=store, embedder=emb), store, emb


def _doc(text, path="projects/x/notes.md", source="vault"):
    return SourceDoc(source=source, path=path, text=text)


def test_new_document_is_indexed_with_embeddings():
    ing, store, emb = _ing()
    assert ing.ingest(_doc("hello world, this is a note")) is IngestOutcome.INDEXED
    assert store.document_state("vault", "projects/x/notes.md")[1] == 1  # generation 1
    chunks = store.chunks("vault", "projects/x/notes.md")
    assert chunks and all(c.embedding for c in chunks)


def test_unchanged_document_is_skipped_and_not_re_embedded():
    ing, store, emb = _ing()
    ing.ingest(_doc("same text"))
    calls_after_first = emb.calls
    assert ing.ingest(_doc("same text")) is IngestOutcome.UNCHANGED
    assert emb.calls == calls_after_first  # no wasted embedding


def test_changed_document_bumps_generation_and_re_embeds():
    ing, store, emb = _ing()
    ing.ingest(_doc("first version"))
    assert ing.ingest(_doc("second, different version")) is IngestOutcome.INDEXED
    assert store.document_state("vault", "projects/x/notes.md")[1] == 2


def test_document_with_a_secret_is_quarantined_not_stored():
    ing, store, emb = _ing()
    outcome = ing.ingest(_doc("deploy key: sk-abcdefghijklmnopqrstuvwxyz0123"))
    assert outcome is IngestOutcome.QUARANTINED
    assert store.document_state("vault", "projects/x/notes.md") is None


def test_a_secret_pulls_a_previously_indexed_copy():
    ing, store, emb = _ing()
    ing.ingest(_doc("clean first"))
    ing.ingest(_doc("now with sk-abcdefghijklmnopqrstuvwxyz0123"))
    assert store.document_state("vault", "projects/x/notes.md") is None  # pulled


def test_empty_document():
    ing, store, emb = _ing()
    assert ing.ingest(_doc("   ")) is IngestOutcome.EMPTY


def test_delete_removes_the_document():
    ing, store, emb = _ing()
    ing.ingest(_doc("to be deleted"))
    ing.delete("vault", "projects/x/notes.md")
    assert store.document_state("vault", "projects/x/notes.md") is None


def test_reconcile_tombstones_paths_no_longer_present():
    ing, store, emb = _ing()
    ing.ingest(_doc("a", path="a.md"))
    ing.ingest(_doc("b", path="b.md"))
    ing.ingest(_doc("c", path="c.md"))
    gone = ing.reconcile("vault", present=["a.md", "c.md"])  # b.md is gone from the source
    assert gone == ["b.md"]
    assert store.known_paths("vault") == {"a.md", "c.md"}
