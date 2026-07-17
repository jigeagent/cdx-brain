"""Passthrough reranking."""
from __future__ import annotations
from .base import RerankingStrategy
from ..registry import reranking_registry


@reranking_registry.register("passthrough")
class PassthroughReranking(RerankingStrategy):
    name = "passthrough"

    async def rerank(self, query: str, candidates: list, top_k: int = 8) -> list:
        return candidates[:top_k]
