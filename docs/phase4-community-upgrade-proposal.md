# Phase 4 cdx-brain 迭代升级方案

> 来源：Codex 社区记忆系统调研（2026-06-27）
> 作者：康少
> 对标项目：Mainline · Thread-Scoped Memory · COMPASS Skills

---

## 一、背景

社区调研发现三个可借鉴方向，与 cdx-brain v0.8.0 现有架构互补：

| 方向 | 来源 | 核心思想 | cdx-brain 现有能力 | 差距 |
|:----:|:----:|:---------|:------------------:|:----:|
| 反事实记忆 | Mainline | Git notes 存"放弃的方案+原因" | 晋升门控只存"被采纳的" | ❌ 无"为什么不做"通道 |
| 哨兵监控 | Thread-Scoped #15432 | 后台 Agent 持续监控记忆健康+预检 | heartbeat 只做简单存活检查 | ❌ 无主动记忆质量巡检 |
| 任务 DAG | COMPASS Skills | 跨会话任务依赖图+用户画像 | session 按时间线存储 | ❌ 无结构化任务关系 |

---

## 二、方案总览

### 2.1 架构新增模块

```
cdx_brain/
├── counterfactual/          ← 新增：反事实记忆模块
│   ├── __init__.py
│   ├── log.py               ← 反事实记录器
│   ├── store.py              ← 反事实存储引擎（FTS5 + 独立 table）
│   └── inject.py             ← 反事实注入器（session_start 时加载相关反事实）
├── sentinel/                ← 新增：哨兵监控模块
│   ├── __init__.py
│   ├── scout.py             ← 哨兵巡检器（记忆质量评估）
│   ├── preflight.py          ← 预检器（session 启动前检查）
│   ├── report.py             ← 报告生成
│   └── cli.py                ← sentinel 子命令
├── task_forest/             ← 新增：任务森林模块
│   ├── __init__.py
│   ├── dag.py               ← 决策 DAG（节点/边/状态）
│   ├── forest.py             ← 森林管理器（跨会话持久化）
│   ├── profile.py            ← 用户画像
│   └── handoff.py            ← Session 交接压缩
└── templates/               ← 更新：钩子模板
    ├── session_start.py     ← + 反事实注入 + 哨兵预检
    ├── store.py             ← + 反事实捕获 + 任务状态更新
    └── compact.py           ← + 哨兵巡检触发
```

### 2.2 整体数据流

```
Session 启动
    │
    ├─ session_start.py
    │   ├── 反事实注入器 → 加载相关 rejection/deprecation 记录
    │   ├── 哨兵预检器 → 检查记忆健康 + 告警
    │   └── 任务森林加载 → 恢复当前任务 DAG
    │
    ├─ 用户交互
    │   ├── 任务森林 → 更新任务状态（start/block/done）
    │   └── 反事实日志 → 记录"放弃/拒绝的方案"
    │
    ├─ Session 结束 (store.py)
    │   ├── 反事实归档 → FTS5 索引
    │   ├── 任务森林持久化 → task_forest.json
    │   ├── 哨兵触发的巡检 → scout_report.md
    │   └── 常规 L1/L2/L3 管线
    │
    └─ Periodic (cdx-brain promote)
        └── 哨兵深度巡检 → 质量评分 → 修复建议
```

---

## 三、方向一：反事实记忆（Counterfactual Memory）

### 3.1 为什么要做

当前 cdx-brain 只记录"被采纳了的知识"。但吉哥和豹哥经常会：
- 试了一个方案发现不行 → 放弃了
- 审 code review 时否决了某个改法
- 从两条路径中选了 A 放弃 B

**没有记录"为什么不做"，下回 Agent 可能重新走进同一个坑。** Mainline 的核心洞察就在于此。

### 3.2 数据模型

```python
@dataclass
class Counterfactual:
    id: str                          # cf_{uuid4}
    subject: str                     # 主体（如"数据库选型"）
    chosen: str                      # 最终选择的方案
    rejected: str                    # 被放弃的方案
    reason: str                      # 放弃原因（核心字段）
    context: str                     # 发生时的上下文
    confidence: float                # 确认度 0-1
    decided_by: str                  # 决策者（吉哥/豹哥/虎哥）
    created_at: str
    tags: list[str]
    source_session: str              # 来源 session ID
```

### 3.3 存储

FTS5 独立表 `counterfactuals`，与现有的 `traces` 表同级，统一由 RRF 检索。

### 3.4 捕获时机

| 触发点 | 检测方式 | 自动/手动 |
|:------|:---------|:---------:|
| promote reject | promote_gate 拒绝 candidate 时 | 自动 |
| Session 中出现"放弃"关键词 | 正则匹配 | 自动 |
| 用户显式标记 | `cdx-brain cf add` 命令 | 手动 |
| CR 否决 | 从对话中提取豹哥的驳回意见 | 半自动 |

### 3.5 注入时机

`session_start.py` 新增加载逻辑，检索与当前 query 相关的反事实记录，注入到 session 上下文。

注入格式示例：

```
## ⚠️ 相关历史决策（反事实）

以下方案曾被尝试并放弃，当前 session 请注意避免重复踩坑：

1. [数据库选型] 选择了 TiDB，放弃了 Redis 队列
   原因：Redis 复制延迟导致计费重复，回滚困难
   决策者：吉哥 | 来源：session_2026-06-20

2. [飞书通知方案] 选择了 webhook，放弃了 lark-cli
   原因：lark-cli 认证配置复杂，不适合 CI/CD 场景
   决策者：豹哥 | 来源：session_2026-06-18
```

---

## 四、方向二：哨兵监控（Sentinel Scout）

### 4.1 为什么要做

Thread-Scoped Memory #15432 提出的后台 sentinel agent 概念：
- 不占用主 session 的推理预算
- 能在 session 间持续监控记忆系统健康
- 主动发现问题而非被动等待用户报告

### 4.2 巡检项

| 巡检项 | 检测方法 | 严重度 |
|:------|:---------|:------:|
| cache.db 大小超限 | > 500MB = warn, > 1GB = critical | 🔴 |
| 记忆碎片率 | FTS5 碎片率 > 30% | 🟡 |
| 孤立的 session | 超过 30 天无关联的 session | 🟡 |
| 低分 content | promote score < 0.3 的 trace | 🟢 |
| OV 连通性 | 健康检查失败 | 🔴 |
| BD 盘同步 | 上次同步 > 24h | 🟡 |
| 反事实未归档 | 未归档的反事实 > 10 条 | 🟢 |

### 4.3 报告格式

```markdown
# 🛡️ 哨兵巡检报告 · 2026-06-27 10:00

## 🔴 Critical
- 无

## 🟡 Warning
- 记忆碎片率 35% → 建议 promote --vacuum
- BD 盘最后同步 2026-06-25（2天前）

## 🟢 Info
- cache.db: 92MB ✅
- OV 连通: 正常 ✅
- 晋升门控: 5 promote / 0 reject
```

---

## 五、方向三：任务森林（Task Forest）

### 5.1 数据模型

```python
@dataclass
class TaskNode:
    id: str                          # task_{uuid4}
    parent_id: str | None
    title: str
    description: str
    status: Literal["open", "in_progress", "blocked", "done", "cancelled"]
    blocked_by: list[str]
    created_at: str
    updated_at: str
    session_ids: list[str]
    tags: list[str]
    decisions: list[str]
```

### 5.2 自动检测

| 触发点 | 检测规则 |
|:------|:---------|
| 提到"拆出/分解为子任务" | 自动创建 subtask edge |
| "等待/阻塞/依赖"关键词 | 自动标注 blocked |
| "做完了/搞定了" | 自动标记 done |
| 显式命令 | `cdx-brain task start/done/block` |

### 5.3 用户画像

同步引入 COMPASS 的 `user-profile-keeper` 思想，存储在 `E:\codex\comsam\user_profile.json`。

---

## 六、实施路线图

| Phase | 内容 | 代码量 | 工期 | 优先级 |
|:----:|:----|:------:|:----:|:------:|
| 4.1 | 反事实记忆 | ~240 行 | 3-5 天 | 🥇 最高 |
| 4.2 | 哨兵监控 | ~305 行 | 3-4 天 | 🥈 中 |
| 4.3 | 任务森林 | ~370 行 | 4-5 天 | 🥉 中 |
| **总计** | | **~915 行** | **10-14 天** | |

---

## 七、与现有架构的关系

### 不破坏已有能力

- L1/L2/L3 管线 → 不影响，新增模块独立
- FTS5 检索 → 增强，增加 counterfactuals 检索源
- OpenViking 同步 → 增强，哨兵报告可同步到 OV
- 晋升门控 → 增强，reject 自动记反事实
- Phase 3 联邦记忆 → 并行关系，反事实数据可通过 OV 同步给其他 Agent

---

## 八、决策清单（豹哥评审后更新）

---

## 九、豹哥评审意见（2026-06-27）

> 豹哥 | 独立评估，供康少参考
> 总体判断：方案可行，三个模块各有价值

### 9.1 反事实记忆 🥇 — 采纳

| 建议 | 处理 |
|:----|:----|
| reason 字段确保 FTS5 索引 | ✅ 已确认，SQL 建表时 reason 加入 FTS5 索引列 |
| 中文"放弃"关键词加否定语境检测 | ✅ 触发规则收紧为：`[方案/改法/路径/方向/路线] + [放弃/否决/不用/不行/不采用]` 才触发 |
| 避免 spaCy+regex 误报陷阱 | ✅ 使用最简单的大括号模式匹配而非 NLP 管线 |

### 9.2 哨兵监控 🥈 — 采纳

| 建议 | 处理 |
|:----|:----|
| 碎片率+孤立 session 是 cdx-brain 独有，不与 cc-star doctor 冲突 | ✅ 确认，保持独立巡检 |
| 报告加"上次巡检后已自动修复"段 | ✅ 新增 `auto_fixed` 报告段，VACUUM 等自动操作在巡检报告中单独呈现 |
| BD 盘同步只告警不自动触发 | ✅ 默认 `--no-auto-sync`，避免 session 高峰 I/O 干扰 |

### 9.3 任务森林 🥉 — 有条件采纳

| 建议 | 处理 |
|:----|:----|
| 只做 done 自动检测，不做 in_progress | ✅ done 语义确定性更强，in_progress 仅支持手动 `cdx-brain task status` |
| 用户画像从决策偏好入手 | ✅ 优先级调整为：技术栈偏好 > 架构风格 > 沟通方式 > 风险边界 |
| blocked_by 加 TTL，30 天自动转 cancelled | ✅ `blocked_ttl_days: 30` 配置项，超时自动标记 stale→cancelled |

---

## 十、实施调整（根据豹哥评审）

### 反事实关键词匹配规则（最终版）

```python
# 触发词：主体 + 动作，且 kwargs 的 subject 必须在最近 3 条对话中
TRIGGER_PATTERNS = [
    # 格式: (主体正则, 动作正则)
    (r'(方案|改法|路径|方向|路线|办法|策略)', r'(放弃|否决|不用|不行|不采用|不考虑|不可行)'),
    (r'(尝试|试验|试过)', r'(不行|失败|失效|不成立)'),
]
# 否定检测：动作前 20 个字符内不出现"没/别/不"以外的否定
# 例如"放弃午休写完了" → "午休"不是方案主体 → 不触发
```

### 哨兵报告格式（最终版）

```markdown
# 🛡️ 哨兵巡检报告 · 2026-06-27 10:00

## ✅ 自动修复（上次巡检以来）
- FTS5 VACUUM → 碎片率 35% → 12% ✅
- 孤立 session 清理 → 3 条 moved to cold storage ✅

## 🔴 Critical
- 无

## 🟡 Warning
- BD 盘最后同步 2026-06-25（2天前）→ 建议手动同步

## 🟢 Info
- cache.db: 92MB ✅
- OV 连通: 正常 ✅
- 反事实记录: 0 条
- 晋升门控: 5 promote / 0 reject
```

### 任务森林 blocked TTL（最终版）

```python
@dataclass
class TaskForestConfig:
    blocked_ttl_days: int = 30       # 超过此天数的 blocked 状态自动转 cancelled
    auto_done_enabled: bool = True   # 仅 done 可自动检测
    auto_in_progress: bool = False   # in_progress 不做自动检测（豹哥建议）
    profile_priority: list[str] = field(default_factory=lambda: [
        "tech_stack_preference",     # 技术栈偏好
        "architecture_style",        # 架构风格
        "communication_style",       # 沟通方式
        "risk_boundary",             # 风险边界
    ])
```

1. **反事实自动捕获**：对话中关键词匹配时自动记录——默认开启还是 opt-in？
2. **哨兵巡检频率**：每次 session 结束 quick check，还是独立定时任务？
3. **任务 DAG 粒度**：记录到"任务"级别还是细分到"子步骤"？
4. **用户画像**：是否从这次开始建立吉哥的 profile？
5. **实施优先级**：按 4.1 → 4.2 → 4.3 推进，还是调整顺序？


---

## 十一、豹哥最终决策（2026-06-27）

### 1. 反事实自动捕获 — 默认开启

✅ 同意。`cdx-brain cf disable` 可关。关键词匹配按收紧后的规则（方案/方向/路径/改法 + 放弃/否决/不用/不行）。

### 2. 哨兵巡检频率 — 两者都有

✅ 同意。
- **quick check**：每次 store.py 结束跑（<3秒）
- **深度巡检**：独立定时任务，每天凌晨 **4:00**（避开 cc-star 凌晨 3:00 的 consolidation_worker）

### 3. 任务 DAG 粒度 — 任务级别

✅ 同意。只建任务节点，子步骤用 timeline 事件流记录。

### 4. 用户画像 — 这次就建

✅ 同意。从吉哥开始，字段从决策偏好入手：

```json
{
  "tech_stack_preferences": [],
  "architecture_style": "",
  "decision_patterns": [],
  "anti_patterns": []
}
```

先存着，数据自然积累。

### 5. 实施优先级 — 4.1 → 4.3 → 4.2

✅ 同意。理由：
- **4.1** 反事实价值最高、改动最小 → 先做
- **4.3** 任务森林最独立，不依赖 4.1/4.2 → 第二个
- **4.2** 哨兵与 cc-star doctor 有重叠，需要协调接口 → 放最后

### 实施排期（更新后）

| 顺序 | Phase | 内容 | 代码量 | 工期 |
|:----:|:----:|:------|:------:|:----:|
| 🥇 第1步 | 4.1 | 反事实记忆模块 | ~240 行 | 3-5 天 |
| 🥈 第2步 | 4.3 | 任务森林 + 用户画像 | ~370 行 | 4-5 天 |
| 🥉 第3步 | 4.2 | 哨兵监控模块 | ~305 行 | 3-4 天 |
| | **总计** | | **~915 行** | **~14 天** |

