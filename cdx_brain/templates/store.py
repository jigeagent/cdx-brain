#!/usr/bin/env python3
"""
Stop Hook — cdx-brain conversation storage + memory promotion.

Reads transcript → stores to cache.db → optionally promotes to native memory.
Config cascade: env var → config.yaml → template-baked default.
"""
from __future__ import annotations

import sys
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")


import hashlib
import json
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path

from cdx_brain.cache.connection import CacheConnection
from cdx_brain.cache.schema import ensure_schema
from cdx_brain.cache.traces import TraceRepository
from cdx_brain.memos.id import new_id
from cdx_brain.memos.memo_types import TraceRow
import sqlite3

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
if not NATIVE_MEMORY_PATH:
    _codex_home = os.environ.get("CODEX_HOME", os.path.expanduser("~/.codex"))
    NATIVE_MEMORY_PATH = os.path.join(_codex_home, "memories", "extensions", "cdx-brain")
PROMOTE_ENABLED = os.environ.get("CDX_BRAIN_PROMOTE_ENABLED", str(_GET("memory.promote_enabled", "True"))) in ("1", "true", "True")
PROMOTE_THRESHOLD = int(os.environ.get("CDX_BRAIN_PROMOTE_THRESHOLD", str(_GET("memory.promote_threshold", "3"))))
PROMOTE_MIN_LENGTH = int(os.environ.get("CDX_BRAIN_PROMOTE_MIN_LENGTH", str(_GET("memory.promote_min_length", "50"))))
PROMOTE_COOLDOWN_DAYS = int(os.environ.get("CDX_BRAIN_PROMOTE_COOLDOWN_DAYS", str(_GET("memory.promote_cooldown_days", "7"))))
MAX_RETRIES = 5
RETRY_DELAY_MS = 150
TRANSCRIPT_POLL_TIMEOUT = 3.0

# ── Promote tracking file ──
_PROMOTE_LOG = Path(CACHE_PATH).parent / "promote_log.jsonl"


# ── Transcript reading ──


def read_transcript_safe(path: str, max_retries: int = MAX_RETRIES) -> list[dict] | None:
    