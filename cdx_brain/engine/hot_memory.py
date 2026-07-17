"""Hot memory ranking based on recency + frequency (O5)."""
from __future__ import annotations
import time
from collections import defaultdict
from typing import Any


class HotMemoryRanker:
    """Rank memories by recency and access frequency."""

    def __init__(self, decay_hours: float = 24.0):
        self._access_log: dict[str, list[float]] = defaultdict(list)
        self._decay_seconds = decay_hours * 3600

    def record_access(self, memory_id: str) -> None:
        self._access_log[memory_id].append(time.time())

    def get_hot_score(self, memory_id: str, now: float | None = None) -> float:
        if memory_id not in self._access_log:
            return 0.0
        now = now or time.time()
        timestamps = self._access_log[memory_id]
        # Prune old entries
        cutoff = now - self._decay_seconds
        recent = [t for t in timestamps if t > cutoff]
        self._access_log[memory_id] = recent
        if not recent:
            return 0.0
        recency = 1.0 / (1.0 + (now - recent[-1]) / 3600.0)
        frequency = len(recent) / 10.0
        return min(1.0, recency * 0.6 + frequency * 0.4)

    def apply_hot_boost(self, results: list[Any], boost_factor: float = 0.2) -> list[Any]:
        now = time.time()
        for r in results:
            mid = self._get_field(r, "id", "") or ""
            hot = self.get_hot_score(str(mid), now)

            current_score = self._get_field(r, "score", None)
            if current_score is None:
                current_score = self._get_field(r, "rrf_score", None)
            if current_score is None:
                current_score = 0.5

            metadata = self._get_metadata(r)
            metadata["hot_score"] = hot
            metadata["score_before_hot"] = current_score

            boosted = current_score * (1.0 + hot * boost_factor)
            if self._get_field(r, "rrf_score", None) is not None:
                self._set_field(r, "rrf_score", boosted)
            elif self._get_field(r, "score", None) is not None:
                self._set_field(r, "score", boosted)
        return results

    # ------------------------------------------------------------------
    # Uniform access pattern for result items (dict or object).
    # ------------------------------------------------------------------
    @staticmethod
    def _get_field(item: Any, key: str, default: Any = None) -> Any:
        if isinstance(item, dict):
            return item.get(key, default)
        return getattr(item, key, default)

    @staticmethod
    def _set_field(item: Any, key: str, value: Any) -> None:
        if isinstance(item, dict):
            item[key] = value
        else:
            setattr(item, key, value)

    @classmethod
    def _get_metadata(cls, item: Any) -> dict:
        metadata = cls._get_field(item, "metadata")
        if not isinstance(metadata, dict):
            metadata = {}
            cls._set_field(item, "metadata", metadata)
        return metadata

    def clear(self) -> None:
        self._access_log.clear()
