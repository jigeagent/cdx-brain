"""Task Forest manager."""
from __future__ import annotations
import json, re
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
from uuid import uuid4
from cdx_brain.task_forest.dag import TaskNode, TaskEdge, TaskStatus, TaskRelation

DONE_PATTERNS = [r"(做完了|搞定了|完成了|已上线|已发布|已交付|搞完|收工|结案)"]
BLOCKED_PATTERNS = [r"(等待|阻塞|依赖|卡在|被..挡住|等..完成)"]
SUBTASK_PATTERNS = [r"(拆出|拆为|分解为|子任务|分拆)"]
BLOCKED_TTL_DAYS = 30


class TaskForest:
    def __init__(self, data_dir: str = ""):
        self._data_dir = Path(data_dir) if data_dir else Path.home() / ".cdx-brain" / "data"
        self._path = self._data_dir / "task_forest.json"
        self.nodes: dict[str, TaskNode] = {}
        self.edges: list[TaskEdge] = []
        self._load()

    def _load(self) -> None:
        if not self._path.is_file(): return
        try:
            data = json.loads(self._path.read_text("utf-8"))
            self.nodes = {k: TaskNode.from_dict(v) for k, v in data.get("nodes", {}).items()}
            self.edges = [TaskEdge.from_dict(e) for e in data.get("edges", [])]
        except (OSError, json.JSONDecodeError): pass

    def save(self) -> None:
        self._data_dir.mkdir(parents=True, exist_ok=True)
        data = {"version": 1, "nodes": {k: v.to_dict() for k, v in self.nodes.items()},
                "edges": [e.to_dict() for e in self.edges],
                "updated_at": datetime.now(timezone.utc).isoformat()}
        self._path.write_text(json.dumps(data, ensure_ascii=False, indent=2), "utf-8")

    def add_node(self, title: str, description: str = "",
                 parent_id: Optional[str] = None, tags: list[str] = None) -> TaskNode:
        now = datetime.now(timezone.utc).isoformat()
        node = TaskNode(id="task_" + uuid4().hex[:12], title=title,
            description=description, status="open", parent_id=parent_id,
            tags=tags or [], created_at=now, updated_at=now)
        self.nodes[node.id] = node
        if parent_id:
            self.edges.append(TaskEdge(source=parent_id, target=node.id, relation="subtask_of"))
        self.save(); return node
    def update_status(self, task_id: str, status: TaskStatus) -> Optional[TaskNode]:
        node = self.nodes.get(task_id)
        if not node: return None
        node.status = status
        node.updated_at = datetime.now(timezone.utc).isoformat()
        self.save(); return node

    def add_block(self, task_id: str, blocked_by: str) -> Optional[TaskNode]:
        node = self.nodes.get(task_id)
        if not node: return None
        if blocked_by not in node.blocked_by:
            node.blocked_by.append(blocked_by)
        node.status = "blocked"
        node.updated_at = datetime.now(timezone.utc).isoformat()
        self.save(); return node

    def link_session(self, task_id: str, session_id: str) -> None:
        node = self.nodes.get(task_id)
        if node and session_id not in node.session_ids:
            node.session_ids.append(session_id)
            node.updated_at = datetime.now(timezone.utc).isoformat()
            self.save()

    def get_active(self) -> list[TaskNode]:
        return [n for n in self.nodes.values() if n.status in ("open", "in_progress", "blocked")]

    def get_by_session(self, session_id: str) -> list[TaskNode]:
        return [n for n in self.nodes.values() if session_id in n.session_ids]
    def get_tree(self, root_id: str) -> list[TaskNode]:
        result = []
        root = self.nodes.get(root_id)
        if not root: return result
        result.append(root)
        child_ids = [e.target for e in self.edges if e.source == root_id and e.relation == "subtask_of"]
        for cid in child_ids: result.extend(self.get_tree(cid))
        return result

    def prune(self) -> int:
        now = datetime.now(timezone.utc)
        count = 0
        for node in self.nodes.values():
            if node.status == "blocked":
                updated = datetime.fromisoformat(node.updated_at) if node.updated_at else now
                if (now - updated).days > BLOCKED_TTL_DAYS:
                    node.status = "cancelled"
                    count += 1
        if count: self.save()
        return count

    def detect_status_from_text(self, text: str) -> Optional[str]:
        for pat in DONE_PATTERNS:
            if re.search(pat, text): return "done"
        return None

    def to_mermaid(self) -> str:
        if not self.nodes: return "flowchart TD\\n  empty[No tasks]"
        lines = ["flowchart TD"]
        icons = {"open": "🟢", "in_progress": "🔵", "blocked": "🔴", "done": "✅", "cancelled": "⚪"}
        for nid, node in self.nodes.items():
            label = (node.title or "")[:30]
            lines.append("  %s[%s %s]" % (nid[:8], icons.get(node.status, "⚪"), label))
        for e in self.edges:
            lines.append("  %s -->|%s| %s" % (e.source[:8], e.relation, e.target[:8]))
        return "\\n".join(lines)

    def stats(self) -> dict:
        by_status = {}
        for n in self.nodes.values(): by_status[n.status] = by_status.get(n.status, 0) + 1
        return {"total": len(self.nodes), "edges": len(self.edges),
                "by_status": by_status, "active": len(self.get_active())}
