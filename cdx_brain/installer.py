"""cdx-brain installer — memory system initialization."""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from cdx_brain.cache.connection import CacheConnection
from cdx_brain.cache.schema import ensure_schema
from cdx_brain.config import ConfigManager


def _get_template_vars(config: dict[str, Any]) -> dict[str, Any]:
    """Build template variables from config."""
    return {
        "config_dir": str(Path(config.get("paths", {}).get("config_dir", "~/.cdx-brain"))),
        "data_dir": str(Path(config.get("paths", {}).get("data_dir", "~/.cdx-brain/data"))),
    }


def init_memory_system(config_manager: ConfigManager, agent_name: str = "", ov_url: str = "") -> dict[str, Any]:
    """Initialize cdx-brain memory system. Returns status dict."""
    config_dir = config_manager.config_path.parent
    data_dir = config_manager.data_dir

    data_dir.mkdir(parents=True, exist_ok=True)
    config = config_manager.load()
    if agent_name:
        config["agent"]["name"] = agent_name
    if ov_url:
        config["ov"]["url"] = ov_url
        config["ov"]["enabled"] = True
    config_manager.save(config)

    cache_path = data_dir / "cache.db"
    cache = CacheConnection(str(cache_path))
    ensure_schema(cache)
    cache.close_all()

    sessions_file = data_dir / "sessions.jsonl"
    if not sessions_file.is_file():
        sessions_file.write_text("", encoding="utf-8")

    memory_path = config.get("memory", {}).get("memory_path", "")
    if memory_path:
        mem_dir = Path(os.path.expanduser(memory_path))
        mem_dir.mkdir(parents=True, exist_ok=True)
        existing = list(mem_dir.glob("*.md"))
        if not existing:
            _write_initial_memories(mem_dir, config)

    trace_count = 0
    try:
        from cdx_brain.cache.traces import TraceRepository
        tr = TraceRepository(cache)
        trace_count = tr.count()
    except Exception:
        pass

    return {
        "config_dir": str(config_dir),
        "data_dir": str(data_dir),
        "cache_path": str(cache_path),
        "agent_name": config["agent"]["name"],
        "ov_enabled": config["ov"]["enabled"],
        "ov_url": config["ov"]["url"],
        "trace_count": trace_count,
    }


def _write_initial_memories(mem_dir: Path, config: dict[str, Any]) -> None:
    """Write initial core memory files when native memory dir is empty."""
    agent_name = config.get("agent", {}).get("name", "comsam")
    memories = {
        "cdx-brain-memory-system.md": (
            "# cdx-brain Memory System\n\n"
            "## Architecture\n"
            "- **L1 Working Memory**: current session, not persisted\n"
            "- **L2 Short-term Memory**: cache.db SQLite+FTS5, auto-retrieval\n"
            "- **L3 Core Memory**: local markdown files, auto-loaded each turn\n\n"
            "## Retrieval Pipeline\n"
            "User Input -> FTS5 full-text(cache.db) + Core Memory keyword match + OpenViking semantic search\n"
            "-> RRF fusion ranking -> injected as additional context\n\n"
            "## Memory Promotion\n"
            "High-frequency/important conversations auto-promoted from L2 to L3\n\n"
            + f"_init: {datetime.now(timezone.utc).strftime('%Y-%m-%d')}_\n"
        ),
        "agent-identity.md": (
            "# Agent Identity\n\n"
            + f"## Name\n{agent_name}\n\n"
            + "## Role\n"
            + "cdx-brain memory system driven Codex Agent\n\n"
            + "## Capabilities\n"
            + "- Semantic memory search (FTS5 + keyword + OpenViking)\n"
            + "- Session auto-store\n"
            + "- Memory auto-promotion\n\n"
            + "## Collaboration\n"
            + "- Team memory shared via OpenViking\n"
            + "- Core knowledge persisted in local markdown\n"
        ),
    }

    for name, content in memories.items():
        fpath = mem_dir / name
        if not fpath.is_file():
            fpath.write_text(content, encoding="utf-8")
            sys.stderr.write(f"[cdx-brain] initial memory: {name}\n")