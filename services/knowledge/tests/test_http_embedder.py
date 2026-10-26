"""The HTTP embedder wraps documents/queries with EmbeddingGemma prompts and parses the reply."""

from dyson_knowledge.http_embedder import HttpEmbedder


class _Resp:
    def __init__(self, data):
        self._data = data

    def raise_for_status(self):
        pass

    def json(self):
        return self._data


class _Client:
    def __init__(self, vectors):
        self.vectors = vectors
        self.sent = {}

    def post(self, url, json, timeout):  # noqa: A002 - matches httpx.post
        self.sent = {"url": url, "json": json}
        # return out-of-order to prove we sort by index
        data = [{"index": i, "embedding": v} for i, v in reversed(list(enumerate(self.vectors)))]
        return _Resp({"data": data})


def test_embed_documents_uses_the_document_prompt_and_keeps_order():
    client = _Client([[1.0, 0.0], [2.0, 0.0]])
    e = HttpEmbedder("http://emb:8098", client=client)
    out = e.embed(["note one", "note two"])
    assert out == [[1.0, 0.0], [2.0, 0.0]]  # sorted back into input order
    assert client.sent["url"] == "http://emb:8098/v1/embeddings"
    assert client.sent["json"]["input"][0].startswith("title: none | text: note one")


def test_embed_query_uses_the_query_prompt():
    client = _Client([[9.0, 9.0]])
    e = HttpEmbedder("http://emb:8098", client=client)
    assert e.embed_query("where is my plan") == [9.0, 9.0]
    assert client.sent["json"]["input"] == ["task: search result | query: where is my plan"]
