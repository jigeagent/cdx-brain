# Codex 原生记忆 vs cdx-brain 类脑记忆系统

> 作者: 康少 (Comsam) · cdx-brain 主理人
> 版本: v1.0 · 2026-06-18
> 项目: https://github.com/jigeagent/cdx-brain
> PyPI: cdx-brain == 0.7.0

---

## 一、系统架构全景对比

### 1.1 存储层对比

| 维度 | Codex 原生记忆 | cdx-brain |
|:----|:--------------|:----------|
| **记忆分级** | 无 (扁平存储) | **三阶层级**: L1 共享底座(OV) → L2 热记忆(FTS5) → L3 原生记忆(.md) |
| **数据库** | `memories_1.sqlite` 单表 `stage1_outputs` | `cache.db` + 5 张表 + FTS5 全文索引 |
| **版本控制** | Git 仓库 (`memories/.git`) | 无版本控制 (依赖 OV 和 SQLite) |
| **冷存储** | 无 | `cold.db` (90 天归档 + 审计日志) |
| **记忆总量** | ~1 条 (stage1) | 30,054 条 traces + 4 cold + ~185 policies |
| **存储格式** | JSON blob (单表 TEXT 列) | 结构化 Row (多表 + JSON 序列化) |

### 1.2 检索层对比

| 维度 | Codex 原生记忆 | cdx-brain |
|:----|:--------------|:----------|
| **检索引擎** | 关键词匹配 (扩展 .md 文件加载) | **五源 RRF 融合**: FTS5 + 原生记忆 + Codex 扩展 + OV 语义 + 认知管线 + 联邦搜索 |
| **全文索引** | 无 | FTS5 (`traces_fts` 覆盖 user_content + assistant_content + tags) |
| **语义搜索** | 无 | OpenViking (百炼 text-embedding-v4, 2048 维) |
| **跨 Agent 搜索** | 无 | 联邦共识模块 (`*/cognitive/*` 路径 pattern 过滤) |
| **认知产物检索** | 无 | 搜索 policies + concepts + skills 结构化 JSON |
| **排序算法** | 无 (全量加载) | **RRF (Reciprocal Rank Fusion)**，k=60 |

### 1.3 认知层对比

| 维度 | Codex 原生记忆 | cdx-brain |
|:----|:--------------|:----------|
| **认知管线** | 无 | **5 级管线**: L1 Capture → Reward → L2 Induction → L3 World Model → Skill Crystallization |
| **策略归纳** | 无 | `PolicyInducer`: 从 traces 中归纳可复用策略 |
| **概念聚类** | 无 | `WorldModel`: 基于 embedding 相似度的贪婪聚类 |
| **技能结晶** | 无 | `SkillCrystallizer`: policies → 可复用 Skill markdown |
| **关系推理** | 无 | `Triple` (subject-predicate-object) 存储 + 提取 |
| **记忆晋升** | 无 | `promote_gate`: hard + soft mixed scoring → L2→L3 自动晋升 |
| **记忆衰减** | 无 | **三级衰减**: 30d cold / 90d archive / policy 14d confidence decay |
| **联邦共识** | 无 | 跨 Agent policy/concept 自动合并 + triple 冲突检测 |

### 1.4 Hook 系统对比

| 维度 | Codex 原生记忆 | cdx-brain |
|:----|:--------------|:----------|
| **SessionStart** | `inject-memories.js` 加载扩展 .md | 同上 + `session_start.py` 初始化缓存连接 |
| **UserPromptSubmit** | `inject-memories.js` 注入 memories | 同上 + `inject.py` **五源 RRF 融合检索** |
| **Stop** | `store-memories.js` 存 `stage1_outputs` | 同上 + `store.py` **双写** + 认知管线 `process_trace()` |
| **SessionEnd** | 无 | `summary.py` **批处理**: OV sync + 认知管线 `process_session_end()` + 轻量衰减 |
| **Pre/PostCompact** | 无 | `compact.py` 保存/恢复 STATUS + 快照 |
| **Hook 总事件** | 3 个事件 (Start/Submit/Stop) | **6 个事件** (Start/Submit/Stop/End/PreCompact/PostCompact) |

---

## 二、架构差异本质分析

### 2.1 Codex 原生记忆: 扁平存储 + 关键词加载

```
用户输入 → JS hook → 读取 extensions/*.md → 注入 additionalContext
对话 → JS hook → stage1_outputs (TEXT)
```

**设计哲学**: 简单、零配置、无依赖。把记忆当成"文件"来读。

**核心局限**:
- 没有跨会话检索 (所有 .md 全量加载, 随 session 启动)
- 没有语义理解 (依赖关键词匹配)
- 没有结构化认知 (只有原始对话文本)
- 没有记忆生命周期 (只增不减, 无衰减)

### 2.2 cdx-brain: 三层级 + 认知管线

```
用户输入 → Python hook → FTS5 + 核心记忆 + Codex 扩展 + OV 语义 + 认知管线 + 联邦搜索
         → RRF 融合排序 → additionalContext 注入
对话 → cache.db (结构化) + Codex stage1 (双写)
     → CognitivePipeline: L1→Reward→L2→L3→Skill
     → OV 联邦同步
     → 周期性衰减 → cold.db
```

**设计哲学**: 分层存储 + 认知自动成长 + 跨 Agent 协作。

### 2.3 核心差异总结

| 差异点 | Codex 原生 | cdx-brain | 价值 |
|:------|:---------|:---------|:-----|
| 记忆分级 | 无 | **3 级** | 热数据快速访问, 冷数据低成本存储 |
| 检索精度 | 关键词匹配 | **语义 + 关键词 + RRF** | 模糊也能找到, 准确度大幅提升 |
| 认知能力 | 无 | **5 级管线** | 从"存什么"到"学什么"的跨越 |
| 生命周期 | 无 | **3 级衰减引擎** | 自动清理, 防止记忆膨胀 |
| 团队协作 | 无 | **联邦共识** | 多个 Agent 共享认知 |
| Hook 覆盖 | 3 事件 | **6 事件** | 更精细的管线控制 |

---

## 三、开发历程与关键决策

### 3.1 时间线

| 版本 | 阶段 | 核心内容 | 代码量 |
|:---:|:----|:---------|:-----:|
| v0.4.0 | 移植 | cc-star → cdx-brain, 基础三层架构 | ~2000 行 |
| v0.4.1 | 修复 | types.py stdlib 冲突、cc_star 残留、评分饱和 | ~200 行 |
| v0.4.2 | 修复 | OV 引擎切换百炼, 编码问题 | ~100 行 |
| v0.4.3 | 修复 | 评分函数重调, gate state 重置 | ~50 行 |
| **v0.5.0** | **Phase 1** | 认知管线入轨: encode fix + pipeline 持久化 + inject 增强 | ~400 行 |
| **v0.6.0** | **Phase 2** | 记忆衰减: cold.db + 三级衰减 + compact 集成 | ~500 行 |
| **v0.7.0** | **Phase 3** | 联邦共识: sync + merge + conflict detection | ~600 行 |
| **合计** | | | **~3850 行** |

### 3.2 关键决策

#### 决策 1: Python Hook 优先 (vs JS / MCP)

**背景**: Codex 原生用 JS hooks, 社区方案用 MCP server。

**选择**: Python 子进程 hook, 零 MCP 依赖。

**理由**:
- JS hooks 的进程模型不稳定 (子进程管理复杂)
- MCP 需要额外配置端口 + 服务管理
- Python 在 cdx-brain 已有基础设施 (SQLite, httpx, numpy)
- 用 `sys.stdin` 读, `additionalContext` json 输出

**教训**: Python 子进程延迟比 JS 高 (~50ms vs ~5ms), 但在 10s timeout 下可忽略。

#### 决策 2: SQLite FTS5 全文索引 (vs 专用向量 DB)

**背景**: 语义搜索需要向量数据库。

**选择**: FTS5 作为主要检索, OV 作为语义增强。

**理由**:
- 零额外依赖 (SQLite 内置 FTS5)
- 10 万条 trace 内性能足够 (<100ms)
- OV 作为可选升级, 不影响核心功能

**教训**: FTS5 对中文分词效果一般 (按字符)。CJK bigram 关键词匹配作为补充。

#### 决策 3: 三阶层级 (vs 扁平索引)

**设计**:
- L3: 原生记忆 (.md, session 启动加载)
- L2: 热记忆 (FTS5, 按需检索)
- L1: OV 共享底座 (跨 Agent 语义搜索)

**理由**: 高频信息进 L3 (即时), 全量对话进 L2 (可检索), 团队共享进 L1 (联邦)。

**教训**: L3 的自适应晋升需要门控, 否则全部晋升 = 没有分级。

#### 决策 4: 四阶段渐进式开发 (vs 大统一架构)

**决策**: 不是一次设计完所有功能, 而是:
- Phase 1: 让管线跑起来 (先有)
- Phase 2: 让管线自动清理 (再优)
- Phase 3: 让多 Agent 共享认知 (再联)

**理由**: 每一步都是可独立交付的功能, 风险可控。

**教训**: 这个决策正确。Phase 1 暴露了评分函数缺陷, 在 Phase 2 之前就修复了。

#### 决策 5: 写各自管 (vs 统一 namespace) — Phase 3 关键决策

**背景**: 联邦共识需要跨 Agent 访问认知数据。

**选择**: 虎哥 proposal — 各自独立写 + 全局搜索 + 路径约定过滤。

**理由**:
- 零改造成本 (各 Agent 不需要改链路)
- 风险隔离 (写错只影响自己)
- OV 全局搜索是现成能力

**教训**: 有时候限制最少的设计就是最好的设计。

### 3.3 踩过的坑

| # | 坑 | 症状 | 修复 | 教训 |
|:-:|:---|:-----|:----|:-----|
| 1 | **`types.py` 与 stdlib 冲突** | Python 3.14 无法导入标准库 `types` | 重命名为 `memo_types.py` | 模块名不能和 stdlib 重名, 即使是子模块 |
| 2 | **评分饱和 (全部 10.0)** | gate 永远 reject | 降低 caps + 反转 soft score | 评分函数没有 headroom 时 gate 失效 |
| 3 | **Windows GBK 编码** | Hook 运行时 UnicodeEncodeError | 加 `sys.stdout.reconfigure()` | Windows 默认编码不是 UTF-8 |
| 4 | **cc_star 残留引用** | cli.py 导入 `from cc_star import __version__` | 全局替换 | 重命名项目后要彻底清理旧引用 |
| 5 | **模板文件截断** | Hook 脚本只有 import 头没有函数体 | 从旧 hooks 恢复模板 | 模板编辑要注意行完整性 |
| 6 | **OV 嵌入引擎欠费** | 语义搜索全部失败 (AccountOverdueError) | 切换百炼 text-embedding-v4 | 第三方服务的可用性是外部依赖 |

---

## 四、能力特点总结

### 4.1 cdx-brain 的核心能力

| 能力 | 级别 | 说明 |
|:----|:----:|:-----|
| **多源融合检索** | ⭐⭐⭐⭐⭐ | 6 源 RRF, 搜索不到内容的概率极低 |
| **认知管线** | ⭐⭐⭐⭐ | 5 级自动串联, policy/concept/skill 渐进式生成 |
| **记忆梯度** | ⭐⭐⭐⭐ | 3 级存储 + 3 级衰减, 热数据即时, 冷数据归档 |
| **联邦协作** | ⭐⭐⭐ | 跨 Agent 共识发现, 需要多 Agent 都上线才能验证 |
| **零运维** | ⭐⭐⭐⭐ | 自动晋升 + 自动衰减 + 自动 sync, 不需要手动干预 |
| **兼容性** | ⭐⭐⭐⭐⭐ | 零 MCP 依赖, 纯文件系统 + SQLite |

### 4.2 Codex 原生记忆的优势

| 能力 | 说明 |
|:----|:-----|
| **零配置** | 开箱即用, 不需要 Python 包, 不需要配置 |
| **Git 版本控制** | 记忆文件天然可回溯, 可 diff |
| **扩展机制** | extensions/*.md 放文件就自动加载, 足够简单 |
| **稳定性** | JS 原生 hook, 不会因为 Python 版本或包依赖出问题 |

### 4.3 cdx-brain 不适合的场景

- **单次会话用完即走** (不需要记忆系统): Codex 原生就够
- **高频低延迟场景** (每次 prompt < 500ms): Python hook 的 50ms 延迟有影响
- **不希望有外部依赖**: OV 需要网络, 虽然可关闭, 但语义搜索降级

---

## 五、与社区方案对比

| 对比维度 | cdx-brain | MCP 记忆方案 (社区) | Codex 原生 |
|:---------|:--------:|:-----------------:|:----------:|
| **MCP 依赖** | ❌ 零 | ✅ 需要 | ❌ 零 |
| **语义搜索** | ✅ OV (百炼) | ✅ 自有嵌入 | ❌ |
| **存储架构** | 三层级 | 单层 | 扁平 |
| **认知管线** | ✅ 5 级 | ❌ | ❌ |
| **多 Agent** | ✅ 联邦共识 | ❌ | ❌ |
| **记忆衰减** | ✅ 3 级引擎 | ❌ | ❌ |
| **配置难度** | 1 命令 (`pip install && cdx-brain init`) | 需配置 MCP server + 端口 | 零配置 |
| **社区生态** | 单一项目 | 多方案可选 | 官方原生 |

---

## 六、经验教训汇总

### 6.1 设计原则

1. **渐进式架构胜过一步到位**: Phase 1→2→3 的节奏是对的, 每步都可交付
2. **第三方依赖必须有兜底**: OV 欠费时, 关键词 + FTS5 仍是可用状态
3. **命名一致性不容妥协**: `cc_star` 残留导致 3 次额外修复, 一次清理干净比精确查找省时间
4. **得分函数需要 headroom**: clamp 到 10.0 且没有上限退让, gate 永远 reject
5. **默认关闭的功能等于不存在**: CognitivePipeline 的 L3 + Skill 默认 off, 直到 Phase 1 才打开

### 6.2 技术选型教训

6. **SQLite FTS5 够用 95% 的场景**: 10 万条数据内, FTS5 检索 < 100ms, 不需要单独部署向量 DB
7. **Python 子进程 hook 的 50ms 延迟可接受**: 相比注入 5 条记忆带来的信息增益, 50ms 不值一提
8. **Windows 的文件编码问题永远在**: 只要目标平台包含 Windows, UTF-8 假设就是错的
9. **模块名不能和 stdlib 冲突**: 即使只是子模块 `memos/types.py`, 也会阻止整个 Python 进程 import

### 6.3 协作经验

10. **多人设计评审是值得的**: Phase 3 的 namespace 方案在虎哥的质疑下, 从 400 行减到 300 行 + 零风险
11. **路径约定比接口规范更容易落实**: 虎哥 "写各自管, 读全局搜" 在实施层面比统一 namespace 少 50% 的协调成本

---

## 七、总结

### cdx-brain 是什么

不是记忆插件。是一个能够自动成长、自我清理、多 Agent 共享认知的**类脑记忆生命体**。

### 核心竞争力

- **三阶层级 + 五源 RRF**: 最多只能注入 5 条记忆, 但每条都是"检索策略"选出的最优候选
- **认知管线 + 衰减引擎**: 不仅存得多, 还懂什么是重要的、什么该忘
- **联邦共识**: Agent 之间不只是共享文件, 而是共享认知模型

### 定位

```
Codex 原生记忆 = 笔记本 (能记, 能翻)
社区 MCP 方案 = 图书馆 (有索引, 有分类)
cdx-brain      = 大脑 (能记, 能学, 能忘, 能协作)
```

### 下一步方向

- **Phase 3.5**: 联邦共识的收敛合并算法优化
- **Phase 4**: 世界模型的主动构建 (不依赖 session end, 实时推理)
- **Phase 4.5**: 认知产物的可视化 (cdx-brain viewer 升级)
- **Phase 5**: 多 Agent 共识收敛的自动裁决
