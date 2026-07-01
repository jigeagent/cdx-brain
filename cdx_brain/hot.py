#!/usr/bin/env python3
"""hot.md — cross-session working state snapshot for cdx-brain.

Read/write a short Markdown file that captures the current session's
work-in-progress state. Written on Stop hook, read on SessionStart hook.

Zero LLM cost — pure file operations. Compatible with cc-star hot.md format.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any


# ── Default config keys ──

HOT_DEFAULT: dict[str, Any] = {
    "enabled": True,
    "path": "~/.cdx-brain/data/hot.md",
    "max_age_hours": 24,
    "max_tokens": 500,
}


# ── Helpers ──


def _resolve_path(raw: str) -> Path:
    """Resolve ~ and env vars, return absolute Path."""
    return Path(os.path.expanduser(os.path.expandvars(raw)))


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _is_expired(updated_at_str: str, max_age_hours: int) -> bool:
    """Check if hot.md is older than max_age_hours."""
    try:
        updated = datetime.fromisoformat(updated_at_str)
        age = datetime.now(timezone.utc) - updated
        return age > timedelta(hours=max_age_hours)
    except (ValueError, TypeError):
        return False


def _truncate(text: str, max_tokens: int) -> str:
    """Rough token-aware truncation (~4 chars per token for Chinese/English mix)."""
    if not text:
        return ""
    avg_chars_per_token = 4
    max_chars = max_tokens * avg_chars_per_token
    if len(text) <= max_chars:
        return text
    return text[:max_chars] + "\n\n...(truncated)"


def _parse_front_matter(text: str) -> dict[str, Any]:
    """Parse YAML-like front matter between --- markers."""
    result: dict[str, Any] = {}
    lines = text.strip().split("\n")
    if not lines or lines[0].strip() != "---":
        return result
    end_idx = -1
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            end_idx = i
            break
    if end_idx == -1:
        return result
    for line in lines[1:end_idx]:
        line = line.strip()
        if ":" in line:
            key, _, val = line.partition(":")
            result[key.strip()] = val.strip()
    return result


def _build_hot_content(state: dict[str, Any]) -> str:
    """Build hot.md content from state dict."""
    updated = state.get("updated_at", _now_iso())
    project = state.get("project", "")
    status = state.get("status", "in_progress")
    blocked = state.get("blocked", "")
    summary = state.get("summary", "")
    next_actions = state.get("next", "")
    todos = state.get("todos", [])

    lines = [
        "---",
        f"updated_at: {updated}",
    ]
    if project:
        lines.append(f"project: {project}")
    lines.append(f"status: {status}")
    if blocked:
        lines.append(f"blocked: {blocked}")
    if summary:
        lines.append(f"summary: {summary}")
    if next_actions:
        lines.append(f"next: {next_actions}")
    lines.append("---")
    lines.append("")
    if todos:
        lines.append("## 待办")
        for item in todos:
            checked = "x" if item.get("done") else " "
            lines.append(f"- [{checked}] {item.get('text', '')}")
        lines.append("")

    return "\n".join(lines)


# ── Public API ──


def read_hot(config: dict[str, Any] | None = None) -> dict[str, Any] | None:
    """Read hot.md and return parsed state, or None if absent/disabled.

    Returns a dict with keys: updated_at, project, status, blocked, summary,
    next, todos, body, expired, raw.
    """
    cfg = _resolve_config(config)
    if not cfg["enabled"]:
        return None

    path = _resolve_path(cfg["path"])
    if not path.is_file():
        return None

    try:
        raw = path.read_text(encoding="utf-8")
    except OSError:
        return None

    if not raw.strip():
        return None

    front = _parse_front_matter(raw)
    updated_at = front.get("updated_at", "")
    expired = _is_expired(updated_at, cfg["max_age_hours"]) if updated_at else False

    # Extract body (everything after second ---)
    body = raw
    parts = raw.split("---")
    if len(parts) >= 3:
        body = "---".join(parts[2:]).strip()

    result = {
        "updated_at": updated_at,
        "project": front.get("project", ""),
        "status": front.get("status", ""),
        "blocked": front.get("blocked", ""),
        "summary": front.get("summary", ""),
        "next": front.get("next", ""),
        "body": body,
        "expired": expired,
        "raw": raw,
    }

    # Truncate
    result["body_truncated"] = _truncate(body, cfg["max_tokens"])

    return result


def write_hot(
    state: dict[str, Any],
    config: dict[str, Any] | None = None,
) -> bool:
    """Write/update hot.md with current session state.

    Args:
        state: Dict with optional keys: project, status, blocked, summary,
               next, todos (list of {text, done}).
        config: cdx-brain config dict (optional, defaults loaded).

    Returns:
        True on success, False on failure.
    """
    cfg = _resolve_config(config)
    if not cfg["enabled"]:
        return False

    path = _resolve_path(cfg["path"])
    path.parent.mkdir(parents=True, exist_ok=True)

    state["updated_at"] = _now_iso()
    content = _build_hot_content(state)

    try:
        path.write_text(content, encoding="utf-8")
        return True
    except OSError:
        return False


def clear_hot(config: dict[str, Any] | None = None) -> bool:
    """Clear (empty) hot.md. User-invoked reset."""
    cfg = _resolve_config(config)
    if not cfg["enabled"]:
        return False
    path = _resolve_path(cfg["path"])
    try:
        if path.is_file():
            path.write_text("", encoding="utf-8")
        return True
    except OSError:
        return False


def _resolve_config(config: dict[str, Any] | None) -> dict[str, Any]:
    """Resolve hot config from config dict or defaults."""
    if config is not None:
        mem = config.get("memory", {})
        hot = mem.get("hot", {})
        return {
            "enabled": hot.get("enabled", HOT_DEFAULT["enabled"]),
            "path": hot.get("path", HOT_DEFAULT["path"]),
            "max_age_hours": hot.get("max_age_hours", HOT_DEFAULT["max_age_hours"]),
            "max_tokens": hot.get("max_tokens", HOT_DEFAULT["max_tokens"]),
        }
    return dict(HOT_DEFAULT)
