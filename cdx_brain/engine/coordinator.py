"""Multi-agent memory coordinator (O6)."""
from __future__ import annotations
import logging
from collections import defaultdict
from typing import Any

logger = logging.getLogger(__name__)


class AgentMemoryCoordinator:
    """Coordinates memory across Codex agents/sessions.

    Provides per-agent isolation with cross-agent entity graph sharing.
    """

    def __init__(self, graph=None):
        self._graph = graph
        self._agent_sessions: dict[str, set[str]] = defaultdict(set)

    def register_session(self, agent_id: str, session_id: str) -> None:
        self._agent_sessions[agent_id].add(session_id)

    def get_agent_sessions(self, agent_id: str) -> list[str]:
        return list(self._agent_sessions.get(agent_id, []))

    def get_shared_entities(self, agent_ids: list[str], limit: int = 20) -> list[dict]:
        """Get entities shared across multiple agents (intersection of all agents)."""
        if not self._graph or not agent_ids or len(agent_ids) < 2:
            return []
        try:
            placeholders = ",".join("?" for _ in agent_ids)
            # Use GROUP BY with COUNT to find entities present in ALL specified agents
            rows = self._graph._conn.execute(
                f"SELECT id, name, type, MAX(weight) as weight FROM entities "
                f"WHERE agent_id IN ({placeholders}) "
                f"GROUP BY id, name, type "
                f"HAVING COUNT(DISTINCT agent_id) = ? "
                f"ORDER BY weight DESC LIMIT ?",
                [*agent_ids, len(agent_ids), limit]
            ).fetchall()
            return [{"id": r[0], "name": r[1], "type": r[2], "weight": r[3]} for r in rows]
        except Exception as e:
            logger.debug("coordinator error: %s", e)
            return []

    def get_agent_context(self, agent_id: str, limit: int = 10) -> dict:
        """Build context dict for a specific agent."""
        sessions = self.get_agent_sessions(agent_id)
        entities = self.get_shared_entities([agent_id], limit)
        return {
            "agent_id": agent_id,
            "sessions": sessions,
            "entities": entities,
        }
