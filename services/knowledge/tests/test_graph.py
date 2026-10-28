"""Building the second-brain graph: nodes per doc, reasoned edges, nothing left unconnected."""

import os

import pytest

pytestmark = pytest.mark.skipif(
    not os.environ.get("DYSON_TEST_DSN"), reason="set DYSON_TEST_DSN to a pgvector Postgres"
)

_TOPICS = {"social": 0, "finance": 1, "sandbox": 2}


def _vec(text):
    v = [0.0] * 768
    v[767] = 1.0
    for word, i in _TOPICS.items():
        if word in text.lower():
            v[i] = 1.0
    return v


class _Embedder:
    model_id = "fake-768"
    dim = 768

    def embed(self, texts):
        return [_vec(t) for t in texts]


@pytest.fixture
def conn():
    from dyson_knowledge.db import connect, migrate

    c = connect(os.environ["DYSON_TEST_DSN"])
    c.execute("DROP SCHEMA IF EXISTS knowledge CASCADE")
    migrate(c)
    yield c
    c.execute("DROP SCHEMA IF EXISTS knowledge CASCADE")
    c.close()


def _ingest(conn, items):
    from dyson_knowledge.ingest import Ingestor
    from dyson_knowledge.model import SourceDoc
    from dyson_knowledge.pgstore import PgStore

    ing = Ingestor(store=PgStore(conn), embedder=_Embedder())
    for source, path, text in items:
        ing.ingest(SourceDoc(source=source, path=path, text=text))


def test_every_node_has_at_least_one_reasoned_edge(conn):
    from dyson_knowledge.graph import build_graph

    _ingest(conn, [
        ("proj-a", "social/plan.md", "social media reels plan"),
        ("proj-a", "social/calendar.md", "social posting calendar schedule"),
        ("proj-b", "finance/gst.md", "finance gst invoice tax"),
        ("proj-b", "finance/ledger.md", "finance ledger accounts"),
        ("proj-c", "misc/sandbox.md", "sandbox browser automation"),
    ])  # fmt: skip
    g = build_graph(conn, neighbours=2)
    assert len(g.nodes) == 5
    linked = {e.source for e in g.edges} | {e.target for e in g.edges}
    assert linked == {n.id for n in g.nodes}  # nobody floats alone
    assert all(e.reason for e in g.edges)  # every edge explains itself
    # the two social docs share meaning and project -> their edge says so
    social = frozenset({"proj-a|social/plan.md", "proj-a|social/calendar.md"})
    same = [e for e in g.edges if frozenset({e.source, e.target}) == social]
    assert same and "same folder 'social' in proj-a" in same[0].reason  # most specific reason wins


def test_graph_json_shape_for_the_force_graph(conn):
    from dyson_knowledge.graph import build_graph

    _ingest(conn, [("p", "a.md", "social one"), ("p", "b.md", "social two")])
    data = build_graph(conn).to_json()
    assert set(data) == {"nodes", "links"}
    assert {"id", "label", "source", "folder", "size", "x", "y", "z"} <= set(data["nodes"][0])
    assert {"source", "target", "similarity", "reason"} <= set(data["links"][0])
    # every node has a real 3D position for the galaxy renderer
    assert all(isinstance(n["x"], (int, float)) for n in data["nodes"])


def test_layout_clusters_each_project_together(conn):
    from dyson_knowledge.graph import build_graph

    _ingest(conn, [
        ("proj-a", "a1.md", "social one"), ("proj-a", "a2.md", "social two"),
        ("proj-b", "b1.md", "finance one"), ("proj-b", "b2.md", "finance two"),
    ])  # fmt: skip
    pos = build_graph(conn).pos
    import math

    def d(p, q):
        return math.dist(p, q)

    a1, a2 = pos["proj-a|a1.md"], pos["proj-a|a2.md"]
    b1 = pos["proj-b|b1.md"]
    # two notes of the same project sit closer than notes of different projects
    assert d(a1, a2) < d(a1, b1)
