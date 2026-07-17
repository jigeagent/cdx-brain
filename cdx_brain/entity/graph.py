"""Entity relationship graph with spreading activation.

Nodes = entities, edges = relations (co-occur, same-session, etc).
Spreading activation walks the graph from seed entities with decay.
"""
from __future__ import annotations
import json
import sqlite3
from collections import deque
from datetime import datetime, timezone
from typing import Any


class EntityGraph:
    """Entity relationship graph backed by SQLite entity_edges table.

    Supports:
    - Add/update entities and edges
    - Spreading activation (BFS with decay)
    - Co-occurrence edge building
    - Retrieval for search augmentation
    """

    DECAY = 0.5
    MAX_DEPTH = 3

    def __init__(self, conn: sqlite3.Connection):
        self._conn = conn

    # ── Entity management ──

    def add_entity(self, entity_id: str, name: str, type_: str = "CONCEPT",
                   metadata: dict | None = None) -> None:
        self._conn.execute(
            "INSERT OR REPLACE INTO entities(id, name, type, metadata, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (entity_id, name, type_,
             json.dumps(metadata or {}, ensure_ascii=False),
             datetime.now(timezone.utc).isoformat()),
        )
        self._conn.commit()

    def get_entity_id(self, name: str) -> str | None:
        row = self._conn.execute(
            "SELECT id FROM entities WHERE name = ?", (name,)
        ).fetchone()
        return row[0] if row else None

    def get_or_create_entity(self, name: str) -> str:
        existing = self.get_entity_id(name)
        if existing:
            return existing
        import uuid
        eid = f"ent-{uuid.uuid4().hex[:12]}"
        self.add_entity(eid, name)
        return eid

    # ── Edge management ──

    def add_edge(self, source: str, target: str, relation: str = "co_occur",
                 weight: float = 1.0) -> None:
        self._conn.execute(
            "INSERT OR REPLACE INTO entity_edges(source, target, relation, weight, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (source, target, relation, weight,
             datetime.now(timezone.utc).isoformat()),
        )
        self._conn.commit()

    def ensure_bidirectional(self, a: str, b: str, relation: str = "co_occur",
                             weight: float = 1.0) -> None:
        self.add_edge(a, b, relation, weight)
        self.add_edge(b, a, relation, weight)

    def build_cooccurrence(self, entity_names: list[str]) -> None:
        """Build co-occurrence edges between all pairs in a list."""
        ids = []
        for name in entity_names:
            eid = self.get_or_create_entity(name)
            ids.append(eid)
        for i in range(len(ids)):
            for j in range(i + 1, len(ids)):
                self.ensure_bidirectional(ids[i], ids[j], "co_occur", 1.0)

    # ── Retrieval ──

    def get_connected(self, entity_id: str, relation: str | None = None,
                      max_results: int = 20) -> list[dict[str, Any]]:
        """Get directly connected entities with edge info."""
        if relation:
            rows = self._conn.execute(
                "SELECT e.id, e.name, e.type, ed.relation, ed.weight "
                "FROM entity_edges ed JOIN entities e ON e.id = ed.target "
                "WHERE ed.source = ? AND ed.relation = ? ORDER BY ed.weight DESC LIMIT ?",
                (entity_id, relation, max_results),
            ).fetchall()
        else:
            rows = self._conn.execute(
                "SELECT e.id, e.name, e.type, ed.relation, ed.weight "
                "FROM entity_edges ed JOIN entities e ON e.id = ed.target "
                "WHERE ed.source = ? ORDER BY ed.weight DESC LIMIT ?",
                (entity_id, max_results),
            ).fetchall()
        return [{"id": r[0], "name": r[1], "type": r[2],
                 "relation": r[3], "weight": r[4]} for r in rows]

    def spreading_activation(self, seed_ids: list[str],
                             max_depth: int = 3) -> list[dict[str, Any]]:
        """Walk graph from seeds with score decay per hop.

        Key differences from standard BFS:
        1. Score multiplied by DECAY (0.5) per hop
        2. Multiple paths to same node: keep max score
        3. Returns sorted by score descending
        """
        scores: dict[str, float] = {s: 1.0 for s in seed_ids}
        visited: set[str] = set(seed_ids)
        queue: deque = deque((s, 0, 1.0) for s in seed_ids)
        results: list[dict[str, Any]] = []

        while queue and len(results) < 50:
            node, depth, score = queue.popleft()
            if depth >= max_depth:
                continue

            rows = self._conn.execute(
                "SELECT ed.source, ed.target, ed.relation, ed.weight, "
                "e1.name AS src_name, e2.name AS tgt_name "
                "FROM entity_edges ed "
                "JOIN entities e1 ON e1.id = ed.source "
                "JOIN entities e2 ON e2.id = ed.target "
                "WHERE ed.source = ? OR ed.target = ?",
                (node, node),
            ).fetchall()

            for src, tgt, rel, w, src_name, tgt_name in rows:
                neighbor = tgt if src == node else src
                neighbor_name = tgt_name if src == node else src_name
                new_score = score * self.DECAY * w

                if neighbor not in visited or new_score > scores.get(neighbor, 0):
                    is_new = neighbor not in visited
                    visited.add(neighbor)
                    scores[neighbor] = max(scores.get(neighbor, 0), new_score)
                    results.append({
                        "from_id": node, "to_id": neighbor,
                        "to_name": neighbor_name,
                        "relation": rel, "score": round(new_score, 3),
                        "depth": depth + 1,
                        "new": is_new,
                    })
                    queue.append((neighbor, depth + 1, new_score))

        results.sort(key=lambda r: r["score"], reverse=True)
        return results

    def retrieve_for_query(self, seed_entities: list[str],
                           max_results: int = 8) -> list[dict[str, Any]]:
        """Retrieve graph-expanded results for a search query.

        Args:
            seed_entities: Entity name strings extracted from query.
            max_results: Max results to return.

        Returns:
            List of enriched results with path info.
        """
        if not seed_entities:
            return []
        seed_ids = [self.get_or_create_entity(name) for name in seed_entities]
        expanded = self.spreading_activation(seed_ids)
        return [{**r, "source": "graph"} for r in expanded[:max_results]]
