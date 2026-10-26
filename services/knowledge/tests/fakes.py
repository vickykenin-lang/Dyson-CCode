"""In-memory fakes for the knowledge-layer ports, used by the unit tests."""

from collections.abc import Sequence

from dyson_knowledge.model import Chunk


class FakeEmbedder:
    model_id = "fake-embed-1"
    dim = 3

    def __init__(self):
        self.calls = 0  # number of embed() calls, to prove unchanged docs are not re-embedded

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        self.calls += 1
        return [[float(len(t)), 1.0, 0.0] for t in texts]


class FakeStore:
    def __init__(self):
        self.docs: dict[tuple[str, str], dict] = {}

    def document_state(self, source: str, path: str):
        d = self.docs.get((source, path))
        return (d["hash"], d["generation"]) if d else None

    def upsert(self, *, source, path, content_hash, generation, mime, tags,
               embedding_model, chunks):  # fmt: skip
        self.docs[(source, path)] = {
            "hash": content_hash, "generation": generation, "mime": mime,
            "tags": tuple(tags), "model": embedding_model, "chunks": list(chunks),
        }  # fmt: skip

    def delete(self, source: str, path: str) -> None:
        self.docs.pop((source, path), None)

    def known_paths(self, source: str) -> set[str]:
        return {p for (s, p) in self.docs if s == source}

    def chunks(self, source: str, path: str) -> list[Chunk]:
        return self.docs[(source, path)]["chunks"]
