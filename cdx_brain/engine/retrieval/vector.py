"""Vector retrieval stub."""
from __future__ import annotations
from .base import RetrievalStrategy
from ..registry import retrieval_registry
from ..types import RetrievalResult
from ..tags import TagsMatch, TagGroup


@retrieval_registry.register("vector")
class VectorRetrieval(RetrievalStrategy):
    name = "vector"

    def __init__(self, store=None):
        self._store = store

    async def retrieve(self, query: str, limit: int = 8, context: dict | None = None,
                       tags: list[str] | None = None, tags_match: TagsMatch = "any",
                       tag_groups: list[TagGroup] | None = None) -> list[RetrievalResult]:
        return []
