"""Sync cognitive pipeline state to OpenViking.

Each agent writes policies, concepts, and skills to their own OV space
using a consistent path pattern: viking://resources/{agent}/cognitive/{type}/{id}

Read: consensus module searches OV with path filter "*/cognitive/*"
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

# Path pattern: viking://resources/{agent}/cognitive/{type}/{id}.{ext}
_COGNITIVE_BASE = "viking://resources/{agent}/cognitive"


def _make_policy_uri(agent: str, policy_id: str) -> str:
    return f"{_COGNITIVE_BASE.format(agent=agent)}/policies/{policy_id}.json"


def _make_concept_uri(agent: str, concept_id: str) -> str:
    return f"{_COGNITIVE_BASE.format(agent=agent)}/concepts/{concept_id}.json"


def _make_skill_uri(agent: str, skill_name: str) -> str:
    return f"{_COGNITIVE_BASE.format(agent=agent)}/skills/{skill_name}.md"


def _make_triple_uri(agent: str, triple_id: str) -> str:
    return f"{_COGNITIVE_BASE.format(agent=agent)}/triples/{triple_id}.json"


def sync_pipeline_to_ov(
    state: dict[str, Any],
    ov_url: str,
    agent: str = "comsam",
    dry_run: bool = False,
) -> dict[str, int]:
    """Sync pipeline state (policies, skills, world model) to OV.

    Args:
        state: Pipeline state dict (from pipeline_state.json or get_stats())
        ov_url: OpenViking server URL.
        agent: Agent name for URI prefix.
        dry_run: If True, only report what would be synced.

    Returns:
        { "policies": int, "concepts": int, "triples": int, "skills": int }
    """
    if not ov_url:
        return {}

    from cdx_brain.ov.client import OpenVikingClient
    client = OpenVikingClient(base_url=ov_url, timeout=5.0)

    counts: dict[str, int] = {"policies": 0, "concepts": 0, "triples": 0, "skills": 0}
    now = datetime.now(timezone.utc).isoformat()

    # Policies
    for p in state.get("policies", []):
        pid = p.get("id", "")
        if not pid:
            continue
        uri = _make_policy_uri(agent, pid)
        if dry_run:
            counts["policies"] += 1
            continue
        try:
            content = json.dumps(p, ensure_ascii=False, default=str)
            client.content_write(uri, content, metadata={"agent": agent, "type": "policy", "synced_at": now})
            counts["policies"] += 1
        except Exception:
            pass

    # World model: concepts + triples
    wm = state.get("world_model", {})
    for cid, cdata in wm.get("concepts", {}).items():
        uri = _make_concept_uri(agent, cid)
        if dry_run:
            counts["concepts"] += 1
            continue
        try:
            content = json.dumps(cdata, ensure_ascii=False, default=str)
            client.content_write(uri, content, metadata={"agent": agent, "type": "concept", "synced_at": now})
            counts["concepts"] += 1
        except Exception:
            pass

    for tid, tdata in wm.get("triples", {}).items():
        uri = _make_triple_uri(agent, tid)
        if dry_run:
            counts["triples"] += 1
            continue
        try:
            content = json.dumps(tdata, ensure_ascii=False, default=str)
            client.content_write(uri, content, metadata={"agent": agent, "type": "triple", "synced_at": now})
            counts["triples"] += 1
        except Exception:
            pass

    # Skills
    for s in state.get("skills", []):
        name = s.get("name", "")
        if not name:
            continue
        uri = _make_skill_uri(agent, name)
        if dry_run:
            counts["skills"] += 1
            continue
        try:
            # Skills are stored as markdown
            md = s.get("usage_guide", "") or s.get("description", "")
            client.content_write(uri, md, metadata={"agent": agent, "type": "skill", "synced_at": now})
            counts["skills"] += 1
        except Exception:
            pass

    # Relations from triples table
    try:
        from pathlib import Path
        import sqlite3
        cache_path = Path.home() / ".cdx-brain" / "data" / "cache.db"
        if cache_path.is_file():
            conn = sqlite3.connect(str(cache_path))
            conn.row_factory = sqlite3.Row
            rels = conn.execute("SELECT * FROM triples WHERE synced = 0 LIMIT 100").fetchall()
            for rel in rels:
                rid = rel["id"]
                if not rid:
                    continue
                uri = f"{_COGNITIVE_BASE.format(agent=agent)}/relations/{rid}.json"
                if dry_run:
                    counts["relations"] = counts.get("relations", 0) + 1
                    continue
                try:
                    rel_dict = dict(rel)
                    content = json.dumps(rel_dict, ensure_ascii=False, default=str)
                    client.content_write(uri, content, metadata={"agent": agent, "type": "relation", "synced_at": now})
                    conn.execute("UPDATE triples SET synced = 1 WHERE id = ?", (rid,))
                    counts["relations"] = counts.get("relations", 0) + 1
                except Exception:
                    pass
            conn.commit()
            conn.close()
    except Exception:
        pass

    client.close()
    return counts


def sync_pipeline_state_file(
    state_path: str,
    ov_url: str,
    agent: str = "comsam",
    dry_run: bool = False,
) -> dict[str, int]:
    """Load pipeline_state.json and sync to OV."""
    path = Path(state_path)
    if not path.is_file():
        logger.warning("Pipeline state not found: %s", state_path)
        return {}
    try:
        state = json.loads(path.read_text("utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return sync_pipeline_to_ov(state, ov_url, agent, dry_run)
