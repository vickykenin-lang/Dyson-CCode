"""The real Embedder: the local EmbeddingGemma server over its OpenAI-compatible endpoint.

Runs on the box (llama.cpp, the `embedder` container), so text and vectors never leave. Gemma
retrieves best with task prompts, so documents and queries are wrapped differently — asymmetric
embedding, standard for retrieval. embed() is for documents at ingest; embed_query() for a search.
"""

from collections.abc import Sequence
from typing import Any

_DOC = "title: none | text: {}"  # EmbeddingGemma document prompt
_QUERY = "task: search result | query: {}"  # EmbeddingGemma retrieval-query prompt
TIMEOUT_S = 120.0


class HttpEmbedder:
    model_id = "embeddinggemma-300m"
    dim = 768

    def __init__(self, base_url: str, *, timeout: float = TIMEOUT_S, batch_size: int = 1,
                 client: Any = None):  # fmt: skip
        self._url = base_url.rstrip("/") + "/v1/embeddings"
        self._timeout = timeout
        # One chunk per request by default: a single request whose inputs exceed the server's batch
        # window (llama.cpp's ubatch) fails whole, so we never pack several long chunks together.
        self._batch = max(1, batch_size)
        self._client = client  # an httpx client for tests; a one-shot request otherwise

    def _post(self, inputs: Sequence[str]) -> list[list[float]]:
        import httpx  # lazy: only when a real call is made

        caller = self._client or httpx
        resp = caller.post(self._url, json={"input": list(inputs)}, timeout=self._timeout)
        resp.raise_for_status()
        data = resp.json()["data"]
        return [d["embedding"] for d in sorted(data, key=lambda d: d.get("index", 0))]

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        """Embed documents (at ingest), in batches so no single request overflows the server."""
        docs = [_DOC.format(t) for t in texts]
        out: list[list[float]] = []
        for i in range(0, len(docs), self._batch):
            out.extend(self._post(docs[i : i + self._batch]))
        return out

    def embed_query(self, text: str) -> list[float]:
        """Embed one search query (at retrieval)."""
        return self._post([_QUERY.format(text)])[0]
