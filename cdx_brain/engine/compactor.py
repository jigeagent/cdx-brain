"""Memory compaction: TTL eviction + similarity merging (O5)."""
from __future__ import annotations
import logging
import time
from typing import Any

logger = logging.getLogger(__name__)


class MemoryCompactor:
    """Periodic memory compaction and TTL eviction."""

    def __init__(self, conn=None, working_ttl: int = 3600, episodic_ttl: int = 604800):
        self._conn = conn
        self._ttl = {"working": working_ttl, "episodic": episodic_ttl, "semantic": None}

    def evict_expired(self, tier: str = "episodic") -> int:
        """Remove expired memories. Returns count removed."""
        ttl = self._ttl.get(tier)
        if ttl is None or not self._conn:
            return 0
        cutoff = time.time() - ttl
        try:
            removed = self._conn.execute(
                "DELETE FROM memories WHERE tier = ? AND created_at < ?",
                (tier, cutoff)
            ).rowcount
            logger.info("Compactor evicted %d %s memories", removed, tier)
            return removed
        except Exception as e:
            logger.warning("Compactor eviction error: %s", e)
            return 0

    def merge_duplicate_entities(self, threshold: float = 0.85) -> int:
        """Merge similar entities. Returns count merged."""
        if not self._conn:
            return 0
        try:
            merged = 0
            rows = self._conn.execute(
                "SELECT source_id, target_id, similarity FROM semantic_links "
                "WHERE similarity >= ? ORDER BY similarity DESC", (threshold,)
            ).fetchall()
            # Use a transaction for atomicity
            self._conn.execute("BEGIN")
            try:
                for src, tgt, sim in rows:
                    if src == tgt:
                        continue  # skip self-loops
                    try:
                        self._conn.execute(
                            "UPDATE entity_edges SET source = ? WHERE source = ?",
                            (src, tgt)
                        )
                        src_affected = self._conn.execute(
                            "UPDATE entity_edges SET target = ? WHERE target = ?",
                            (src, tgt)
                        ).rowcount
                        self._conn.execute("DELETE FROM entities WHERE id = ?", (tgt,))
                        merged += 1
                    except Exception:
                        pass
                if merged:
                    self._conn.execute("DELETE FROM semantic_links WHERE similarity >= ?", (threshold,))
                self._conn.execute("COMMIT")
            except Exception:
                self._conn.execute("ROLLBACK")
                raise
            if merged:
                logger.info("Compactor merged %d entity pairs", merged)
            return merged
        except Exception as e:
            logger.warning("Compactor merge error: %s", e)
            return 0

    def run_all(self) -> dict[str, int]:
        """Run all compaction tasks. Returns stats dict."""
        stats = {
            "working_evicted": self.evict_expired("working"),
            "episodic_evicted": self.evict_expired("episodic"),
            "entities_merged": self.merge_duplicate_entities(),
        }
        return stats
