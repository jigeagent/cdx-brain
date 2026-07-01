# cdx-brain hot.md 接入方案

> 提案人：康少 | 2026-06-29
> 审阅：豹哥 → 吉哥拍板

---

## 一、动机

cc-star v0.7.1 新增 hot.md 跨会话续接机制。cdx-brain 作为记忆底座需同步接入：

1. **Stop 时写入**：hot.md 反映当前会话工作状态，跟 cache.db + 晋升走同一批
2. **SessionStart 时读取**：注入到 agent 上下文，解决"新会话失忆"
3. **promote_gate 候选源**：hot.md 中的活跃状态可作为短期记忆候选晋升至原生记忆

---

## 二、架构变更

### 2.1 新增文件：cdx_brain/hot.py

纯标准库依赖（pathlib + datetime + yaml），零外部依赖。

`python
# 接口
read_hot(config) -> dict | None       # 读取 hot.md，超24h标注
write_hot(config, state: dict) -> None # 写入/更新 hot.md
`

### 2.2 config.yaml 新增

`yaml
memory:
  hot:
    enabled: true
    path: "~/.cdx-brain/data/hot.md"      # 默认路径
    max_age_hours: 24                       # 过期阈值
    max_tokens: 500                         # SessionStart 注入长度
`

### 2.3 store.py 改动（Stop hook）

在现有流程末尾追加 hot.md 写入，不阻塞主流程：

`python
# 现有：cache.db write → FTS5 → promote → OV sync → 追加 hot.md
if _GET("memory.hot.enabled", "True"):
    from cdx_brain.hot import write_hot
    write_hot(_CFG, {
        "project": _detect_project(transcript),
        "status": "in_progress",
        "summary": _summarize_turns(transcript),
        "next": _extract_next_actions(transcript),
    })
`

### 2.4 session_start.py 改动

在现有 OV 健康检查 + sessions.jsonl 摘要之后，追加 hot.md 注入：

`python
# 读取 hot.md
if _GET("memory.hot.enabled", "True"):
    from cdx_brain.hot import read_hot
    hot_state = read_hot(_CFG)
    if hot_state:
        msg_parts.append(f"Hot: {hot_state['summary'][:60]}")
`

---

## 三、hot.md 格式

与 cc-star v0.7.1 规划中的格式一致：

`markdown
---
updated_at: 2026-06-29T22:00:00Z
project: cdx-brain
status: in_progress
blocked: 无
summary: store.py hot.md 写入完毕，待 session_start 集成
next: session_start.py hot.md 读取 + 测试
---

## 当前工作
- store.py 已接入 hot.md 写入

## 待办
- [ ] session_start.py 接入 hot.md 读取
- [ ] 过期检测测试
`

---

## 四、注入策略

SessionStart 时 hot.md 的注入方式：

| 情况 | 策略 | 输出 |
|:--|:--|:--|
| hot.md 不存在 | 不注入 | — |
| hot.md < 24h | 注入全部内容 | Hot: {summary} | Next: {next} |
| hot.md >= 24h | 注入并标注过期 | (上次会话 24h+ 前) Hot: {summary} |
| hot.md > 500 tokens | 截断至 max_tokens | — |

注入内容拼接在现有 systemMessage 中，追加  |  分隔。

---

## 五、变更清单

| 文件 | 操作 | 估算 |
|:--|:--|:--:|
| cdx_brain/hot.py | **新增** — hot.md 读写器 | 0.2d |
| cdx_brain/config.py | **修改** — 增加 memory.hot 默认配置 | 0.05d |
| cdx_brain/templates/store.py | **修改** — Stop hook 追加 hot.md 写入 | 0.15d |
| cdx_brain/templates/session_start.py | **修改** — 追加 hot.md 读取注入 | 0.15d |
| 	ests/test_hot.py | **新增** — hot.md 读写测试 | 0.15d |
| | **合计** | **~0.7d** |

---

## 六、与 cc-star hot.md 的关系

| 维度 | cc-star hot.md | cdx-brain hot.md |
|:--|:--|:--|
| 写入时机 | Stop hook | Stop hook |
| 读取时机 | SessionStart | SessionStart |
| 格式 | 同一标准 | 同一标准 |
| 存储路径 | cc-star data dir | cdx-brain data dir |
| 用途 | cc-star 工作状态 | cdx-brain 记忆状态 |
| 两者关系 | 各自维护，路径不冲突 | 可配置为同一路径共享 |

两个模块走同一套格式和生命周期逻辑，路径独立不冲突。用户可配置为同一个文件（如果两个模块都在用），也可各自独立。

---

## 七、不做什么

- ❌ hot.md 不取代 cache.db FTS5 —— 长期检索仍靠 FTS5
- ❌ hot.md 不取代 promote_gate —— 晋升引擎不变
- ❌ 不与 OV 同步（hot.md 是本地活跃态，OV 存长期记忆）
- ❌ 不做 LLM 端推理 —— 纯文件操作，零 token 成本
