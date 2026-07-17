"""LRU embedding cache with thread safety and model versioning (O8)."""
from __future__ import annotations
import hashlib
import threading
from collections import OrderedDict
from typing import Any


class EmbeddingCache:
    """Thread-safe LRU cache for query embeddings with model version namespacing."""

    def __init__(self, capacity: int = 1024, model_version: str = ""):
        self._cache: OrderedDict[str, list[float]] = OrderedDict()
        self._capacity = capacity
        self._model_version = model_version
        self._lock = threading.Lock()

    def _key(self, text: str) -> str:
        raw = text.encode("utf-8")
        if self._model_version:
            raw = self._model_version.encode("utf-8") + b"::" + raw
        return hashlib.md5(raw).hexdigest()

    def get(self, text: str) -> list[float] | None:
        key = self._key(text)
        with self._lock:
            if key in self._cache:
                self._cache.move_to_end(key)
                return self._cache[key]
            return None

    def put(self, text: str, embedding: list[float]) -> None:
        key = self._key(text)
        with self._lock:
            if key in self._cache:
                self._cache.move_to_end(key)
            self._cache[key] = embedding
            while len(self._cache) > self._capacity:
                self._cache.popitem(last=False)

    def clear(self) -> None:
        with self._lock:
            self._cache.clear()

    @property
    def size(self) -> int:
        with self._lock:
            return len(self._cache)
