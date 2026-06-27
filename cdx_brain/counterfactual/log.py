"""Counterfactual logger - auto-log rejected decisions from promote_gate and conversation."""

from __future__ import annotations

import re
from datetime import datetime, timezone
from uuid import uuid4
from typing import Optional


TRIGGER_PATTERNS: list[tuple[str, str]] = [
    (r"(方案|改法|路径|方向|路线|办法|策略|架构)", r"(放弃|否决|不用|不行|不采用|不考虑|不可行)"),
    (r"(尝试|试验|试过)", r"(不行|失败|失效|不成立)"),
]

NEGATION_PREFIX = r"(没|别|不会|不能|不想|不要|还没|暂时)"


def extract_counterfactual_from_text(
    text: str,
    session_id: str = "",
    decider: str = "",
) -> Optional[dict]:
    for subject_pat, action_pat in TRIGGER_PATTERNS:
        sub_match = re.search(subject_pat, text)
        if not sub_match:
            continue
        action_match = re.search(action_pat, text)
        if not action_match:
            continue
        action_pos = action_match.start()
        prefix_start = max(0, action_pos - 20)
        prefix_text = text[prefix_start:action_pos]
        if re.search(NEGATION_PREFIX, prefix_text):
            continue
        ctx_start = max(0, sub_match.start() - 50)
        ctx_end = min(len(text), action_match.end() + 50)
        context = text[ctx_start:ctx_end].strip()
        return {
            "id": "cf_" + uuid4().hex[:12],
            "subject": sub_match.group(0),
            "chosen": "",
            "rejected": action_match.group(0),
            "reason": context,
            "context": context,
            "confidence": 0.7,
            "decided_by": decider or "auto",
            "tags": "",
            "source_session": session_id,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
    return None


def log_counterfactual(conn_or_cache, cf_data: dict) -> bool:
    conn = conn_or_cache.conn if hasattr(conn_or_cache, "conn") else conn_or_cache
    from cdx_brain.counterfactual.store import ensure_counterfactual_schema
    ensure_counterfactual_schema(conn)
    try:
        conn.execute("""
            INSERT INTO counterfactuals
                (id, subject, chosen, rejected, reason, context,
                 confidence, decided_by, tags, source_session, created_at, synced)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0)
        """, (
            cf_data.get("id", "cf_" + uuid4().hex[:12]),
            cf_data.get("subject", ""),
            cf_data.get("chosen", ""),
            cf_data.get("rejected", ""),
            cf_data.get("reason", ""),
            cf_data.get("context", ""),
            float(cf_data.get("confidence", 0.7)),
            cf_data.get("decided_by", "auto"),
            cf_data.get("tags", ""),
            cf_data.get("source_session", ""),
            cf_data.get("created_at", datetime.now(timezone.utc).isoformat()),
        ))
        conn.commit()
        return True
    except Exception:
        return False


def log_rejection_from_gate(
    conn_or_cache,
    candidate_id: str,
    candidate_text: str,
    current_score: float,
    candidate_score: float,
    session_id: str = "",
) -> bool:
    cf = extract_counterfactual_from_text(candidate_text, session_id, "promote_gate")
    if not cf:
        cf = {
            "id": "cf_" + uuid4().hex[:12],
            "subject": "memory_promotion",
            "chosen": "",
            "rejected": "score=" + str(candidate_score) + " < current=" + str(current_score),
            "reason": candidate_text[:200],
            "context": candidate_text[:500],
            "confidence": 0.5,
            "decided_by": "promote_gate",
            "tags": "",
            "source_session": session_id,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
    return log_counterfactual(conn_or_cache, cf)
