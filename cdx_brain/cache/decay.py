"""Memory decay engine — cold storage for L2 traces, policy/skill decay, pipeline concept aging.

Three-tier decay policy:
- Trace decay: age-based → cold mark + FTS5 removal + optional archive
- Policy decay: confidence decay + inactivity → archive
- Pipeline decay: concept/triple aging + skill version pruning

Usage:
    python -m cdx_brain.cache.decay --db ~/.cdx-brain/data/cache.db --cold-db ~/.cdx-brain/data/cold.db
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

# ── Default thresholds ─────────────────────────────────────

TRACE_COLD_DAYS = 30       # Traces older than this get marked cold
TRACE_ARCHIVE_DAYS = 90    # Traces older than this get archived to cold.db
POLICY_DECAY_DAYS = 14     # Policies not activated in this many days lose confidence
POLICY_MIN_CONFIDENCE = 0.1  # Policies below this get archived
CONCEPT_DECAY_DAYS = 21    # Concepts not referenced in this many days lose weight

# ── Env overrides ──
_TRACE_COLD_DAYS = int(os.environ.get("CDX_BRAIN_DECAY_TRACE_COLD_DAYS", str(TRACE_COLD_DAYS)))
_TRACE_ARCHIVE_DAYS = int(os.environ.get("CDX_BRAIN_DECAY_TRACE_ARCHIVE_DAYS", str(TRACE_ARCHIVE_DAYS)))
_POLICY_DECAY_DAYS = int(os.environ.get("CDX_BRAIN_DECAY_POLICY_DAYS", str(POLICY_DECAY_DAYS)))
_CONCEPT_DECAY_DAYS = int(os.environ.get("CDX_BRAIN_DECAY_CONCEPT_DAYS", str(CONCEPT_DECAY_DAYS)))
_POLICY_MIN_CONFIDENCE = float(os.environ.get("CDX_BRAIN_DECAY_POLICY_MIN_CONFIDENCE", str(POLICY_MIN_CONFIDENCE)))


@dataclass
class DecayResult:
    """Summary of decay operations."""
    traces_cold: int = 0
    traces_archived: int = 0
    policies_decayed: int = 0
    policies_archived: int = 0
    concepts_decayed: int = 0
    cold_db_size: int = 0
    elapsed_ms: float = 0.0


def ensure_cold_schema(conn: sqlite3.Connection) -> None:
    """Create cold storage tables."""
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS cold_traces (
            id          TEXT PRIMARY KEY,
            session_id  TEXT NOT NULL,
            turn_index  INTEGER NOT NULL DEFAULT 0,
            user_content TEXT NOT NULL,
            assistant_content TEXT NOT NULL DEFAULT '',
            embedding   BLOB,
            reward      REAL NOT NULL DEFAULT 0.0,
            tags        TEXT DEFAULT '',
            metadata    TEXT DEFAULT '{}',
            created_at  TEXT NOT NULL,
            archived_at TEXT NOT NULL,
            archived_from TEXT DEFAULT ''
        );
        CREATE INDEX IF NOT EXISTS idx_cold_created ON cold_traces(created_at);
        CREATE INDEX IF NOT EXISTS idx_cold_archived ON cold_traces(archived_at);

        CREATE TABLE IF NOT EXISTS cold_policies (
            id              TEXT PRIMARY KEY,
            name            TEXT NOT NULL,
            description     TEXT NOT NULL DEFAULT '',
            trigger_pattern TEXT NOT NULL DEFAULT '',
            action_template TEXT NOT NULL DEFAULT '',
            confidence      REAL NOT NULL DEFAULT 0.0,
            activation_count INTEGER NOT NULL DEFAULT 0,
            source_trace_ids TEXT DEFAULT '[]',
            metadata        TEXT DEFAULT '{}',
            created_at      TEXT NOT NULL,
            archived_at     TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS decay_audit (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            run_at      TEXT NOT NULL,
            traces_cold INTEGER NOT NULL DEFAULT 0,
            traces_archived INTEGER NOT NULL DEFAULT 0,
            policies_decayed INTEGER NOT NULL DEFAULT 0,
            policies_archived INTEGER NOT NULL DEFAULT 0,
            concepts_decayed INTEGER NOT NULL DEFAULT 0,
            cold_db_size INTEGER NOT NULL DEFAULT 0,
            duration_ms REAL NOT NULL DEFAULT 0.0
        );
    """)
    conn.commit()


def _add_cold_column_if_needed(cache: "CacheConnection") -> None:
    """Add 'cold' column to traces if missing (migration)."""
    from cdx_brain.cache.connection import CacheConnection
    conn = cache.conn if isinstance(cache, CacheConnection) else cache
    try:
        conn.execute("ALTER TABLE traces ADD COLUMN cold INTEGER NOT NULL DEFAULT 0")
        conn.commit()
    except sqlite3.OperationalError:
        pass  # Column already exists


# ── Trace Decay ──────────────────────────────────────────


def _decay_traces(cache, cold_path: str, dry_run: bool = False) -> tuple[int, int, int]:
    """Mark old traces as cold, archive very old ones.

    Args:
        cache: CacheConnection or sqlite3.Connection.
        cold_path: Path to cold storage DB.
        dry_run: If True, only report, don't modify.

    Returns:
        (cold_count, archived_count, cold_db_size_bytes)
    """
    from cdx_brain.cache.connection import CacheConnection
    conn = cache.conn if isinstance(cache, CacheConnection) else cache

    _add_cold_column_if_needed(conn)

    now = datetime.now(timezone.utc)
    cold_cutoff = (now - timedelta(days=_TRACE_COLD_DAYS)).isoformat()
    archive_cutoff = (now - timedelta(days=_TRACE_ARCHIVE_DAYS)).isoformat()

    # Count cold candidates
    cold_count = conn.execute(
        "SELECT COUNT(*) FROM traces WHERE created_at < ? AND (cold IS NULL OR cold = 0)",
        (cold_cutoff,),
    ).fetchone()[0]

    archive_count = conn.execute(
        "SELECT COUNT(*) FROM traces WHERE created_at < ? AND (cold IS NULL OR cold = 0)",
        (archive_cutoff,),
    ).fetchone()[0]

    if dry_run:
        return cold_count, 0, 0

    # Mark cold
    if cold_count > 0:
        conn.execute(
            "UPDATE traces SET cold = 1 WHERE created_at < ? AND (cold IS NULL OR cold = 0)",
            (cold_cutoff,),
        )
        conn.commit()

    # Archive very old traces to cold.db
    archived = 0
    cold_db_size = 0
    if archive_count > 0 and cold_path:
        cold_rows = conn.execute(
            "SELECT id, session_id, turn_index, user_content, assistant_content, "
            "embedding, reward, tags, metadata, created_at "
            "FROM traces WHERE created_at < ? AND (cold IS NULL OR cold = 0)",
            (archive_cutoff,),
        ).fetchall()

        if cold_rows:
            cold_conn = sqlite3.connect(cold_path)
            try:
                ensure_cold_schema(cold_conn)
                now_str = now.isoformat()
                for row in cold_rows:
                    cold_conn.execute(
                        "INSERT OR IGNORE INTO cold_traces "
                        "(id, session_id, turn_index, user_content, assistant_content, "
                        "embedding, reward, tags, metadata, created_at, archived_at, archived_from) "
                        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        (*row, now_str, str(cache._db_path if hasattr(cache, '_db_path') else ""))
                    )
                cold_conn.commit()

                # Delete archived traces from main DB (triggers FTS5 cleanup)
                conn.execute(
                    "DELETE FROM traces WHERE created_at < ?",
                    (archive_cutoff,),
                )
                conn.commit()

                cold_db_size = Path(cold_path).stat().st_size if Path(cold_path).is_file() else 0
                archived = len(cold_rows)
            finally:
                cold_conn.close()

    # Mark remaining cold traces (already done above)
    return cold_count, archived, cold_db_size


# ── Policy Decay ─────────────────────────────────────────


def _decay_policies(cache, cold_path: str, dry_run: bool = False) -> tuple[int, int]:
    """Decay policy confidence over time, archive very low confidence ones.

    Args:
        cache: CacheConnection or sqlite3.Connection.
        cold_path: Path to cold storage DB.
        dry_run: If True, only report.

    Returns:
        (decayed_count, archived_count)
    """
    from cdx_brain.cache.connection import CacheConnection
    conn = cache.conn if isinstance(cache, CacheConnection) else cache

    now = datetime.now(timezone.utc)
    cutoff = (now - timedelta(days=_POLICY_DECAY_DAYS)).isoformat()

    # Reduce confidence for old policies
    decayed = conn.execute(
        "UPDATE policies SET confidence = MAX(confidence * 0.85, ?) "
        "WHERE created_at < ? AND activation_count < 3",
        (_POLICY_MIN_CONFIDENCE, cutoff),
    ).rowcount
    conn.commit()

    # Archive very low confidence policies
    archived = 0
    if cold_path:
        low_policies = conn.execute(
            "SELECT id, name, description, trigger_pattern, action_template, "
            "confidence, activation_count, source_trace_ids, metadata, created_at "
            "FROM policies WHERE confidence < ? AND activation_count < 1",
            (_POLICY_MIN_CONFIDENCE,),
        ).fetchall()

        if low_policies and not dry_run:
            cold_conn = sqlite3.connect(cold_path)
            try:
                ensure_cold_schema(cold_conn)
                now_str = now.isoformat()
                for row in low_policies:
                    cold_conn.execute(
                        "INSERT OR IGNORE INTO cold_policies "
                        "(id, name, description, trigger_pattern, action_template, "
                        "confidence, activation_count, source_trace_ids, metadata, created_at, archived_at) "
                        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        (*row, now_str)
                    )
                cold_conn.commit()

                # Remove archived policies from main DB
                conn.execute(
                    "DELETE FROM policies WHERE confidence < ? AND activation_count < 1",
                    (_POLICY_MIN_CONFIDENCE,),
                )
                conn.commit()
                archived = len(low_policies)
            finally:
                cold_conn.close()

    return decayed, archived


# ── Pipeline State Decay ──────────────────────────────────


def _decay_pipeline_state(state_path: str, dry_run: bool = False) -> int:
    """Decay pipeline concepts and triples based on age.

    Args:
        state_path: Path to pipeline_state.json.
        dry_run: If True, only report.

    Returns:
        Number of concepts decayed/removed.
    """
    path = Path(state_path)
    if not path.is_file():
        return 0

    try:
        state = json.loads(path.read_text("utf-8"))
    except (OSError, json.JSONDecodeError):
        return 0

    now = datetime.now(timezone.utc)
    cutoff = (now - timedelta(days=_CONCEPT_DECAY_DAYS)).isoformat()

    wm = state.get("world_model", {})
    concepts = wm.get("concepts", {})
    triples = wm.get("triples", {})

    removed_concepts = 0

    # Check concept ages - no created_at on concepts, mark for removal by session age
    # Simple heuristic: if concept has no member traces, it's stale
    stale_concepts = [
        cid for cid, c in concepts.items()
        if not c.get("member_trace_ids") and not c.get("member_policy_ids")
    ]

    # Also check by created_at if available
    for cid, c in concepts.items():
        created = c.get("created_at", "")
        if created and created < cutoff:
            if not c.get("member_trace_ids"):
                stale_concepts.append(cid)

    if stale_concepts and not dry_run:
        for cid in set(stale_concepts):
            concepts.pop(cid, None)
        # Also clean up orphan triples
        active_concept_ids = set(concepts.keys())
        stale_triples = [
            tid for tid, t in triples.items()
            if t.get("subject") not in active_concept_ids
            and t.get("object_") not in active_concept_ids
        ]
        for tid in stale_triples:
            triples.pop(tid, None)

        wm["concepts"] = concepts
        wm["triples"] = triples
        state["world_model"] = wm

        if not dry_run:
            path.write_text(json.dumps(state, ensure_ascii=False, default=str), encoding="utf-8")

        removed_concepts = len(set(stale_concepts))

    return removed_concepts


# ── Main Entry Point ─────────────────────────────────────


def run_decay(
    cache_path: str,
    cold_db_path: str = "",
    dry_run: bool = False,
    pipeline_state_path: str = "",
) -> DecayResult:
    """Run full memory decay pipeline.

    Args:
        cache_path: Path to main cache.db.
        cold_db_path: Path to cold storage DB (empty = skip archive).
        dry_run: Preview only, no modifications.
        pipeline_state_path: Path to pipeline_state.json (empty = no pipeline decay).

    Returns:
        DecayResult with counts.
    """
    t0 = time.time()

    if not os.path.isfile(cache_path):
        logger.warning("Cache DB not found: %s", cache_path)
        return DecayResult()

    from cdx_brain.cache.connection import CacheConnection
    cache = CacheConnection(cache_path)
    conn = cache.conn

    result = DecayResult()

    try:
        # 1. Trace decay
        cold, archived, cold_sz = _decay_traces(conn, cold_db_path, dry_run)
        result.traces_cold = cold
        result.traces_archived = archived
        result.cold_db_size = cold_sz

        # 2. Policy decay
        pol_decayed, pol_archived = _decay_policies(conn, cold_db_path, dry_run)
        result.policies_decayed = pol_decayed
        result.policies_archived = pol_archived

        # 3. Pipeline state decay
        if pipeline_state_path:
            result.concepts_decayed = _decay_pipeline_state(pipeline_state_path, dry_run)

        # 4. Audit log
        if not dry_run and cold_db_path and os.path.isfile(cold_db_path):
            cold_conn = sqlite3.connect(cold_db_path)
            try:
                ensure_cold_schema(cold_conn)
                cold_conn.execute(
                    "INSERT INTO decay_audit "
                    "(run_at, traces_cold, traces_archived, policies_decayed, "
                    "policies_archived, concepts_decayed, cold_db_size, duration_ms) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        datetime.now(timezone.utc).isoformat(),
                        cold, archived, pol_decayed, pol_archived,
                        result.concepts_decayed, cold_sz,
                        (time.time() - t0) * 1000,
                    )
                )
                cold_conn.commit()
            finally:
                cold_conn.close()

    finally:
        cache.close_all()

    result.elapsed_ms = (time.time() - t0) * 1000
    return result


def format_decay_report(result: DecayResult) -> str:
    """Format decay result as a human-readable report."""
    lines = [
        f"  Decay completed in {result.elapsed_ms:.0f}ms",
        f"  Traces: {result.traces_cold} cold, {result.traces_archived} archived",
    ]
    if result.policies_decayed > 0 or result.policies_archived > 0:
        lines.append(f"  Policies: {result.policies_decayed} decayed, {result.policies_archived} archived")
    if result.concepts_decayed > 0:
        lines.append(f"  Concepts: {result.concepts_decayed} removed")
    if result.cold_db_size > 0:
        lines.append(f"  Cold DB: {result.cold_db_size / 1024:.0f} KB")
    return "\n".join(lines)


# ── CLI helper ──


def get_default_paths() -> tuple[str, str, str]:
    """Get default cache, cold_db, and pipeline state paths."""
    home = Path.home() / ".cdx-brain" / "data"
    cache_path = str(home / "cache.db")
    cold_path = str(home / "cold.db")
    pipeline_state = str(home / "pipeline_state.json")
    return cache_path, cold_path, pipeline_state
