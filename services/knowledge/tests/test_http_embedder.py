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
    """Echoes a vector per input (len-based), recording every request it was sent."""

    def __init__(self):
        self.sent = []

    def post(self, url, json, timeout):  # noqa: A002 - matches httpx.post
        self.sent.append({"url": url, "json": json})
        pairs = list(enumerate(json["input"]))
        # return out-of-order to prove we sort by index within a request
        data = [{"index": i, "embedding": [float(len(t))]} for i, t in reversed(pairs)]
        return _Resp({"data": data})


def test_embed_documents_uses_the_document_prompt_and_keeps_order():
    client = _Client()
    e = HttpEmbedder("http://emb:8098", client=client)  # default batch_size=1
    out = e.embed(["note one", "note two longer"])
    want = [
        [float(len("title: none | text: note one"))],
        [float(len("title: none | text: note two longer"))],
    ]
    assert out == want
    assert [r["url"] for r in client.sent] == ["http://emb:8098/v1/embeddings"] * 2  # one per doc
    assert client.sent[0]["json"]["input"] == ["title: none | text: note one"]


def test_embed_documents_can_batch_several_per_request():
    client = _Client()
    e = HttpEmbedder("http://emb:8098", batch_size=2, client=client)
    e.embed(["a", "b", "c"])
    assert len(client.sent) == 2  # [a, b] then [c]
    assert client.sent[0]["json"]["input"] == ["title: none | text: a", "title: none | text: b"]


def test_embed_query_uses_the_query_prompt():
    client = _Client()
    e = HttpEmbedder("http://emb:8098", client=client)
    wrapped = "task: search result | query: where is my plan"
    assert e.embed_query("where is my plan") == [float(len(wrapped))]
    assert client.sent[0]["json"]["input"] == [wrapped]
