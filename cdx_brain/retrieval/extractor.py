"""Relation extractor — discovers edges between policies and concepts.

Trigger edges (A->B) via fuzzy pattern matching on policy trigger_pattern,
and relates_to edges (undirected) via description similarity.
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone
from difflib import SequenceMatcher
from typing import Any

import sqlite3

from cdx_brain.memos.id import new_id

logger = logging.getLogger(__name__)


class RelationExtractor:
    """Extracts and persists triples (edges) between policies and concepts."""

    def __init__(self, conn: sqlite3.Connection):
        self._conn = conn
        self._conn.row_factory = sqlite3.Row
        self._ensure_triples_table()

    def _ensure_triples_table(self) -> None:
        self._conn.executescript("""
            CREATE TABLE IF NOT EXISTS triples (
                id          TEXT PRIMARY KEY,
                subject     TEXT NOT NULL,
                predicate   TEXT NOT NULL,
                object      TEXT NOT NULL,
                confidence  REAL NOT NULL DEFAULT 1.0,
                source_type TEXT NOT NULL DEFAULT '',
                metadata    TEXT NOT NULL DEFAULT '{}',
                created_at  TEXT NOT NULL,
                synced      INTEGER NOT NULL DEFAULT 0
            );
            CREATE INDEX IF NOT EXISTS idx_triples_subject ON triples(subject);
            CREATE INDEX IF NOT EXISTS idx_triples_predicate ON triples(predicate);
            CREATE INDEX IF NOT EXISTS idx_triples_object ON triples(object);
        """)
        self._conn.commit()

    # ── Public API ────────────────────────────────────────

    def extract(
        self,
        policies: list,
        concepts: list,
    ) -> int:
        """Discover edges and persist them to the triples table.

        Two edge types:
        - **triggers**: policy A's trigger_pattern fuzzy-matches policy B's name
        - **relates_to**: two items' description similarity > 0.3 (undirected)

        Returns count of new triples inserted.
        """
        count = 0
        now = datetime.now(timezone.utc).isoformat()
        seen = self._existing_keys()

        # ── triggers: policy A -> policy B ────────────────
        for a in policies:
            for b in policies:
                if a.id == b.id:
                    continue
                if not a.trigger_pattern or not b.name:
                    continue
                if self._fuzzy_match(a.trigger_pattern, b.name):
                    key = (a.id, "triggers", b.id)
                    if key not in seen:
                        self._conn.execute(
                            """INSERT INTO triples
                                (id, subject, predicate, object, confidence,
                                 source_type, metadata, created_at, synced)
                                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                            (
                                f"tri_{new_id(20)}",
                                a.id,
                                "triggers",
                                b.id,
                                0.7,
                                "policy_policy",
                                json.dumps({
                                    "trigger_pattern": a.trigger_pattern,
                                    "target_name": b.name,
                                }),
                                now,
                                0,
                            ),
                        )
                        seen.add(key)
                        count += 1

        # ── relates_to: undirected description similarity ─
        all_items: list[tuple[str, str, str]] = []
        seen_labels: set[str] = set()
        for p in policies:
            key_l = p.name or p.id
            if key_l not in seen_labels:
                all_items.append((p.id, p.name or p.description, p.description))
                seen_labels.add(key_l)
        for c in concepts:
            key_l = c.label or c.id
            if key_l not in seen_labels:
                all_items.append((c.id, c.label or c.description, c.description))
                seen_labels.add(key_l)

        for i in range(len(all_items)):
            for j in range(i + 1, len(all_items)):
                id_a, _, desc_a = all_items[i]
                id_b, _, desc_b = all_items[j]
                if not desc_a or not desc_b:
                    continue
                ratio = SequenceMatcher(None, desc_a, desc_b).ratio()
                if ratio > 0.3:
                    key_a = (id_a, "relates_to", id_b)
                    key_b = (id_b, "relates_to", id_a)
                    if key_a not in seen and key_b not in seen:
                        self._conn.execute(
                            """INSERT INTO triples
                                (id, subject, predicate, object, confidence,
                                 source_type, metadata, created_at, synced)
                                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                            (
                                f"tri_{new_id(20)}",
                                id_a,
                                "relates_to",
                                id_b,
                                round(ratio, 4),
                                "similarity",
                                json.dumps({"similarity": round(ratio, 4)}),
                                now,
                                0,
                            ),
                        )
                        seen.add(key_a)
                        seen.add(key_b)
                        count += 1

        if count:
            self._conn.commit()

        logger.info("RelationExtractor.extract: inserted %d new triples", count)
        return count

    def get_stats(self) -> dict[str, Any]:
        """Return summary statistics about the triple store."""
        total = self._conn.execute(
            "SELECT COUNT(*) AS cnt FROM triples"
        ).fetchone()
        total_edges = total["cnt"] if total else 0

        rows = self._conn.execute(
            "SELECT predicate, COUNT(*) AS cnt FROM triples GROUP BY predicate"
        ).fetchall()
        by_predicate: dict[str, int] = {}
        for r in rows:
            by_predicate[r["predicate"]] = r["cnt"]

        # Subjects that never appear in a relates_to edge
        all_subjects = self._conn.execute(
            "SELECT DISTINCT subject FROM triples"
        ).fetchall()
        relates_participants = self._conn.execute(
            "SELECT DISTINCT subject AS ent FROM triples WHERE predicate = 'relates_to' "            "UNION SELECT DISTINCT object AS ent FROM triples WHERE predicate = 'relates_to'"
        ).fetchall()
        relates_set = {r["ent"] for r in relates_participants}
        orphan_subjects = [
            r["subject"]
            for r in all_subjects
            if r["subject"] not in relates_set
        ]

        return {
            "total_edges": total_edges,
            "by_predicate": by_predicate,
            "orphan_subjects": orphan_subjects,
        }

    # ── Internal helpers ──────────────────────────────────

    @staticmethod
    def _fuzzy_match(trigger: str, target: str) -> bool:
        """Return True if trigger fuzzy-matches target.

        Criteria (either is sufficient):
        1. Substring match (case-insensitive)
        2. Token overlap >= 2 shared tokens
        """
        t_lower = trigger.lower().strip()
        p_lower = target.lower().strip()

        # Guard: empty strings always return False
        if not t_lower or not p_lower:
            return False

        # Substring match
        if t_lower in p_lower or p_lower in t_lower:
            return True

        # Token overlap: split on word chars (including underscores)
        t_tokens = set(re.findall(r"[a-zA-Z0-9]+(?:'[a-zA-Z]+)?", t_lower))
        p_tokens = set(re.findall(r"[a-zA-Z0-9]+(?:'[a-zA-Z]+)?", p_lower))

        shared = t_tokens & p_tokens
        return len(shared) >= 2

    def _existing_keys(self) -> set[tuple[str, str, str]]:
        """Return set of (subject, predicate, object) already stored."""
        rows = self._conn.execute(
            "SELECT subject, predicate, object FROM triples"
        ).fetchall()
        return {(r["subject"], r["predicate"], r["object"]) for r in rows}

