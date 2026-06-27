#!/usr/bin/env python3
"""
SessionStart Hook — cdx-brain session startup check.

Checks OV health + reads last session summary.
"""
from __future__ import annotations

import json
import os
import sys
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

    last = last_session_summary()
    if last:
        msg_parts.append(last)

    # Write health heartbeat
    try:
        health_file = SESSIONS_FILE.parent / ".cdx_brain_health"
        health_file.write_text(
            datetime.datetime.now(datetime.timezone.utc).isoformat(),
            encoding="utf-8"
        )
    except OSError:
        pass

    output = {"systemMessage": " | ".join(msg_parts)}
    json.dump(output, sys.stdout, ensure_ascii=False)


if __name__ == "__main__":
    main()
