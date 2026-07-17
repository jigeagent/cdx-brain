"""Graph retrieval ABC."""
from __future__ import annotations
from abc import ABC, abstractmethod
from typing import Any
from ..types import RetrievalResult


class GraphRetrievalStrategy(ABC):
    @property
    @abstractmethod
    def name(self) -> str: ...

    @abstractmethod
    async def retrieve(self, query: str, limit: int = 8, context: dict | None = None,
                       tags: list[str] | None = None, tags_match: str = "any",
                       tag_groups: list | None = None) -> list[RetrievalResult]: ...
