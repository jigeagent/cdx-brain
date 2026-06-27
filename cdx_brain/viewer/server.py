
"""cdx-brain Viewer — stdlib-only HTTP server + SPA dashboard.

Covers all capabilities from v0.5.0 to v0.9.0.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sqlite3
import sys
import time
from datetime import datetime, timezone, timedelta
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from typing import Any, Optional
from urllib.parse import urlparse, parse_qs

from cdx_brain.cache.connection import CacheConnection
from cdx_brain.cache.schema import ensure_schema

logger = logging.getLogger(__name__)
_HERE = Path(__file__).parent


class _APIHandler(BaseHTTPRequestHandler):
    _cache: Optional[CacheConnection] = None
    _ov_url: str = ""
    _data_dir: str = ""

    def log_message(self, fmt: str, *args: Any) -> None:
        logger.debug(fmt, *args)

    def _send_json(self, data: Any, status: int = 200) -> None:
        body = json.dumps(data, ensure_ascii=False, default=str).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_html(self, html: str, status: int = 200) -> None:
        body = html.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_error(self, msg: str, status: int = 400) -> None:
        self._send_json({"error": msg}, status)

    def _get_db(self) -> sqlite3.Connection:
        if self._cache is None:
            raise RuntimeError("Cache not initialized")
        return self._cache.conn

    def _table_exists(self, name: str) -> bool:
        try:
            return bool(self._get_db().execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name=?", (name,)).fetchone())
        except Exception:
            return False

    def _read_json(self, *parts: str) -> dict:
        p = Path(self._data_dir, *parts)
        if not p.is_file():
            return {}
        try:
            return json.loads(p.read_text("utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}

    # ── Dashboard ────────────────────────────────────────────

    def _dashboard(self) -> dict:
        db = self._get_db()
        trace_count = db.execute("SELECT COUNT(*) FROM traces").fetchone()[0] or 0
        synced = db.execute("SELECT COUNT(*) FROM traces WHERE synced=1").fetchone()[0] or 0
        week_ago = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()
        new_week = db.execute("SELECT COUNT(*) FROM traces WHERE created_at >= ?", (week_ago,)).fetchone()[0] or 0
        cache_path = Path(self._data_dir, "cache.db")
        cache_mb = round(cache_path.stat().st_size / (1024*1024), 1) if cache_path.is_file() else 0

        # Pipeline
        pl = self._read_json("pipeline_state.json")
        policies = pl.get("policies", [])
        skills = pl.get("skills", [])
        concepts = pl.get("concepts", [])

        # CF
        cf_total = 0
        cf_this_month = 0
        cf_convergence = "no_data"
        cf_top = ""
        try:
            from cdx_brain.counterfactual.store import ensure_counterfactual_schema, count_counterfactuals
            ensure_counterfactual_schema(db)
            cf = count_counterfactuals(db)
            cf_total = cf.get("total", 0)
            if cf_total > 0:
                month_start = datetime.now(timezone.utc).replace(day=1).isoformat()
                cf_this_month = db.execute("SELECT COUNT(*) FROM counterfactuals WHERE created_at >= ?",
                    (month_start,)).fetchone()[0] or 0
                subjects = db.execute("""
                    SELECT subject, COUNT(*) as c FROM counterfactuals
                    GROUP BY subject ORDER BY c DESC LIMIT 5
                """).fetchall()
                if subjects:
                    cf_top = subjects[0][0]
                    total_cf = sum(r[1] for r in subjects)
                    top_ratio = subjects[0][1] / total_cf if total_cf > 0 else 0
                    hhi = sum((r[1]/total_cf)**2 for r in subjects)
                    if hhi > 0.6:
                        cf_convergence = "converged"
                    elif hhi > 0.3:
                        cf_convergence = "converging"
                    else:
                        cf_convergence = "exploring"
        except Exception:
            pass

        # Tasks
        tf = self._read_json("task_forest.json")
        nodes = tf.get("nodes", {})
        by_status = {}
        for nd in nodes.values():
            s = nd.get("status", "open")
            by_status[s] = by_status.get(s, 0) + 1

        # Graph
        triple_count = db.execute("SELECT COUNT(*) FROM triples").fetchone()[0] if self._table_exists("triples") else 0

        # Sentinel
        sentinel_status = "ok"
        sentinel_ts = ""
        sentinel_checks = {}
        try:
            from cdx_brain.sentinel.scout import run_quick_check
            qc = run_quick_check()
            sentinel_ts = qc.get("timestamp", "")
            sentinel_checks = qc.get("checks", {})
            statuses = [c.get("status","ok") for c in sentinel_checks.values()]
            if "critical" in statuses: sentinel_status = "critical"
            elif "error" in statuses: sentinel_status = "error"
            elif "warning" in statuses: sentinel_status = "warning"
        except Exception:
            pass

        return {
            "memory": {"traces": trace_count, "synced": synced, "new_this_week": new_week, "cache_mb": cache_mb},
            "pipeline": {"policies": len(policies), "skills": len(skills), "concepts": len(concepts)},
            "graph": {"triples": triple_count},
            "cf": {"total": cf_total, "this_month": cf_this_month, "convergence": cf_convergence, "top_subject": cf_top},
            "tasks": {"total": len(nodes), "active": by_status.get("open",0)+by_status.get("in_progress",0)+by_status.get("blocked",0),
                      "blocked": by_status.get("blocked",0), "done": by_status.get("done",0)},
            "sentinel": {"status": sentinel_status, "timestamp": sentinel_ts, "checks": sentinel_checks},
            "promote": {"total": 0},
        }

    # ── CF API ──────────────────────────────────────────────

    def _cf_timeline(self, months: int = 6) -> list[dict]:
        db = self._get_db()
        try:
            from cdx_brain.counterfactual.store import ensure_counterfactual_schema
            ensure_counterfactual_schema(db)
            cutoff = (datetime.now(timezone.utc) - timedelta(days=months*30)).isoformat()
            rows = db.execute("""
                SELECT strftime('%%Y-%%m', created_at) as m, subject, rejected, confidence
                FROM counterfactuals WHERE created_at >= ? ORDER BY m
            """, (cutoff,)).fetchall()
            months_map = {}
            for r in rows:
                m = r["m"]
                if m not in months_map:
                    months_map[m] = {"month": m, "total": 0, "by_subject": {}, "by_rejected": [], "confidences": []}
                months_map[m]["total"] += 1
                subj = r["subject"] or "其他"
                months_map[m]["by_subject"][subj] = months_map[m]["by_subject"].get(subj, 0) + 1
                months_map[m]["by_rejected"].append(r["rejected"] or "?")
                months_map[m]["confidences"].append(r["confidence"] or 0.5)
            result = []
            for mk in sorted(months_map.keys()):
                md = months_map[mk]
                rej = sorted(md["by_subject"].items(), key=lambda x: -x[1])
                total = md["total"]
                hhi = sum((v/total)**2 for v in md["by_subject"].values()) if total > 0 else 0
                result.append({
                    "month": mk, "total": md["total"],
                    "by_subject": dict(rej[:5]),
                    "avg_confidence": round(sum(md["confidences"])/len(md["confidences"]), 2) if md["confidences"] else 0,
                    "hhi": round(hhi, 3),
                })
            return result
        except Exception as e:
            return []

    # ── Tasks API ───────────────────────────────────────────

    def _tasks_data(self) -> dict:
        tf = self._read_json("task_forest.json")
        nodes = tf.get("nodes", {})
        if not nodes:
            return {"total": 0, "by_status": {}, "active_list": []}
        by_status = {}
        active_list = []
        for nid, nd in nodes.items():
            s = nd.get("status", "open")
            by_status[s] = by_status.get(s, 0) + 1
            if s in ("open", "in_progress", "blocked"):
                updated = nd.get("updated_at", "")
                ttl = None
                if s == "blocked" and updated:
                    try:
                        ttl = max(0, 30 - (datetime.now(timezone.utc) - datetime.fromisoformat(updated)).days)
                    except Exception:
                        pass
                active_list.append({
                    "id": nid[:12], "title": (nd.get("title","?") or "?")[:30],
                    "status": s, "blocked_by": nd.get("blocked_by", []),
                    "ttl_days": ttl,
                })
        active_list.sort(key=lambda x: {"blocked":0,"in_progress":1,"open":2}.get(x["status"], 9))
        return {"total": len(nodes), "by_status": by_status, "active_list": active_list[:20]}

    def _tasks_mermaid(self) -> str:
        try:
            from cdx_brain.task_forest.forest import TaskForest
            f = TaskForest(data_dir=self._data_dir)
            return f.to_mermaid()
        except Exception:
            return "flowchart TD\\n  empty[No tasks]"

    # ── Activity API ────────────────────────────────────────

    def _memory_activity(self, days: int = 7) -> list[dict]:
        try:
            cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
            rows = self._get_db().execute("""
                SELECT date(created_at) as d, COUNT(*) as c
                FROM traces WHERE created_at >= ?
                GROUP BY d ORDER BY d DESC LIMIT 30
            """, (cutoff,)).fetchall()
            return [{"date": r["d"], "traces": r["c"]} for r in rows]
        except Exception:
            return []

    # ── Sentinel ────────────────────────────────────────────

    def _sentinel_quick(self) -> dict:
        try:
            from cdx_brain.sentinel.scout import run_quick_check
            return dict(run_quick_check())
        except Exception:
            return {"type": "quick", "checks": {}, "timestamp": datetime.now(timezone.utc).isoformat()}

    def _sentinel_history(self, days: int = 7) -> list[dict]:
        path = Path(self._data_dir, "scout_reports.jsonl")
        if not path.is_file():
            return []
        cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
        entries = []
        try:
            for line in path.read_text("utf-8").strip().split("\n"):
                if not line.strip():
                    continue
                e = json.loads(line)
                if e.get("timestamp","") >= cutoff:
                    entries.append({"timestamp": e["timestamp"][:19], "checks": e.get("checks",{})})
        except Exception:
            pass
        return entries[-30:]

    # ── Search ──────────────────────────────────────────────

    def _search(self, q: str) -> dict:
        if not q:
            return {"results": [], "sources": {}}
        from cdx_brain.cache.traces import TraceRepository
        from cdx_brain.retrieval.ranker import rrf_merge
        repo = TraceRepository(self._cache)
        results = []
        try:
            for t in repo.search_fts(q, limit=6):
                uc = (t.user_content or "")[:150]
                ac = (t.assistant_content or "")[:150]
                results.append({"text": uc + (" | " + ac if ac else ""), "source": "local",
                    "score": 1.0, "date": (t.created_at or "")[:10]})
        except Exception:
            pass
        try:
            from cdx_brain.counterfactual.store import search_counterfactuals as cf_search
            for r in cf_search(self._get_db(), q, limit=3):
                results.append({"text": f'[{r.get("subject","?")}] 放弃{r.get("rejected","?")}: {r.get("reason","")[:100]}', 
                    "source": "counterfactual", "score": r.get("confidence",0.5), "date": (r.get("created_at","") or "")[:10]})
        except Exception:
            pass
        results.sort(key=lambda x: -x["score"])
        sources = {}
        for r in results:
            sources[r["source"]] = sources.get(r["source"], 0) + 1
        return {"results": results[:20], "sources": sources}

    # ── Legacy handlers ─────────────────────────────────────

    def _handle_stats(self) -> None:
        db = self._get_db()
        tc = db.execute("SELECT COUNT(*) FROM traces").fetchone()[0] or 0
        pc = db.execute("SELECT COUNT(*) FROM policies").fetchone()[0] if self._table_exists("policies") else 0
        sc = db.execute("SELECT COUNT(*) FROM skills").fetchone()[0] if self._table_exists("skills") else 0
        sync = db.execute("SELECT COUNT(*) FROM traces WHERE synced=1").fetchone()[0] or 0
        self._send_json({"traces": tc, "policies": pc, "skills": sc, "synced": sync, "ov_url": self._ov_url})

    def _handle_traces(self, params: dict) -> None:
        db = self._get_db()
        limit = min(int(params.get("limit", ["50"])[0]), 200)
        offset = int(params.get("offset", ["0"])[0])
        q = params.get("search", [None])[0]
        if q:
            rows = db.execute("SELECT * FROM traces WHERE user_content LIKE ? OR assistant_content LIKE ? ORDER BY created_at DESC LIMIT ? OFFSET ?",
                (f"%{q}%", f"%{q}%", limit, offset)).fetchall()
        else:
            rows = db.execute("SELECT * FROM traces ORDER BY created_at DESC LIMIT ? OFFSET ?", (limit, offset)).fetchall()
        self._send_json([dict(r) for r in rows])

    def _handle_trace_detail(self, tid: str) -> None:
        row = self._get_db().execute("SELECT * FROM traces WHERE id=?", (tid,)).fetchone()
        self._send_json(dict(row) if row else {"error": "not found"})

    def _handle_policies(self) -> None:
        self._send_json(self._read_json("pipeline_state.json").get("policies", []))

    def _handle_skills(self) -> None:
        self._send_json(self._read_json("pipeline_state.json").get("skills", []))

    def _handle_concepts(self) -> None:
        self._send_json(self._read_json("pipeline_state.json").get("concepts", []))

    def _handle_triples(self) -> None:
        if not self._table_exists("triples"):
            self._send_json([])
            return
        rows = self._get_db().execute("SELECT * FROM triples ORDER BY created_at DESC LIMIT 100").fetchall()
        self._send_json([dict(r) for r in rows])

    def _handle_timeline(self, params: dict) -> None:
        days = int(params.get("days", ["30"])[0])
        cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
        rows = self._get_db().execute("SELECT date(created_at) as d, COUNT(*) as c FROM traces WHERE created_at >= ? GROUP BY d ORDER BY d",
            (cutoff,)).fetchall()
        self._send_json([{"date": r["d"], "count": r["c"]} for r in rows])

    def _handle_search(self, params: dict) -> None:
        self._send_json(self._search(params.get("q", [""])[0]))

    def _handle_graph(self) -> None:
        db = self._get_db()
        if not self._table_exists("triples"):
            self._send_json({"nodes": [], "edges": [], "node_count": 0, "edge_count": 0})
            return
        trips = db.execute("SELECT subject, predicate, object, confidence FROM triples ORDER BY confidence DESC LIMIT 200").fetchall()
        node_ids, nodes, edges = set(), [], []
        for t in trips:
            for name in (t["subject"], t["object"]):
                if name not in node_ids:
                    node_ids.add(name)
                    nodes.append({"id": name, "label": name, "group": "concept"})
            edges.append({"source": t["subject"], "target": t["object"], "predicate": t["predicate"],
                "confidence": t.get("confidence", 0.5)})
        self._send_json({"nodes": nodes, "edges": edges, "node_count": len(nodes), "edge_count": len(edges)})

    def _load_template(self, name: str) -> str:
        tpl = _HERE / "templates" / name
        if tpl.is_file():
            return tpl.read_text("utf-8")
        return f"<html><body><h1>Template {name} not found</h1></body></html>"

    # ── Routing ───────────────────────────────────────────

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/")
        params = parse_qs(parsed.query)
        try:
            if path in ("", "/", "/index.html"):
                self._send_html(self._load_template("dashboard.html"))
            elif path == "/api/dashboard":
                self._send_json(self._dashboard())
            elif path == "/api/stats":
                self._handle_stats()
            elif path == "/api/traces":
                self._handle_traces(params)
            elif path.startswith("/api/traces/"):
                self._handle_trace_detail(path.split("/api/traces/")[1])
            elif path == "/api/policies":
                self._handle_policies()
            elif path == "/api/skills":
                self._handle_skills()
            elif path == "/api/concepts":
                self._handle_concepts()
            elif path == "/api/triples":
                self._handle_triples()
            elif path == "/api/timeline":
                self._handle_timeline(params)
            elif path == "/api/search":
                self._handle_search(params)
            elif path == "/api/graph":
                self._handle_graph()
            elif path == "/graph.html":
                self._send_html(self._load_template("graph.html"))
            elif path == "/api/health":
                self._send_json(self._sentinel_quick())
            elif path == "/api/cf/timeline":
                self._send_json(self._cf_timeline(int(params.get("months", ["6"])[0])))
            elif path == "/api/tasks/data":
                self._send_json(self._tasks_data())
            elif path == "/api/tasks/mermaid":
                self._send_json({"mermaid": self._tasks_mermaid()})
            elif path == "/api/pipeline":
                self._send_json(self._read_json("pipeline_state.json"))
            elif path == "/api/activity":
                self._send_json(self._memory_activity(int(params.get("days", ["7"])[0])))
            elif path == "/api/health/history":
                self._send_json(self._sentinel_history(int(params.get("days", ["7"])[0])))
            else:
                self._send_error("Not found", 404)
        except Exception as e:
            logger.exception("API error: %s", e)
            self._send_error(str(e), 500)


# ── Server setup ─────────────────────────────────────────

def serve(cache_path="", ov_url="", port=8080, host="127.0.0.1", data_dir=""):
    if not cache_path:
        cache_path = str(Path.home() / ".cdx-brain" / "data" / "cache.db")
    if not data_dir:
        data_dir = str(Path(cache_path).parent)
    cache = CacheConnection(cache_path)
    ensure_schema(cache)
    _APIHandler._cache = cache
    _APIHandler._ov_url = ov_url
    _APIHandler._data_dir = data_dir
    server = HTTPServer((host, port), _APIHandler)
    logger.info("Viewer on http://%s:%d", host, port)
    print(f"cdx-brain Viewer: http://{host}:{port}", file=sys.stderr)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.shutdown()
        cache.close_all()
        logger.info("Viewer stopped")


def main():
    parser = argparse.ArgumentParser(description="cdx-brain Viewer")
    parser.add_argument("--port", type=int, default=int(os.environ.get("CDX_VIEWER_PORT", "8080")))
    parser.add_argument("--host", default=os.environ.get("CDX_VIEWER_HOST", "127.0.0.1"))
    parser.add_argument("--db", dest="cache_path", default="")
    parser.add_argument("--data-dir", default="")
    parser.add_argument("--ov-url", default=os.environ.get("OV_URL", "http://localhost:1933"))
    args = parser.parse_args()
    serve(cache_path=args.cache_path, ov_url=args.ov_url, port=args.port, host=args.host, data_dir=args.data_dir)


if __name__ == "__main__":
    main()
