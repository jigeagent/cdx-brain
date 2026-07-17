"""No-op query rewriting."""
from __future__ import annotations
from .base import QueryRewritingStrategy
from ..registry import query_rewriting_registry


@query_rewriting_registry.register("noop")
class NoOpQueryRewriting(QueryRewritingStrategy):
    name = "noop"

    async def rewrite(self, query: str) -> list[str]:
        return [query] if query else []
