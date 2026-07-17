"""Query rewriting ABC."""
from __future__ import annotations
from abc import ABC, abstractmethod
from ..types import QueryAnalysis


class QueryRewritingStrategy(ABC):
    @property
    @abstractmethod
    def name(self) -> str: ...

    @abstractmethod
    async def rewrite(self, query: str) -> list[str]: ...

    async def analyze(self, query: str) -> QueryAnalysis:
        return QueryAnalysis(query=query, rewritten_query=query)
