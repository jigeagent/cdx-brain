"""Reciprocal Rank Fusion."""
from __future__ import annotations
import logging
from typing import Any
from . import FusionStrategy
from ..registry import fusion_registry
from ..types import MergedCandidate

logger = logging.getLogger(__name__)


@fusion_registry.register("rrf")
class RRFFusion(FusionStrategy):
    name = "rrf"

    def fuse(self, ranked_lists: list[list[Any]], k: int = 60, max_results: int = 16) -> list[Any]:
        if not ranked_lists:
            return []
        rrf_scores: dict[str, dict] = {}
        for rank_list in ranked_lists:
            for rank, item in enumerate(rank_list):
                item_id = item.get("id", str(id(item)))
                if item_id not in rrf_scores:
                    rrf_scores[item_id] = {
                        "score": 0.0, "sources": [], "ranks": {},
                        "content": item.get("content", ""),
                        "metadata": item.get("metadata", {}),
                    }
                rrf_scores[item_id]["score"] += 1.0 / (k + rank + 1)
                rrf_scores[item_id]["sources"].append(item.get("source", "unknown"))
                rrf_scores[item_id]["ranks"][item.get("source", "unknown")] = rank + 1

        sorted_items = sorted(rrf_scores.items(), key=lambda x: x[1]["score"], reverse=True)
        results = []
        for item_id, data in sorted_items[:max_results]:
            results.append(MergedCandidate(
                id=item_id, content=data["content"],
                rrf_score=data["score"],
                sources=data["sources"],
                ranks=data["ranks"],
                metadata=data["metadata"],
            ))
        return results
