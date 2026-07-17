"""Causal retrieval implementations with multi-hop + LLM support (HMS v2)."""
from __future__ import annotations
import asyncio
import logging
from typing import Any
from .strategies import CausalLinkStrategy, causal_registry
from ..types import CausalNeighbor, CausalContext
from ..llm.client import LLMClient, LLMConfig

logger = logging.getLogger(__name__)


@causal_registry.register("memory_links")
class MemoryLinksCausal(CausalLinkStrategy):
    """Multi-hop causal expansion via entity_edges (depth=N)."""
    name = "memory_links"

    def __init__(self, graph=None, max_depth: int = 3, decay: float = 0.5):
        self._graph = graph
        self._max_depth = max_depth
        self._decay = decay

    async def expand(
        self, seed_ids: list[str], query: str = "",
        budget: int = 20, context: dict | None = None,
    ) -> CausalContext:
        ctx = CausalContext(query=query, seed_ids=seed_ids, depth=self._max_depth)
        if not self._graph or not seed_ids:
            return ctx
        loop = asyncio.get_running_loop()

        async def _run_sql(sql: str, params: tuple) -> list:
            return await loop.run_in_executor(
                None, lambda: self._graph._conn.execute(sql, params).fetchall()
            )

        visited: set[str] = set(seed_ids)
        frontier: list[tuple[str, float, int]] = [(sid, 1.0, 0) for sid in seed_ids]
        results: dict[str, tuple[float, str, str, dict]] = {}

        while frontier and len(results) < budget:
            sid, weight, depth = frontier.pop(0)
            if depth >= self._max_depth:
                continue
            try:
                rows = await _run_sql(
                    "SELECT target, relation, weight FROM entity_edges "
                    "WHERE source = ? ORDER BY weight DESC LIMIT ?",
                    (sid, max(budget // len(seed_ids), 1)),
                )
                # Batch fetch names for new targets
                new_targets = [r[0] for r in rows if r[0] not in visited]
                if new_targets:
                    placeholders = ",".join("?" for _ in new_targets)
                    name_rows = await _run_sql(
                        f"SELECT id, name FROM entities WHERE id IN ({placeholders})",
                        tuple(new_targets),
                    )
                    name_map = {r[0]: r[1] for r in name_rows}

                for target, relation, edge_w in rows:
                    if target in visited:
                        continue
                    visited.add(target)
                    decayed = weight * edge_w * (self._decay ** depth)
                    if target not in results or decayed > results[target][0]:
                        name = name_map.get(target, target) if new_targets else target
                        results[target] = (decayed, relation, name, {"seed": sid, "depth": depth})
                        frontier.append((target, decayed, depth + 1))
            except Exception as e:
                logger.debug("causal expand error: %s", e)

        for tid, (score, rel, name, prov) in results.items():
            ctx.neighbors.append(CausalNeighbor(
                neighbor_id=tid, link_weight=score,
                link_type=rel, provenance=prov,
            ))
        return ctx


@causal_registry.register("llm_driven")
class LLMDrivenCausal(CausalLinkStrategy):
    """LLM-driven causal chain inference (O1: real LLM)."""
    name = "llm_driven"

    def __init__(self, llm_client: LLMClient | None = None, llm_config: LLMConfig | None = None):
        self._client = llm_client or (LLMClient(llm_config) if llm_config else None)

    async def expand(
        self, seed_ids: list[str], query: str = "",
        budget: int = 20, context: dict | None = None,
    ) -> CausalContext:
        ctx = CausalContext(query=query, seed_ids=seed_ids, depth=1)
        if not self._client or not seed_ids:
            return ctx
        ctx_text = (context or {}).get("text", "")
        try:
            relations = await self._client.infer_causal_chain(seed_ids, ctx_text)
            for rel in relations[:budget]:
                ctx.neighbors.append(CausalNeighbor(
                    neighbor_id=rel.get("target", rel.get("source", "unknown")),
                    link_weight=rel.get("confidence", 0.5),
                    link_type=rel.get("relation", "correlates"),
                    provenance={"source": rel.get("source"), "rationale": rel.get("rationale", "")},
                ))
        except Exception as e:
            logger.warning("LLM causal failed: %s", e)
        return ctx


@causal_registry.register("session_expansion")
class SessionExpansionCausal(CausalLinkStrategy):
    """Expand from session context."""
    name = "session_expansion"

    def __init__(self, trace_repo=None, session_lookback: int = 5):
        self._repo = trace_repo
        self._lookback = session_lookback

    async def expand(
        self, seed_ids: list[str], query: str = "",
        budget: int = 20, context: dict | None = None,
    ) -> CausalContext:
        ctx = CausalContext(query=query, seed_ids=seed_ids, depth=1)
        if not self._repo:
            return ctx
        try:
            recent = self._repo.list_recent(limit=self._lookback)
        except Exception:
            return ctx
        count = 0
        for t in recent:
            if count >= budget:
                break
            user_text = t.user_content or ""
            assistant_text = t.assistant_content or ""
            text = (user_text + " " + assistant_text)[:200] if (user_text or assistant_text) else ""
            ctx.neighbors.append(CausalNeighbor(
                neighbor_id=t.id, link_weight=0.5,
                link_type="session_context",
                provenance={"session_id": t.session_id, "text": text},
            ))
            count += 1
        return ctx
