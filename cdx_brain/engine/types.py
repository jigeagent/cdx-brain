"""Structured result types + MemoryTier (HMS v2)."""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, Optional
from enum import IntEnum


class MemoryTier(IntEnum):
    """Three-tier memory hierarchy (HMS v2)."""
    WORKING = 1    # Current session, TTL=session
    EPISODIC = 2   # Recent interactions, TTL=7 days
    SEMANTIC = 3   # Persistent knowledge graph, TTL=permanent


@dataclass
class RetrievalResult:
    """Result from a single retrieval method."""
    id: str = ""
    content: str = ""
    score: float = 0.0
    source: str = ""
    fact_type: str = ""
    metadata: dict = field(default_factory=dict)
    event_date: str | None = None
    tier: MemoryTier = MemoryTier.SEMANTIC

    def get(self, key: str, default: Any = None) -> Any:
        return getattr(self, key, default)

    def __getitem__(self, key: str) -> Any:
        try:
            return getattr(self, key)
        except AttributeError:
            raise KeyError(key)

    def __contains__(self, key: str) -> bool:
        return hasattr(self, key)

    def to_dict(self) -> dict:
        d = {f.name: getattr(self, f.name) for f in self.__dataclass_fields__.values()}
        d["tier"] = int(self.tier)
        return d


@dataclass
class MergedCandidate:
    """RRF-fused result with source tracking."""
    id: str = ""
    content: str = ""
    rrf_score: float = 0.0
    sources: list[str] = field(default_factory=list)
    ranks: dict[str, int] = field(default_factory=dict)
    metadata: dict = field(default_factory=dict)
    tier: MemoryTier = MemoryTier.SEMANTIC

    def get(self, key: str, default: Any = None) -> Any:
        return getattr(self, key, default)

    def __getitem__(self, key: str) -> Any:
        try:
            return getattr(self, key)
        except AttributeError:
            raise KeyError(key)


@dataclass
class ScoredResult:
    """Reranked result with combined scores."""
    id: str = ""
    content: str = ""
    ce_score: float = 0.0
    combined_score: float = 0.0
    source: str = ""
    ranks: dict[str, int] = field(default_factory=dict)
    metadata: dict = field(default_factory=dict)
    tier: MemoryTier = MemoryTier.SEMANTIC

    def get(self, key: str, default: Any = None) -> Any:
        return getattr(self, key, default)

    def __getitem__(self, key: str) -> Any:
        try:
            return getattr(self, key)
        except AttributeError:
            raise KeyError(key)


@dataclass
class SearchTimings:
    """Performance tracking."""
    retrieval_ms: float = 0.0
    fusion_ms: float = 0.0
    reranking_ms: float = 0.0
    total_ms: float = 0.0


@dataclass
class QueryAnalysis:
    """Structured query analysis result."""
    query: str = ""
    rewritten_query: str = ""
    expanded_aliases: list[str] = field(default_factory=list)
    needs_expansion: bool = False
    needs_time_window: bool = False
    time_window_start: str | None = None
    time_window_end: str | None = None

    def get(self, key: str, default: Any = None) -> Any:
        return getattr(self, key, default)


@dataclass
class CausalNeighbor:
    """Individual neighbor with link info."""
    neighbor_id: str = ""
    link_weight: float = 0.0
    link_type: str = ""
    provenance: dict | None = None

    def get(self, key: str, default: Any = None) -> Any:
        return getattr(self, key, default)

    def __getitem__(self, key: str) -> Any:
        try:
            return getattr(self, key)
        except AttributeError:
            raise KeyError(key)

    def to_retrieval_result(self) -> RetrievalResult:
        return RetrievalResult(
            id=self.neighbor_id, content=self.neighbor_id,
            score=self.link_weight, source="causal",
            fact_type=f"causal_{self.link_type or 'link'}",
            metadata={"link_type": self.link_type, "link_weight": self.link_weight},
        )


@dataclass
class CausalScore:
    """Scoring for causal expansion."""
    base_score: float = 0.0
    link_boost: float = 0.0
    final_score: float = 0.0


@dataclass
class CausalContext:
    """Full causal expansion context."""
    query: str = ""
    seed_ids: list[str] = field(default_factory=list)
    depth: int = 1
    neighbors: list[CausalNeighbor] = field(default_factory=list)

    def to_retrieval_results(self) -> list[RetrievalResult]:
        return [n.to_retrieval_result() for n in self.neighbors]
