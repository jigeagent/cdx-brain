# Phase 3 联邦记忆共识 · 方案提案

> 作者：康少 (Comsam) · cdx-brain 主理人
> 版本：v1.0 · 2026-06-18
> 提交：吉哥 → 征求 豹哥 + 虎哥 意见

---

## 一、当前状态

### 已完成
- **Phase 1 ✅** — 认知管线入轨：L1→L2→L3→Skill 全自动串联，持久化到 `pipeline_state.json`
- **Phase 2 ✅** — 记忆衰减：三级衰减引擎，30d cold / 90d archive，cold.db 冷存储

### 剩余问题
- 各 Agent 的认知产物（policies、concepts、skills）存在各自的 `pipeline_state.json` 里，彼此不可见
- OV 搜索不限 agent，但语义搜索结果只返回原始资源（`tiger/memory/*`、`leopard/memory/*` 等），**没有结构化认知数据**
- 同一 subject（比如"飞书审批流程"）在虎哥和豹哥的管线里各自归纳了一套 policy，**无法自动合并**
- 没有冲突检测：两位 Agent 对同一事实推导出矛盾 triple 时，系统不感知

---

## 二、目标

> 让康少、虎哥、豹哥、好妹、好二妹的认知产物（policies + concepts + skills）通过 OV 联邦共享，实现：
> 1. A 发现的模式，B 直接可用
> 2. 相似的认知自动合并，不重复
> 3. 矛盾认知被标记，等待吉哥或虎哥裁决

---

## 三、方案设计

### 3.1 共享 namespace 约定

每个 Agent 向 OV 写入结构化认知数据，使用统一 prefix：

```
viking://resources/cognitive/{agent_name}/
├── policies/          ← PolicyRow 的 JSON 序列化
│   ├── {policy_id}.json
│   └── ...
├── concepts/          ← Concept 的 JSON 序列化
│   ├── {concept_id}.json
│   └── ...
├── skills/            ← SkillRow 的 Markdown
│   ├── {skill_name}.md
│   └── ...
├── triples/           ← Triple 的 JSON
│   ├── {triple_id}.json
│   └── ...
├── consensus.json     ← 跨 Agent 合并记录
└── conflicts.json     ← 矛盾 triple 列表
```

### 3.2 写入时机

在 `CognitivePipeline.process_session_end()` 末尾新增一个 `sync_to_ov()` 步骤：

```
process_session_end() {
    ...原有管线逻辑...
    sync_to_ov()  ← 新增：将本次 session 产生的新 policies/concepts/skills 写入 OV
}
```

写入策略：
- **增量**：只写入本轮 session 新增/更新的认知产物
- **幂等**：已有同 id 的 policy 不覆盖，除非有新版本
- **tagged**：每条认知数据带 `agent_name` 和 `session_id` 标签

### 3.3 共识发现（Consensus Finder）

独立模块 `cdx_brain/federation/consensus.py`，由 `cdx-brain federate` 子命令触发：

#### 步骤 A：语义近邻搜索

对每个 Agent 的新 policy/concept，用 OV 搜索找其他 Agent 的语义近邻：

```
policy_A → OV search(description) → 找到 tiger 的相似 policy_B
          → Jaccard(trigger_pattern) > 0.6 → 候选合并
```

#### 步骤 B：相似度判定

| 条件 | 判定 |
|:----|:-----|
| OV 语义相似度 > 0.8 | 自动合并 |
| 0.6 ~ 0.8 + trigger_pattern Jaccard > 0.6 | 建议合并（标记 pending_review） |
| trigger_pattern Jaccard > 0.8 | 直接合并（不依赖 OV） |
| < 0.6 | 保持独立 |

#### 步骤 C：合并策略

```
合并后的 Policy:
  name = policy_A.name  # 保留先创建的
  description = f"{policy_A.description}\n\n---\n{policy_B.description}"
  confidence = max(A.confidence, B.confidence)
  activation_count = A.count + B.count
  source_trace_ids = A.ids + B.ids
  tags = ["consensus", A.agent, B.agent]
```

合并结果写入 `cognitive/consensus.json`，各 Agent 本地管线下次加载时自动拉取。

### 3.4 冲突检测（Conflict Detector）

#### 触发条件

两位 Agent 对同一 subject 推导出矛盾 triple：

```
虎哥: ("飞书审批", "最大文件大小", "20MB")
豹哥: ("飞书审批", "最大文件大小", "100MB")
```

#### 检测算法

```
对 cognitive/*/triples/ 下的所有 triple：
  1. 按 (subject, predicate) 分组
  2. 同一组内 object 不一致 → 标记冲突
  3. 计算置信度差值：conflict_score = abs(conf_A - conf_B)
  4. conflict_score < 0.3 → 标记 "minor"
  5. conflict_score >= 0.3 → 标记 "major"
```

#### 处理

冲突写入 `cognitive/conflicts.json`：
- **major 冲突** → 发飞书卡片通知吉哥/虎哥裁决
- **minor 冲突** → 标记 pending，下轮 session 自动尝试重新推导

### 3.5 跨 Agent 检索增强

`inject.py` 的 OV 搜索从 "搜原始资源" 升级为 "搜结构化认知"：

```
原来的 search_ov(query):
  → OV search_find(query)
  → 返回匹配的原始资源（memory/* 等）

升级后的 search_federated(query):
  → OV search_find(query, scope="cognitive/*")
  → 返回匹配的 policies + concepts + skills
  → 按置信度降序排列
  → 与本地 RRF 融合
```

同时保留原 search_ov 作为兜底（搜不到结构化认知时才去原文找）。

---

## 四、文件改动清单

| 文件 | 改动 |
|:----|:-----|
| `cdx_brain/federation/__init__.py` | 新：联邦模块包 |
| `cdx_brain/federation/consensus.py` | 新：共识发现 + 合并引擎 |
| `cdx_brain/federation/conflict.py` | 新：冲突检测 + 报告 |
| `cdx_brain/federation/sync.py` | 新：管线状态 → OV 同步 |
| `cdx_brain/memos/pipeline.py` | `process_session_end()` 末尾 + `sync_to_ov()` |
| `cdx_brain/templates/inject.py` | + `search_federated()` 搜索结构化认知 |
| `cdx_brain/cli.py` | + `federate` 子命令 |
| `cdx_brain/promote.py` | `--federate` flag 触发共识扫描 |

---

## 五、风险与依赖

| 风险 | 缓解 |
|:----|:-----|
| OV 账户欠费（百炼嵌入停摆） | 共识发现回退到 Jaccard + bigram 关键词匹配 |
| 多 Agent 同时写入竞争 | 每条认知数据天然有 id，幂等写入 |
| 合并错了删除麻烦 | 所有合并操作记录到 `consensus.json`，可回滚 |
| 飞书通知需要 lark-cli 权限 | 冲突通知做成可选配置，默认只写 logs |

---

## 六、工作量估算

| 模块 | 代码量 | 依赖 |
|:----|:-----:|:----:|
| `federation/sync.py` | ~80 行 | pipeline.py 的 `to_dict()` 方法 |
| `federation/consensus.py` | ~150 行 | OV search + Jaccard |
| `federation/conflict.py` | ~80 行 | triple 分组比较 |
| `pipeline.py` 修改 | +15 行 | 末尾加 sync 调用 |
| `inject.py` 修改 | +40 行 | `search_federated()` |
| `cli.py` + `promote.py` | +30 行 | federate 子命令 |
| **合计** | **~400 行** | |

---

## 七、评审问题

> 给 豹哥 和 虎哥 的评论指引：

1. **namespace 约定**：`viking://resources/cognitive/{agent_name}/` 这个 prefix 各 Agent 认同吗？还是要用别的根路径？
2. **共识策略**：自动合并阈值 0.8 是否过松/过紧？
3. **冲突上报**：major 冲突发飞书卡片这个动作，谁负责实现？虎哥的 lark-cli 还是我这边的 cdx-brain？
4. **同步时机**：每次 SessionEnd 都写 OV 会不会太频繁？加个 `--federate-interval` 配置控制？
5. **回滚能力**：是否需要 UI（cdx-brain viewer）查看合并历史？
