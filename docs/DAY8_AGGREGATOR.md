# Day 8 — Aggregator（RAG 分桶摘要 + embedding 回填）

> 目标：把 D2-D7 的所有数据浓缩成"字节后端 2025Q2 高频考点"这种可读 markdown，存进 summaries 表。
> **D8 完成 = 整个 LangGraph 闭环跑通。**

## 0. 这一步带来什么

| 之前 | 现在 |
|---|---|
| questions.embedding 永远 NULL | bge-m3 批量回填，HNSW 索引终于发挥作用 |
| 重复题目不去重 | 余弦相似度 ≥0.92 自动合并，输出 freq 计数 |
| 每个 post 单独看 | (公司 × 岗位 × 季度) 分桶聚合 |
| 没有可读摘要 | DeepSeek 生成 markdown 含 4 章节 |
| 看面经要翻原 url | `il show-summary` 直接看高频考点 |

## 1. 端到端三步

```bash
# 1. 把现有 questions 全部跑 embedding（bge-m3）
uv run il backfill-embeddings

# 2. 跑 Aggregator —— 单桶或全桶
uv run il aggregate --company 字节跳动 --position 后端开发 --period 2025Q2
uv run il aggregate                         # 全桶批量

# 3. 看结果
uv run il show-summary 字节跳动 后端开发 --period 2025Q2
```

## 2. 阻塞流程图

```
posts.questions
    │
    ├─ backfill-embeddings → questions.embedding (1024 维 bge-m3)
    │
    └─ aggregate
         ├─ SQL 分页查桶内全部合格题目（top_n 仅作为显式上限）
         ├─ NumPy 分块相似度 + 阈值建图 + Union-Find → 每簇稳定代表题 + 真实 freq
         ├─ 按 freq 排序，只取 Top-M 代表簇交给 LLM（默认 M=100）
         ├─ DeepSeek 总结 → markdown（4 章节）
         └─ upsert summaries 表
```

## 3. RAG 分桶细节

**SQL 桶定义**：
- post 必须 `extract_status='done'` 且 `content_score >= MIN_CONTENT_SCORE (默认 30)`
- post 关联了指定 (company_id, position_id)
- period 通过 `to_char(posted_at, 'YYYY"Q"Q')` 匹配；传 `--period` 不传走"全部"

**候选读取**：默认读取每桶全部合格题目，按 `content_score DESC, question.id DESC` 使用 keyset 分页，避免把一次 SQL 结果集全部压在数据库连接中。`top_n` 只有在需要限流时才显式设置；它会改变统计人口。
**LLM 上限**：去重和 `freq` 统计完成后，按频次取前 `llm_max_clusters` 个代表簇（CLI 默认 100）送给 LLM；这个上限不改变 `sample_count`。
历史季度摘要不使用当前日期的 freshness，避免同一季度的摘要因今天日期变化而漂移。

**去重策略**：
- 余弦相似度 ≥ 0.92 视为一条边
- 对全量题目分块计算相似度，边构成的图用 Union-Find 求连通分量；结果不依赖输入顺序，也能处理 A≈B、B≈C 的链式合并
- 每个分量选择内容分最高、再用题目 ID 打破平局的稳定代表；`freq` 是该分量覆盖的原始题目数

**摘要 prompt**（见 `llm/prompts.py:AGGREGATOR_SYSTEM`）：
- 4 章节模板：高频考点 Top10 / 重点考察方向 / 易忽略偏门题 / 备考建议
- 铁律：每条考点必须引用原题；不臆造；备考建议要具体到技术点

**输出可靠性**：Aggregator 使用 `response_format=json_object`，但不把 JSON mode 当作业务 schema。响应先经 `json.loads`，失败时尝试 `json-repair`，再由 `llm/aggregator_schema.py` 的 `AggregatorResult` 做 Pydantic 校验；题目引用还要能在当前输入 bucket 中找到。空输出、解析失败或校验失败时最多追加一次纠正提示，网络/API 异常由独立的指数退避处理。两次内容尝试都失败时不写入未经校验的摘要，批量任务跳过当前 bucket。

**缓存有效性**：`summaries.input_fingerprint` 保存有序输入题目、筛选参数、去重阈值、模型和指纹版本的 SHA-256。它不再用 `sample_count` 比较 `raw`/`clusters` 数量，因此去重后不会永远 miss，数量相同但内容变化也不会错误命中。`sample_count` 表示实际送入聚合的原始题目数；旧摘要没有指纹时会在下次运行自动重算。

## 4. 单桶 vs 全桶

```bash
# 单桶（开发调试用）
uv run il aggregate --company 字节跳动 --position 后端开发 --period 2025Q2 --no-write
# 不写库，只想看输出格式

# 全桶（每天一次的批处理）
uv run il aggregate
# 自动扫所有 (company × position) 组合，跳过 quality 太低的桶
```

## 5. SQL 验证

```sql
-- summaries 表内容
SELECT s.id, c.canonical, p.canonical, s.period, s.sample_count, s.input_fingerprint, length(s.content_md) AS chars
FROM summaries s
JOIN companies c ON c.id = s.company_id
JOIN positions p ON p.id = s.position_id
ORDER BY s.updated_at DESC LIMIT 20;

-- 看具体内容
SELECT content_md FROM summaries WHERE id = 1;

-- embedding 回填进度
SELECT
  COUNT(*) FILTER (WHERE embedding IS NOT NULL) AS embedded,
  COUNT(*) AS total
FROM questions;
```

## 6. 性能与成本

- bge-m3 batch 64：CPU 约 200 题/分钟；GPU 远快
- DeepSeek-V4：单桶 100 题输入约 3000-5000 tokens，输出 1500-2500 tokens
- 单桶成本：约 0.005-0.010 元
- 1 公司 5 岗位 4 季度 = 20 桶 ≈ 0.2 元
- 100 公司常见 5-10 岗位 4 季度 ≈ 5-10 元跑全表

## 7. 关键设计要点（面试讲故事）

- **Aggregator 不进 LangGraph**：它是定时批处理，不是单 URL 实时处理；分离让 graph 保持精简
- **embedding 回填独立命令**：questions 表写入时不阻塞回填，graph 跑完立刻可用，回填延后做
- **dedup 用 embedding 而非字符串相似度**：「Redis 分布式锁」和「Redis 实现分布式锁的方案」字符串差很多，但向量空间近，能正确合并
- **freq 进 prompt 喂给 LLM**：不让 LLM 从全量题目里“猜”哪些是高频，代码先统计真实频次，LLM 只负责措辞和分组
- **upsert summaries**：(c, p, period) 是 unique 索引，重跑覆盖，不堆历史
- **质量分门槛**：min_quality=30 过滤水帖噪声，避免摘要被"我感觉良好"这种空话污染
- **period 可选**：不传时聚合"全时间"，适合冷启动数据稀疏期

## 8. 验收清单

- [ ] `il backfill-embeddings` 完成后 SQL 查 questions 表 embedding 字段非空率 100%
- [ ] `il aggregate --company X --position Y --no-write` 终端打出 summary metadata
- [ ] `il aggregate` 全跑，summaries 表新增/更新行
- [ ] `il show-summary 字节跳动 后端开发` 看到 4 章节 markdown
- [ ] markdown 中"高频考点"每条都有原题引用（> 引用块）
- [ ] `pytest tests/test_aggregator_cluster.py -v` 聚类单测全部通过（含顺序无关、跨 block 连通分量）

## 9. 整个 LangGraph 闭环到这里完整

```
URL → Crawler → Cleaner → Extractor → Normalizer → Scorer → END
                                           ↓
                                      backfill-embed (异步)
                                           ↓
                                       Aggregator (定时)
                                           ↓
                                       summaries 表
                                           ↓
                                       il show-summary
```

## 10. 下一步（D9 预告）

D9：Celery 批量化 —— 把 graph 包成 Celery task，写一个"扫牛客列表页"的爬虫批量入队 100+ URL。
然后 D10-D14 是 FastAPI / Next.js 前端 / 真实数据 / README 简历化。
