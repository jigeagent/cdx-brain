#!/usr/bin/env python3
"""
SessionEnd Hook — cdx-brain session summary + batch sync.

Extracts session summary from transcript -> saves sessions.jsonl -> batch syncs unsynced traces to OV.
"""
from __future__ import annotations

import sys
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")


import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from cdx_brain.cache.connection import CacheConnection
from cdx_brain.cache.schema import ensure_schema
from cdx_brain.cache.traces import TraceRepository

CACHE_PATH = os.path.expanduser("C:/Users/Administrator/.cdx-brain/data/cache.db")
OV_URL = os.environ.get("CDX_BRAIN_OV_URL", "http://127.0.0.1:1933")
OV_ENABLED = os.environ.get("CDX_BRAIN_OV_ENABLED", "$ov_enabled") in ("1", "true", "True")
SESSIONS_FILE = Path(os.path.expanduser("C:/Users/Administrator/.cdx-brain/data/sessions.jsonl"))
SYNC_BATCH_SIZE = 50


def extract_session_info(transcript_path: str) -> dict | None:
    """Extract first/last prompt, turn count, timestamps from transcript."""
    if not transcript_path or not os.path.isfile(transcript_path):
        return None

    try:
        with open(transcript_path, "r", encoding="utf-8") as f:
            content = f.read()
    except OSError:
        return None

    lines = [l.strip() for l in content.split("\n") if l.strip()]
    if not lines:
        return None

    first_prompt = None
    last_prompt = None
    turn_count = 0
    first_ts = None
    last_ts = None

    for line in lines:
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue

        # Timestamps
        ts = entry.get("timestamp") or entry.get("created_at", "")
        if ts:
            if not first_ts:
                first_ts = ts
            last_ts = ts

        # Turn count
        if entry.get("type") == "system" and entry.get("subtype") == "turn_duration":
            turn_count += 1

        # User messages
        if entry.get("type") == "user":
            msg = entry.get("message", {})
            content = msg.get("content", "")
            if isinstance(content, str) and content.strip():
                if not first_prompt:
                    first_prompt = content.strip()[:200]
                last_prompt = content.strip()[:200]

        # Flat format
        if entry.get("role") == "user" and entry.get("content"):
            content = str(entry["content"]).strip()
            if content:
                if not first_prompt:
                    first_prompt = content[:200]
                last_prompt = content[:200]

    return {
        "first_prompt": first_prompt or "",
        "last_prompt": last_prompt or "",
        "turn_count": turn_count,
        "first_timestamp": first_ts or "",
        "last_timestamp": last_ts or "",
    }


def save_session_info(info: dict) -> None:
    """Append session summary to sessions.jsonl."""
    try:
        SESSIONS_FILE.parent.mkdir(parents=True, exist_ok=True)
        record = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "first_prompt": info["first_prompt"],
            "turn_count": info["turn_count"],
        }
        with open(SESSIONS_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    except OSError:
        pass



# -- Cognitive Pipeline: full processing at session end --


def _run_pipeline(all_traces, cache_path):
    """Load pipeline state, run session_end processing, save state."""
    if not all_traces:
        return {}
    try:
        from cdx_brain.memos.pipeline import CognitivePipeline
        pipe = CognitivePipeline.load_state(str(Path(cache_path).parent))
        for t in all_traces:
            pipe.process_trace(t)
        pipe.process_session_end(all_traces)
        pipe.save_state(str(Path(cache_path).parent))
        stats = pipe.get_stats()
        sys.stderr.write(f"[summary] pipeline: "
            f"{stats.get('policies', 0)} policies, "
            f"{stats.get('skills', 0)} skills, "
            f"{stats.get('concepts', 0)} concepts, "
            f"sessions={stats.get('traces_processed', 0)}\n")
        return stats
    except Exception as e:
        import sys, traceback
        sys.stderr.write(f"[summary] pipeline error: {e}\n")
        traceback.print_exc()
        return {}


def sync_unsynced_traces(repo: TraceRepository) -> tuple[int, int]:
    """Batch sync unsynced traces to OpenViking."""
    if not OV_URL or not OV_ENABLED:
        return 0, 0
    try:
        from cdx_brain.ov.client import OpenVikingClient
        client = OpenVikingClient(base_url=OV_URL, timeout=5.0)
    except Exception as e:
        print(f"[summary] OV client init error: {e}", file=sys.stderr)
        return 0, 0

    synced = 0
    errors = 0
    while True:
        batch = repo.get_unsynced(limit=SYNC_BATCH_SIZE)
        if not batch:
            break
        for trace in batch:
            try:
                uri = f"viking://resources/comsam/traces/{trace.id}.json"
                client.content_write(uri, trace.to_dict())
                synced += 1
            except Exception as e:
                print(f"[summary] sync error {trace.id}: {e}", file=sys.stderr)
                errors += 1
        repo.mark_synced_batch([t.id for t in batch if t.id])
        time.sleep(0.05)

    return synced, errors


def main() -> None:
    """Main hook handler."""
    try:
        input_data = json.loads(sys.stdin.read())
    except json.JSONDecodeError:
        sys.exit(0)

    transcript_path = input_data.get("transcript_path", "")
    info = extract_session_info(transcript_path)

    if info and info["first_prompt"]:
        save_session_info(info)
        sys.stderr.write(
            f"[summary] session: {info['turn_count']} turns, "
            f"first: {info['first_prompt'][:40]}...\n"
        )

    # Lightweight memory decay (run every ~10 sessions)
    try:
        import random
        if random.random() < 0.1:
            from cdx_brain.cache.decay import run_decay
            dr = run_decay(
                cache_path=CACHE_PATH,
                cold_db_path=str(Path(CACHE_PATH).parent / "cold.db"),
                dry_run=False,
                pipeline_state_path=str(Path(CACHE_PATH).parent / "pipeline_state.json"),
            )
            if dr.traces_cold > 0 or dr.policies_decayed > 0:
                print(f"[summary] decay: {dr.traces_cold} cold, {dr.policies_decayed} policies", file=sys.stderr)
    except Exception:
        pass

    # Batch sync unsynced traces
    try:
        cache = CacheConnection(CACHE_PATH)
        ensure_schema(cache)
        repo = TraceRepository(cache)
        synced, errors = sync_unsynced_traces(repo)
        if synced or errors:
            sys.stderr.write(f"[summary] OV sync: {synced} ok, {errors} err\n")
        cache.close_all()
    except Exception as e:
        print(f"[summary] sync error: {e}", file=sys.stderr)



if __name__ == "__main__":
    main()
