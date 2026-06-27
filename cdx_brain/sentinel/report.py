"""Scout report persistence."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from cdx_brain.sentinel.scout import ScoutReport, run_quick_check, run_deep_check, format_report


_REPORT_DIR = Path.home() / ".cdx-brain" / "data" / "scout_reports"


def save_report(report: ScoutReport) -> str:
    """Save scout report to disk."""
    _REPORT_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    rtype = report.get("type", "quick")
    path = _REPORT_DIR / ("scout_%s_%s.json" % (rtype, ts))
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), "utf-8")
    return str(path)


def get_latest() -> Optional[ScoutReport]:
    """Get the latest scout report."""
    if not _REPORT_DIR.is_dir():
        return None
    files = sorted(_REPORT_DIR.glob("scout_*.json"), reverse=True)
    if not files:
        return None
    try:
        return json.loads(files[0].read_text("utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def generate_and_save(cache_path: str = "", ov_url: str = "http://127.0.0.1:1933", deep: bool = False) -> dict:
    """Run checks, save report, return result."""
    report = run_deep_check(cache_path, ov_url) if deep else run_quick_check(cache_path, ov_url)
    path = save_report(report)
    md = format_report(report)
    md_path = _REPORT_DIR.parent / "last_scout_report.md"
    md_path.write_text(md, "utf-8")
    return {"report": report, "json_path": path, "md_path": str(md_path)}
