# -*- coding: utf-8 -*-
"""SearchModuleManager v2 with parallel retrieval, multi-hop causal, tier support."""
from __future__ import annotations
import asyncio, json, logging, os, time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from .fusion import FusionStrategy, RRFFusion
from .query_rewriting import QueryRewritingStrategy, NoOpQueryRewriting
from .reranking import RerankingStrategy, PassthroughReranking
from .causal import CausalLinkStrategy, causal_registry
from .retrieval import RetrievalStrategy
from .retrieval.parallel import ParallelRetrievalExecutor
from .registry import (
    retrieval_registry, graph_retrieval_registry,
    fusion_registry, reranking_registry, query_rewriting_registry,
)
from .tracer import SearchTracer
from .tags import TagsMatch, TagGroup, filter_results_by_tags, filter_results_by_tag_groups
from .types import RetrievalResult, MergedCandidate, ScoredResult, SearchTimings, CausalContext, MemoryTier
from .hot_memory import HotMemoryRanker
from .compactor import MemoryCompactor

logger = logging.getLogger(__name__)


@dataclass
class SearchConfig:
    """Configuration with memory tier support."""

    def __post_init__(self):
        """Validate configuration at creation time."""
        valid_retrievals = {"vector", "fts5", "temporal", "graph", "link_expansion"}
        for r in self.retrievals:
            if r not in valid_retrievals:
                raise ValueError(f"Unknown retrieval strategy: {r}")
        if self.retrieval_k <= 0:
            raise ValueError(f"retrieval_k must be positive, got {self.retrieval_k}")
        if self.max_results <= 0:
            raise ValueError(f"max_results must be positive, got {self.max_results}")
        if self.timeout_ms <= 0:
            raise ValueError(f"timeout_ms must be positive, got {self.timeout_ms}")

    retrieval_strategy: str = "vector"
    graph_retrieval_strategy: str = "graph"
    fusion_strategy: str = "rrf"
    reranking_strategy: str = ""
    query_rewriting_strategy: str = ""
    causal_strategy: str = ""
    retrievals: list[str] = field(default_factory=lambda: ["vector", "fts5", "temporal"])
    retrieval_k: int = 8
    fusion_k: int = 60
    max_results: int = 8
    timeout_ms: int = 5000
    tracing: bool = False
    trace_log_path: str = ""
    reranking_top_k: int = 8
    parallel_retrieval: bool = True
    retrieval_params: dict = field(default_factory=dict)
    fusion_params: dict = field(default_factory=dict)
    reranking_params: dict = field(default_factory=dict)
    query_rewriting_params: dict = field(default_factory=dict)
    causal_params: dict = field(default_factory=dict)
    tags: list[str] = field(default_factory=list)
    tags_match: TagsMatch = "any"
    tag_groups: list[TagGroup] = field(default_factory=list)
    memory_tiers: list[str] = field(default_factory=lambda: ["working", "episodic", "semantic"])


class SearchResult:
    """Final search result."""
    def __init__(self, items: list | None = None, trace: Any = None,
                 raw_results: dict | None = None, timings: SearchTimings | None = None):
        self.items = items or []
        self.trace = trace
        self.raw_results = raw_results
        self.timings = timings or SearchTimings()


class SearchModuleManager:
    """HMS v2 orchestrator with parallel retrieval and multi-hop causal."""

    def __init__(self, config: SearchConfig | None = None):
        self._config = config or SearchConfig()
        self._retrieval_strategies: dict[str, RetrievalStrategy] = {}
        self._graph_strategy: Any = None
        self._fusion_strategy: FusionStrategy | None = None
        self._reranking_strategy: RerankingStrategy | None = None
        self._rewriting_strategy: QueryRewritingStrategy | None = None
        self._causal_strategy: CausalLinkStrategy | None = None
        self._hot_memory: HotMemoryRanker = HotMemoryRanker()
        self._compactor: MemoryCompactor | None = None

    @property
    def config(self) -> SearchConfig:
        return self._config

    def set_config(self, config: SearchConfig) -> None:
        self._config = config
        self._retrieval_strategies.clear()
        self._fusion_strategy = None
        self._reranking_strategy = None
        self._rewriting_strategy = None
        self._causal_strategy = None

    def get_retrieval(self, name: str) -> RetrievalStrategy:
        if name not in self._retrieval_strategies:
            params = self._config.retrieval_params.get(name, {})
            self._retrieval_strategies[name] = retrieval_registry.create(name, **params)
        return self._retrieval_strategies[name]

    def get_fusion(self) -> FusionStrategy:
        if self._fusion_strategy is None:
            params = self._config.fusion_params.get(self._config.fusion_strategy, {})
            self._fusion_strategy = fusion_registry.create(self._config.fusion_strategy, **params)
        return self._fusion_strategy

    def get_reranking(self) -> RerankingStrategy:
        if self._reranking_strategy is None:
            if not self._config.reranking_strategy:
                return PassthroughReranking()
            params = self._config.reranking_params.get(self._config.reranking_strategy, {})
            self._reranking_strategy = reranking_registry.create(self._config.reranking_strategy, **params)
        return self._reranking_strategy

    def get_causal(self) -> CausalLinkStrategy | None:
        if self._causal_strategy is None:
            if not self._config.causal_strategy:
                return None
            params = self._config.causal_params.get(self._config.causal_strategy, {})
            self._causal_strategy = causal_registry.create(self._config.causal_strategy, **params)
        return self._causal_strategy

    def get_rewriting(self) -> QueryRewritingStrategy:
        if self._rewriting_strategy is None:
            if not self._config.query_rewriting_strategy:
                return NoOpQueryRewriting()
            params = self._config.query_rewriting_params.get(self._config.query_rewriting_strategy, {})
            self._rewriting_strategy = query_rewriting_registry.create(
                self._config.query_rewriting_strategy, **params
            )
        return self._rewriting_strategy

    async def execute(self, query: str, context: dict | None = None) -> SearchResult:
        t_start = time.monotonic()
        tracer = SearchTracer() if self._config.tracing else None

        if tracer:
            tracer.step("start", input=query)

        # Step 1: Query Rewriting
        rewriting = self.get_rewriting()
        rewritten = await rewriting.rewrite(query)
        if tracer:
            tracer.step("rewriting", input=query, output=rewritten)
        queries = rewritten or [query]
        primary = queries[0]

        # Step 2: Parallel Retrieval
        selected_names = self._config.retrievals or ["vector", "fts5", "temporal"]
        strategies = {}
        for name in selected_names:
            try:
                strategies[name] = self.get_retrieval(name)
            except KeyError:
                logger.debug("retrieval strategy %s not registered", name)
        all_candidates: list[RetrievalResult | dict] = []

        if self._config.parallel_retrieval and len(strategies) > 1:
            executor = ParallelRetrievalExecutor(strategies)
            raw_results = await executor.execute_all(
                primary, limit=self._config.retrieval_k, context=context,
                tags=self._config.tags, tags_match=self._config.tags_match,
                tag_groups=self._config.tag_groups,
            )
            for name, results in raw_results.items():
                all_candidates.extend(results)
                if tracer:
                    tracer.step(f"retrieval:{name}", output=len(results))
        else:
            for name, strategy in strategies.items():
                try:
                    results = await strategy.retrieve(
                        primary, limit=self._config.retrieval_k, context=context,
                        tags=self._config.tags, tags_match=self._config.tags_match,
                        tag_groups=self._config.tag_groups,
                    )
                    all_candidates.extend(results)
                    if tracer:
                        tracer.step(f"retrieval:{name}", output=len(results))
                except Exception as e:
                    logger.debug("retrieval %s failed: %s", name, e)

        # Graph retrieval
        graph_name = self._config.graph_retrieval_strategy
        if graph_name and graph_name in graph_retrieval_registry:
            try:
                graph_strat = graph_retrieval_registry.create(graph_name)
                graph_results = await graph_strat.retrieve(
                    primary, limit=self._config.retrieval_k, context=context,
                )
                all_candidates.extend(graph_results)
                if tracer:
                    tracer.step(f"graph:{graph_name}", output=len(graph_results))
            except Exception as e:
                logger.debug("graph retrieval failed: %s", e)

        # Causal expansion
        causal = self.get_causal()
        if causal:
            try:
                seed_ids = list({r.get("id", "") for r in all_candidates if r.get("id")})
                causal_ctx = await causal.expand(
                    seed_ids, query=primary, budget=self._config.retrieval_k, context=context
                )
                if causal_ctx and causal_ctx.neighbors:
                    all_candidates.extend(causal_ctx.to_retrieval_results())
            except Exception as e:
                logger.debug("causal expansion failed: %s", e)

        t_retrieval = time.monotonic()
        retrieval_ms = (t_retrieval - t_start) * 1000

        if tracer:
            tracer.step("retrieval", input=len(strategies), output=len(all_candidates))

        # Tag filtering
        if self._config.tags or self._config.tag_groups:
            all_candidates = filter_results_by_tags(
                all_candidates, self._config.tags, self._config.tags_match
            )
            all_candidates = filter_results_by_tag_groups(all_candidates, self._config.tag_groups)

        # Hot memory boost
        all_candidates = self._hot_memory.apply_hot_boost(all_candidates)

        # Step 3: Fusion
        fused: list[MergedCandidate] = []
        if all_candidates:
            fusion = self.get_fusion()
            by_source: dict[str, list] = {}
            for item in all_candidates:
                src = item.get("source", "unknown")
                by_source.setdefault(src, []).append(item)
            ranked_lists = list(by_source.values())
            fused = fusion.fuse(ranked_lists, k=self._config.fusion_k, max_results=self._config.max_results * 2)

        t_fusion = time.monotonic()
        fusion_ms = (t_fusion - t_retrieval) * 1000

        if tracer:
            tracer.step("fusion", input=len(all_candidates), output=len(fused))

        # Step 4: Reranking
        if fused:
            reranking = self.get_reranking()
            if not isinstance(reranking, PassthroughReranking):
                try:
                    reranked = await reranking.rerank(query, fused, top_k=self._config.reranking_top_k)
                    fused = reranked
                except Exception as e:
                    logger.debug("reranking failed: %s", e)

        t_rerank = time.monotonic()
        reranking_ms = (t_rerank - t_fusion) * 1000

        if tracer:
            tracer.step("reranking", input=len(fused), output=len(fused))

        final = fused[:self._config.max_results]

        # Record access for hot memory
        for item in final:
            self._hot_memory.record_access(item.get("id", ""))

        if tracer:
            tracer.step("result", output=len(final))

        trace_data = tracer.serialize() if tracer else None
        if trace_data and self._config.trace_log_path:
            try:
                p = Path(self._config.trace_log_path).expanduser()
                p.parent.mkdir(parents=True, exist_ok=True)
                with open(p, "a", encoding="utf-8") as f:
                    f.write(json.dumps(trace_data, ensure_ascii=False) + "\n")
            except OSError as e:
                logger.warning("trace log failed: %s", e)

        total_ms = (time.monotonic() - t_start) * 1000
        timings = SearchTimings(
            retrieval_ms=retrieval_ms, fusion_ms=fusion_ms,
            reranking_ms=reranking_ms, total_ms=total_ms,
        )
        return SearchResult(items=final, trace=trace_data, timings=timings)

    def run_compaction(self) -> dict[str, int]:
        """Run memory compaction if available."""
        if self._compactor:
            return self._compactor.run_all()
        return {}


class SearchPipeline:
    """Backward-compatible wrapper."""

    def __init__(self, config: SearchConfig | None = None):
        self._config = config or SearchConfig()
        self._manager = SearchModuleManager(self._config)

    def register_retrieval(self, name: str, strategy: Any) -> None:
        pass

    def set_fusion(self, fn: Callable) -> None:
        pass

    def set_rewriting(self, strategy: Any) -> None:
        pass

    def set_reranking(self, strategy: Any) -> None:
        pass

    async def execute(self, query: str, context: dict | None = None) -> SearchResult:
        return await self._manager.execute(query, context)


DEFAULT_CONFIG = SearchConfig(
    retrievals=["vector", "fts5", "temporal"],
    retrieval_k=8, fusion_k=60, max_results=8, timeout_ms=5000,
    tracing=False, reranking_top_k=8, parallel_retrieval=True,
    trace_log_path=os.path.expanduser("~/.cdx-brain/data/search_traces.jsonl"),
)
