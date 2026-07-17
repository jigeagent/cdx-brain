"""Reranking ABC."""
from __future__ import annotations
from abc import ABC, abstractmethod
from typing import Any


class RerankingStrategy(ABC):
    @property
    @abstractmethod
    def name(self) -> str: ...

    @abstractmethod
    async def rerank(self, query: str, candidates: list[dict | Any], top_k: int = 8) -> list[dict | Any]: ...
