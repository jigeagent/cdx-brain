"""Graph retrieval via EntityGraph."""
from __future__ import annotations
from .graph_base import GraphRetrievalStrategy
from ..registry import graph_retrieval_registry
from ..types import RetrievalResult


@graph_retrieval_registry.register("graph")
class GraphRetrieval(GraphRetrievalStrategy):
    name = "graph"

    def __init__(self, resolver=None, graph=None):
        self._resolver = resolver
        self._graph = graph

    async def retrieve(self, query: str, limit: int = 8, context: dict | None = None,
                       tags: list[str] | None = None, tags_match: str = "any",
                       tag_groups: list | None = None) -> list[RetrievalResult]:
        return []
