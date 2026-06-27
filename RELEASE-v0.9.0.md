# cdx-brain v0.9.0 — 社区升级版

> 2026-06-27
> 从 v0.8.0 升级
> 来源：Codex 社区记忆系统调研（Mainline · Thread-Scoped Memory · COMPASS Skills）

---

## 新增

### 🆕 Phase 4.1 — 反事实记忆（Counterfactual Memory）

记录"被放弃的方案+原因"，避免 Agent 重复踩坑。

- counterfactual/store.py — FTS5 存储引擎，FTS5 + LIKE 双通道检索（解决 CJK 中文搜索）
- counterfactual/log.py — 自动记录器，支持对话文本提取 + promote_gate reject 联动
- counterfactual/inject.py — session_start 注入器，加 ⚠️ 标记提示历史决策
- CLI: cdx-brain cf add/list/search/stats

### 🆕 Phase 4.3 — 任务森林（Task Forest）

跨会话任务 DAG，解决"上次做到哪了？在等什么？"

- 	ask_forest/dag.py — TaskNode / TaskEdge 数据模型
- 	ask_forest/forest.py — 森林管理器（CRUD/DAG/Mermaid/状态自动检测/TTL）
- 	ask_forest/profile.py — 用户画像（技术栈偏好/架构风格/反模式）
- 	ask_forest/handoff.py — Session 交接压缩
- CLI: cdx-brain task add/status/block/list/graph/prune/stats/profile

### 🆕 Phase 4.2 — 哨兵监控（Sentinel Scout）

主动巡检记忆系统健康，而非被动等用户报告。

- sentinel/scout.py — Quick check（<3s）+ Deep check 引擎
- sentinel/preflight.py — Session 启动前预检
- sentinel/report.py — 结构化报告 + Markdown 输出 + 自动修复（VACUUM）
- CLI: cdx-brain sentinel quick/deep/status

---

## 改进

- **promote.py**: reject 时自动触发 log_rejection_from_gate，记入反事实记忆
- **cache/schema.py**: 初始化时自动创建 counterfactuals FTS5 表
- **regex 精准匹配**: "放弃"关键词收窄为 [方案/方向/路径/改法] + [放弃/否决/不用/不行] 组合，带否定语境守卫

---

## 与 v0.8.0 的关系

- v0.8.0 知识图谱 + 联邦共识 → 保留不动
- v0.9.0 新增三个正交模块，不破坏已有管线
- 所有 Phase 4 模块可通过 CLI 独立使用，无需修改现有 hook 配置

---

## 升级说明

`ash
pip install -e .
# 或者：cdx-brain init --force
# 新表 counterfactuals 会在首次调用时自动创建
`

---

## 技术统计

- 新建 13 个文件，修改 3 个（schema.py / promote.py / cli.py）
- 总计 ~950 行代码
- 全部通过 Python syntax check + 集成测试
- 三个模块合计 30+ 项集成测试用例

---

## 致谢

- **Mainline** — 反事实记忆的"Git notes 存意图"启发
- **Thread-Scoped Memory #15432** — 哨兵 sentinel 架构启发
- **COMPASS Skills** — 任务森林 + 用户画像启发
- **豹哥** — Phase 4 全面评审，收紧 regex 规则、blocked TTL、in_progress 误标防护
