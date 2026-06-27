"""Task Forest DAG — data models for cross-session task tracking."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Literal, Optional


TaskStatus = Literal["open", "in_progress", "blocked", "done", "cancelled"]
TaskRelation = Literal["depends_on", "blocks", "subtask_of", "duplicates", "related"]


@dataclass
class TaskNode:
    """A single task node in the forest DAG."""
    id: str                          # task_{uuid4}
    title: str                       # 任务标题
    description: str = ""             # 任务描述
    status: TaskStatus = "open"       # 当前状态
    parent_id: Optional[str] = None   # 父任务 ID
    blocked_by: list[str] = field(default_factory=list)  # 依赖/阻塞项
    tags: list[str] = field(default_factory=list)
    decisions: list[str] = field(default_factory=list)   # 关键决策
    session_ids: list[str] = field(default_factory=list) # 涉及的 session
    created_at: str = ""
    updated_at: str = ""

    def to_dict(self) -> dict:
        return {
            "id": self.id, "title": self.title,
            "description": self.description, "status": self.status,
            "parent_id": self.parent_id, "blocked_by": self.blocked_by,
            "tags": self.tags, "decisions": self.decisions,
            "session_ids": self.session_ids,
            "created_at": self.created_at, "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, d: dict) -> TaskNode:
        return cls(
            id=d.get("id", ""), title=d.get("title", ""),
            description=d.get("description", ""), status=d.get("status", "open"),
            parent_id=d.get("parent_id"),
            blocked_by=d.get("blocked_by", []),
            tags=d.get("tags", []), decisions=d.get("decisions", []),
            session_ids=d.get("session_ids", []),
            created_at=d.get("created_at", ""),
            updated_at=d.get("updated_at", ""),
        )


@dataclass
class TaskEdge:
    """A directed edge between two task nodes."""
    source: str    # source task ID
    target: str    # target task ID
    relation: TaskRelation = "depends_on"

    def to_dict(self) -> dict:
        return {"source": self.source, "target": self.target, "relation": self.relation}

    @classmethod
    def from_dict(cls, d: dict) -> TaskEdge:
        return cls(
            source=d.get("source", ""),
            target=d.get("target", ""),
            relation=d.get("relation", "depends_on"),
        )
