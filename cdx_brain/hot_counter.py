#!/usr/bin/env python3
"""hot_counter.py - pattern frequency counter for behavior promotion."""

from __future__ import annotations
import json, os, re, time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


COUNTER_DIR = "~/.cdx-brain/data"
COUNTER_FILE = "pattern_counter.jsonl"
PROMOTE_THRESHOLD = 3
NATIVE_MEMORY_PATH = "~/.codex/memories/extensions/cdx-brain"


_PATTERN_TRIGGERS = [
    (r"\u8bb0\u4f4f\s*(?:\u4ee5\u540e\s*)?(?:\u90fd\s*)?\u7528\s*(.+?)(?:[\uff0c\u3002\uff01\uff1f\n]|$)", "preference"),
    (r"\u4ee5\u540e\s*(?:\u90fd\s*)?\u7528\s*(.+?)(?:[\uff0c\u3002\uff01\uff1f\n]|$)", "preference"),
    (r"\u4e0d\u8981\s*(?:\u518d\s*)?\u7528\s*(.+?)(?:[\uff0c\u3002\uff01\uff1f\n]|$)", "avoid"),
    (r"\u7528\s*(.+?)\s*\u800c\u4e0d\u662f\s*(.+?)(?:[\uff0c\u3002\uff01\uff1f\n]|$)", "preference"),
    (r"\u6bcf\u6b21\s*(?:\u90fd\s*)?(?:\u8981\s*)?\u7528\s*(.+?)(?:[\uff0c\u3002\uff01\uff1f\n]|$)", "preference"),
    (r"\u56fa\u5b9a\s*(?:\u7528\s*)?(.+?)(?:[\uff0c\u3002\uff01\uff1f\n]|$)", "preference"),
    (r"always\s+use\s+(.+?)(?:[,.!?\n]|$)", "preference"),
    (r"never\s+use\s+(.+?)(?:[,.!?\n]|$)", "avoid"),
    (r"remember\s+to\s+use\s+(.+?)(?:[,.!?\n]|$)", "preference"),
    (r"(?:\u4e0d\u5bf9|\u9519\u4e86|\u4e0d\u662f|\u4e0d\u8981)\s*[\uff0c,]?\s*(?:\u5e94\u8be5|\u8981|\u5f97)?\s*\u7528\s*(.+?)(?:[\uff0c\u3002\uff01\uff1f\n]|$)", "correction"),
]


class PatternRecord:
    def __init__(self, pattern: str, category: str = "preference"):
        self.pattern = pattern
        self.category = category
        self.count = 1
        self.last_seen = datetime.now(timezone.utc).isoformat()
        self.promoted = False
        self.promoted_at = None

    def to_dict(self):
        return {"pattern": self.pattern, "category": self.category, "count": self.count,
                "last_seen": self.last_seen, "promoted": self.promoted, "promoted_at": self.promoted_at}

    @classmethod
    def from_dict(cls, d):
        rec = cls(d.get("pattern", ""), d.get("category", "preference"))
        rec.count = int(d.get("count", 1))
        rec.last_seen = str(d.get("last_seen", rec.last_seen))
        rec.promoted = bool(d.get("promoted", False))
        rec.promoted_at = d.get("promoted_at")
        return rec


def _counter_path():
    return Path(os.path.expanduser(COUNTER_DIR)) / COUNTER_FILE


def _native_memory_dir():
    return Path(os.path.expanduser(NATIVE_MEMORY_PATH))


def extract_patterns(text):
    results = []
    for regex, category in _PATTERN_TRIGGERS:
        for m in re.finditer(regex, text, re.IGNORECASE):
            pt = m.group(1).strip()
            if pt and len(pt) < 100:
                pt = pt.rstrip(".,;:\uff0c\u3002\uff1b\uff1a")
                results.append((pt, category))
    return results


def load_records():
    path = _counter_path()
    if not path.is_file():
        return []
    records = []
    try:
        for line in path.read_text("utf-8").strip().split("\n"):
            line = line.strip()
            if not line:
                continue
            records.append(PatternRecord.from_dict(json.loads(line)))
    except (OSError, json.JSONDecodeError, KeyError):
        pass
    return records


def save_records(records):
    path = _counter_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        lines = [json.dumps(r.to_dict(), ensure_ascii=False) for r in records]
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return True
    except OSError:
        return False


def record_pattern(pattern_text, category="preference"):
    records = load_records()
    norm = pattern_text.strip().lower()
    existing = None
    for rec in records:
        if rec.pattern.strip().lower() == norm:
            existing = rec
            break
    if existing:
        existing.count += 1
        existing.last_seen = datetime.now(timezone.utc).isoformat()
    else:
        existing = PatternRecord(pattern_text, category)
        records.append(existing)
    save_records(records)
    if existing.count >= PROMOTE_THRESHOLD and not existing.promoted:
        return existing
    return None


def promote_pattern(record):
    now = datetime.now(timezone.utc).isoformat()
    memory_dir = _native_memory_dir()
    memory_dir.mkdir(parents=True, exist_ok=True)
    safe_name = re.sub(r'[^\w\-\u4e00-\u9fff]', '_', record.pattern)[:40].strip("_").lower()
    if not safe_name:
        safe_name = f"pattern_{int(time.time())}"
    filepath = memory_dir / f"pattern_{safe_name}.md"
    action = "\u2705 \u91c7\u7eb3" if record.category in ("preference", "correction") else "\u274c \u907f\u514d"
    lines = [
        f"# behavior: {record.pattern}",
        f"- pattern: {record.pattern}",
        f"- category: {record.category}",
        f"- action: {action}",
        f"- count: {record.count}",
        f"- promoted_at: {now}",
    ]
    try:
        filepath.write_text("\n".join(lines) + "\n", encoding="utf-8")
    except OSError:
        return False
    records = load_records()
    for rec in records:
        if rec.pattern.strip().lower() == record.pattern.strip().lower():
            rec.promoted = True
            rec.promoted_at = now
            break
    save_records(records)
    return True


def process_text(text):
    patterns = extract_patterns(text)
    promoted = []
    for pattern_text, category in patterns:
        result = record_pattern(pattern_text, category)
        if result:
            ok = promote_pattern(result)
            if ok:
                promoted.append(result)
    return promoted


def get_summary():
    records = load_records()
    if not records:
        return ""
    active = [r for r in records if r.count >= 2 and not r.promoted]
    promoted_recs = [r for r in records if r.promoted]
    parts = []
    if active:
        items = [f"{r.pattern}({r.count}x)" for r in active[:3]]
        parts.append(f"Patterns: {', '.join(items)}")
    if promoted_recs:
        items = [r.pattern[:30] for r in promoted_recs[-3:]]
        parts.append(f"Crystalized: {', '.join(items)}")
    return " | ".join(parts)
