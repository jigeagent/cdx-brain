#!/usr/bin/env python3
"""
PreCompact / PostCompact Hook — cdx-brain context compression protection.

Save: saves STATUS.md / MEMORY.md / Snapshot -> tmp JSON before compression.
Restore: restores from tmp JSON -> additionalContext after compression.

Config cascade: env var > config.yaml > template-baked default.
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
from pathlib import Path

# ── Runtime config (cascade: env var → config.yaml → baked fallback) ──
try:
    from cdx_brain.config import ConfigManager
    _CFG_MGR = ConfigManager()
    _CFG = _CFG_MGR.load()
    _GET = lambda k, d=None: _CFG_MGR.get(k) or d  # noqa: E731
except Exception:
    _GET = lambda k, d=None: d                      # standalone fallback


def _resolve(key: str, env: str, baked: str) -> str:
    