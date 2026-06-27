"""Sentinel scout - periodic memory system health checks."""

from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


class ScoutReport(dict):
    """Structured scout report."""
    pass


def check_cache_size(cache_path: str = "") -> dict:
    """Check cache.db size."""
    if not cache_path:
        cache_path = str(Path.home() / ".cdx-brain" / "data" / "cache.db")
    path = Path(cache_path)
    if not path.is_file():
        return {"status": "error", "message": "cache.db not found"}
    size_mb = path.stat().st_size / (1024 * 1024)
    if size_mb > 1000:
        return {"status": "critical", "size_mb": round(size_mb, 1), "message": "cache.db > 1GB"}
    if size_mb > 500:
        return {"status": "warning", "size_mb": round(size_mb, 1), "message": "cache.db > 500MB, consider compact"}
    return {"status": "ok", "size_mb": round(size_mb, 1), "message": "OK"}


def check_ov_health(ov_url: str = "http://127.0.0.1:1933") -> dict:
    """Check OpenViking connectivity."""
    try:
        import httpx
        r = httpx.get(ov_url + "/health", timeout=3.0)
        if r.status_code == 200:
            return {"status": "ok", "message": "OV online"}
        return {"status": "warning", "message": "OV returned status %d" % r.status_code}
    except Exception as e:
        return {"status": "error", "message": "OV unreachable: %s" % str(e)}


def check_bdpan_sync(sync_log_path: str = "") -> dict:
    """Check baidu netdisk sync freshness."""
    if not sync_log_path:
        sync_log_path = str(Path.home() / ".cdx-brain" / "logs" / "bdpan_sync.log")
    path = Path(sync_log_path)
    if not path.is_file():
        return {"status": "warning", "message": "No BD sync log found"}
    try:
        mtime = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
        days_ago = (datetime.now(timezone.utc) - mtime).days
        if days_ago > 7:
            return {"status": "warning", "message": "BD sync %d days ago" % days_ago}
        return {"status": "ok", "message": "BD sync %d days ago" % days_ago}
    except OSError:
        return {"status": "error", "message": "Cannot read BD sync log"}


def check_fragmentation(cache_path: str = "") -> dict:
    """Check FTS5 fragmentation via integrity check."""
    if not cache_path:
        cache_path = str(Path.home() / ".cdx-brain" / "data" / "cache.db")
    path = Path(cache_path)
    if not path.is_file():
        return {"status": "error", "message": "cache.db not found"}
    try:
        import sqlite3
        conn = sqlite3.connect(str(path))
        cur = conn.execute("PRAGMA integrity_check")
        result = cur.fetchone()[0]
        conn.execute("PRAGMA schema.quick_check")
        quick = conn.fetchone()[0] if conn else "ok"
        conn.close()
        if result != "ok":
            return {"status": "error", "message": "Integrity check: %s" % result}
        return {"status": "ok", "message": "Integrity OK"}
    except Exception as e:
        return {"status": "error", "message": "Check failed: %s" % str(e)}


def check_memory_stats(cache_path: str = "") -> dict:
    """Check memory statistics."""
    if not cache_path:
        cache_path = str(Path.home() / ".cdx-brain" / "data" / "cache.db")
    path = Path(cache_path)
    if not path.is_file():
        return {"status": "error", "message": "cache.db not found"}
    try:
        import sqlite3
        conn = sqlite3.connect(str(path))
        total = conn.execute("SELECT COUNT(*) FROM traces").fetchone()[0]
        cold = conn.execute("SELECT COUNT(*) FROM traces WHERE cold=1").fetchone()[0]
        conn.close()
        return {"status": "ok", "total_traces": total, "cold_traces": cold,
                "message": "%d traces (%d cold)" % (total, cold)}
    except Exception as e:
        return {"status": "error", "message": str(e)}


def run_quick_check(cache_path: str = "", ov_url: str = "http://127.0.0.1:1933") -> ScoutReport:
    """Quick health check (<3 seconds)."""
    report = ScoutReport({
        "type": "quick",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "checks": {
            "cache_size": check_cache_size(cache_path),
            "ov_health": check_ov_health(ov_url),
            "bdpan_sync": check_bdpan_sync(),
        },
    })
    return report


def run_deep_check(cache_path: str = "", ov_url: str = "http://127.0.0.1:1933") -> ScoutReport:
    """Deep health check with all diagnostics."""
    report = ScoutReport({
        "type": "deep",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "auto_fixed": [],
        "checks": {
            "cache_size": check_cache_size(cache_path),
            "ov_health": check_ov_health(ov_url),
            "bdpan_sync": check_bdpan_sync(),
            "fragmentation": check_fragmentation(cache_path),
            "memory_stats": check_memory_stats(cache_path),
        },
    })
    # Auto-fix: VACUUM if fragmentation detected
    if report["checks"]["fragmentation"].get("status") == "warning":
        try:
            import sqlite3
            conn = sqlite3.connect(cache_path or str(Path.home() / ".cdx-brain" / "data" / "cache.db"))
            conn.execute("VACUUM")
            conn.close()
            report["auto_fixed"].append("FTS5 VACUUM completed")
            report["checks"]["fragmentation"]["status"] = "ok"
        except Exception as e:
            report["auto_fixed"].append("VACUUM failed: %s" % str(e))
    return report


def format_report(report: ScoutReport) -> str:
    """Format scout report as markdown."""
    lines = [
        "# Scout Report",
        "Type: %s | %s" % (report.get("type", "?"), report.get("timestamp", "")[:19]),
        "",
    ]
    auto_fixed = report.get("auto_fixed", [])
    if auto_fixed:
        lines.append("## Auto-fixed")
        for item in auto_fixed:
            lines.append("- %s" % item)
        lines.append("")
    checks = report.get("checks", {})
    critical = [k for k, v in checks.items() if v.get("status") == "critical"]
    warning = [k for k, v in checks.items() if v.get("status") == "warning"]
    error = [k for k, v in checks.items() if v.get("status") == "error"]
    ok = [k for k, v in checks.items() if v.get("status") == "ok"]
    if critical:
        lines.append("## Critical")
        for k in critical:
            lines.append("- %s: %s" % (k, checks[k].get("message", "")))
        lines.append("")
    if warning:
        lines.append("## Warning")
        for k in warning:
            lines.append("- %s: %s" % (k, checks[k].get("message", "")))
        lines.append("")
    if error:
        lines.append("## Error")
        for k in error:
            lines.append("- %s: %s" % (k, checks[k].get("message", "")))
        lines.append("")
    lines.append("## OK")
    for k in ok:
        v = checks[k]
        detail = v.get("size_mb", v.get("total_traces", ""))
        msg = "%s: %s" % (k, v.get("message", "OK"))
        if detail:
            msg += " (%s)" % detail
        lines.append("- " + msg)
    return "\n".join(lines)
