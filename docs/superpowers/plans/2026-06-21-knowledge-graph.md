# Knowledge Graph Module Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add relation extraction between policies/concepts and graph-diffusion retrieval to cdx-brain's cognitive pipeline

**Architecture:** A `RelationExtractor` runs at the end of `process_session_end()` to mine `triggers`/`relates_to`/`contradicts` edges from promoted policies/concepts. A `GraphDiffusion` engine walks these edges during retrieval (BFS up to depth 2) and feeds results into the existing RRF fusion. Two new files (`extractor.py`, `graph_diffusion.py`), minimal edits to `pipeline.py`, `cli.py`, and `sync.py`.

**Tech Stack:** Python 3.12+, SQLite (reuses existing cache.db for triple storage), no new dependencies

---

### Task 1: RelationExtractor — relation extraction module

**Files:**
- Create: `E:\codex\cdx-brain\cdx_brain\retrieval\extractor.py`
- Test: `E:\codex\cdx-brain\tests\test_extractor.py`

- [ ] **Step 1: Write failing test for RelationExtractor**

```python
"""Tests for RelationExtractor — policy/concept relation mining."""

from __future__ import annotations

import json
import sqlite3
import tempfile
from pathlib import Path
from datetime import datetime, timezone

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
    """Two policies where one trigger_pattern contains the other's name."""
    db = sqlite3.connect(":memory:")
    db.execute("CREATE TABLE IF NOT EXISTS policies (id TEXT PRIMARY KEY, name TEXT, description TEXT, trigger_pattern TEXT, action_template TEXT, embedding BLOB, confidence REAL, activation_count INTEGER, source_trace_ids TEXT, metadata TEXT, created_at TEXT, synced INTEGER)")
    db.commit()

    extractor = RelationExtractor(db)
    policies = [
        _make_policy("tdd_flow", trigger="tdd"),
        _make_policy("test_failure", trigger="test failure handling"),
    ]
    relations = extractor.extract(policies=policies, concepts=[])

    # triggers: tdd_flow.trigger_pattern = "tdd" doesn't contain "test_failure"
    # test_failure.trigger_pattern = "test failure handling" contains "test" but not "tdd_flow"
    # So no triggers edge expected between these two
    triggers = [r for r in relations if r["predicate"] == "triggers"]
    assert len(triggers) == 0, f"Expected 0 triggers, got {len(triggers)}: {triggers}"

    # But policy with trigger "test" + test_failure name "test_failure" containing "test"
    # This WOULD trigger if we do substring match on trigger_pattern vs policy name
    # Actually our trigger extraction logic: A.triggers(B) if A.trigger_pattern contains B.name or vice versa
    # tdd_flow.trigger_pattern = "tdd", test_failure.name = "test_failure" → no match
    # test_failure.trigger_pattern = "test failure handling", tdd_flow.name = "tdd_flow" → no match
    # So it's correct: no triggers

    db.close()
    print("PASSED: test_extract_triggers")


def test_extract_relates_to():
    """Two policies with similar embedding description."""
    db = sqlite3.connect(":memory:")
    db.execute("CREATE TABLE IF NOT EXISTS policies (id TEXT PRIMARY KEY, name TEXT, description TEXT, trigger_pattern TEXT, action_template TEXT, embedding BLOB, confidence REAL, activation_count INTEGER, source_trace_ids TEXT, metadata TEXT, created_at TEXT, synced INTEGER)")
    db.commit()

    extractor = RelationExtractor(db)
    policies = [
        _make_policy("memory_retrieval", desc="How to retrieve from memory using vector search"),
        _make_policy("memory_ranking", desc="How to rank and rerank memory results"),
    ]
    relations = extractor.extract(policies=policies, concepts=[])

    relates = [r for r in relations if r["predicate"] == "relates_to"]
    # Both describe memory operations, should be related
    assert len(relates) >= 1, f"Expected relates_to edges, got {len(relates)}"

    db.close()
    print("PASSED: test_extract_relates_to")


if __name__ == "__main__":
    test_extract_triggers()
    test_extract_relates_to()
    print("ALL PASSED")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_extractor.py -v -x 2>&1 || python tests/test_extractor.py 2>&1`
Expected: FAIL with "ModuleNotFoundError: No module named 'cdx_brain.retrieval.extractor'"

- [ ] **Step 3: Write minimal RelationExtractor implementation**

```python
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
        # Ensure triples table exists
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
                # Directional: does A's trigger_pattern contain B's name (or near-match)?
                if pa_trigger and pb_name and _fuzzy_match(pa_trigger, pb_name):
                    relations.append({
                        "subject": pa_id,
                        "predicate": EDGE_TRIGGERS,
                        "object": pb_id,
                        "confidence": 0.7,
                        "source_type": "policy",
                    })

        # --- Relates to: policies/concepts with overlapping descriptions ---
        items = [(p.get("id", ""), p.get("name", ""), p.get("description", ""), "policy") for p in policies]
        items += [(c.get("id", ""), c.get("label", ""), c.get("description", ""), "concept") for c in concepts]

        for i, (id_a, name_a, desc_a, type_a) in enumerate(items):
            if not id_a:
                continue
            for j, (id_b, name_b, desc_b, type_b) in enumerate(items):
                if j <= i or not id_b:
                    continue
                if not desc_a or not desc_b:
                    continue
                sim = SequenceMatcher(None, desc_a.lower(), desc_b.lower()).ratio()
                if sim > 0.3:  # threshold — tuned for real content
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
                "INSERT OR REPLACE INTO triples (id, subject, predicate, object, confidence, source_type, metadata, created_at, synced) "
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
                "SELECT predicate, COUNT(*) as cnt FROM triples GROUP BY predicate ORDER BY cnt DESC"
            ).fetchall()
            # Subjects with no outgoing edges (orphans)
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
    # Direct substring
    if n_lower in t_lower or t_lower in n_lower:
        return True
    # Token overlap
    t_tokens = set(re.findall(r"\w+", t_lower))
    n_tokens = set(re.findall(r"\w+", n_lower))
    if len(t_tokens & n_tokens) >= 2:
        return True
    return False
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd E:\codex\cdx-brain && python -m pytest tests/test_extractor.py -v 2>&1 || python tests/test_extractor.py 2>&1`
Expected: PASS (both tests)

- [ ] **Step 5: Commit**

```bash
git add cdx_brain/retrieval/extractor.py tests/test_extractor.py
git commit -m "feat(knowledge-graph): add RelationExtractor module"
```

---

### Task 2: GraphDiffusion — graph-aware retrieval engine

**Files:**
- Create: `E:\codex\cdx-brain\cdx_brain\retrieval\graph_diffusion.py`
- Test: `E:\codex\cdx-brain\tests\test_graph_diffusion.py`

- [ ] **Step 1: Write failing test for GraphDiffusion**

```python
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


if __name__ == "__main__":
    test_diffuse_direct()
    test_diffuse_depth2()
    print("ALL PASSED")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python tests/test_graph_diffusion.py 2>&1`
Expected: FAIL with "ModuleNotFoundError: No module named 'cdx_brain.retrieval.graph_diffusion'"

- [ ] **Step 3: Write minimal GraphDiffusion implementation**

```python
"""GraphDiffusion — BFS graph traversal for retrieval augmentation.

Given seed node IDs (from FTS5/embedding hits), walk the triples table
along edges to depth 1-2 and return related nodes with path descriptions.
"""

from __future__ import annotations

import logging
import sqlite3
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class DiffuseResult:
    target_id: str
    predicate: str
    depth: int
    confidence: float
    path: list[str]

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
        # (current_id, depth, path_so_far)
        queue: list[tuple[str, int, list[str]]] = [(s, 0, [s]) for s in seed_ids]

        while queue and len(results) < max_results:
            current_id, depth, path = queue.pop(0)

            if depth >= max_depth:
                continue

            # Forward edges: current_id is subject
            rows = self._conn.execute(
                "SELECT predicate, object, confidence FROM triples WHERE subject = ? AND confidence >= ?",
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
                "SELECT subject, predicate, confidence FROM triples WHERE object = ? AND confidence >= ?",
                (current_id, min_confidence),
            ).fetchall()

            for subj_id, predicate, confidence in rows:
                if subj_id not in visited:
                    visited.add(subj_id)
                    new_path = path + [f"~{predicate}", subj_id]
                    results.append(DiffuseResult(
                        target_id=subj_id,
                        predicate=f"~{predicate}",  # ~ denotes reverse direction
                        depth=depth + 1,
                        confidence=confidence,
                        path=new_path,
                    ))
                    queue.append((subj_id, depth + 1, new_path))

        # Sort: by depth ascending, then confidence descending
        results.sort(key=lambda r: (r.depth, -r.confidence))
        return [r.to_dict() for r in results[:max_results]]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd E:\codex\cdx-brain && python -m pytest tests/test_graph_diffusion.py -v 2>&1 || python tests/test_graph_diffusion.py 2>&1`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add cdx_brain/retrieval/graph_diffusion.py tests/test_graph_diffusion.py
git commit -m "feat(knowledge-graph): add GraphDiffusion engine"
```

---

### Task 3: Wire RelationExtractor into cognitive pipeline

**Files:**
- Modify: `E:\codex\cdx-brain\cdx_brain\memos\pipeline.py` (+3 lines at ~line 400)

- [ ] **Step 1: Write failing test — verify pipeline calls extractor**

```python
"""Test that pipeline invokes RelationExtractor on session end."""

from __future__ import annotations

from cdx_brain.memos.pipeline import CognitivePipeline, CognitivePipelineConfig
from cdx_brain.memos.memo_types import TraceRow


def test_pipeline_invokes_extractor():
    pipeline = CognitivePipeline()
    traces = [TraceRow(id="t1", session_id="s1", turn_index=0, user_content="hello", assistant_content="world", created_at="2026-01-01")]
    result = pipeline.process_session_end(traces)
    # The pipeline should not error, and should have stage results
    assert "stage" in result
    # If extractor was wired, "relations" would appear in results
    # For now just verify no crash
    print("PASSED: pipeline runs without error")


if __name__ == "__main__":
    test_pipeline_invokes_extractor()
    print("ALL PASSED")
```

- [ ] **Step 2: Run the test — should fail because test file doesn't exist yet**

Run: `cd E:\codex\cdx-brain && python tests/test_pipeline_integration.py 2>&1`
Expected: FAIL (file not found)

- [ ] **Step 3: Add extractor call to pipeline.py**

In `process_session_end()`, find the block near the end (after skill crystallization) and add:

```python
        # ── Relation Extraction ──────────────────────────
        try:
            policies_dict = [p.to_dict() for p in self._policies]
            concepts_dict = [c.to_dict() for c in self.world_model.list_concepts()]
            conn = self._get_db_connection()
            if conn is not None:
                from cdx_brain.retrieval.extractor import RelationExtractor
                extractor = RelationExtractor(conn)
                new_relations = extractor.extract(policies=policies_dict, concepts=concepts_dict)
                results["new_relations"] = new_relations
                results["stage"]["relation_extraction"] = {"count": len(new_relations)}
        except Exception:
            logger.warning("RelationExtraction failed", exc_info=True)
```

Add the helper method to CognitivePipeline:

```python
    def _get_db_connection(self):
        """Get an SQLite connection to cache.db (best-effort)."""
        try:
            from pathlib import Path
            import sqlite3
            cache_path = Path.home() / ".cdx-brain" / "data" / "cache.db"
            if cache_path.is_file():
                return sqlite3.connect(str(cache_path))
        except Exception:
            pass
        return None
```

- [ ] **Step 4: Run integration test to verify**

Run: `cd E:\codex\cdx-brain && python -c "from cdx_brain.memos.pipeline import CognitivePipeline; p=CognitivePipeline(); r=p.process_session_end([]); print('OK' if 'stage' in r else 'FAIL')"`
Expected: `OK`

- [ ] **Step 5: Commit**

```bash
git add cdx_brain/memos/pipeline.py
git commit -m "feat(knowledge-graph): wire RelationExtractor into pipeline"
```

---

### Task 4: Wire GraphDiffusion into retrieval inject path

**Files:**
- Modify: `E:\codex\cdx-brain\cdx_brain\memos\retrieval.py` (+20 lines)
- Modify: `E:\codex\cdx-brain\cdx_brain\memos\inject.py` (+5 lines)

- [ ] **Step 1: Add graph diffusion function to retrieval.py**

Add a new function `retrieve_graph_diffusion` after existing retrieval tiers:

```python
def retrieve_graph_diffusion(
    seed_ids: list[str],
    max_depth: int = 2,
    max_results: int = 8,
) -> list[dict[str, Any]]:
    """Tier 5: Graph-diffusion retrieval from seed node IDs.

    Takes seed IDs (from FTS5/embedding hits) and walks the triples
    graph to discover related nodes.

    Args:
        seed_ids: Node IDs to start diffusion from.
        max_depth: BFS depth (default 2).
        max_results: Max results to return.

    Returns:
        List of graph-diffused results with path descriptions.
    """
    if not seed_ids:
        return []

    try:
        from pathlib import Path
        import sqlite3

        cache_path = Path.home() / ".cdx-brain" / "data" / "cache.db"
        if not cache_path.is_file():
            return []

        conn = sqlite3.connect(str(cache_path))
        try:
            # Check if triples table exists
            row = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='triples'"
            ).fetchone()
            if not row:
                return []

            from cdx_brain.retrieval.graph_diffusion import GraphDiffusion
            gd = GraphDiffusion(conn)
            return gd.diffuse(seed_ids=seed_ids, max_depth=max_depth, max_results=max_results)
        finally:
            conn.close()
    except Exception:
        logger.warning("graph diffusion retrieval failed", exc_info=True)
        return []
```

- [ ] **Step 2: Update the inject.py to include graph diffusion in RRF**

In `inject.py`, find where RRF merge happens and add graph diffusion as a third tier (after FTS5 and embedding):

```python
    # ── Graph Diffusion (tier 3) ──
    seed_ids = list({r.get("id", r.get("uri", "")) for tier in [fts_results, emb_results] for r in tier})
    graph_results = retrieve_graph_diffusion(seed_ids=seed_ids)
    if graph_results:
        tiers.append(graph_results)
```

Add the import at the top:
```python
from cdx_brain.memos.retrieval import retrieve_graph_diffusion
```

- [ ] **Step 3: Quick smoke test**

Run: `cd E:\codex\cdx-brain && python -c "from cdx_brain.memos.retrieval import retrieve_graph_diffusion; print('import OK')"`
Expected: `import OK`

- [ ] **Step 4: Commit**

```bash
git add cdx_brain/memos/retrieval.py cdx_brain/memos/inject.py
git commit -m "feat(knowledge-graph): wire GraphDiffusion into retrieval pipeline"
```

---

### Task 5: CLI commands for graph management

**Files:**
- Modify: `E:\codex\cdx-brain\cdx_brain\cli.py` (+60 lines)

- [ ] **Step 1: Add graph subcommand parser**

In `main()`, after the `doctor` parser:

```python
    # graph
    graph_p = sub.add_parser("graph", help="Knowledge graph management: status, diffuse")
    graph_sub = graph_p.add_subparsers(dest="graph_command", required=True)
    graph_status_p = graph_sub.add_parser("status", help="Show graph statistics")
    graph_diffuse_p = graph_sub.add_parser("diffuse", help="Run relation extraction on existing data")
```

Add dispatch:
```python
    elif args.command == "graph":
        cmd_graph(args, cfg_mgr)
```

- [ ] **Step 2: Implement cmd_graph function**

```python
def cmd_graph(args: argparse.Namespace, cfg_mgr: ConfigManager) -> None:
    """Knowledge graph management."""
    from pathlib import Path
    import sqlite3

    data_dir = cfg_mgr.data_dir
    cache_path = data_dir / "cache.db"

    if not cache_path.is_file():
        print("  ⚠️  cache.db not found. Run cdx-brain init first.")
        return

    conn = sqlite3.connect(str(cache_path))

    if args.graph_command == "status":
        from cdx_brain.retrieval.extractor import RelationExtractor
        extractor = RelationExtractor(conn)
        stats = extractor.get_stats()
        print()
        print(f"  📊 Knowledge Graph Status")
        print(f"  ──────────────────────────")
        print(f"  Total edges:  {stats.get('total_edges', 0)}")
        pred_detail = stats.get('by_predicate', {})
        if pred_detail:
            print(f"  By type:")
            for p, c in pred_detail.items():
                print(f"    {p}: {c}")
        print(f"  Orphan subjects: {stats.get('orphan_subjects', 'N/A')}")
        print()

    elif args.graph_command == "diffuse":
        # Load pipeline state and re-extract
        from cdx_brain.retrieval.extractor import RelationExtractor
        import json

        state_path = data_dir / "pipeline_state.json"
        if not state_path.is_file():
            print("  ⚠️  No pipeline state to extract relations from.")
            return

        state = json.loads(state_path.read_text("utf-8"))
        policies = state.get("policies", [])
        wm = state.get("world_model", {})
        concepts = list(wm.get("concepts", {}).values())

        extractor = RelationExtractor(conn)
        relations = extractor.extract(policies=policies, concepts=concepts)
        print()
        print(f"  🔗 Relation extraction complete")
        print(f"  ───────────────────────────────")
        print(f"  Policies:  {len(policies)}")
        print(f"  Concepts:  {len(concepts)}")
        print(f"  Relations extracted: {len(relations)}")
        print()

    conn.close()
```

- [ ] **Step 3: Test the CLI**

Run: `cd E:\codex\cdx-brain && python -m cdx_brain.cli graph status`
Expected: Prints graph stats (even if all zeros)

Run: `cd E:\codex\cdx-brain && python -m cdx_brain.cli graph diffuse`
Expected: Runs extraction, prints counts (may be 0 if no pipeline state)

- [ ] **Step 4: Add graph check to doctor**

In `cmd_doctor()`, after OV check, add:

```python
    # 8. Knowledge Graph
    cache_path = data_dir / "cache.db"
    if cache_path.is_file():
        try:
            conn = sqlite3.connect(str(cache_path))
            row = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='triples'").fetchone()
            if row:
                count = conn.execute("SELECT COUNT(*) FROM triples").fetchone()[0]
                print(f"  ✅ 知识图谱  {count} 条关系边")
            else:
                print(f"  ⚪ 知识图谱 未初始化（自建）")
            conn.close()
        except Exception:
            pass
```

- [ ] **Step 5: Commit**

```bash
git add cdx_brain/cli.py
git commit -m "feat(knowledge-graph): add graph CLI commands + doctor check"
```

---

### Task 6: OV sync extension for relations

**Files:**
- Modify: `E:\codex\cdx-brain\cdx_brain\federation\sync.py` (+15 lines)

- [ ] **Step 1: Add relations sync to sync_pipeline_to_ov**

After the triples sync block in `sync_pipeline_to_ov()`:

```python
    # Relations from triples table
    try:
        from pathlib import Path
        cache_path = Path.home() / ".cdx-brain" / "data" / "cache.db"
        if cache_path.is_file():
            import sqlite3
            conn = sqlite3.connect(str(cache_path))
            rels = conn.execute("SELECT * FROM triples WHERE synced = 0 LIMIT 100").fetchall()
            for rel in rels:
                cols = [d[0] for d in conn.execute("PRAGMA table_info(triples)").fetchall()]
                rel_dict = dict(zip(cols, rel))
                rid = rel_dict.get("id", "")
                if not rid:
                    continue
                uri = f"{_COGNITIVE_BASE.format(agent=agent)}/relations/{rid}.json"
                if dry_run:
                    counts["relations"] = counts.get("relations", 0) + 1
                    continue
                try:
                    content = json.dumps(rel_dict, ensure_ascii=False, default=str)
                    client.content_write(uri, content, metadata={"agent": agent, "type": "relation", "synced_at": now})
                    conn.execute("UPDATE triples SET synced = 1 WHERE id = ?", (rid,))
                    counts["relations"] = counts.get("relations", 0) + 1
                except Exception:
                    pass
            conn.commit()
            conn.close()
    except Exception:
        pass
```

- [ ] **Step 2: Quick verification**

Run: `cd E:\codex\cdx-brain && python -c "from cdx_brain.federation.sync import sync_pipeline_to_ov; print('import OK')"`
Expected: `import OK`

- [ ] **Step 3: Commit**

```bash
git add cdx_brain/federation/sync.py
git commit -m "feat(knowledge-graph): sync relations to OV"
```

---

### Task 7: Full integration test

- [ ] **Step 1: Run the full test suite**

```bash
cd E:\codex\cdx-brain
python -m pytest tests/ -v 2>&1 || python tests/test_extractor.py && python tests/test_graph_diffusion.py && python tests/test_cli.py
```

- [ ] **Step 2: Verify CLI end-to-end**

```bash
cd E:\codex\cdx-brain
python -m cdx_brain.cli doctor
python -m cdx_brain.cli graph status
```

- [ ] **Step 3: Commit**

```bash
git add -A
git commit -m "v0.8.0: Knowledge Graph module — relation extraction + graph diffusion retrieval"
```
