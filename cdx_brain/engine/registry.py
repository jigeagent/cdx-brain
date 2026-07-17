"""Strategy registry with HMS-style decorator registration."""
from __future__ import annotations
import logging
from typing import Any, Type, Callable

logger = logging.getLogger(__name__)


class StrategyRegistry:
    """Generic registry for strategy classes."""

    def __init__(self):
        self._items: dict[str, Type] = {}

    def register(self, name: str) -> Callable[[Type], Type]:
        def decorator(cls: Type) -> Type:
            if name in self._items:
                logger.warning(f"Strategy {name!r} already registered, overwriting")
            self._items[name] = cls
            return cls
        return decorator

    def get(self, name: str) -> Type | None:
        return self._items.get(name)

    def create(self, name: str, **kwargs) -> Any:
        cls = self.get(name)
        if cls is None:
            raise KeyError(f"Unknown strategy: {name!r}")
        return cls(**kwargs)

    def list(self) -> list[str]:
        return list(self._items.keys())

    def __contains__(self, name: str) -> bool:
        return name in self._items


retrieval_registry = StrategyRegistry()
graph_retrieval_registry = StrategyRegistry()
fusion_registry = StrategyRegistry()
reranking_registry = StrategyRegistry()
query_rewriting_registry = StrategyRegistry()
