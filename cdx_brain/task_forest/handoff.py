"""Session handoff compression for cross-session continuity."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from cdx_brain.task_forest.dag import TaskNode
from cdx_brain.task_forest.forest import TaskForest
from cdx_brain.task_forest.profile import load_profile


def build_handoff_prompt(forest: TaskForest, session_summary: str = "") -> str:
    """Build a paste-ready handoff prompt for a new session."""
    profile = load_profile()
    active = forest.get_active()

    lines = [
        "## Session 交接摘要",
        "",
    ]

    if session_summary:
        lines.append("### 上一 Session 总结")
        lines.append(session_summary)
        lines.append("")

    if active:
        lines.append("### 活跃任务（%d 项）" % len(active))
        for t in active:
            status_icon = {"open": "🟢", "in_progress": "🔵", "blocked": "🔴"}.get(t.status, "⚪")
            lines.append("%s **%s** [%s]" % (status_icon, t.title, t.status))
            if t.blocked_by:
                lines.append("   阻塞于: %s" % ", ".join(t.blocked_by))
            if t.decisions:
                lines.append("   决策: %s" % "; ".join(t.decisions[-2:]))
        lines.append("")

    if profile.tech_stack_preferences:
        lines.append("### 用户偏好")
        lines.append("技术栈: %s" % ", ".join(profile.tech_stack_preferences))
        if profile.architecture_style:
            lines.append("架构风格: %s" % profile.architecture_style)
        if profile.anti_patterns:
            lines.append("反模式: %s" % ", ".join(profile.anti_patterns))
        lines.append("")

    return "\n".join(lines)


def compress_to_summary(forest: TaskForest) -> str:
    """Generate a one-paragraph summary of current forest state."""
    stats = forest.stats()
    active = forest.get_active()
    if not active:
        return "当前无活跃任务。"
    parts = ["当前%d个活跃任务:" % len(active)]
    for t in active[:5]:
        parts.append("  [%s] %s" % (t.status, t.title))
    if stats["total"] > 5:
        parts.append("  ...共%d个任务" % stats["total"])
    return "\n".join(parts)
