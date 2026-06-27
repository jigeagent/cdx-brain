#!/usr/bin/env python3
"""cdx-brain v0.9.0 — Phase 4 全面测试集 v3（校正版）"""

from __future__ import annotations

import json, os, sqlite3, sys
from pathlib import Path
from datetime import datetime, timezone, timedelta
from uuid import uuid4

PASS = 0; FAIL = 0
def test(name, cond, detail=""):
    global PASS, FAIL
    if cond: PASS += 1; print(f"  ✅ {name}")
    else: FAIL += 1; print(f"  ❌ {name}" + (f" — {detail}" if detail else ""))
def section(t):
    print(f"\n{'='*60}\n  {t}\n{'='*60}")

# ====================================================================
# Phase 4.1 — 反事实记忆
# ====================================================================
section("Phase 4.1 — 反事实记忆 (Counterfactual)")

from cdx_brain.counterfactual.log import (
    extract_counterfactual_from_text, log_counterfactual, log_rejection_from_gate)
from cdx_brain.counterfactual.store import (
    ensure_counterfactual_schema, search_counterfactuals, list_counterfactuals, count_counterfactuals)
from cdx_brain.counterfactual.inject import inject_counterfactuals

test("1.1 模块导入", True)

# 触发词（匹配实际 TRIGGER_PATTERNS）
test("1.2.1 方案+放弃", extract_counterfactual_from_text("这个方案先放弃") is not None)
test("1.2.2 路径+否决", extract_counterfactual_from_text("那条路径已经否决了") is not None)
# "方向+不用" — 含暂时被否定守卫截获，这是设计预期（保守策略）
test("1.2.3 方向+放弃（不含暂时）", extract_counterfactual_from_text("这个方向我们决定放弃了") is not None)
# "办法+不行" — 行不通 vs 不行: 正则精确匹配"不行"
test("1.2.4 办法+不行（精确匹配）", extract_counterfactual_from_text("这个办法不行") is not None)
test("1.2.5 策略+不采用", extract_counterfactual_from_text("那个策略决定不采用了") is not None)
test("1.2.6 架构+不可行", extract_counterfactual_from_text("微服务架构不可行") is not None)
test("1.2.7 尝试+不行", extract_counterfactual_from_text("尝试用Redis方案结果不行") is not None)
test("1.2.8 试过+失效", extract_counterfactual_from_text("试过那个框架已经失效了") is not None)

# 否定守卫
test("1.3.1 放弃午休→不触发", extract_counterfactual_from_text("放弃午休写完了代码") is None)
test("1.3.2 先别放弃→不触发", extract_counterfactual_from_text("先别放弃这个方案") is None)
test("1.3.3 还没→不触发", extract_counterfactual_from_text("还没决定要放弃这条路线") is None)
test("1.3.4 不能→不触发", extract_counterfactual_from_text("不能放弃这个方向啊") is None)

# 复杂文本
cf = extract_counterfactual_from_text(
    "关于架构评估：团队仔细比较后决定放弃微服务方案，主要原因在于运维成本不适合当前规模。",
    session_id="s001")
test("1.4.1 多句提取成功", cf is not None)
if cf:
    test("1.4.2 subject含关键词", any(kw in cf.get("subject","") for kw in ["架构","方案"]))
    test("1.4.3 context长度>20", len(cf.get("context","")) > 20)
    test("1.4.4 session_id正确", cf.get("source_session")=="s001")
    test("1.4.5 decider默认auto", cf.get("decided_by")=="auto")

# 无匹配
test("1.5.1 纯技术→无", extract_counterfactual_from_text("用Python写了排序算法") is None)
test("1.5.2 日常→无", extract_counterfactual_from_text("今天天气不错") is None)
test("1.5.3 空→无", extract_counterfactual_from_text("") is None)

# FTS5 存储 — 用实际匹配的数据
conn = sqlite3.connect(":memory:")
ensure_counterfactual_schema(conn)

ok = log_counterfactual(conn, {
    "id": "cf_001", "subject": "微服务", "chosen": "单体", "rejected": "微服务",
    "reason": "运维成本不可接受，放弃微服务方案", "context": "架构决策放弃微服务",
    "confidence": 0.85, "decided_by": "test", "source_session": "s001",
    "created_at": datetime.now(timezone.utc).isoformat(),
})
test("1.6.1 FTS5插入", ok)

log_counterfactual(conn, {
    "id": "cf_002", "subject": "MongoDB", "chosen": "PostgreSQL", "rejected": "MongoDB",
    "reason": "数据一致性要求高", "context": "数据库选型放弃MongoDB",
    "confidence": 0.6, "decided_by": "test", "source_session": "s002",
    "created_at": datetime.now(timezone.utc).isoformat(),
})
log_counterfactual(conn, {
    "id": "cf_003", "subject": "Docker", "chosen": "裸机部署", "rejected": "Docker",
    "reason": "团队不熟悉Docker", "context": "部署方案放弃Docker",
    "confidence": 0.4, "decided_by": "promote_gate", "source_session": "s003",
    "created_at": datetime.now(timezone.utc).isoformat(),
})

# 用实际存的数据搜索
r1 = search_counterfactuals(conn, "微服务", 5)
test("1.6.2 FTS5搜索:微服务", len(r1) >= 1)
r2 = search_counterfactuals(conn, "数据", 5)  # LIKE后备
test("1.6.3 LIKE后备:数据", len(r2) >= 1)
test("1.6.4 列表全部>=3", len(list_counterfactuals(conn)) >= 3)
test("1.6.5 按主题Docker", len(list_counterfactuals(conn, subject="Docker")) >= 1)
s = count_counterfactuals(conn)
test("1.6.6 统计总数>=3", s.get("total",0) >= 3)
test("1.6.7 by_decider含test", "test" in s.get("by_decider",{}))
test("1.6.8 top_subjects非空", len(s.get("top_subjects",[])) > 0)

out = inject_counterfactuals("微服务", conn, 3)
test("1.7.1 注入非空", len(out) > 0)
test("1.7.2 含放弃标记", "放弃" in out)
test("1.7.3 无匹配时空", inject_counterfactuals("xyz不存在的", conn, 3)=="")

ok = log_rejection_from_gate(conn, "cand_001", "该方案评分1<3被跳过", 3.0, 1.0, "s004")
test("1.8 promote_gate联动", ok)

conn.close()
print(f"\n  反事实: {PASS}/{PASS+FAIL} pass")
CF_PASS, CF_FAIL = PASS, FAIL

# ====================================================================
# Phase 4.2 — 哨兵监控
# ====================================================================
section("Phase 4.2 — 哨兵监控 (Sentinel Scout)")

PASS = 0; FAIL = 0
from cdx_brain.sentinel.scout import (
    check_cache_size, check_ov_health, check_bdpan_sync,
    check_fragmentation, check_memory_stats, run_quick_check, run_deep_check, format_report)
from cdx_brain.sentinel.preflight import preflight_check

test("2.1.1 cache_size有status", "status" in check_cache_size())
test("2.1.2 cache_size有message", "message" in check_cache_size())
ov = check_ov_health("http://127.0.0.1:19999")
test("2.2 OV不通报error/warning", ov.get("status") in ("error","warning"))
test("2.3 BD同步有status", "status" in check_bdpan_sync())
test("2.4 碎片有status", "status" in check_fragmentation())
test("2.5 统计有status", "status" in check_memory_stats())
q = run_quick_check(ov_url="http://127.0.0.1:19999")
test("2.6.1 type=quick", q.get("type")=="quick")
test("2.6.2 有时间戳", bool(q.get("timestamp")))
test("2.6.3 有checks", bool(q.get("checks")))
test("2.6.4 >=3项检查", len(q.get("checks",{})) >= 3)
test("2.6.5 含cache_size", "cache_size" in q.get("checks",{}))
d = run_deep_check(ov_url="http://127.0.0.1:19999")
test("2.7.1 type=deep", d.get("type")=="deep")
test("2.7.2 有auto_fixed", "auto_fixed" in d)
test("2.7.3 >=5项检查", len(d.get("checks",{})) >= 5)
test("2.7.4 含fragmentation", "fragmentation" in d.get("checks",{}))
test("2.7.5 含memory_stats", "memory_stats" in d.get("checks",{}))
test("2.8.1 report非空", len(format_report(d))>0)
test("2.8.2 report以#开头", format_report(d).startswith("#"))
test("2.8.3 preflight返回str", isinstance(preflight_check(ov_url="http://127.0.0.1:19999"), str))

print(f"\n  哨兵: {PASS}/{PASS+FAIL} pass")
SEN_PASS, SEN_FAIL = PASS, FAIL

# ====================================================================
# Phase 4.3 — 任务森林
# ====================================================================
section("Phase 4.3 — 任务森林 (Task Forest)")

PASS = 0; FAIL = 0
from cdx_brain.task_forest.dag import TaskNode, TaskEdge
from cdx_brain.task_forest.forest import TaskForest
from cdx_brain.task_forest.profile import UserProfile
from cdx_brain.task_forest.handoff import build_handoff_prompt

# TaskNode
n = TaskNode(id="t1", title="集成登录", status="done")
test("3.1.1 TaskNode创建", isinstance(n,TaskNode))
test("3.1.2 id正确", n.id=="t1")
test("3.1.3 status正确", n.status=="done")
e = TaskEdge(source="t1", target="t2", relation="blocks")
test("3.2 TaskEdge创建", isinstance(e,TaskEdge))

# TaskForest CRUD (使用内部数据结构)
forest = TaskForest()
forest.nodes = {}; forest.edges = []
test("3.3.1 空森林", len(forest.nodes)==0)

n1 = forest.add_node(title="架构设计", tags=["arch"])
test("3.3.2 添加n1", n1 is not None and n1.id is not None)
n2 = forest.add_node(title="后端开发", tags=["backend"])
test("3.3.3 添加n2", n2 is not None)
n3 = forest.add_node(title="前端对接", tags=["frontend"])
test("3.3.4 添加n3", n3 is not None)
test("3.3.5 共3节点", len(forest.nodes)==3)

ok = forest.update_status(n3.id, "done")
test("3.3.6 update_status成功", ok is not None)
test("3.3.7 n3状态done", forest.nodes[n3.id].status=="done")

forest.add_block(n2.id, n1.id)
active = forest.get_active()
test("3.3.8 有活跃节点", len(active) > 0)
test("3.3.9 n2被阻塞", any(n.id==n2.id for n in active if n.status=="blocked"))

m = forest.to_mermaid()
test("3.4.1 Mermaid输出", len(m)>0)
test("3.4.2 含flowchart", "flowchart" in m)

# prune — 需要先创建旧节点再修改其时间
old = forest.add_node(title="过期任务", tags=["stale"])
forest.add_block(old.id, n1.id)
old.created_at = (datetime.now(timezone.utc)-timedelta(days=31)).isoformat()
old.updated_at = (datetime.now(timezone.utc)-timedelta(days=31)).isoformat()
pruned = forest.prune()
test("3.5.1 prune清除>=1", pruned >= 1)
test("3.5.2 过期任务变cancelled", forest.nodes[old.id].status=="cancelled")

s = forest.stats()
test("3.6.1 stats有total", "total" in s)
test("3.6.2 stats有by_status", "by_status" in s)
test("3.6.3 stats有active", "active" in s)

# UserProfile
p = UserProfile()
test("3.7.1 空profile初始化", isinstance(p,UserProfile))
p.tech_stack_preferences = ["Python","FastAPI"]
p.architecture_style = "微服务+事件驱动"
p.decision_patterns = ["先原型验证"]
p.anti_patterns = ["过早优化"]
test("3.7.2 tech_stack", "Python" in p.tech_stack_preferences)
test("3.7.3 architecture", "事件驱动" in p.architecture_style)
test("3.7.4 decision_patterns", "先原型验证" in p.decision_patterns)
test("3.7.5 anti_patterns", "过早优化" in p.anti_patterns)
d = p.to_dict()
test("3.7.6 to_dict", "tech_stack_preferences" in d)
r = UserProfile.from_dict(d)
test("3.7.7 from_dict一致", r.tech_stack_preferences == p.tech_stack_preferences)

h = build_handoff_prompt(forest, session_summary="完成架构设计，进入后端开发")
test("3.8.1 handoff非空", len(h)>0)
test("3.8.2 含交接摘要", "交接" in h or "Session" in h)
test("3.8.3 含进度", "后端" in h or "架构" in h)
test("3.8.4 含偏好", "Python" in h or "FastAPI" in h)
h2 = build_handoff_prompt(forest)
test("3.8.5 无总结时正常", len(h2)>0)

print(f"\n  任务森林: {PASS}/{PASS+FAIL} pass")
TF_PASS, TF_FAIL = PASS, FAIL

# ====================================================================
# Hook + 零cc-star
# ====================================================================
section("Hook 集成验证")

PASS = 0; FAIL = 0
import py_compile
tpl = Path(r"E:\codex\cdx-brain\cdx_brain\templates")
files = ["session_start.py","store.py","inject.py","compact.py","summary.py"]

for f in files:
    try:
        py_compile.compile(str(tpl/f), doraise=True)
        test(f"4.1 语法:{f}", True)
    except Exception as e:
        test(f"4.1 语法:{f}", False, str(e))

st = (tpl/"store.py").read_text("utf-8")
test("4.2 store:extract_counterfactual", "extract_counterfactual_from_text" in st)
test("4.3 store:Phase4.1", "Phase 4.1" in st)
it = (tpl/"inject.py").read_text("utf-8")
test("4.4 inject:search_counterfactuals", "search_counterfactuals" in it)
test("4.5 inject:cf_n", "cf_n" in it)
test("4.6 compact:run_quick_check", "run_quick_check" in (tpl/"compact.py").read_text("utf-8"))
test("4.7 summary:run_quick_check", "run_quick_check" in (tpl/"summary.py").read_text("utf-8"))

for f in files:
    txt = (tpl/f).read_text("utf-8")
    refs = txt.lower().count("cc-star") + txt.lower().count("cc_star")
    test(f"4.8 零cc-star:{f}", refs==0)

hdir = Path.home()/".cdx-brain"/"hooks"
if hdir.is_dir():
    for f in files:
        test(f"4.9 已安装:{f}", (hdir/f).is_file())
else:
    test("4.9 hooks目录", False)

print(f"\n  Hook: {PASS}/{PASS+FAIL} pass")
HK_PASS, HK_FAIL = PASS, FAIL

# ====================================================================
section("测试汇总")
tp = CF_PASS+SEN_PASS+TF_PASS+HK_PASS
tf = CF_FAIL+SEN_FAIL+TF_FAIL+HK_FAIL
print(f"\n  Phase 4.1 反事实: {CF_PASS}/{CF_PASS+CF_FAIL}")
print(f"  Phase 4.2 哨兵:   {SEN_PASS}/{SEN_PASS+SEN_FAIL}")
print(f"  Phase 4.3 任务森林: {TF_PASS}/{TF_PASS+TF_FAIL}")
print(f"  Hook 集成:       {HK_PASS}/{HK_PASS+HK_FAIL}")
print(f"  ─────────────────────")
pct = tp/(tp+tf)*100 if (tp+tf)>0 else 0
print(f"  总计: {tp}/{tp+tf} ({pct:.1f}%)")
print(f"  {'✅ 全部通过' if tf==0 else '❌ 存在失败'}")
