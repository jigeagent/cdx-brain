"""Tests for RelationExtractor — policy/concept relation mining."""

from __future__ import annotations

import sqlite3

from cdx_brain.retrieval.extractor import RelationExtractor


def _make_policy(name: str, trigger: str = "", desc: str = "") -> dict:
    return {
        "id": f"policy_{name}",
        "name": name,
        "description": desc or f"Policy for {name}",
        "trigger_pattern": trigger or name,
        "action_template": f"Do {name}",
        "confidence": 0.8,
        "activation_count": 10,
        "metadata": {},
    }


def test_extract_triggers():
    """Two policies where trigger_pattern does not match each other."""
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE IF NOT EXISTS policies (id TEXT PRIMARY KEY, name TEXT)")
    conn.commit()

    extractor = RelationExtractor(conn)
    policies = [
        _make_policy("tdd_flow", trigger="tdd"),
        _make_policy("test_failure", trigger="test failure handling"),
    ]
    relations = extractor.extract(policies=policies, concepts=[])

    triggers = [r for r in relations if r["predicate"] == "triggers"]
    assert len(triggers) == 0, f"Expected 0 triggers, got {len(triggers)}: {triggers}"
    conn.close()
    print("PASSED: test_extract_triggers")


def test_extract_relates_to():
    """Two policies with overlapping descriptions."""
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE IF NOT EXISTS policies (id TEXT PRIMARY KEY, name TEXT)")
    conn.commit()

    extractor = RelationExtractor(conn)
    policies = [
        _make_policy("memory_retrieval", desc="How to retrieve from memory using vector search and ranking"),
        _make_policy("memory_ranking", desc="How to rank and rerank memory search results"),
    ]
    relations = extractor.extract(policies=policies, concepts=[])

    relates = [r for r in relations if r["predicate"] == "relates_to"]
    assert len(relates) >= 1, f"Expected relates_to edges, got {len(relates)}"
    conn.close()
    print("PASSED: test_extract_relates_to")


def test_get_stats():
    """Stats after inserting relations."""
    conn = sqlite3.connect(":memory:")
    extractor = RelationExtractor(conn)
    policies = [
        _make_policy("memory_retrieval", desc="Retrieve from memory"),
        _make_policy("memory_ranking", desc="Rank memory results"),
    ]
    extractor.extract(policies=policies, concepts=[])
    stats = extractor.get_stats()
    assert stats["total_edges"] >= 1
    conn.close()
    print("PASSED: test_get_stats")


if __name__ == "__main__":
    test_extract_triggers()
    test_extract_relates_to()
    test_get_stats()
    print("ALL PASSED")
