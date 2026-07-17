# -*- coding: utf-8 -*-
"""cdx-brain v2.1.0 --- HMS v2: tiered memory + real LLM + multi-agent + bugfixes."""
from __future__ import annotations
__version__ = "2.1.0"
from cdx_brain.entity import EntityResolver, Entity, EntityGraph
from cdx_brain.engine import (
    StrategyRegistry, SearchConfig, SearchPipeline, SearchModuleManager, SearchResult, DEFAULT_CONFIG,
    SearchTracer, SearchStep,
    RetrievalStrategy, GraphRetrievalStrategy,
    QueryRewritingStrategy, NoOpQueryRewriting, AliasExpansionRewriting,
    LLMQueryRewriting, LLMAnalysisRewriting,
    RerankingStrategy, PassthroughReranking, CrossEncoderReranker, CombinedScoringReranker,
    FusionStrategy, RRFFusion,
    ParallelRetrievalExecutor, GraphRetrieval, LinkExpansionRetrieval,
    CausalLinkStrategy, causal_registry, MemoryLinksCausal, LLMDrivenCausal, SessionExpansionCausal,
    RetrievalResult, MergedCandidate, ScoredResult, SearchTimings, QueryAnalysis,
    CausalNeighbor, CausalScore, CausalContext, MemoryTier,
    TagsMatch, TagGroup, filter_results_by_tags, filter_results_by_tag_groups,
    LLMClient, LLMConfig, HotMemoryRanker, MemoryCompactor,
    AgentMemoryCoordinator, EmbeddingCache,
    retrieval_registry, graph_retrieval_registry, fusion_registry,
    reranking_registry, query_rewriting_registry,
)
from cdx_brain.engine.retrieval import VectorRetrieval, FTS5Retrieval, TemporalRetrieval
from cdx_brain.vector.store import VectorStore
from cdx_brain.vector.embedding import compute_query_embedding, compute_trace_embedding
__all__ = [
    "__version__",
    "StrategyRegistry", "SearchConfig", "SearchPipeline", "SearchModuleManager", "SearchResult", "DEFAULT_CONFIG",
    "SearchTracer", "SearchStep",
    "RetrievalStrategy", "GraphRetrievalStrategy",
    "QueryRewritingStrategy", "NoOpQueryRewriting", "AliasExpansionRewriting", "LLMQueryRewriting", "LLMAnalysisRewriting",
    "RerankingStrategy", "PassthroughReranking", "CrossEncoderReranker", "CombinedScoringReranker",
    "FusionStrategy", "RRFFusion",
    "VectorRetrieval", "FTS5Retrieval", "TemporalRetrieval",
    "ParallelRetrievalExecutor", "GraphRetrieval", "LinkExpansionRetrieval",
    "CausalLinkStrategy", "causal_registry", "MemoryLinksCausal", "LLMDrivenCausal", "SessionExpansionCausal",
    "RetrievalResult", "MergedCandidate", "ScoredResult", "SearchTimings", "QueryAnalysis",
    "CausalNeighbor", "CausalScore", "CausalContext", "MemoryTier",
    "TagsMatch", "TagGroup", "filter_results_by_tags", "filter_results_by_tag_groups",
    "LLMClient", "LLMConfig", "HotMemoryRanker", "MemoryCompactor",
    "AgentMemoryCoordinator", "EmbeddingCache",
    "retrieval_registry", "graph_retrieval_registry", "fusion_registry",
    "reranking_registry", "query_rewriting_registry",
    "EntityResolver", "Entity", "EntityGraph",
    "VectorStore", "compute_query_embedding", "compute_trace_embedding", ]
