"""Parallel retrieval executor (O4)."""
from __future__ import annotations
import asyncio, logging
from typing import Any
from .base import RetrievalStrategy
from ..types import RetrievalResult
from ..tags import TagsMatch, TagGroup

logger = logging.getLogger(__name__)


class ParallelRetrievalExecutor:
    """Execute multiple retrieval strategies in parallel with error isolation."""

    def __init__(self, strategies: dict[str, RetrievalStrategy], concurrency: int = 4):
        self._strategies = strategies
        self._sem = asyncio.Semaphore(concurrency)

    async def execute_all(
        self, query: str, limit: int = 8, context: dict | None = None,
        tags: list[str] | None = None, tags_match: TagsMatch = "any",
        tag_groups: list[TagGroup] | None = None,
    ) -> dict[str, list[RetrievalResult]]:
        async def run_one(name: str, strategy: RetrievalStrategy) -> tuple[str, list[RetrievalResult]]:
            async with self._sem:
                try:
                    results = await strategy.retrieve(
                        query, limit=limit, context=context,
                        tags=tags, tags_match=tags_match, tag_groups=tag_groups,
                    )
                    return name, results
                except Exception as e:
                    logger.warning("retrieval %s failed: %s", name, e)
                    return name, []

        tasks = [run_one(n, s) for n, s in self._strategies.items()]
        outcomes = await asyncio.gather(*tasks, return_exceptions=True)
        results = {}
        for outcome in outcomes:
            if isinstance(outcome, tuple):
                results[outcome[0]] = outcome[1]
            elif isinstance(outcome, Exception):
                logger.debug("parallel retrieval error: %s", outcome)
        return results
