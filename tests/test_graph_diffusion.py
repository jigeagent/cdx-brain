"""Tests for GraphDiffusion — graph-aware retrieval."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone

from cdx_brain.retrieval.graph_diffusion import GraphDiffusion


def _seed_db(conn: sqlite3.Connection):
    conn.execute("""
        CREATE TABLE IF NOT EXISTS triples (
            id TEXT PRIMARY KEY, subject TEXT, predicate TEXT,
            object TEXT, confidence REAL, source_type TEXT,
            metadata TEXT, created_at TEXT, synced INTEGER
        )
    """)
    now = datetime.now(timezone.utc).isoformat()
    conn.executemany(
        "INSERT INTO triples VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0)",
        [
            ("p1:triggers:p2", "policy_tdd", "triggers", "policy_test_failure", 0.7, "policy", "{}", now),
            ("p2:relates_to:p3", "policy_test_failure", "relates_to", "concept_testing", 0.85, "policy:concept", "{}", now),
        ],
    )
    conn.commit()


def test_diffuse_direct():
    """Seed node returns direct neighbors."""
    conn = sqlite3.connect(":memory:")
    _seed_db(conn)
    gd = GraphDiffusion(conn)
    results = gd.diffuse(seed_ids=["policy_tdd"], max_depth=1)
    assert len(results) == 1
    assert results[0]["target_id"] == "policy_test_failure"
    assert results[0]["predicate"] == "triggers"
    assert results[0]["depth"] == 1
    conn.close()
    print("PASSED: test_diffuse_direct")


def test_diffuse_depth2():
    """Depth 2 reaches concept_testing via policy_test_failure."""
    conn = sqlite3.connect(":memory:")
    _seed_db(conn)
    gd = GraphDiffusion(conn)
    results = gd.diffuse(seed_ids=["policy_tdd"], max_depth=2)
    targets = {r["target_id"] for r in results}
    assert "concept_testing" in targets, f"Expected concept_testing, got {targets}"
    assert "policy_test_failure" in targets
    conn.close()
    print("PASSED: test_diffuse_depth2")


def test_diffuse_max_results():
    """Limits results."""
    conn = sqlite3.connect(":memory:")
    _seed_db(conn)
    gd = GraphDiffusion(conn)
    results = gd.diffuse(seed_ids=["policy_tdd"], max_depth=2, max_results=1)
    assert len(results) == 1
    conn.close()
    print("PASSED: test_diffuse_max_results")


def test_diffuse_empty_seed():
    """Empty seed returns empty."""
    conn = sqlite3.connect(":memory:")
    gd = GraphDiffusion(conn)
    results = gd.diffuse(seed_ids=[], max_depth=2)
    assert results == []
    conn.close()
    print("PASSED: test_diffuse_empty_seed")


if __name__ == "__main__":
    test_diffuse_direct()
    test_diffuse_depth2()
    test_diffuse_max_results()
    test_diffuse_empty_seed()
    print("ALL PASSED")
