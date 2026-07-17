"""Causal link strategy ABC with registry (HMS v2)."""
from __future__ import annotations
from abc import ABC, abstractmethod
from typing import Any
from ..registry import StrategyRegistry
from ..types import CausalContext

causal_registry = StrategyRegistry()


class CausalLinkStrategy(ABC):
    """Abstract base for causal/contextual expansion strategies."""

    @property
    @abstractmethod
    def name(self) -> str: ...

    @abstractmethod
    async def expand(
        self, seed_ids: list[str], query: str = "",
        budget: int = 20, context: dict | None = None,
    ) -> CausalContext: ...
