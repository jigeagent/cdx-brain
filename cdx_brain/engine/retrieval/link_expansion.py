"""Link expansion retrieval (entity + semantic + causal links)."""
from __future__ import annotations
import logging
from typing import Any
from .graph_base import GraphRetrievalStrategy
from ..registry import graph_retrieval_registry
from ..types import RetrievalResult

logger = logging.getLogger(__name__)


@graph_retrieval_registry.register("link_expansion")
class LinkExpansionRetrieval(GraphRetrievalStrategy):
    name = "link_expansion"

    def __init__(self, resolver=None, graph=None,
                 entity_weight=1.0, semantic_weight=0.8, causal_weight=1.2):
        self._resolver = resolver
        self._graph = graph
        self._entity_weight = entity_weight
        self._semantic_weight = semantic_weight
        self._causal_weight = causal_weight

    async def retrieve(self, query: str, limit: int = 8, context: dict | None = None,
                       tags: list[str] | None = None, tags_match: str = "any",
                       tag_groups: list | None = None) -> list[RetrievalResult]:
        if not self._resolver or not self._graph:
            return []
        entities = self._resolver.extract_ids(query)
        if not entities:
            return []
        seed_ids = []
        for name in entities:
            eid = self._graph.get_entity_id(name)
            seed_ids.append(eid if eid else self._graph.get_or_create_entity(name))
        if not seed_ids:
            return []
        results = []
        results.extend(self._expand_entity_links(seed_ids, limit))
        results.extend(self._expand_semantic_links(seed_ids, limit))
        results.extend(self._expand_causal_links(seed_ids, limit))
        seen = {}
        for r in results:
            if r.id not in seen or r.score > seen[r.id].score:
                seen[r.id] = r
        sorted_r = sorted(seen.values(), key=lambda x: x.score, reverse=True)
        return sorted_r[:limit]

    def _expand_entity_links(self, seed_ids: list[str], limit: int) -> list[RetrievalResult]:
        results = []
        for eid in seed_ids:
            connected = self._graph.get_connected(eid, max_results=max(limit // len(seed_ids), 1))
            for item in connected:
                results.append(RetrievalResult(
                    id=item.get("id", ""), content=item.get("name", ""),
                    score=item.get("weight", 1.0) * self._entity_weight,
                    source="link_expansion", fact_type="entity_link",
                    metadata={"relation": item.get("relation", ""), "seed": eid},
                ))
        return results

    def _expand_semantic_links(self, seed_ids: list[str], limit: int) -> list[RetrievalResult]:
        results = []
        for eid in seed_ids:
            try:
                rows = self._graph._conn.execute(
                    "SELECT target_id, similarity FROM semantic_links WHERE source_id = ? "
                    "ORDER BY similarity DESC LIMIT ?",
                    (eid, max(limit // len(seed_ids), 1)),
                ).fetchall()
                for tid, sim in rows:
                    nr = self._graph._conn.execute(
                        "SELECT name FROM entities WHERE id = ?", (tid,)
                    ).fetchone()
                    name = nr[0] if nr else tid
                    results.append(RetrievalResult(
                        id=tid, content=name, score=sim * self._semantic_weight,
                        source="link_expansion", fact_type="semantic_link",
                        metadata={"seed": eid, "similarity": sim},
                    ))
            except Exception:
                pass
        return results

    def _expand_causal_links(self, seed_ids: list[str], limit: int) -> list[RetrievalResult]:
        results = []
        for eid in seed_ids:
            try:
                rows = self._graph._conn.execute(
                    "SELECT target_id, weight, link_type FROM memory_links "
                    "WHERE source_id = ? ORDER BY weight DESC LIMIT ?",
                    (eid, max(limit // len(seed_ids), 1)),
                ).fetchall()
                for tid, wgt, lt in rows:
                    nr = self._graph._conn.execute(
                        "SELECT name FROM entities WHERE id = ?", (tid,)
                    ).fetchone()
                    name = nr[0] if nr else tid
                    results.append(RetrievalResult(
                        id=tid, content=name, score=wgt * self._causal_weight,
                        source="link_expansion", fact_type=f"causal_{lt or 'link'}",
                        metadata={"seed": eid, "link_type": lt},
                    ))
            except Exception:
                pass
        return results
