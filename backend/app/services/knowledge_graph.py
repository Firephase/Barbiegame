"""Research map / knowledge graph (spec §14).

The graph is built from **metadata we hold**, not from model imagination:
topics come from provider-assigned concepts and title keywords, authorship and
venue edges from citation metadata, and finding nodes only from claims that
survived verification.  So every node is clickable back to something real.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import Any, Literal

from ..core.provenance import Answer, Claim, Epistemic, Source
from ..core.text import content_tokens

NodeKind = Literal["topic", "paper", "author", "venue", "method", "finding", "concept", "question"]


@dataclass
class Node:
    id: str
    label: str
    kind: NodeKind
    weight: float = 1.0
    detail: str = ""
    source_ids: list[str] = field(default_factory=list)
    meta: dict[str, Any] = field(default_factory=dict)


@dataclass
class Edge:
    source: str
    target: str
    relation: str
    weight: float = 1.0


@dataclass
class Graph:
    nodes: list[Node] = field(default_factory=list)
    edges: list[Edge] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "nodes": [n.__dict__ for n in self.nodes],
            "edges": [e.__dict__ for e in self.edges],
            "stats": {
                "nodes": len(self.nodes),
                "edges": len(self.edges),
                "by_kind": dict(Counter(n.kind for n in self.nodes)),
            },
        }


# Words that look topical but carry no discriminating signal in a title.
_NOISE = frozenset(
    "study studies analysis review research paper article report results using based effects "
    "effect role novel new approach method methods evidence data patients clinical trial "
    "systematic meta towards toward via investigation assessment evaluation".split()
)

_METHOD_TERMS = {
    "rct": "Randomised controlled trial", "randomised": "Randomised controlled trial",
    "randomized": "Randomised controlled trial", "cohort": "Cohort study",
    "case-control": "Case-control study", "cross-sectional": "Cross-sectional study",
    "meta-analysis": "Meta-analysis", "systematic": "Systematic review",
    "in vitro": "In vitro", "in vivo": "In vivo", "xenograft": "Xenograft model",
    "knockout": "Knockout model", "crispr": "CRISPR", "pcr": "PCR", "qpcr": "qPCR",
    "rna-seq": "RNA-seq", "scrna": "Single-cell RNA-seq", "western blot": "Western blot",
    "elisa": "ELISA", "flow cytometry": "Flow cytometry", "mass spectrometry": "Mass spectrometry",
    "immunohistochemistry": "Immunohistochemistry", "microscopy": "Microscopy",
    "simulation": "Simulation", "regression": "Regression modelling",
}


def _topic_terms(source: Source, limit: int = 4) -> tuple[list[str], bool]:
    """Topics for one source, and whether they came from a provider.

    Provider-assigned concepts (OpenAlex, Semantic Scholar) are real topical
    labels and are used as-is.  Title words are a weak fallback, so they are
    marked as such and only survive if several sources share them — otherwise
    the map fills with one-off fragments that connect nothing.
    """
    concepts = [c for c in (source.extra.get("concepts") or []) if c]
    if concepts:
        return [str(c) for c in concepts[:limit]], True
    words = [
        w for w in content_tokens(source.title)
        if w not in _NOISE and len(w) > 3
    ]
    return [w.title() for w in dict.fromkeys(words)][:8], False


def _methods_in(source: Source) -> list[str]:
    haystack = " ".join(
        filter(None, [source.title, source.abstract or "", source.extra.get("pub_types") or ""])
    ).lower()
    return sorted({label for term, label in _METHOD_TERMS.items() if term in haystack})


def build(
    sources: list[Source],
    *,
    answers: list[Answer] | None = None,
    question: str | None = None,
    max_authors_per_paper: int = 3,
) -> Graph:
    graph = Graph()
    seen: dict[str, Node] = {}

    def add_node(node_id: str, label: str, kind: NodeKind, **kw) -> Node:
        existing = seen.get(node_id)
        if existing:
            existing.weight += 1
            for sid in kw.get("source_ids", []):
                if sid not in existing.source_ids:
                    existing.source_ids.append(sid)
            return existing
        node = Node(id=node_id, label=label, kind=kind, **kw)
        seen[node_id] = node
        graph.nodes.append(node)
        return node

    def add_edge(a: str, b: str, relation: str) -> None:
        for edge in graph.edges:
            if edge.source == a and edge.target == b and edge.relation == relation:
                edge.weight += 1
                return
        graph.edges.append(Edge(source=a, target=b, relation=relation))

    if question:
        add_node("question", question[:90], "question", detail=question)

    topic_papers: defaultdict[str, list[str]] = defaultdict(list)

    # Weak (title-derived) terms must be shared by at least two sources to earn
    # a node; a term appearing once is a word, not a topic.
    weak_counts: Counter[str] = Counter()
    for source in sources:
        terms, from_provider = _topic_terms(source)
        if not from_provider:
            weak_counts.update({t.lower() for t in terms})

    for source in sources:
        paper_id = f"paper:{source.id}"
        add_node(
            paper_id,
            (source.title[:80] + "…") if len(source.title) > 80 else source.title,
            "paper",
            detail=source.title,
            source_ids=[source.id],
            meta={
                "year": source.year,
                "doi": source.doi,
                "url": source.url,
                "tier": source.quality.tier if source.quality else None,
                "peer_reviewed": source.is_peer_reviewed,
                "cited_by": source.cited_by_count,
            },
        )
        if question:
            add_edge("question", paper_id, "answered by")

        for author in source.authors[:max_authors_per_paper]:
            aid = f"author:{author.name.lower()}"
            add_node(aid, author.name, "author", source_ids=[source.id],
                     meta={"orcid": author.orcid, "affiliation": author.affiliation})
            add_edge(aid, paper_id, "authored")

        venue = source.container_title or source.site_name
        if venue:
            vid = f"venue:{venue.lower()}"
            add_node(vid, venue, "venue", source_ids=[source.id],
                     meta={"peer_reviewed": source.is_peer_reviewed})
            add_edge(paper_id, vid, "published in")

        terms, from_provider = _topic_terms(source)
        if not from_provider:
            terms = [t for t in terms if weak_counts[t.lower()] >= 2][:4]
        for term in terms:
            tid = f"topic:{term.lower()}"
            add_node(tid, term, "topic", source_ids=[source.id])
            add_edge(tid, paper_id, "covered by")
            topic_papers[tid].append(paper_id)

        for method in _methods_in(source):
            mid = f"method:{method.lower()}"
            add_node(mid, method, "method", source_ids=[source.id])
            add_edge(paper_id, mid, "uses")

    # Findings: only claims that actually survived verification become nodes.
    for answer in answers or []:
        for claim in answer.claims:
            if claim.status not in (Epistemic.VERIFIED, Epistemic.INTERPRETATION):
                continue
            fid = f"finding:{claim.id}"
            add_node(
                fid,
                (claim.text[:90] + "…") if len(claim.text) > 90 else claim.text,
                "finding",
                detail=claim.text,
                source_ids=[c.source_id for c in claim.citations],
                meta={"status": claim.status.value, "support": claim.support_score},
            )
            for citation in claim.citations:
                add_edge(f"paper:{citation.source_id}", fid, "supports")
            for contested in claim.contested_by:
                add_edge(f"paper:{contested}", fid, "disputes")

    # Topics that co-occur across papers are related; two shared papers is the floor.
    topic_ids = list(topic_papers)
    for i, a in enumerate(topic_ids):
        for b in topic_ids[i + 1 :]:
            shared = set(topic_papers[a]) & set(topic_papers[b])
            if len(shared) >= 2:
                add_edge(a, b, f"co-occur ({len(shared)} papers)")

    return graph


def neighbourhood(graph: Graph, node_id: str, *, depth: int = 1) -> Graph:
    """The sub-graph around one node — what 'click a node and explore it' returns."""
    keep = {node_id}
    frontier = {node_id}
    for _ in range(max(depth, 1)):
        nxt: set[str] = set()
        for edge in graph.edges:
            if edge.source in frontier:
                nxt.add(edge.target)
            if edge.target in frontier:
                nxt.add(edge.source)
        nxt -= keep
        keep |= nxt
        frontier = nxt
        if not frontier:
            break
    return Graph(
        nodes=[n for n in graph.nodes if n.id in keep],
        edges=[e for e in graph.edges if e.source in keep and e.target in keep],
    )
