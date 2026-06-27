#!/usr/bin/env python3
"""cdx-brain CLI — init, status, search, config subcommands."""

from __future__ import annotations

import argparse
import io
import json
import os
import sys
from pathlib import Path

# Reconfigure stdout for Windows terminals — use UTF-8, replace, don't crash
if hasattr(sys.stdout, "buffer"):
    sys.stdout = io.TextIOWrapper(
        sys.stdout.buffer,
        encoding="utf-8",
        errors="replace",
        line_buffering=True,
    )

from cdx_brain.cache.connection import CacheConnection
from cdx_brain.cache.schema import ensure_schema
from cdx_brain.cache.traces import TraceRepository
from cdx_brain.task_forest.forest import TaskForest
from cdx_brain.task_forest.profile import load_profile, save_profile, UserProfile
from cdx_brain.sentinel.scout import run_quick_check, run_deep_check, format_report
from cdx_brain.sentinel.report import generate_and_save, get_latest
from cdx_brain.counterfactual.store import (
    ensure_counterfactual_schema, search_counterfactuals,
    list_counterfactuals, count_counterfactuals,
)

from cdx_brain import __version__
from cdx_brain.config import ConfigManager
from cdx_brain.installer import init_memory_system


def _get_config_manager() -> ConfigManager:
    """Create a ConfigManager from the default config dir."""
    return ConfigManager()


def cmd_init(args: argparse.Namespace) -> None:
    """Initialize cdx-brain memory system."""
    cfg_mgr = _get_config_manager()
    config_dir = cfg_mgr.config_path.parent

    if config_dir.is_dir() and not args.force:
        print(f"  ⚠️  cdx-brain 已初始化于 {config_dir}")
        print(f"  使用 --force 可重新初始化")
        print(f"  使用 cdx-brain doctor 可做运行检查")
        sys.exit(0)

    if config_dir.is_dir() and args.force:
        print(f"  🔄 重新初始化 cdx-brain ...")

    result = init_memory_system(cfg_mgr, agent_name=args.agent_name, ov_url=args.ov_url or "")

    # ── 输出 ──
    print()
    print(f"  ✅ cdx-brain v{__version__}  初始化成功")
    print(f"  ───────────────────────────────────")
    print(f"  配置目录  {result['config_dir']}")
    print(f"  数据文件  {result['cache_path']}")
    print(f"  当前身份  {result['agent_name']}")
    ov_status = f"已连接 {result['ov_url']}" if result['ov_enabled'] else "未配置"
    print(f"  OpenViking {ov_status}")
    print()

    # ── 自动检测 ──
    checks = []
    # Python version
    pyver = f"{sys.version_info.major}.{sys.version_info.minor}"
    checks.append(f"  ✓ Python {pyver}")

    # Config file
    if (config_dir / "config.yaml").is_file():
        checks.append(f"  ✓ 配置文件已写入")



    # OpenViking connectivity
    ov_url = result.get("ov_url", "")
    if ov_url:
        try:
            import httpx
            r = httpx.get(f"{ov_url}/health", timeout=2.0)
            if r.status_code == 200:
                checks.append(f"  ✓ OpenViking 在线 ({ov_url})")
            else:
                checks.append(f"  ⚠️ OpenViking 返回异常状态")
        except Exception:
            checks.append(f"  ⚠️ OpenViking 不可达 ({ov_url})")

    # Native memory
    mem_path = cfg_mgr.get("memory.memory_path")
    if mem_path:
        mem_dir = Path(os.path.expanduser(mem_path))
        if mem_dir.is_dir():
            count = len(list(mem_dir.glob("*.md")))
            checks.append(f"  ✓ 原生记忆目录就绪 ({count} 份文件)")

    # Cache DB
    cache_path = cfg_mgr.data_dir / "cache.db"
    if cache_path.is_file():
        size_mb = cache_path.stat().st_size / (1024 * 1024)
        checks.append(f"  ✓ 记忆数据库 {size_mb:.0f}MB ({result.get('trace_count', '?')} 条)")

    print(f"  ── 环境检测 ──")
    for c in checks:
        print(f"  {c}")
    print()

    # ── 下一步 ──
    print(f"  ── 下一步 ──")
    print(f"  1. 运行 cdx-brain doctor    全面自检")
    print(f"  2. 运行 cdx-brain status    查看运行状态")
    print(f"  3. 运行 cdx-brain promote   记忆维护（建议每周一次）")
    print(f"  4. 运行 cdx-brain promote   记忆维护（建议每周一次）")
    print(f"  5. 运行 cdx-brain search    测试记忆检索")
    print()

    # ── 首次使用提示 ──
    print(f"  💡 cdx-brain v0.3 三核能力")
    print(f"     🔍 三源检索  对话 + 核心记忆 + 团队共享 → RRF 融合")
    print(f"     ⬆  自动晋升  高频内容自动写入原生记忆")
    print(f"     🧹 生命周期   自动回收 + 去重 + 热扫")
    print()


def cmd_status(args: argparse.Namespace) -> None:
    """Show memory system status."""
    cfg_mgr = _get_config_manager()
    config = cfg_mgr.load()
    data_dir = cfg_mgr.data_dir
    cache_path = data_dir / "cache.db"

    if not cache_path.is_file():
        print(f"cdx-brain not initialized. Run 'cdx-brain init' first.")
        sys.exit(1)

    # Open cache and get stats
    try:
        cache = CacheConnection(str(cache_path))
        ensure_schema(cache)
        repo = TraceRepository(cache)

        total = repo.count()
        unsynced = len(repo.get_unsynced(limit=999999))
        recent = repo.list_recent(limit=1)

        # DB file size
        db_size = cache_path.stat().st_size
        if db_size < 1024:
            size_str = f"{db_size} B"
        elif db_size < 1024 * 1024:
            size_str = f"{db_size / 1024:.1f} KB"
        else:
            size_str = f"{db_size / (1024 * 1024):.1f} MB"

        print(f"cdx-brain v{__version__}  running")
        print()
        print("Storage:")
        print(f"  Database: {cache_path} ({size_str})")
        print(f"  Traces:   {total}")
        print(f"  Unsynced: {unsynced}")

        # OV status
        ov_url = config.get("ov", {}).get("url", "")
        ov_enabled = config.get("ov", {}).get("enabled", False)
        if ov_enabled and ov_url:
            ov_ok = _check_ov_health(ov_url)
            if ov_ok:
                print(f"  OpenViking: configured  online")
            else:
                print(f"  OpenViking: configured  offline")
        else:
            print(f"  OpenViking: disabled")

        # Last session
        sessions_file = data_dir / "sessions.jsonl"
        if sessions_file.is_file():
            try:
                lines = sessions_file.read_text(encoding="utf-8").strip().split("\n")
                if lines and lines[0]:
                    last = json.loads(lines[-1])
                    prompt = last.get("first_prompt", "")
                    turns = last.get("turn_count", 0)
                    ts = last.get("timestamp", "")
                    if prompt:
                        print(f"  Last session: {turns} turns | \"{prompt[:60]}\" | {ts[:16]}")
            except (OSError, json.JSONDecodeError):
                pass

        cache.close_all()

    except Exception as e:
        print(f"Error reading cache: {e}")
        sys.exit(1)


def _safe(text: str, maxlen: int = 100) -> str:
    """Truncate and normalize whitespace for console output."""
    if not text:
        return ""
    return text.replace("\n", " ")[:maxlen]


def cmd_search(args: argparse.Namespace) -> None:
    """Search local memory."""
    cfg_mgr = _get_config_manager()
    data_dir = cfg_mgr.data_dir
    cache_path = data_dir / "cache.db"

    if not cache_path.is_file():
        print("cdx-brain not initialized. Run 'cdx-brain init' first.")
        sys.exit(1)

    try:
        cache = CacheConnection(str(cache_path))
        ensure_schema(cache)
        repo = TraceRepository(cache)

        results = repo.search_fts(args.query, limit=args.limit)

        if not results:
            print("No matches found.")
            sys.exit(0)

        print(f"Found {len(results)} matching memories:")
        print()

        for i, t in enumerate(results, 1):
            ts = (t.created_at or "")[:10]
            user_preview = _safe(t.user_content, 100)
            assistant_preview = _safe(t.assistant_content, 100)

            print(f"{i}. [{ts}] user: {user_preview}")
            if assistant_preview:
                print(f"   assistant: {assistant_preview}")
            print()

        cache.close_all()

    except Exception as e:
        print(f"Search error: {e}")
        sys.exit(1)


def cmd_config(args: argparse.Namespace) -> None:
    """Get/set configuration."""
    cfg_mgr = _get_config_manager()

    if not args.key:
        # Print all config
        config = cfg_mgr.load()
        import yaml
        yaml.safe_dump(config, sys.stdout, default_flow_style=False, allow_unicode=True)
        return

    if not args.value:
        # Get single key
        val = cfg_mgr.get(args.key)
        if val is None:
            print(f"Unknown key: {args.key}")
            sys.exit(1)
        print(val)
        return

    # Set key
    # Try to parse as JSON for complex values, otherwise use string
    try:
        parsed = json.loads(args.value)
    except (json.JSONDecodeError, ValueError):
        parsed = args.value

    cfg_mgr.set(args.key, parsed)
    print(f"Set {args.key} = {parsed}")

    # If OV settings changed, re-render hooks
    if args.key.startswith("ov.") or args.key.startswith("agent."):
        pass  # Hook registration removed - cdx-brain is Codex-only





def cmd_promote(args: argparse.Namespace) -> None:
    """Run memory maintenance: cache limit, dedup, hot promote."""
    from cdx_brain.promote import run_maintenance
    results = run_maintenance(dry_run=args.dry_run or False)

    # ── Baidu Netdisk sync (best-effort) ─────
    if not args.dry_run:
        try:
            from cdx_brain.sync.bdpan import sync_all_cognitive
            sync_all_cognitive()
        except Exception:
            pass

    json.dump(results, sys.stdout, indent=2, ensure_ascii=False)


def cmd_doctor(args: argparse.Namespace) -> None:
    """全面自检：环境 + 配置 + hook + DB + OV 一次查清."""
    print()
    print(f"  🏥 cdx-brain doctor — 全面自检")
    print(f"  ───────────────────────────────────")
    print()

    cfg_mgr = _get_config_manager()
    config_dir = cfg_mgr.config_path.parent
    data_dir = cfg_mgr.data_dir
    all_ok = True

    # 1. 配置
    if (config_dir / "config.yaml").is_file():
        print(f"  ✅ 配置文件  {config_dir / 'config.yaml'}")
    else:
        print(f"  ❌ 配置文件缺失 — 请运行 cdx-brain init")
        all_ok = False

    # 2. 数据库
    cache_path = data_dir / "cache.db"
    if cache_path.is_file():
        size_mb = cache_path.stat().st_size / (1024 * 1024)
        import sqlite3
        try:
            conn = sqlite3.connect(str(cache_path))
            count = conn.execute("SELECT COUNT(*) FROM traces").fetchone()[0]
            conn.close()
            print(f"  ✅ 记忆数据库  {cache_path} ({size_mb:.0f}MB, {count} 条)")
        except Exception as e:
            print(f"  ❌ 数据库异常 — {e}")
            all_ok = False
    else:
        print(f"  ⚠️ 数据库文件不存在（新装机正常，使用后会自动创建）")



    # 5. 原生记忆
    mem_path = cfg_mgr.get("memory.memory_path")
    if mem_path:
        mem_dir = Path(os.path.expanduser(mem_path))
        if mem_dir.is_dir():
            count = len(list(mem_dir.glob("*.md")))
            print(f"  ✅ 原生记忆  {mem_dir} ({count} 份文件)")
        else:
            print(f"  ⚠️ 原生记忆目录不存在 — 将自动创建")
    else:
        print(f"  ⚠️ 原生记忆未配置 — 设置 memory.memory_path 可启用")

    # 6. 快照 / STATUS
    for key, label in [("memory.status_path", "STATUS"), ("memory.snapshot_path", "快照")]:
        path = cfg_mgr.get(key)
        if path:
            p = Path(os.path.expanduser(path))
            if p.is_file():
                print(f"  ✅ {label}文件  {p}")
            elif p.exists():
                print(f"  ✅ {label}路径  {p}")
            else:
                print(f"  ⚠️ {label}路径不存在 — {p}")

    # 7. OpenViking
    ov_url = cfg_mgr.get("ov.url")
    ov_enabled = cfg_mgr.get("ov.enabled")
    if ov_enabled and ov_url:
        try:
            import httpx
            r = httpx.get(f"{ov_url}/health", timeout=2.0)
            if r.status_code == 200:
                print(f"  ✅ OpenViking 在线  {ov_url}")
            else:
                print(f"  ⚠️ OpenViking 异常状态 ({r.status_code})")
        except Exception:
            print(f"  ❌ OpenViking 不可达  {ov_url}")
            all_ok = False
    else:
        print(f"  ⚪ OpenViking 未配置（可选）")

    print()
    if all_ok:
        print(f"  ✅ 全部就绪！cdx-brain v{__version__} 运行正常")
    else:
        print(f"  ⚠️ 存在需要修复的项目，请按上述提示操作")
    print()


def _check_ov_health(url: str) -> bool:
    """Check OpenViking connectivity."""
    if not url:
        return False
    try:
        import httpx
        r = httpx.get(f"{url}/health", timeout=2.0)
        return r.status_code == 200
    except Exception:
        return False




def cmd_decay(args: argparse.Namespace) -> None:
    """Run memory decay independently."""
    cfg_mgr = _get_config_manager()
    cache_path = str(cfg_mgr.data_dir / "cache.db")
    cold_db = os.path.expanduser(args.cold_db) if args.cold_db else str(cfg_mgr.data_dir / "cold.db")
    pipeline_state = str(cfg_mgr.data_dir / "pipeline_state.json")

    from cdx_brain.cache.decay import run_decay, format_decay_report
    result = run_decay(
        cache_path=cache_path,
        cold_db_path=cold_db,
        dry_run=args.dry_run,
        pipeline_state_path=pipeline_state,
    )
    print()
    print(format_decay_report(result))
    if result.traces_archived > 0 or result.policies_archived > 0:
        print(f"  Cold DB: {cold_db}")
    print()




def cmd_federate(args: argparse.Namespace) -> None:
    """Run federated consensus."""
    cfg_mgr = _get_config_manager()
    ov_url = args.ov_url or cfg_mgr.get("ov.url", "")
    if not ov_url:
        print("  OpenViking not configured. Use --ov-url or set ov.url in config.")
        return

    agent = cfg_mgr.get("agent.name", "comsam")
    state_path = str(cfg_mgr.data_dir / "pipeline_state.json")

    # Step 1: Sync local pipeline state to OV
    if not args.consensus_only:
        from cdx_brain.federation.sync import sync_pipeline_state_file
        counts = sync_pipeline_state_file(state_path, ov_url, agent, dry_run=args.dry_run)
        print()
        print(f"  Synced to OV ({agent}):")
        for k, v in counts.items():
            if v:
                print(f"    {k}: {v}")
        if not any(counts.values()):
            print(f"    (no new data to sync)")

    # Step 2: Search OV for cognitive data from all agents
    from cdx_brain.ov.client import OpenVikingClient
    client = OpenVikingClient(base_url=ov_url, timeout=5.0)
    print()
    print("  Searching OV for cognitive data...")

    # Search for policies
    policy_results = client.search_find(query="cognitive policy", k=20)
    concept_results = client.search_find(query="cognitive concept", k=20)

    from cdx_brain.federation.consensus import find_candidates, run_consensus
    all_candidates = find_candidates(policy_results + concept_results)

    agents_found = set(c.get("_agent", "?") for c in all_candidates)
    print(f"    Found {len(all_candidates)} cognitive items from agents: {agents_found}")

    if not all_candidates:
        print("    (no other agents have cognitive data yet)")
        return

    # Step 3: Run consensus
    import json
    from pathlib import Path
    state = {}
    if Path(state_path).is_file():
        state = json.loads(Path(state_path).read_text("utf-8"))

    consensus = run_consensus(state, all_candidates)
    if consensus["merges"]:
        print(f"  Merges: {len(consensus['merges'])}")
        for m in consensus["merges"]:
            print(f"    + {m['local_name'][:40]} <- {m['remote_agent']} (sim={m['similarity']:.2f}, method={m['method']})")
    if consensus["pending_reviews"]:
        print(f"  Pending reviews: {len(consensus['pending_reviews'])}")
        for p in consensus["pending_reviews"]:
            print(f"    ? {p['local_name'][:40]} vs {p['remote_agent']} (sim={p['similarity']:.2f})")

    # Step 4: Conflict detection
    from cdx_brain.federation.conflict import detect_conflicts, format_conflict_report
    local_triples = list(state.get("world_model", {}).get("triples", {}).values())
    remote_triples = {}
    for r in all_candidates:
        agent_n = r.get("_agent", "")
        if agent_n != agent and "/triples/" in r.get("id", ""):
            tdata = r.get("user_content", {})
            if isinstance(tdata, dict):
                remote_triples.setdefault(agent_n, []).append(tdata)

    conflicts = detect_conflicts(local_triples, remote_triples)
    if conflicts:
        print(f"  Conflicts: {len(conflicts)}")
        print(f"    {format_conflict_report(conflicts)}")
    else:
        print(f"  Conflicts: none")

    print()



def cmd_graph(args: argparse.Namespace) -> None:
    """Knowledge graph management."""
    cfg_mgr = _get_config_manager()
    """Knowledge graph management."""
    from pathlib import Path
    import sqlite3

    data_dir = cfg_mgr.data_dir
    cache_path = data_dir / "cache.db"

    if not cache_path.is_file():
        print("  \u26a0\ufe0f  cache.db not found. Run cdx-brain init first.")
        return

    conn = sqlite3.connect(str(cache_path))

    if args.graph_command == "status":
        from cdx_brain.retrieval.extractor import RelationExtractor
        extractor = RelationExtractor(conn)
        stats = extractor.get_stats()
        print()
        print(f"  \ud83d\udcca Knowledge Graph Status")
        print(f"  \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500")
        print(f"  Total edges:  {stats.get('total_edges', 0)}")
        pred_detail = stats.get("by_predicate", {})
        if pred_detail:
            print(f"  By type:")
            for p, c in pred_detail.items():
                print(f"    {p}: {c}")
        print(f"  Orphan subjects: {stats.get('orphan_subjects', 'N/A')}")
        print()

    elif args.graph_command == "diffuse":
        from cdx_brain.retrieval.extractor import RelationExtractor
        import json

        state_path = data_dir / "pipeline_state.json"
        if not state_path.is_file():
            print("  \u26a0\ufe0f  No pipeline state to extract relations from.")
            conn.close()
            return

        state = json.loads(state_path.read_text("utf-8"))
        policies = state.get("policies", [])
        wm = state.get("world_model", {})
        concepts = list(wm.get("concepts", {}).values())

        extractor = RelationExtractor(conn)
        relations = extractor.extract(policies=policies, concepts=concepts)
        print()
        print(f"  \ud83d\udd17 Relation extraction complete")
        print(f"  \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500")
        print(f"  Policies:  {len(policies)}")
        print(f"  Concepts:  {len(concepts)}")
        print(f"  Relations extracted: {len(relations)}")
        print()

    conn.close()

def main() -> None:
    """Entry point for cdx-brain CLI."""
    parser = argparse.ArgumentParser(
        prog="cdx-brain",
        description="cdx-brain memory system CLI",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # init
    init_p = sub.add_parser("init", help="Initialize cdx-brain memory system")
    init_p.add_argument("--agent-name", default="assistant",
                        help="Agent name for tags and OV URIs")
    init_p.add_argument("--ov-url", default="",
                        help="OpenViking server URL (optional)")
    init_p.add_argument("--non-interactive", action="store_true",
                        help="Skip prompts, use defaults")
    init_p.add_argument("--force", action="store_true",
                        help="Reinitialize even if already configured")

    # status
    sub.add_parser("status", help="Show memory system status")

    # search
    search_p = sub.add_parser("search", help="Search local memory")
    search_p.add_argument("query", help="Search query")
    search_p.add_argument("--limit", type=int, default=8,
                          help="Max results (default: 8)")

    # config
    config_p = sub.add_parser("config", help="Get/set configuration")
    config_p.add_argument("key", nargs="?", help="Config key (e.g. agent.name)")
    config_p.add_argument("value", nargs="?", help="Config value")

    # uninstall

    # promote
    promote_p = sub.add_parser("promote", help="Run memory maintenance (cache limit, dedup, hot promote)")

    cf_p = sub.add_parser("cf", help="反事实记忆")

    task_p = sub.add_parser("task", help="任务森林：跨会话任务 DAG 管理")
    task_sub = task_p.add_subparsers(dest="task_command", required=True)
    task_add = task_sub.add_parser("add", help="新建任务")
    task_add.add_argument("title", help="任务标题")
    task_add.add_argument("--desc", default="", help="任务描述")
    task_add.add_argument("--parent", default="", help="父任务ID")
    task_add.add_argument("--tags", default="", help="标签（逗号分隔）")
    task_status = task_sub.add_parser("status", help="更新任务状态")
    task_status.add_argument("id", help="任务ID")
    task_status.add_argument("status", choices=["open","in_progress","blocked","done","cancelled"])
    task_block = task_sub.add_parser("block", help="标注阻塞")
    task_block.add_argument("id", help="任务ID")
    task_block.add_argument("reason", help="阻塞原因")
    task_list = task_sub.add_parser("list", help="列出活跃任务")
    task_graph = task_sub.add_parser("graph", help="Mermaid DAG 可视化")
    task_prune = task_sub.add_parser("prune", help="清理超时阻塞任务")
    task_stats = task_sub.add_parser("stats", help="任务统计")
    profile_p = task_sub.add_parser("profile", help="查看/更新用户画像")
    profile_p.add_argument("--key", default="", help="字段名")
    profile_p.add_argument("--value", default="", help="字段值")
    profile_p.add_argument("--list", dest="list_field", default="", help="列表字段追加值")
    sentinel_p = sub.add_parser("sentinel", help="哨兵监控：记忆系统健康巡检")
    sentinel_sub = sentinel_p.add_subparsers(dest="sentinel_command", required=True)
    sentinel_quick = sentinel_sub.add_parser("quick", help="快速巡检（<3秒）")
    sentinel_deep = sentinel_sub.add_parser("deep", help="深度巡检（含VACUUM自动修复）")
    sentinel_status = sentinel_sub.add_parser("status", help="查看最近一次巡检报告")
    cf_sub = cf_p.add_subparsers(dest="cf_command", required=True)
    cf_add = cf_sub.add_parser("add", help="手动记录")
    cf_add.add_argument("--subject", required=True)
    cf_add.add_argument("--rejected", required=True)
    cf_add.add_argument("--chosen", default="")
    cf_add.add_argument("--reason", default="")
    cf_add.add_argument("--decider", default="")
    cf_add.add_argument("--session", default="")
    cf_add.add_argument("--confidence", type=float, default=0.7)
    cf_list = cf_sub.add_parser("list", help="列出")
    cf_list.add_argument("--subject", default="")
    cf_list.add_argument("--limit", type=int, default=20)
    cf_search = cf_sub.add_parser("search", help="搜索")
    cf_search.add_argument("query")
    cf_search.add_argument("--limit", type=int, default=5)
    cf_stats = cf_sub.add_parser("stats", help="统计")
    

    # decay
    decay_p = sub.add_parser("decay", help="Run memory decay: cold storage + policy aging + concept pruning")
    

    # federate
    fed_p = sub.add_parser("federate", help="Run federated consensus: OV sync + merge + conflict detect")
    fed_p.add_argument("--dry-run", "-n", action="store_true",
                       help="Preview without making changes")
    fed_p.add_argument("--ov-url", default="",
                       help="OpenViking URL (default: from config)")
    fed_p.add_argument("--consensus-only", action="store_true",
                       help="Skip OV sync, only run consensus + conflict detection")
    decay_p.add_argument("--dry-run", "-n", action="store_true",
                         help="Preview without making changes")
    decay_p.add_argument("--cold-db", default="",
                         help="Cold storage DB path")
    promote_p.add_argument("--dry-run", "-n", action="store_true",
                           help="Preview without making changes")

    # doctor
    sub.add_parser("doctor", help="全面自检：环境 + 配置 + hook + DB + OV 一次查清")

    # graph
    graph_p = sub.add_parser("graph", help="Knowledge graph: status, diffuse")
    graph_sub = graph_p.add_subparsers(dest="graph_command", required=True)
    graph_sub.add_parser("status", help="Show graph statistics")
    graph_sub.add_parser("diffuse", help="Run relation extraction on existing data")

    args = parser.parse_args()

    if args.command == "sentinel":
        if args.sentinel_command == "quick":
            result = generate_and_save(deep=False)
            print(format_report(result["report"]))
            print("\nReport saved: " + result["json_path"])
        elif args.sentinel_command == "deep":
            result = generate_and_save(deep=True)
            print(format_report(result["report"]))
            print("\nReport saved: " + result["json_path"])
        elif args.sentinel_command == "status":
            report = get_latest()
            if report:
                print(format_report(report))
            else:
                print("No scout reports found. Run 'cdx-brain sentinel quick' first.")
        return

    if args.command == "cf":
        dbpath = str(_get_config_manager().data_dir / "cache.db")
        cache = CacheConnection(dbpath)
        ensure_counterfactual_schema(cache)
        if args.cf_command == "add":
            from cdx_brain.counterfactual.log import log_counterfactual
            data = {"subject":args.subject,"rejected":args.rejected,
                "chosen":args.chosen,"reason":args.reason,
                "decided_by":args.decider,"source_session":args.session,
                "confidence":args.confidence}
            ok = log_counterfactual(cache, data)
            print("OK" if ok else "FAIL")
        elif args.cf_command == "list":
            for r in list_counterfactuals(cache, args.subject, args.limit):
                print("%s [%s] %s" % (r["id"][:12], r.get("subject","?"), (r.get("rejected","") or "")[:40]))
        elif args.cf_command == "search":
            for k, r in enumerate(search_counterfactuals(cache, args.query, args.limit), 1):
                print("#%d [%s] %s" % (k, r.get("subject","?"), (r.get("rejected","") or "")[:40]))
        elif args.cf_command == "stats":
            s = count_counterfactuals(cache)
            print("total: %d" % s["total"])
        cache.close_all()
        return

    # Dispatch
    if args.command == "init":
        cmd_init(args)
    elif args.command == "status":
        cmd_status(args)
    elif args.command == "search":
        cmd_search(args)
    elif args.command == "config":
        cmd_config(args)
    elif args.command == "promote":
        cmd_promote(args)
    elif args.command == "doctor":
        cmd_doctor(args)

    elif args.command == "graph":
        cmd_graph(args)


if __name__ == "__main__":
    main()
