# cdx-brain v0.9.1 — hot.md 跨会话续接

> 2026-06-29
> 从 v0.9.0 升级
> 来源：cc-star v0.7.1 hot.md 启发 + 吉哥需求

---

## 新增

### 🆕 hot.md 跨会话续接

零 LLM 成本的工作状态快照，解决"新会话失忆"。

- **hot.py** — hot.md 读写器，纯标准库依赖
  - `read_hot()`：读取并解析 YAML front matter + Markdown body，超时标注（expired）
  - `write_hot()`：写入当前会话 work-in-progress 状态
  - `clear_hot()`：用户主动重置
  - 内置过期检测（默认 24h）、截断保护（默认 500 tokens）
  - 格式与 cc-star v0.7.1 兼容

### 🆕 生命周期集成

- **store.py (Stop hook)** — 自动写入 hot.md（project / summary / status / next）
- **session_start.py (SessionStart hook)** — 自动读取并注入 systemMessage：

```
OV:online | Hot: hot.md integration done | Next: add tests
```

过期时追加 `(上次会话 24h+ 前)` 前缀。

---

## 改进

- **config.yaml** — 新增 `memory.hot` 配置段（enabled / path / max_age_hours / max_tokens）

---

## 与 v0.9.0 的关系

- 新增 1 个模块（hot.py），修改 3 个文件（config.py / store.py / session_start.py）
- 不破坏已有管线，不与 cache.db / promote_gate / OV 冲突
- hot.md 与 cc-star 各自维护，路径独立不冲突

---

## 升级说明

```bash
pip install -e .
# hot.md 自动在 Stop 时创建；无需额外配置
```

---

## 技术统计

- 新建 1 个文件 + 25 项单元测试
- 全部测试通（25/25），零回归
- 零外部依赖，零 LLM token 成本
