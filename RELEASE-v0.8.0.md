# cdx-brain v0.8.0 — 知识图谱版

> 2026-06-21
> 从 v0.7.1 升级

---

## 新增

### 🆕 RelationExtractor — 关系自动抽取

从认知管线的 policies/concepts 中自动挖掘三类关系边：

| 关系类型 | 语义 | 抽取方式 |
|:--------:|------|---------|
| `triggers` | A 触发 B | trigger_pattern 模糊匹配 name |
| `relates_to` | A 与 B 语义相关 | description SequenceMatcher > 0.3 |
| `contradicts` | A 与 B 策略矛盾 | 预留，reward 数据积累后启用 |

- 在 `process_session_end()` 末尾自动执行，零人工干预
- 持久化到 `cache.db` 的 `triples` 表，含置信度、时间戳、同步标记
- 25 项单元测试覆盖表创建、模糊匹配、触发/关系/统计逻辑

### 🆕 GraphDiffusion — 图扩散检索引擎

在 FTS5 + 向量 RRF 融合基础上，新增第三路检索 **Tier 5：图扩散**。

- BFS 遍历 `triples` 表，从 FTS5/embedding 命中节点出发
- 支持 depth=1（直接邻居）和 depth=2（间接关联）
- 正向边 + 反向边双向遍历
- 返回路径描述，agent 知道"为什么关联"
- 4 项单元测试覆盖直接扩散、深度2、限制、空种子

### 🆕 CLI 子命令

```
cdx-brain graph status     # 查看图统计（总边数、按类型、孤立节点）
cdx-brain graph diffuse    # 手动补跑关系抽取
```

`cdx-brain doctor` 新增知识图谱健康检查项。

### 🆕 OV 联邦同步

`federation/sync.py` 新增 relations 同步通道，relations 按 `viking://resources/{agent}/cognitive/relations/{id}.json` 写入 OV。

## 架构

```
认知管线                        检索管线
┌────────────┐                ┌──────────┐
│ L1 Capture │                │ FTS5     │ ← 全文检索
├────────────┤                ├──────────┤
│ Reward     │                │ Embedding│ ← 向量检索
├────────────┤                ├──────────┤
│ L2 Induction│               │ Graph    │ ← 图扩散检索 🆕
├────────────┤                │ Diffusion│
│ L3 World   │                └──────────┘
│  Model     │                   ↓
├────────────┤               RRF 融合排序
│ Skill Crys │                    ↓
├────────────┤               additionalContext
│ Relation   │ ← 🆕
│ Extraction │
└────────────┘
```

## 文件变更

| 文件 | 变更 | 行数 |
|:----|:----:|:----:|
| `cdx_brain/retrieval/extractor.py` | 新增 | ~220 |
| `cdx_brain/retrieval/graph_diffusion.py` | 新增 | ~100 |
| `cdx_brain/memos/retrieval.py` | 修改 | +47 |
| `cdx_brain/memos/pipeline.py` | 修改 | +4 |
| `cdx_brain/cli.py` | 修改 | +60 |
| `cdx_brain/federation/sync.py` | 修改 | +15 |
| `cdx_brain/__init__.py` | 修改 | 版本号 |
| `pyproject.toml` | 修改 | 版本号 |
| `tests/test_extractor.py` | 新增 | 25项 |
| `tests/test_graph_diffusion.py` | 新增 | 4项 |
| `docs/superpowers/plans/2026-06-21-knowledge-graph.md` | 新增 | 实现计划 |

## 升级方式

```bash
pip install -e .     # 本地开发模式
# 或
pip install --upgrade cdx-brain
cdx-brain init --force  # 重新部署 hook（如有需要）
```

## 技术债务

- `contradicts` 边类型已预留但暂未启用（需要 reward 方向数据积累）
- `graph diffuse` 需要已有管道状态数据（无存量数据时输出为空，属于正常行为）
- 图扩散暂未接入 hook 模板的 inject.py，需要在下次 `init --force` 后激活

---

*测试：所有 29 项单元测试通过（extractor 25 + graph_diffusion 4）*
