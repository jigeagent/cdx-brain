#!/usr/bin/env python3
"""
SessionStart Hook — cdx-brain session startup check.

Checks OV health + reads last session summary.
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

OV_URL = os.environ.get("CDX_BRAIN_OV_URL", "http://127.0.0.1:1933")
SESSIONS_FILE = Path(os.path.expanduser("C:/Users/Administrator/.cdx-brain/data/sessions.jsonl"))


def check_ov_health() -> bool:
    """Check OpenViking connectivity."""
    url = OV_URL
    if not url:
        return False
    try:
        import httpx
        r = httpx.get(f"{url}/health", timeout=2.0)
        return r.status_code == 200
    except Exception:
        return False


def last_session_summary() -> str | None:
    """Read last session info from sessions.jsonl."""
    if not SESSIONS_FILE.is_file():
        return None
    try:
        lines = SESSIONS_FILE.read_text(encoding="utf-8").strip().split("\n")
        if not lines:
            return None
        last = json.loads(lines[-1])
        prompt = last.get("first_prompt", "")
        turns = last.get("turn_count", 0)
        if prompt:
            return f"Last session: {turns} turns | {prompt[:60]}"
    except (OSError, json.JSONDecodeError):
        pass
    return None


def main() -> None:
    ov_ok = check_ov_health()
    msg_parts = []
    if ov_ok:
        msg_parts.append("OV:online")
    else:
        msg_parts.append("OV:offline (local mode)")

    # OV anchor --- write presence marker for cross-Agent visibility
    try:
        from cdx_brain.ov.client import OpenVikingClient
        import uuid
        _sid = str(uuid.uuid4())[:8]
        ovc = OpenVikingClient()
        anchor_lines = [
            "# kongshao active anchor",
            f"- last_active: {datetime.now(timezone.utc).isoformat()}",
            f"- session_id: {_sid}",
            "- status: active",
            "- host: codex",
        ]
        ovc.content_write(
            "viking://agent/comsam/workspace/HEARTBEAT/last-active.md",
            "\n".join(anchor_lines) + "\n",
        )
        ovc.close()
    except Exception:
        pass

    last = last_session_summary()
    if last:
        msg_parts.append(last)

    # Write health heartbeat
    try:
        health_file = SESSIONS_FILE.parent / ".cdx_brain_health"
        health_file.write_text(
            datetime.now(timezone.utc).isoformat(),
            encoding="utf-8"
        )
    except OSError:
        pass

    hot_info = _read_hot()
    if hot_info:
        msg_parts.append(hot_info)

    # Pattern counter status
    try:
        from cdx_brain.hot_counter import get_summary
        summary = get_summary()
        if summary:
            msg_parts.append(summary)
    except Exception:
        pass

    output = {"systemMessage": " | ".join(msg_parts)}
    json.dump(output, sys.stdout, ensure_ascii=False)


def _read_hot() -> str | None:
    """Read hot.md and return a formatted status string, or None."""
    try:
        from cdx_brain.hot import read_hot
        from cdx_brain.config import ConfigManager
        cfg = ConfigManager().load()
        state = read_hot(cfg)
        if not state:
            return None
        parts = []
        prefix = "(上次会话 24h+ 前) " if state.get("expired") else ""
        if state.get("summary"):
            parts.append(f"{prefix}Hot: {state['summary'][:80]}")
        if state.get("next"):
            parts.append(f"Next: {state['next'][:60]}")
        if state.get("blocked"):
            parts.append(f"Blocked: {state['blocked']}")
        return " | ".join(parts) if parts else None
    except Exception:
        return None
if __name__ == "__main__":
    main()

