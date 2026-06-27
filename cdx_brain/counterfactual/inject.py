"""Counterfactual injector - add relevant abandoned decisions to session context."""

from __future__ import annotations

from cdx_brain.cache.connection import CacheConnection
from cdx_brain.counterfactual.store import ensure_counterfactual_schema, search_counterfactuals


def inject_counterfactuals(
    query: str,
    conn_or_cache,
    limit: int = 3,
) -> str:
    results = search_counterfactuals(conn_or_cache, query, limit=limit)
    if not results:
        return ""
    lines = ["", "## \u26a0\ufe0f 相关历史决策（反事实记忆）", "", "以下方案曾被尝试并放弃：", ""]
    for i, r in enumerate(results, 1):
        subj = r.get("subject", "?")
        rej = r.get("rejected", "?")
        chosen = r.get("chosen", "") or ""
        reason = (r.get("reason", "") or "")[:200]
        decided = r.get("decided_by", "?") or "?"
        session = (r.get("source_session", "") or "?")[:20]
        lines.append("%d. **[\u26a0 %s]** \u653e\u5f03\u4e86\u300c%s\u300d" % (i, subj, rej))
        if chosen:
            lines.append("   最终选择：" + chosen)
        if reason:
            lines.append("   原因：" + reason)
        lines.append("   决策者：%s | 来源：%s" % (decided, session))
        lines.append("")
    return "\n".join(lines)


def format_counterfactual_block(results: list[dict]) -> str:
    if not results:
        return ""
    lines = ["## \u26a0\ufe0f 反事实记忆"]
    for r in results:
        subj = r.get("subject", "?")
        rej = (r.get("rejected", "") or "")[:60]
        reason = (r.get("reason", "") or "")[:120]
        lines.append("- [%s] 放弃: %s | 原因: %s" % (subj, rej, reason))
    return "\n".join(lines)
