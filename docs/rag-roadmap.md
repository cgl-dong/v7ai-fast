# RAG 增强路线图

> 当前 v7ai-fast 已实现基础的 Dense Retrieval（BGE 768d 语义检索），
> 以下为后续迭代计划，逐步提升检索质量和答案准确率。

---

## 1. 混合检索（Dense + BM25 → RRF 融合）

### 动机

纯 Dense 检索对精确关键词匹配（如工号、型号、法律条款编号）效果差；
BM25 对语义理解弱但关键词命中精准。混合两者互补。

### 方案

```
用户查询 → ──┬── Dense (BGE)  → top_k=20
             │
             └── BM25   →  top_k=20
             │
             └── RRF 融合 → top_k=5 → 送入 generate
```

### 关键技术

- **BM25 实现**：用 PostgreSQL `tsvector` + `ts_rank` 或引入 `rank_bm25` 库
- **RRF 融合**：`RRF(d) = Σ 1/(k + rank_i(d))`，k=60 经典参数
- **索引维护**：chunk 入库时同步写入 `tsvector` 列（中文需 `zhparser` 或 `jieba` 分词）

### 涉及改动

- 数据库：`document_chunks` 加 `tsv_content` 列（`tsvector` GIN 索引）
- 服务：`indexer.py` 索引时生成 `tsvector`
- 检索：`search_chunks` 改为两路检索 + RRF
- 配置：settings 加 `BM25_WEIGHT` 超参

---

## 2. Cross-Encoder 重排序

### 动机

Dense + BM25 召回 20 条候选，但排序质量有限。
Cross-Encoder 将 query+document 拼接后打分，精度远高于 Bi-Encoder。

### 方案

```
top_k=5 → top_k=20 (粗排) → Cross-Encoder 精排 → top_k=5 (最终)
```

### 关键技术

- **模型**：`BAAI/bge-reranker-base` 或 `BAAI/bge-reranker-v2-m3`
- **Pipeline**：`sentence_transformers.CrossEncoder`
- **延迟优化**：候选数 ≤ 20 时 Cross-Encoder 延迟可接受（~200ms on CPU）

### 涉及改动

- 服务：`indexer.py` 检索返回 top_k=20
- 服务：新增 `rerank.py` — Cross-Encoder 精排
- 配置：settings 加 `RERANK_ENABLED`、`RERANK_CANDIDATES`

---

## 3. Query 改写（HyDE + Multi-Query）

### HyDE（Hypothetical Document Embeddings）

用 LLM 先生成假设答案，再拿假设答案去检索，缩小 query-document 语义 gap。

```
用户问题 "2025年营收" 
  → LLM 生成假设文档 "公司2025年营收达到XX亿元..."
    → BGE embedding
      → 语义检索
```

### Multi-Query

一次查询拆成多个视角的子查询，合并去重结果。

```
原始: "对比Q1和Q2的营收"
  → LLM 生成: "Q1营收数据"、"Q2营收数据"、"Q1与Q2营收对比分析"
    → 并行检索
      → 去重 → 送入 generate
```

### 涉及改动

- 服务：新增 `query_rewrite.py`
- 配置：settings 加 `HYDE_ENABLED`、`MULTI_QUERY_ENABLED`
- 注意：每次改写 = 一次 LLM 调用，需权衡延迟

---

## 4. 检索质量评估（Hit Rate / MRR / NDCG）

### 动机

没有评估就无法判断检索改动的效果。
需要一套离线 benchmark 定量衡量每次策略变更的收益。

### 方案

```
评测数据集 (questions + relevant_chunks)
        │
  ┌─────┴─────┐
  ▼           ▼
 当前策略    新策略
  │           │
  ▼           ▼
 Hit Rate / MRR / NDCG 对比
```

### 指标

| 指标 | 含义 | 用途 |
|------|------|------|
| **Hit Rate@K** | Top-K 中至少命中一条相关文档的比例 | 衡量"有没有找到" |
| **MRR@K** | 第一条相关文档的排名倒数均值 | 衡量"排得多靠前" |
| **NDCG@K** | 归一化折损累积增益 | 综合排名质量（含多相关文档） |

### 涉及改动

- 数据：创建评测数据集 `data/eval/sample_questions.jsonl`
- 服务：新增 `eval.py` — 批量检索 + 指标计算
- 脚本：`python -m scripts.eval_retrieval` 一键跑分

---

## 实施优先级建议

| 步骤 | 模块 | 预期收益 | 复杂度 |
|:---:|------|---------|:---:|
| 1 | **检索质量评估** | 建立 baseline，后续改动可量化 | 中 |
| 2 | **混合检索 BM25** | 关键词精确命中，解决 Dense 短板 | 低 |
| 3 | **Query 改写** | 多视角覆盖，长尾查询提升 | 中 |
| 4 | **Cross-Encoder 重排序** | 排序精准度显著提升 | 中 |
| 5 | **HyDE** | 缩小 query-doc gap，复杂场景有效 | 高 |

> 实施顺序原则：先建立评估体系（知道改好了还是改坏了），
> 再做低成本高收益的改动（BM25），最后做 LLM 依赖的优化（改写/重排）。
