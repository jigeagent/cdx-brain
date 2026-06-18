#!/usr/bin/env python3
"""
UserPromptSubmit Hook — cdx-brain memory retrieval injection.

Reads user prompt → cache.db FTS5 + native memory + OpenViking → additionalContext.
Three sources fused via RRF merge (config cascade: env var → config.yaml → baked).
"""
from __future__ import annotations

import sys
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")


import json
import os
import re
import sys
import time
from pathlib import Path

from cdx_brain.cache.connection import CacheConnection
from cdx_brain.cache.schema import ensure_schema
from cdx_brain.cache.traces import TraceRepository
from cdx_brain.retrieval.ranker import rrf_merge

# ── Runtime config ──
try:
    from cdx_brain.config import ConfigManager
    _CFG_MGR = ConfigManager()
    _CFG = _CFG_MGR.load()
    _GET = lambda k, d=None: _CFG_MGR.get(k) or d
except Exception:
    _GET = lambda k, d=None: d

CACHE_PATH = os.path.expanduser(os.environ.get("CDX_BRAIN_CACHE_PATH", "$cache_path"))
OV_URL = os.environ.get("CDX_BRAIN_OV_URL", _GET("ov.url", "$ov_url"))
OV_ENABLED = os.environ.get("CDX_BRAIN_OV_ENABLED", "$ov_enabled") in ("1", "true", "True")
NATIVE_MEMORY_PATH = os.path.expanduser(
    os.environ.get("CDX_BRAIN_MEMORY_PATH", _GET("memory.memory_path", "$memory_path"))
)
MIN_WORDS = 3
MAX_MEMORIES = int(os.environ.get("CDX_BRAIN_MAX_INJECT", _GET("memory.max_inject", "$max_inject")))
MAX_INJECT_NATIVE = int(os.environ.get("CDX_BRAIN_MAX_INJECT_NATIVE", _GET("memory.max_inject_native", "3")))
CODEX_HOME = os.environ.get("CODEX_HOME", os.path.expanduser("~/.codex"))


def sanitize_query(text: str) -> str:
    