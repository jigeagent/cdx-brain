"""Session preflight check - runs before session start."""

from __future__ import annotations

from cdx_brain.sentinel.scout import run_quick_check


def preflight_check(cache_path: str = "", ov_url: str = "http://127.0.0.1:1933") -> str:
    """Quick preflight before session start. Returns warning summary or empty."""
    report = run_quick_check(cache_path, ov_url)
    warnings = []
    for name, check in report.get("checks", {}).items():
        status = check.get("status", "")
        if status in ("critical", "error"):
            warnings.append("%s: %s" % (name, check.get("message", status)))
        elif status == "warning" and name != "bdpan_sync":  # BD sync is informational
            warnings.append("%s: %s" % (name, check.get("message", status)))
    if warnings:
        return "Sentinel preflight warnings: " + "; ".join(warnings)
    return ""
