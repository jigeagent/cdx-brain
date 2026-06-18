"""Baidu Netdisk (bdpan) sync wrapper for cdx-brain cognitive products.

Discovers the bdpan Go binary from env / well-known paths and provides
upload helpers for pipeline_state.json, cold.db, and federated artifacts.

Team convention:
  Remote base path relative to bdpan root (/apps/bdpan/):
    hermes/shared/{agent}/
  Actual Baidu Pan path:
    /apps/bdpan/hermes/shared/comsam/cognitive/pipeline_state.json
  The bdpan binary limits remote paths to its authorized app directory (/apps/bdpan/).
  Cloud VM (好妹): reads from /apps/bdpan/hermes/shared/comsam/cognitive/
"""

from __future__ import annotations

import json
import logging
import os
import shlex
import subprocess
import sys
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

# ── Default paths ──────────────────────────────────────────────

_WELL_KNOWN_BDPAN_PATHS = [
    "D:/WorkBuddy/.local/bin/bdpan",
    os.path.expanduser("~/.local/bin/bdpan"),
    os.path.expanduser("~/AppData/Local/bdpan/bdpan"),
]

BDPAN_REMOTE_BASE = "hermes/shared/{agent}"

# ── Binary discovery ───────────────────────────────────────────


def _find_bdpan() -> str | None:
    """Locate the bdpan Go binary."""
    # 1. Env var override
    env_path = os.environ.get("CDX_BRAIN_BDPAN_PATH", "")
    if env_path and os.path.isfile(env_path):
        return env_path

    # 2. Well-known paths
    for p in _WELL_KNOWN_BDPAN_PATHS:
        if os.path.isfile(p):
            return p

    # 3. PATH lookup
    try:
        import shutil
        return shutil.which("bdpan")
    except Exception:
        return None


def _get_bdpan() -> str:
    """Get bdpan binary path or raise."""
    bp = _find_bdpan()
    if not bp:
        raise FileNotFoundError(
            "bdpan binary not found. Set CDX_BRAIN_BDPAN_PATH or install from "
            "https://github.com/lyswhut/bdpan"
        )
    return bp


# ── Core upload ────────────────────────────────────────────────


def sync_to_bdpan(
    local_path: str,
    remote_path: str,
    timeout: int = 120,
) -> dict[str, Any]:
    """Upload a single file to Baidu Pan via bdpan CLI.

    Args:
        local_path: Absolute path to local file.
        remote_path: Remote path (relative to Baidu Pan root, e.g.
                     "hermes/shared/comsam/cognitive/pipeline_state.json"
                     or absolute "/apps/hermes/...").
        timeout: Max seconds for upload.

    Returns:
        {"ok": bool, "error": str, "local": str, "remote": str}
    """
    result: dict[str, Any] = {
        "ok": False,
        "error": "",
        "local": local_path,
        "remote": remote_path,
    }

    if not os.path.isfile(local_path):
        result["error"] = f"local file not found: {local_path}"
        logger.warning("sync_to_bdpan: %s", result["error"])
        return result

    try:
        bp = _get_bdpan()
    except FileNotFoundError as e:
        result["error"] = str(e)
        logger.warning("sync_to_bdpan: %s", result["error"])
        return result

    cmd = [bp, "upload", local_path, remote_path]

    try:
        p = subprocess.run(
            cmd,
            capture_output=True,
            timeout=timeout,
        )
        stdout = p.stdout.decode("utf-8", errors="replace")
        stderr = p.stderr.decode("utf-8", errors="replace")

        if p.returncode == 0:
            result["ok"] = True
            logger.info("bdpan upload OK: %s → %s", local_path, remote_path)
        else:
            result["error"] = (stderr or stdout).strip()[:500]
            logger.warning("bdpan upload FAILED (%d): %s", p.returncode, result["error"])
    except subprocess.TimeoutExpired:
        result["error"] = f"upload timed out after {timeout}s"
        logger.warning("sync_to_bdpan: %s", result["error"])
    except Exception as e:
        result["error"] = str(e)[:500]
        logger.warning("sync_to_bdpan exception: %s", result["error"])

    return result


# ── Config helpers ─────────────────────────────────────────────


def _is_sync_enabled() -> bool:
    """Check if bdpan sync is enabled by config or env."""
    from cdx_brain.config import ConfigManager
    cfg = ConfigManager()
    return cfg.get("sync.bdpan.enabled") is True


def _get_agent_name() -> str:
    """Get agent name for remote path templating."""
    from cdx_brain.config import ConfigManager
    cfg = ConfigManager()
    return cfg.get("agent.name") or "comsam"


def _make_remote_path(relative: str, agent: str | None = None) -> str:
    """Build absolute remote path from relative.
    
    Example:
        _make_remote_path("cognitive/pipeline_state.json", "comsam")
        → "hermes/shared/comsam/cognitive/pipeline_state.json"
        (maps to /apps/bdpan/hermes/shared/comsam/cognitive/pipeline_state.json on Baidu Pan)
    """
    a = agent or _get_agent_name()
    base = os.environ.get("CDX_BRAIN_BDPAN_REMOTE_BASE", BDPAN_REMOTE_BASE)
    base = base.format(agent=a)
    base = base.rstrip("/")
    rel = relative.lstrip("/")
    return f"{base}/{rel}"


# ── Data dir helpers ───────────────────────────────────────────


def _get_data_dir() -> str:
    """Get the cdx-brain data directory."""
    from cdx_brain.config import ConfigManager
    cfg = ConfigManager()
    raw = cfg.get("storage.path") or "~/.cdx-brain/data"
    return os.path.expanduser(raw)


def _get_pipeline_state_path() -> str:
    return os.path.join(_get_data_dir(), "pipeline_state.json")


def _get_cold_db_path() -> str:
    return os.path.join(_get_data_dir(), "cold.db")


def _get_cache_db_path() -> str:
    return os.path.join(_get_data_dir(), "cache.db")


# ── Cognitive product sync ─────────────────────────────────────


def sync_pipeline_state(
    agent: str | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Sync pipeline_state.json to Baidu Pan."""
    local = _get_pipeline_state_path()
    remote = _make_remote_path("cognitive/pipeline_state.json", agent)
    if dry_run:
        return {"ok": True, "dry_run": True, "local": local, "remote": remote}
    return sync_to_bdpan(local, remote)


def sync_cold_db(
    agent: str | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Sync cold.db to Baidu Pan."""
    local = _get_cold_db_path()
    if not os.path.isfile(local):
        return {"ok": False, "error": "cold.db not found on disk", "local": local, "remote": _make_remote_path("cognitive/cold.db", agent)}
    remote = _make_remote_path("cognitive/cold.db", agent)
    if dry_run:
        return {"ok": True, "dry_run": True, "local": local, "remote": remote}
    return sync_to_bdpan(local, remote)


def sync_cache_db(
    agent: str | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Sync cache.db to Baidu Pan (optional, may be large)."""
    local = _get_cache_db_path()
    if not os.path.isfile(local):
        return {"ok": False, "error": "cache.db not found", "local": local, "remote": _make_remote_path("cognitive/cache.db", agent)}
    remote = _make_remote_path("cognitive/cache.db", agent)
    if dry_run:
        return {"ok": True, "dry_run": True, "local": local, "remote": remote}
    return sync_to_bdpan(local, remote)


def sync_promote_log(
    agent: str | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Sync promote_log.jsonl to Baidu Pan."""
    local = os.path.join(_get_data_dir(), "promote_log.jsonl")
    if not os.path.isfile(local):
        return {"ok": False, "error": "promote_log not found", "local": local, "remote": _make_remote_path("cognitive/promote_log.jsonl", agent)}
    remote = _make_remote_path("cognitive/promote_log.jsonl", agent)
    if dry_run:
        return {"ok": True, "dry_run": True, "local": local, "remote": remote}
    return sync_to_bdpan(local, remote)


def sync_all_cognitive(
    agent: str | None = None,
    dry_run: bool = False,
    skip_cache_db: bool = True,
) -> list[dict[str, Any]]:
    """Sync all cognitive products to Baidu Pan.

    Uploads: pipeline_state.json, cold.db, promote_log.jsonl
    Optionally: cache.db (disabled by default — can be large)

    Args:
        agent: Override agent name (default: from config).
        dry_run: Preview only.
        skip_cache_db: Skip cache.db upload (large file).

    Returns:
        List of per-file sync results.
    """
    results: list[dict[str, Any]] = []

    results.append(sync_pipeline_state(agent, dry_run))
    results.append(sync_cold_db(agent, dry_run))
    results.append(sync_promote_log(agent, dry_run))
    if not skip_cache_db:
        results.append(sync_cache_db(agent, dry_run))

    ok_count = sum(1 for r in results if r.get("ok"))
    fail_count = sum(1 for r in results if not r.get("ok") and r.get("error"))
    logger.info(
        "sync_all_cognitive: %d OK, %d failed (dry_run=%s)",
        ok_count, fail_count, dry_run,
    )

    return results
