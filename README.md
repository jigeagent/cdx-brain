# cdx-brain — Codex 类脑记忆系统

**不是记忆插件。是认知引擎。**

## 三层级记忆架构

```
┌─────────────────────────────────────────────────┐
│           原生记忆 (Codex extensions)            │
│  精炼 · 必需 · session 启动自动加载              │
│  promoted by cdx-brain promote_gate               │
├─────────────────────────────────────────────────┤
│            热记忆 (cdx-brain cache.db)             │
│  全部对话 · FTS5 全文检索 · 按需注入             │
│  Stored by Stop hook → cache.db                 │
├─────────────────────────────────────────────────┤
│          共享底座 (OpenViking)                   │
│  跨 Agent 语义检索 · 联邦记忆                    │
│  synced by SessionEnd hook                      │
└─────────────────────────────────────────────────┘
```

### 一条命令安装

```bash
pip install cdx-brain && cdx-brain init
```

### 无需 MCP 配置
- 零 MCP 依赖 — 不装服务、不配端口、不挂后台
- 三源合一检索 — FTS5 + 关键词 + OpenViking 语义
- 自动成长 — 高频内容自动晋升，相似内容去重
- 零维护 — 自动回收、自动去重、自动晋升

## 对比

| 对比维度 | cdx-brain | 其他记忆方案 |
|---------|:-------:|:----------:|
| MCP 依赖 | ❌ 零 | ✅ 需要 |

## 许可证

AGPL-3.0

## v0.5.0 认知管线就绪

```
L1 Capture → Reward → L2 Induction → L3 World Model → Skill Crystallization
```

- 每轮对话：`process_trace()` 实时处理
- 会话结束：`process_session_end()` 全流程触发
- 管线状态持久化到 `~/.cdx-brain/data/pipeline_state.json`
- 认知产物(policies + concepts)通过 RRF 注入 additionalContext
