"""FTS5 retrieval stub."""
from __future__ import annotations
from .base import RetrievalStrategy
from ..registry import retrieval_registry
from ..types import RetrievalResult
from ..tags import TagsMatch, TagGroup


@retrieval_registry.register("fts5")
class FTS5Retrieval(RetrievalStrategy):
    name = "fts5"

    def __init__(self, conn=None):
        self._conn = conn

    async def retrieve(self, query: str, limit: int = 8, context: dict | None = None,
                       tags: list[str] | None = None, tags_match: TagsMatch = "any",
                       tag_groups: list[TagGroup] | None = None) -> list[RetrievalResult]:
        return []
