"""LLM-powered query rewriting with real API calls (O1)."""
from __future__ import annotations
import json, logging
from typing import Any
from .base import QueryRewritingStrategy
from ..registry import query_rewriting_registry
from ..types import QueryAnalysis
from ..llm.client import LLMClient, LLMConfig

logger = logging.getLogger(__name__)


@query_rewriting_registry.register("llm")
class LLMQueryRewriting(QueryRewritingStrategy):
    """LLM query rewriting with real API calls."""
    name = "llm_rewrite"

    def __init__(self, api_url="", api_key="", model="", llm_client: LLMClient | None = None):
        self._client = llm_client

    async def rewrite(self, query: str) -> list[str]:
        if not query:
            return []
        if not self._client:
            return [query]
        try:
            prompt = f"Generate 2-3 alternative phrasings for this search query. Return as JSON array of strings. Query: {query}"
            messages = [
                {"role": "system", "content": "Return ONLY a JSON array of query strings."},
                {"role": "user", "content": prompt},
            ]
            result = await self._client.chat_json(messages, temperature=0.3, max_tokens=300)
            alts = result if isinstance(result, list) else []
            return [query] + [a for a in alts if isinstance(a, str) and a != query]
        except Exception as e:
            logger.debug("LLM rewrite failed: %s", e)
            return [query]


@query_rewriting_registry.register("llm_analysis")
class LLMAnalysisRewriting(QueryRewritingStrategy):
    """HMS-style analysis: aliases + time window + optimization."""
    name = "llm_analysis"

    def __init__(self, api_url="", api_key="", model="", llm_client: LLMClient | None = None):
        self._client = llm_client or LLMClient()

    async def rewrite(self, query: str) -> list[str]:
        analysis = await self.analyze(query)
        results = [analysis.rewritten_query or query]
        if analysis.expanded_aliases:
            results.extend(analysis.expanded_aliases)
        return results

    async def analyze(self, query: str) -> QueryAnalysis:
        if not query or not self._client:
            return QueryAnalysis(query=query, rewritten_query=query)
        try:
            result = await self._client.analyze_query(query)
            return QueryAnalysis(
                query=query,
                rewritten_query=result.get("rewritten_query", query),
                expanded_aliases=result.get("aliases", []),
                needs_expansion=bool(result.get("aliases", [])),
                needs_time_window=result.get("needs_time_window", False),
                time_window_start=result.get("time_window_start"),
                time_window_end=result.get("time_window_end"),
            )
        except Exception as e:
            logger.debug("LLM analysis failed: %s", e)
            return QueryAnalysis(query=query, rewritten_query=query)
