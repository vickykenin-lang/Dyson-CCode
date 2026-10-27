"""Build the second-brain graph: one node per document, edges that say WHY two docs are linked.

Each document becomes a node (sized by how much it holds). Edges come from meaning — every document
is joined to its nearest neighbours by the cosine distance between their chunk centroids — and the
reason is spelled out from what they share: the same folder, the same project, or just a similar
topic. Every node gets at least its single closest neighbour, so nothing floats alone in the galaxy.
"""

from collections.abc import Sequence
from dataclasses import dataclass, field

import psycopg

NEIGHBOURS = 3  # nearest neighbours to link per document
MIN_SIM = 0.30  # keep extra neighbours only above this cosine; the closest one is always kept


@dataclass(frozen=True)
class Node:
    id: str  # "source|path", unique
    label: str  # filename
    source: str  # the project/repo it came from (used to colour/cluster)
    folder: str
    size: int  # chunk count


@dataclass(frozen=True)
class Edge:
    source: str  # node id
    target: str  # node id
    similarity: float
    reason: str


@dataclass(frozen=True)
class Graph:
    nodes: list[Node] = field(default_factory=list)
    edges: list[Edge] = field(default_factory=list)

    def to_json(self) -> dict:
        return {
            "nodes": [
                {"id": n.id, "label": n.label, "source": n.source, "folder": n.folder,
                 "size": n.size}
                for n in self.nodes
            ],
            "links": [
                {"source": e.source, "target": e.target,
                 "similarity": round(e.similarity, 4), "reason": e.reason}
                for e in self.edges
            ],
        }  # fmt: skip


def _reason(a: Node, b: Node, sim: float) -> str:
    pct = f"{sim:.0%}"
    if a.source == b.source and a.folder and a.folder == b.folder:
        return f"same folder '{a.folder}' in {a.source} · {pct} similar"
    if a.source == b.source:
        return f"same project {a.source} · {pct} similar"
    return f"similar topic across projects · {pct} similar"


def build_graph(
    conn: psycopg.Connection, *, neighbours: int = NEIGHBOURS, min_sim: float = MIN_SIM
) -> Graph:
    """Nodes for every live document and reasoned edges to each one's nearest neighbours."""
    rows = conn.execute(
        "SELECT d.source, d.path, d.folder, d.filename,"
        "       (SELECT count(*) FROM knowledge.chunks c WHERE c.doc_id = d.doc_id) AS n"
        "  FROM knowledge.documents d WHERE NOT d.deleted"
    ).fetchall()
    nodes = [
        Node(id=f"{r['source']}|{r['path']}", label=r["filename"] or r["path"],
             source=r["source"], folder=r["folder"] or "", size=int(r["n"]))
        for r in rows
    ]  # fmt: skip
    by_id = {n.id: n for n in nodes}
    if len(nodes) < 2:
        return Graph(nodes=nodes, edges=[])

    # One centroid vector per document (mean of its chunk embeddings), then nearest neighbours.
    # A CTE (not a temp table) keeps this to a plain SELECT, so B's read-only role can run it.
    pairs = conn.execute(
        "WITH cent AS ("
        "   SELECT source || '|' || path AS id, avg(embedding) AS cv"
        "     FROM knowledge.chunks GROUP BY source, path"
        ")"
        " SELECT a.id AS src, b.id AS tgt, 1 - (a.cv <=> b.cv) AS sim"
        "   FROM cent a"
        "   JOIN LATERAL ("
        "        SELECT id, cv FROM cent x WHERE x.id <> a.id"
        "        ORDER BY a.cv <=> x.cv LIMIT %(k)s"
        "   ) b ON true",
        {"k": neighbours},
    ).fetchall()

    # Undirected: keep each pair once (best similarity), always keep a node's closest neighbour.
    best_of: dict[str, tuple[float, str]] = {}  # node id -> (sim, other id) of its closest
    chosen: dict[frozenset, float] = {}
    for r in pairs:
        src, tgt, sim = r["src"], r["tgt"], float(r["sim"])
        if src not in by_id or tgt not in by_id:
            continue
        if src not in best_of or sim > best_of[src][0]:
            best_of[src] = (sim, tgt)
        if sim >= min_sim:
            key = frozenset((src, tgt))
            chosen[key] = max(chosen.get(key, 0.0), sim)
    for src, (sim, tgt) in best_of.items():  # guarantee connectivity
        chosen.setdefault(frozenset((src, tgt)), sim)

    edges = []
    for key, sim in chosen.items():
        a_id, b_id = tuple(key)
        a, b = by_id[a_id], by_id[b_id]
        edges.append(Edge(source=a_id, target=b_id, similarity=sim, reason=_reason(a, b, sim)))
    edges.sort(key=lambda e: e.similarity, reverse=True)
    return Graph(nodes=nodes, edges=edges)


def sources(nodes: Sequence[Node]) -> list[str]:
    return sorted({n.source for n in nodes})
