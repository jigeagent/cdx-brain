"""FTS5 storage engine for counterfactual memories."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
from cdx_brain.cache.connection import CacheConnection


@dataclass
class Counterfactual:
    """A record of a rejected/abandoned decision."""
    id: str
    subject: str
    chosen: str = ""
    rejected: str = ""
    reason: str = ""
    context: str = ""
    confidence: float = 0.0
    decided_by: str = ""
    tags: str = ""
    source_session: str = ""
    created_at: str = ""
    synced: int = 0


def ensure_counterfactual_schema(conn_or_cache) -> None:
    """Create counterfactuals FTS5 table if not exists."""
    conn = conn_or_cache.conn if hasattr(conn_or_cache, "conn") else conn_or_cache
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS counterfactuals (
            id              TEXT PRIMARY KEY,
            subject         TEXT NOT NULL,
            chosen          TEXT NOT NULL DEFAULT "",
            rejected        TEXT NOT NULL,
            reason          TEXT NOT NULL,
            context         TEXT NOT NULL DEFAULT "",
            confidence      REAL NOT NULL DEFAULT 0.0,
            decided_by      TEXT NOT NULL DEFAULT "",
            tags            TEXT DEFAULT "",
            source_session  TEXT NOT NULL DEFAULT "",
            created_at      TEXT NOT NULL,
            synced          INTEGER NOT NULL DEFAULT 0
        );

        CREATE INDEX IF NOT EXISTS idx_cf_subject
            ON counterfactuals(subject);
        CREATE INDEX IF NOT EXISTS idx_cf_confidence
            ON counterfactuals(confidence DESC);

        CREATE VIRTUAL TABLE IF NOT EXISTS counterfactuals_fts
            USING fts5(
                subject, chosen, rejected, reason, context,
                content="counterfactuals",
                content_rowid="rowid",
                tokenize="unicode61"
            );

        CREATE TRIGGER IF NOT EXISTS cf_ai AFTER INSERT ON counterfactuals BEGIN
            INSERT INTO counterfactuals_fts(rowid, subject, chosen, rejected, reason, context)
            VALUES (new.rowid, new.subject, new.chosen, new.rejected, new.reason, new.context);
        END;

        CREATE TRIGGER IF NOT EXISTS cf_ad AFTER DELETE ON counterfactuals BEGIN
            INSERT INTO counterfactuals_fts(counterfactuals_fts, rowid, subject, chosen, rejected, reason, context)
            VALUES ("delete", old.rowid, old.subject, old.chosen, old.rejected, old.reason, old.context);
        END;

        CREATE TRIGGER IF NOT EXISTS cf_au AFTER UPDATE ON counterfactuals BEGIN
            INSERT INTO counterfactuals_fts(counterfactuals_fts, rowid, subject, chosen, rejected, reason, context)
            VALUES ("delete", old.rowid, old.subject, old.chosen, old.rejected, old.reason, old.context);
            INSERT INTO counterfactuals_fts(rowid, subject, chosen, rejected, reason, context)
            VALUES (new.rowid, new.subject, new.chosen, new.rejected, new.reason, new.context);
        END;
    """)
    conn.commit()


def search_counterfactuals(conn_or_cache, query: str, limit: int = 5) -> list[dict]:
    """Search counterfactuals via FTS5 with LIKE fallback for CJK."""
    conn = conn_or_cache.conn if hasattr(conn_or_cache, "conn") else conn_or_cache
    ensure_counterfactual_schema(conn)
    results = []
    # FTS5 search
    try:
        rows = conn.execute("""
            SELECT c.id, c.subject, c.chosen, c.rejected, c.reason,
                   c.context, c.confidence, c.decided_by, c.tags,
                   c.source_session, c.created_at
            FROM counterfactuals_fts f
            JOIN counterfactuals c ON c.rowid = f.rowid
            WHERE counterfactuals_fts MATCH ?
            ORDER BY rank
            LIMIT ?
        """, (query, limit)).fetchall()
        if rows:
            results = [
                {
                    "id": r[0], "subject": r[1], "chosen": r[2],
                    "rejected": r[3], "reason": r[4], "context": r[5],
                    "confidence": r[6], "decided_by": r[7], "tags": r[8],
                    "source_session": r[9], "created_at": r[10],
                    "source": "counterfactual",
                }
                for r in rows
            ]
    except Exception:
        pass
    # Fallback: LIKE search on subject and reason
    if not results:
        try:
            like_q = "%" + query.replace("%", "%%") + "%"
            rows = conn.execute("""
                SELECT id, subject, chosen, rejected, reason, context,
                       confidence, decided_by, tags, source_session, created_at
                FROM counterfactuals
                WHERE subject LIKE ? OR reason LIKE ? OR rejected LIKE ?
                ORDER BY confidence DESC
                LIMIT ?
            """, (like_q, like_q, like_q, limit)).fetchall()
            results = [
                {
                    "id": r[0], "subject": r[1], "chosen": r[2],
                    "rejected": r[3], "reason": r[4], "context": r[5],
                    "confidence": r[6], "decided_by": r[7], "tags": r[8],
                    "source_session": r[9], "created_at": r[10],
                    "source": "counterfactual",
                }
                for r in rows
            ]
        except Exception:
            pass
    return results
    """Search counterfactuals via FTS5."""
    conn = conn_or_cache.conn if hasattr(conn_or_cache, "conn") else conn_or_cache
    ensure_counterfactual_schema(conn)
    try:
        rows = conn.execute("""
            SELECT c.id, c.subject, c.chosen, c.rejected, c.reason,
                   c.context, c.confidence, c.decided_by, c.tags,
                   c.source_session, c.created_at
            FROM counterfactuals_fts f
            JOIN counterfactuals c ON c.rowid = f.rowid
            WHERE counterfactuals_fts MATCH ?
            ORDER BY rank
            LIMIT ?
        """, (query, limit)).fetchall()
        return [
            {
                "id": r[0], "subject": r[1], "chosen": r[2],
                "rejected": r[3], "reason": r[4], "context": r[5],
                "confidence": r[6], "decided_by": r[7], "tags": r[8],
                "source_session": r[9], "created_at": r[10],
                "source": "counterfactual",
            }
            for r in rows
        ]
    except Exception:
        return []


def list_counterfactuals(conn_or_cache, subject: str = "", limit: int = 20) -> list[dict]:
    """List counterfactuals, optionally filtered by subject."""
    conn = conn_or_cache.conn if hasattr(conn_or_cache, "conn") else conn_or_cache
    ensure_counterfactual_schema(conn)
    if subject:
        rows = conn.execute("""
            SELECT id, subject, chosen, rejected, reason, confidence,
                   decided_by, tags, source_session, created_at
            FROM counterfactuals
            WHERE subject LIKE ?
            ORDER BY confidence DESC, created_at DESC
            LIMIT ?
        """, (f"%{subject}%", limit)).fetchall()
    else:
        rows = conn.execute("""
            SELECT id, subject, chosen, rejected, reason, confidence,
                   decided_by, tags, source_session, created_at
            FROM counterfactuals
            ORDER BY created_at DESC
            LIMIT ?
        """, (limit,)).fetchall()
    return [
        {"id": r[0], "subject": r[1], "chosen": r[2], "rejected": r[3],
         "reason": r[4], "confidence": r[5], "decided_by": r[6],
         "tags": r[7], "source_session": r[8], "created_at": r[9]}
        for r in rows
    ]


def count_counterfactuals(conn_or_cache) -> dict:
    """Get counterfactual statistics."""
    conn = conn_or_cache.conn if hasattr(conn_or_cache, "conn") else conn_or_cache
    ensure_counterfactual_schema(conn)
    total = conn.execute("SELECT COUNT(*) FROM counterfactuals").fetchone()[0]
    by_decider = conn.execute("""
        SELECT decided_by, COUNT(*) FROM counterfactuals
        GROUP BY decided_by ORDER BY COUNT(*) DESC
    """).fetchall()
    top_subjects = conn.execute("""
        SELECT subject, COUNT(*) as cnt FROM counterfactuals
        GROUP BY subject ORDER BY cnt DESC LIMIT 10
    """).fetchall()
    return {
        "total": total,
        "by_decider": dict(by_decider),
        "top_subjects": [{"subject": r[0], "count": r[1]} for r in top_subjects],
    }
