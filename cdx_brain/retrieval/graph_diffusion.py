"""GraphDiffusion — BFS graph traversal for retrieval augmentation.

Given seed node IDs (from FTS5/embedding hits), walk the triples table
along edges to depth 1-2 and return related nodes with path descriptions.
"""

from __future__ import annotations

import logging
import sqlite3
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class DiffuseResult:
    """A single graph-diffused result."""

    target_id: str
    predicate: str
    depth: int
    confidence: float
    path: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "target_id": self.target_id,
            "predicate": self.predicate,
            "depth": self.depth,
            "confidence": self.confidence,
            "path": self.path,
            "source": "graph_diffusion",
        }


class GraphDiffusion:
    """BFS-based graph diffusion from seed nodes."""

    def __init__(self, conn: sqlite3.Connection):
        self._conn = conn

    def diffuse(
        self,
        seed_ids: list[str],
        max_depth: int = 2,
        max_results: int = 10,
        min_confidence: float = 0.5,
    ) -> list[dict[str, Any]]:
        """Walk the triples graph from seed nodes.

        Args:
            seed_ids: Starting node IDs (from retrieval hits).
            max_depth: Max BFS depth (default 2).
            max_results: Max results to return.
            min_confidence: Minimum edge confidence threshold.

        Returns:
            List of DiffuseResult dicts, sorted by depth then confidence.
        """
        if not seed_ids:
            return []

        visited: set[str] = set(seed_ids)
        results: list[DiffuseResult] = []
        queue: list[tuple[str, int, list[str]]] = [(s, 0, [s]) for s in seed_ids]

        while queue and len(results) < max_results:
            current_id, depth, path = queue.pop(0)

            if depth >= max_depth:
                continue

            # Forward edges: current_id is subject
            rows = self._conn.execute(
                "SELECT predicate, object, confidence FROM triples "
                "WHERE subject = ? AND confidence >= ?",
                (current_id, min_confidence),
            ).fetchall()

            for predicate, obj_id, confidence in rows:
                if obj_id not in visited:
                    visited.add(obj_id)
                    new_path = path + [predicate, obj_id]
                    results.append(DiffuseResult(
                        target_id=obj_id,
                        predicate=predicate,
                        depth=depth + 1,
                        confidence=confidence,
                        path=new_path,
                    ))
                    queue.append((obj_id, depth + 1, new_path))

            # Reverse edges: current_id is object (incoming)
            rows = self._conn.execute(
                "SELECT subject, predicate, confidence FROM triples "
                "WHERE object = ? AND confidence >= ?",
                (current_id, min_confidence),
            ).fetchall()

            for subj_id, predicate, confidence in rows:
                if subj_id not in visited:
                    visited.add(subj_id)
                    new_path = path + [f"~{predicate}", subj_id]
                    results.append(DiffuseResult(
                        target_id=subj_id,
                        predicate=f"~{predicate}",
                        depth=depth + 1,
                        confidence=confidence,
                        path=new_path,
                    ))
                    queue.append((subj_id, depth + 1, new_path))

        results.sort(key=lambda r: (r.depth, -r.confidence))
        return [r.to_dict() for r in results[:max_results]]
