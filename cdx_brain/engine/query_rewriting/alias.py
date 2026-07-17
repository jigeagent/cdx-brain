"""Alias expansion using LLM."""
from __future__ import annotations
from .base import QueryRewritingStrategy
from ..registry import query_rewriting_registry


@query_rewriting_registry.register("alias_expansion")
class AliasExpansionRewriting(QueryRewritingStrategy):
    name = "alias_expansion"

    def __init__(self, llm_client=None):
        self._client = llm_client

    async def rewrite(self, query: str) -> list[str]:
        return [query] if query else []
