"""Conflict detector — cross-agent triple contradiction detection.

Detects when two agents derive conflicting triples for the same (subject, predicate).
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# ── Conflict thresholds ────────────────────────────────────

MAJOR_CONFIDENCE_GAP = 0.3  # confidence diff >= this -> major conflict


def detect_conflicts(
    local_triples: list[dict],
    remote_triples_by_agent: dict[str, list[dict]],
) -> list[dict]:
    """Detect triple conflicts between local and remote agents.

    Args:
        local_triples: List of triple dicts from local pipeline state.
        remote_triples_by_agent: Dict of agent_name -> [triple_dicts].

    Returns:
        List of conflict records.
    """
    conflicts = []

    # Build local index by (subject, predicate)
    local_index: dict[tuple[str, str], dict] = {}
    for t in local_triples:
        key = (t.get("subject", ""), t.get("predicate", ""))
        if key[0] and key[1]:
            local_index[key] = t

    for agent, triples in remote_triples_by_agent.items():
        if agent == "comsam":
            continue
        for t in triples:
            key = (t.get("subject", ""), t.get("predicate", ""))
            if key not in local_index:
                continue

            local_t = local_index[key]
            local_obj = str(local_t.get("object_", local_t.get("object", "")))
            remote_obj = str(t.get("object_", t.get("object", "")))

            if local_obj == remote_obj:
                continue  # Consistent

            # Conflict detected
            local_conf = float(local_t.get("confidence", 0.5))
            remote_conf = float(t.get("confidence", 0.5))
            conf_gap = abs(local_conf - remote_conf)

            conflict = {
                "subject": key[0],
                "predicate": key[1],
                "local_object": local_obj,
                "remote_object": remote_obj,
                "remote_agent": agent,
                "local_confidence": local_conf,
                "remote_confidence": remote_conf,
                "confidence_gap": round(conf_gap, 2),
                "severity": "major" if conf_gap >= MAJOR_CONFIDENCE_GAP else "minor",
                "detected_at": datetime.now(timezone.utc).isoformat(),
            }
            conflicts.append(conflict)

    return conflicts


def format_conflict_report(conflicts: list[dict]) -> str:
    """Format conflicts as human-readable text."""
    if not conflicts:
        return "No conflicts detected."

    lines = [f"Found {len(conflicts)} triple conflict(s):", ""]
    for c in conflicts:
        severity = c["severity"].upper()
        lines.append(
            f"  [{severity}] ({c['subject']}, {c['predicate']})"
            f"\n         local:  '{c['local_object']}' (conf={c['local_confidence']})"
            f"\n         remote: '{c['remote_object']}' (conf={c['remote_confidence']}, agent={c['remote_agent']})"
        )
        lines.append("")
    return "\n".join(lines)
