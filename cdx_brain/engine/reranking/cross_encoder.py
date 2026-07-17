"""Cross-encoder + Combined Scoring rerankers (HMS v2)."""
from __future__ import annotations
import math, logging
from datetime import datetime, timezone
from typing import Any
from .base import RerankingStrategy
from ..registry import reranking_registry
from ..types import ScoredResult, MemoryTier

logger = logging.getLogger(__name__)

_RECENCY_ALPHA = 0.2
_TEMPORAL_ALPHA = 0.2
_PROOF_ALPHA = 0.1
_TIER_BOOST = {MemoryTier.SEMANTIC: 1.0, MemoryTier.EPISODIC: 0.9, MemoryTier.WORKING: 0.8}


@reranking_registry.register("cross_encoder")
class CrossEncoderReranker(RerankingStrategy):
    """Cross-encoder + combined scoring with memory tier boost."""
    name = "cross_encoder"

    def __init__(self, model_name="cross-encoder/ms-marco-MiniLM-L-6-v2",
                 recency_alpha=_RECENCY_ALPHA, temporal_alpha=_TEMPORAL_ALPHA,
                 proof_alpha=_PROOF_ALPHA):
        self._model_name = model_name
        self._model = None
        self._recency_alpha = recency_alpha
        self._temporal_alpha = temporal_alpha
        self._proof_alpha = proof_alpha

    def _lazy_load(self):
        if self._model:
            return True
        try:
            from sentence_transformers import CrossEncoder
            self._model = CrossEncoder(self._model_name)
            return True
        except ImportError:
            logger.warning("sentence-transformers not available")
            return False
        except Exception as e:
            logger.warning("CE load failed: %s", e)
            return False

    async def rerank(self, query: str, candidates: list, top_k: int = 8) -> list:
        if not candidates or not query:
            return candidates[:top_k]
        if not self._lazy_load():
            return candidates[:top_k]
        try:
            pairs = [(query, str(c.get("content", ""))[:512]) for c in candidates if c.get("content")]
            if not pairs:
                return candidates[:top_k]
            scores = self._model.predict(pairs)
            now = datetime.now(timezone.utc)
            scored = []
            for idx, ce_score in zip(range(len(pairs)), scores):
                c = candidates[idx]
                ce_norm = float(ce_score)
                recency = self._compute_recency(c, now)
                temporal = self._compute_temporal(c, now)
                proof = self._compute_proof(c)
                tier_val = self._get_tier_boost(c)
                recency_boost = 1.0 + self._recency_alpha * (recency - 0.5)
                temporal_boost = 1.0 + self._temporal_alpha * (temporal - 0.5)
                proof_boost = 1.0 + self._proof_alpha * (proof - 0.5)
                combined = ce_norm * recency_boost * temporal_boost * proof_boost * tier_val
                scored.append((combined, c))
            scored.sort(key=lambda x: x[0], reverse=True)
            return [c for _, c in scored[:top_k]]
        except Exception as e:
            logger.warning("reranking failed: %s", e)
            return candidates[:top_k]

    def _compute_recency(self, c: Any, now: datetime) -> float:
        ts = c.get("event_date") or c.get("metadata", {}).get("created_at")
        if not ts:
            return 0.5
        try:
            dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            days = (now - dt).total_seconds() / 86400
            return max(0.0, 1.0 - days / 365.0)
        except Exception:
            return 0.5

    def _compute_temporal(self, c: Any, now: datetime) -> float:
        ts = c.get("metadata", {}).get("time_window_start")
        if not ts:
            return 0.5
        try:
            dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
            prox = max(0.0, 1.0 - abs((now - dt).total_seconds()) / 86400)
            return min(1.0, prox * 2)
        except Exception:
            return 0.5

    def _compute_proof(self, c: Any) -> float:
        pc = c.get("metadata", {}).get("proof_count")
        if pc is None:
            return 0.5
        try:
            return min(1.0, math.log(int(pc) + 1) / 5.0)
        except Exception:
            return 0.5

    def _get_tier_boost(self, c: Any) -> float:
        tier = c.get("tier", MemoryTier.SEMANTIC)
        if isinstance(tier, int):
            try:
                tier = MemoryTier(tier)
            except ValueError:
                pass
        return _TIER_BOOST.get(tier, 1.0)


@reranking_registry.register("combined_scoring")
class CombinedScoringReranker(RerankingStrategy):
    """Signal-based scoring without CE model."""
    name = "combined_scoring"

    def __init__(self, recency_alpha=_RECENCY_ALPHA, temporal_alpha=_TEMPORAL_ALPHA, proof_alpha=_PROOF_ALPHA):
        self._recency_alpha = recency_alpha
        self._temporal_alpha = temporal_alpha
        self._proof_alpha = proof_alpha

    async def rerank(self, query: str, candidates: list, top_k: int = 8) -> list:
        if not candidates:
            return []
        now = datetime.now(timezone.utc)
        scored = []
        for c in candidates:
            base = c.get("score", 0.5)
            recency = 0.5
            ts = c.get("event_date")
            if ts:
                try:
                    dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
                    if dt.tzinfo is None:
                        dt = dt.replace(tzinfo=timezone.utc)
                    recency = max(0.0, 1.0 - (now - dt).total_seconds() / 86400 / 365.0)
                except Exception:
                    pass
            boost = 1.0 + self._recency_alpha * (recency - 0.5)
            tier = c.get("tier", MemoryTier.SEMANTIC)
            if isinstance(tier, int):
                try:
                    tier = MemoryTier(tier)
                except ValueError:
                    pass
            tier_boost = _TIER_BOOST.get(tier, 1.0)
            scored.append((base * boost * tier_boost, c))
        scored.sort(key=lambda x: x[0], reverse=True)
        return [c for _, c in scored[:top_k]]
