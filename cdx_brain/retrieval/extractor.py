"""RelationExtractor — mine triple edges from promoted policies/concepts.

Runs at the end of process_session_end() to discover:
  - triggers:  A.trigger_pattern matches B.name (directional)
  - relates_to: A.description and B.description share significant overlap (undirected)
  - contradicts: A and B have opposite actions on the same trigger (rare, requires reward data)
"""

from __future__ import annotations

import json
import logging
import re
import sqlite3
from datetime import datetime, timezone
from typing import Any
from difflib import SequenceMatcher

logger = logging.getLogger(__name__)

# Standard edge types
EDGE_TRIGGERS = "triggers"
EDGE_RELATES_TO = "relates_to"
EDGE_CONTRADICTS = "contradicts"

_SQL_TRIPLES = """
    CREATE TABLE IF NOT EXISTS triples (
        id TEXT PRIMARY KEY,
        subject TEXT NOT NULL,
        predicate TEXT NOT NULL,
        object TEXT NOT NULL,
        confidence REAL NOT NULL DEFAULT 1.0,
        source_type TEXT DEFAULT '',
        metadata TEXT DEFAULT '{}',
        created_at TEXT NOT NULL,
        synced INTEGER NOT NULL DEFAULT 0
    );
    CREATE INDEX IF NOT EXISTS idx_triples_subject ON triples(subject);
    CREATE INDEX IF NOT EXISTS idx_triples_predicate ON triples(predicate);
    CREATE INDEX IF NOT EXISTS idx_triples_object ON triples(object);
"""


class RelationExtractor:
    """Extract relations from policies/concepts and persist to triples table."""

    def __init__(self, conn: sqlite3.Connection):
        self._conn = conn
        for statement in _SQL_TRIPLES.strip().split(";"):
            s = statement.strip()
            if s:
                self._conn.execute(s)
        self._conn.commit()

    def extract(
        self,
        policies: list[dict[str, Any]],
        concepts: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Run extraction across policies and concepts.

        Args:
            policies: List of promoted policy dicts.
            concepts: List of concept dicts.

        Returns:
            List of extracted relation dicts.
        """
        relations: list[dict[str, Any]] = []

        # --- Triggers: policy A triggers policy B if A.trigger_pattern matches B.name ---
        for pa in policies:
            pa_name = pa.get("name", "")
            pa_trigger = pa.get("trigger_pattern", "")
            pa_id = pa.get("id", "")
            if not pa_id:
                continue
            for pb in policies:
                pb_id = pb.get("id", "")
                pb_name = pb.get("name", "")
                if pa_id == pb_id or not pb_id:
                    continue
                if pa_trigger and pb_name and _fuzzy_match(pa_trigger, pb_name):
                    relations.append({
                        "subject": pa_id,
                        "predicate": EDGE_TRIGGERS,
                        "object": pb_id,
                        "confidence": 0.7,
                        "source_type": "policy",
                    })

        # --- Relates to: policies/concepts with overlapping descriptions ---
        items: list[tuple[str, str, str, str]] = []
        items.extend(
            (p.get("id", ""), p.get("name", ""), p.get("description", ""), "policy")
            for p in policies
        )
        items.extend(
            (c.get("id", ""), c.get("label", ""), c.get("description", ""), "concept")
            for c in concepts
        )

        for i, (id_a, name_a, desc_a, type_a) in enumerate(items):
            if not id_a:
                continue
            for j, (id_b, name_b, desc_b, type_b) in enumerate(items):
                if j <= i or not id_b:
                    continue
                if not desc_a or not desc_b:
                    continue
                sim = SequenceMatcher(None, desc_a.lower(), desc_b.lower()).ratio()
                if sim > 0.3:
                    relations.append({
                        "subject": id_a,
                        "predicate": EDGE_RELATES_TO,
                        "object": id_b,
                        "confidence": round(sim, 3),
                        "source_type": f"{type_a}:{type_b}",
                    })

        # --- Persist to DB ---
        now = datetime.now(timezone.utc).isoformat()
        for rel in relations:
            self._conn.execute(
                "INSERT OR REPLACE INTO triples "
                "(id, subject, predicate, object, confidence, source_type, metadata, created_at, synced) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0)",
                (
                    f"{rel['subject']}:{rel['predicate']}:{rel['object']}",
                    rel["subject"],
                    rel["predicate"],
                    rel["object"],
                    rel["confidence"],
                    rel.get("source_type", ""),
                    "{}",
                    now,
                ),
            )
        self._conn.commit()

        logger.info("RelationExtractor: %d relations extracted", len(relations))
        return relations

    def get_stats(self) -> dict[str, Any]:
        """Get graph statistics from triples table."""
        try:
            total = self._conn.execute("SELECT COUNT(*) FROM triples").fetchone()[0]
            by_predicate = self._conn.execute(
                "SELECT predicate, COUNT(*) as cnt FROM triples "
                "GROUP BY predicate ORDER BY cnt DESC"
            ).fetchall()
            orphan_count = self._conn.execute(
                "SELECT COUNT(DISTINCT t1.subject) FROM triples t1 "
                "WHERE NOT EXISTS (SELECT 1 FROM triples t2 WHERE t2.object = t1.subject)"
            ).fetchone()[0]
            return {
                "total_edges": total,
                "by_predicate": dict(by_predicate),
                "orphan_subjects": orphan_count,
            }
        except Exception:
            return {"total_edges": 0, "by_predicate": {}, "orphan_subjects": 0}


def _fuzzy_match(trigger: str, target: str) -> bool:
    """Check if trigger text approximately matches target name."""
    t_lower = trigger.lower()
    n_lower = target.lower().replace("_", " ").replace("-", " ")
    if n_lower in t_lower or t_lower in n_lower:
        return True
    t_tokens = set(re.findall(r"\w+", t_lower))
    n_tokens = set(re.findall(r"\w+", n_lower))
    if len(t_tokens & n_tokens) >= 2:
        return True
    return False
