"""Dyson's knowledge layer (the "second brain").

Ingests the Founder's files, notes, chats and projects into a governed index the conversation
engine can search: a source item is scanned for secrets, chunked, embedded, and upserted with a
content hash and a generation so re-ingesting an unchanged file is a no-op and a deleted file is
tombstoned. Everything here is provider-agnostic — the embedding model and the vector store are
injected (ports.py), so a local embedder and pgvector in the existing Postgres plug in without
changing this core. No file content ever leaves the box through this layer; retrieval and
model-routing stay behind C/G as everywhere else.
"""

from .ingest import Ingestor, IngestOutcome
from .model import Chunk, SourceDoc
from .ports import Embedder, Store

__all__ = ["Chunk", "Embedder", "IngestOutcome", "Ingestor", "SourceDoc", "Store"]
