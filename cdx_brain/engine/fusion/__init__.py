from __future__ import annotations
from abc import ABC, abstractmethod
from typing import Any
from ..registry import fusion_registry


class FusionStrategy(ABC):
    @abstractmethod
    def fuse(self, ranked_lists: list[list[Any]], k: int = 60, max_results: int = 16) -> list[Any]: ...


from .rrf import RRFFusion

__all__ = ["FusionStrategy", "RRFFusion"]
