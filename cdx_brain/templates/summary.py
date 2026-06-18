#!/usr/bin/env python3
"""
SessionEnd Hook — cdx-brain session summary + batch sync.

Extracts session summary from transcript -> saves sessions.jsonl -> batch syncs unsynced traces to OV.
"""
from __future__ import annotations

import sys
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")


import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from cdx_brain.cache.connection import CacheConnection
from cdx_brain.cache.schema import ensure_schema
from cdx_brain.cache.traces import TraceRepository

CACHE_PATH = os.path.expanduser("$cache_path")
OV_URL = os.environ.get("CDX_BRAIN_OV_URL", "$ov_url")
OV_ENABLED = os.environ.get("CDX_BRAIN_OV_ENABLED", "$ov_enabled") in ("1", "true", "True")
SESSIONS_FILE = Path(os.path.expanduser("$sessions_file"))
SYNC_BATCH_SIZE = $sync_batch


def extract_session_info(transcript_path: str) -> dict | None:
    