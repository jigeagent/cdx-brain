"""Consensus finder — cross-agent policy/concept merging via OV search.

Strategy (虎哥 proposal):
  Write: each agent manages their own space
  Read:  global OV search filtered by path pattern "*/cognitive/*"
  Merge: semantic + Jaccard similarity → auto/pending merge
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

# ── Similarity thresholds ──────────────────────────────────

AUTO_MERGE_THRESHOLD = 0.8       # OV semantic score → auto merge
PENDING_MERGE_THRESHOLD = 0.6    # OV score + Jaccard → pending review
JACCARD_DIRECT_MERGE = 0.8       # trigger_pattern Jaccard → direct merge (no OV)

# ── Path pattern for cognitive data ─────────────────────────

_COGNITIVE_PATH_PATTERN = re.compile(r"(?:.*/)?cognitive/(policies|concepts|skills|triples)/")
"""Match OV resource paths containing "cognitive/{type}/"."""


def is_cognitive_path(path: str) -> bool:
    """Check if an OV resource path matches the cognitive pattern."""
    return bool(_COGNITIVE_PATH_PATTERN.search(path))


def extract_agent_from_path(path: str) -> str:
    """Extract agent name from OV path like resources/tiger/cognitive/policies/..."""
    # Pattern: resources/{agent}/cognitive/...
    m = re.search(r"resources/([^/]+)/cognitive/", path)
    return m.group(1) if m else "unknown"


# ── Similarity helpers (no OV dependency) ───────────────────


def _tokenize(text: str) -> set[str]:
    """Tokenize text into CJK bigrams + English keywords."""
    if not text:
        return set()
    cjk_chars = re.findall(r"[一-鿿㐀-䶿]", text)
    bigrams = {cjk_chars[i] + cjk_chars[i + 1] for i in range(len(cjk_chars) - 1)}
    words = set(re.findall(r"[a-z0-9_-]{3,}", text.lower()))
    return bigrams | words


def jaccard_similarity(a: str, b: str) -> float:
    """Jaccard similarity between two text strings."""
    ta = _tokenize(a)
    tb = _tokenize(b)
    if not ta or not tb:
        return 0.0
    intersection = len(ta & tb)
    union = len(ta | tb)
    return intersection / max(union, 1)


def trigger_pattern_similarity(policy_a: dict, policy_b: dict) -> float:
    """Compare trigger_pattern of two policies using Jaccard."""
    pa = policy_a.get("trigger_pattern", "")
    pb = policy_b.get("trigger_pattern", "")
    return jaccard_similarity(pa, pb)


# ── Merge logic ─────────────────────────────────────────────


def merge_policies(
    policy_a: dict,
    policy_b: dict,
    agent_a: str = "unknown",
    agent_b: str = "unknown",
) -> dict:
    """Merge two similar policies into one consolidated policy.

    Merge strategy:
      - name: keep first-created
      - description: concatenate
      - confidence: max of both
      - activation_count: sum
      - source_trace_ids: merge
      - tags: add consensus markers
    """
    created_a = policy_a.get("created_at", "")
    created_b = policy_b.get("created_at", "")
    use_a_first = created_a <= created_b if created_a and created_b else True

    merged = dict(policy_b if use_a_first else policy_a)
    other = policy_a if use_a_first else policy_b

    merged["name"] = policy_a.get("name", "")  # keep first-created name
    merged["description"] = (
        policy_a.get("description", "")
        + "\n\n---\n"
        + policy_b.get("description", "")
    )
    merged["confidence"] = max(
        float(policy_a.get("confidence", 0)),
        float(policy_b.get("confidence", 0)),
    )
    merged["activation_count"] = int(policy_a.get("activation_count", 0)) + int(
        policy_b.get("activation_count", 0)
    )
    merged["source_trace_ids"] = list(
        set(policy_a.get("source_trace_ids", []) + policy_b.get("source_trace_ids", []))
    )

    tags = set(policy_a.get("tags", []) + policy_b.get("tags", []))
    tags.add("consensus")
    tags.add(f"agent:{agent_a}")
    tags.add(f"agent:{agent_b}")
    merged["tags"] = list(tags)
    merged["consensus_merged_at"] = __import__("datetime").datetime.now(
        __import__("datetime").timezone.utc
    ).isoformat()

    return merged


# ── Consensus runner ────────────────────────────────────────


def find_candidates(
    ov_results: list[dict],
) -> list[dict]:
    """Filter OV search results to only cognitive path items."""
    candidates = []
    for r in ov_results:
        rid = r.get("id", "")
        if is_cognitive_path(rid):
            agent = extract_agent_from_path(rid)
            r["_agent"] = agent
            candidates.append(r)
    return candidates


def run_consensus(
    local_state: dict,
    ov_cognitive_results: list[dict],
) -> dict[str, Any]:
    """Run consensus discovery between local pipeline state and OV cognitive data.

    Args:
        local_state: Local pipeline_state.json content.
        ov_cognitive_results: OV search results filtered to cognitive paths.

    Returns:
        { "merges": [], "pending_reviews": [], "conflicts": [] }
    """
    result: dict[str, Any] = {
        "merges": [],
        "pending_reviews": [],
        "new_policies": [],
    }

    local_policies = {p.get("id", ""): p for p in local_state.get("policies", [])}
    if not local_policies:
        return result

    # Group OV results by type
    ov_policies = []
    for r in ov_cognitive_results:
        if "/policies/" in r.get("id", ""):
            ov_policies.append(r)

    for local_id, local_p in local_policies.items():
        for ov_p in ov_policies:
            # Skip self
            if ov_p.get("_agent", "") == "comsam":
                continue

            # Try direct trigger_pattern match first
            tp_sim = trigger_pattern_similarity(local_p, ov_p)
            if tp_sim >= JACCARD_DIRECT_MERGE:
                merged = merge_policies(local_p, ov_p, "comsam", ov_p.get("_agent", ""))
                result["merges"].append({
                    "local_id": local_id,
                    "remote_id": ov_p.get("id", ""),
                    "remote_agent": ov_p.get("_agent", ""),
                    "similarity": tp_sim,
                    "method": "jaccard_direct",
                    "merged": merged,
                })
                continue

            # Use OV semantic score when available
            ov_score = ov_p.get("score", 0)
            if ov_score >= AUTO_MERGE_THRESHOLD:
                merged = merge_policies(local_p, ov_p, "comsam", ov_p.get("_agent", ""))
                result["merges"].append({
                    "local_id": local_id,
                    "remote_id": ov_p.get("id", ""),
                    "remote_agent": ov_p.get("_agent", ""),
                    "similarity": ov_score,
                    "method": "semantic_auto",
                    "merged": merged,
                })
            elif ov_score >= PENDING_MERGE_THRESHOLD:
                result["pending_reviews"].append({
                    "local_id": local_id,
                    "remote_id": ov_p.get("id", ""),
                    "remote_agent": ov_p.get("_agent", ""),
                    "similarity": ov_score,
                    "tp_similarity": tp_sim,
                    "local_name": local_p.get("name", ""),
                    "remote_name": ov_p.get("name", ""),
                })

    # Deduplicate merges by pair
    seen_pairs = set()
    deduped_merges = []
    for m in result["merges"]:
        pair = (m["local_id"], m["remote_id"])
        if pair not in seen_pairs:
            seen_pairs.add(pair)
            deduped_merges.append(m)
    result["merges"] = deduped_merges

    return result
