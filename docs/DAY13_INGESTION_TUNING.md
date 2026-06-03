# Day 13 — 真实数据填充 + Prompt 调优 + 性能调优

> 目标：把项目从"骨架完整"推到"有真数据、有调优记录、有度量"。这天产出的是**简历素材**：真实的 token 数、命中率、p50、错误率。

## 0. 这一天要解决的 4 个问题

1. 怎么从"5 条 demo 数据"扩到"500+ 条真面经"
2. 怎么发现 prompt 哪里效果差，怎么改
3. 怎么发现哪个节点是瓶颈，怎么调
4. 怎么从仪表里挑出**3-5 个数字写简历**

## 1. 跑批量抓取（一晚事）

```bash
# 0. 确保 .env 里 NOWCODER_COOKIE 是新鲜的，DEEPSEEK_API_KEY 有余额
uv run il info     # 看 cookie 字段是否 set

# 1. 启 worker（独立终端，让它一直跑）
uv run celery -A interviewlens.tasks.celery_app worker \
  --concurrency=4 --loglevel=INFO

# 2. 主终端：扫 30 页（每页 ~30 条 → ~900 条 URL）
uv run il batch --pages 30
# 输出 task_id，所有 URL 自动进 Celery 队列

# 3. 等。每隔半小时进一下：
uv run il metrics
docker exec il-postgres psql -U il -d interviewlens -c \
  "SELECT extract_status, COUNT(*) FROM posts GROUP BY extract_status;"

# 4. 第二天起来：
uv run il dlq list                # 看哪些 URL 卡住
uv run il backfill-embeddings     # 给所有新题目算 embedding
uv run il aggregate               # 全公司全岗位摘要
```

**预期产出**（按 cookie 健康度浮动）：
- 抓取成功率 70-90%（其余被牛客限流 / 登录引导 / 短文档跳过）
- LLM 抽取成功率 90-95%
- 写入 `posts.extract_status='done'` 的最终条数：~600

## 2. 看仪表找瓶颈

```bash
uv run il metrics
```

典型输出（跑了 600 条之后）：
```
LLM cache:        hits=120 misses=480 hit_rate=20.0%
Tokens & cost:    prompt=1.4M completion=480k total=1.88M  ¥3.36
Per-node latency:
  crawler        runs=600  avg=2400ms
  cleaner        runs=600  avg=80ms
  extractor      runs=600  avg=4800ms
  normalizer     runs=600  avg=1200ms
  scorer         runs=600  avg=15ms
```

**该读出来的信号**：
- `hit_rate=20%` → 多数题目 cleaned_text 不完全相同（每帖 unique），缓存收益主要靠 retry。**这是事实，不需要硬刷上去。**
- `extractor avg=4800ms` → 大头在 LLM 网络延迟，DeepSeek-V3 平均 4-6s/帖正常
- `normalizer avg=1200ms` → bge-m3 + LLM 兜底；如果你看到 normalizer 时间随 alias 字典增长不变，说明三级归一在 tier1/tier2 命中率高
- `crawler avg=2400ms` → Playwright + 网络 RTT，这个数字是好的

**写简历时挑这 3 行**：
- "百万级 token 处理，单条平均 0.005-0.008 元"
- "三级归一化让 normalizer P50 < 1.5s"
- "节点级 trace 让 90 分钟批量任务里的瓶颈一眼可见"

## 3. Prompt A/B（调优手段最值钱的一招）

**步骤**：
1. 复制现有 `EXTRACTOR_SYSTEM` 到新版本（v2），改一处你怀疑的措辞
2. `.env` 里 `EXTRACT_PROMPT_VERSION=2`
3. **不要重抓**，直接 `il extract <post_id> --no-cache` 单条试 5 个样本
4. 比较 `il show-post <id>` 看 questions 表内容差异
5. 满意了就 `il rescore --all`，token 仍然没花，因为缓存按 (text, version) 隔离

**值得试的 A/B**：
- 把 `不臆造内容` 改成 `如果原文是吐槽/抒情就跳过整段`：会减少 noise question
- 加 `只保留技术题，HR 题独立成轮`：让分类更准
- 在 user prompt 里加 `如果题目超过 200 字截断到关键句`：减少 cleaned_text 太长导致的 LLM 漏抽

**重要**：`EXTRACT_PROMPT_VERSION` 升级后**老 cache key 自动失效**（key 含 version），新版会重新调 LLM；想清掉旧 cache 释放内存：
```bash
docker exec il-redis redis-cli --scan --pattern 'il:llm:extract:v1:*' | \
  xargs docker exec il-redis redis-cli del
```

## 4. ScorerWeights 调优（0 token 成本）

打开 `src/interviewlens/scoring/scorer.py`，改 `ScorerWeights` 默认值：

| 想要的效果 | 改动 |
|---|---|
| 更看重答案完整度 | `answers_max=30, quantity_max=20` |
| 更看重轮次（多面有体系） | `rounds_per_round=10, rounds_max=30` |
| 历史帖也保留排面 | `recency_table=[(6,30),(12,20),(24,10),(36,5)]` |

改完跑：
```bash
uv run il rescore --all
uv run il top-posts --limit 30
```

观察哪些帖子排上去/掉下来，**用感觉判断**（这种主观打分没标准答案，凭哪个排序看着最有用）。

## 5. Normalizer 调优

跑了 600 条之后看字典：
```bash
uv run il aliases --type company --limit 200
```

**典型问题**：
- "字节AI Lab" 没并入 "字节跳动" → 加进 `data/seed_aliases.yaml` 的字节别名后 `il seed-aliases` 重灌
- "推荐算法 - 字节" 这种带后缀的进了 LLM 走 tier3 → 看是不是要加 tier2 文本预清理

**embed 阈值调优**（在 `normalizer/resolver.py`）：
- 如果发现"美团" 和 "美团点评" 没合并 → 把 `EMBED_THRESHOLD_HIGH` 从 0.85 降到 0.82
- 如果发现"阿里" 和 "蚂蚁" 被错误合并（向量空间挺近）→ 升到 0.90

## 6. 一组录简历可用的指标

跑完 600 条后建议列下这些数字写简历/项目说明：

```bash
# 总数据量
docker exec il-postgres psql -U il -d interviewlens -c "
SELECT
  (SELECT COUNT(*) FROM posts WHERE extract_status='done') AS posts,
  (SELECT COUNT(*) FROM questions) AS questions,
  (SELECT COUNT(*) FROM questions WHERE embedding IS NOT NULL) AS embedded,
  (SELECT COUNT(*) FROM companies) AS companies,
  (SELECT COUNT(*) FROM positions) AS positions,
  (SELECT COUNT(*) FROM summaries) AS summaries;"

# 性能
uv run il bench-search

# 成本
uv run il metrics

# 分数分布
docker exec il-postgres psql -U il -d interviewlens -c "
SELECT
  CASE WHEN quality_score>=80 THEN '80-100'
       WHEN quality_score>=60 THEN '60-79'
       WHEN quality_score>=40 THEN '40-59'
       ELSE '<40' END AS bucket,
  COUNT(*) FROM posts WHERE quality_score IS NOT NULL GROUP BY bucket;"
```

把这些贴进 README 的"实测数据"段。

## 7. 错误兜底（跑不动时按这个 checklist 排）

| 现象 | 排查 |
|---|---|
| `il batch` 入队成功但 worker 不动 | `docker compose ps`；worker 没起就 `uv run celery ... worker` |
| 大量 `extract_status='skipped'` | cookie 失效，重抓 cookie；或牛客返回登录引导页 |
| 大量 `extract_status='failed'` | LLM key 余额不足 or 限流；看 `posts.extract_error` |
| Playwright 报 `Timeout 30000ms` | 牛客慢；调 `NowcoderFetcher(timeout_ms=60000)` |
| Celery worker 卡住 5 分钟自动 kill | 已经设了 `task_time_limit=300`；让它 kill 没问题 |
| DLQ 越来越大 | `il dlq list` 看错误共性；改完 `il dlq drain` 重入 |
| 同样 URL 抓多次 | 正常，`upsert_raw_post` 已幂等；想强制重抓加 `--no-reuse` |

## 8. 验收清单（跑完一晚后）

- [ ] `posts` 表 `extract_status='done'` ≥ 200 条
- [ ] `questions` 表 ≥ 1500 条且 100% 有 embedding
- [ ] `summaries` 表 ≥ 10 条 (≥ 3 公司 × ≥ 3 岗位)
- [ ] `il metrics` 显示总成本 < ¥10
- [ ] `il bench-search` 显示 p50 < 50ms
- [ ] DLQ 长度 < 总抓取数的 5%
- [ ] `il top-posts --limit 5` 第一条质量分 > 80

## 9. 下一步（D14 预告）

D14 是把现在的"代码 + 数据"包装成"简历可用项目"：
- README 顶部加 GIF demo + 实测数字
- 一份 1-page 项目自介绍（PDF/Markdown）
- 部署到 Vercel + 一台便宜 VPS（可选）
- Tag v0.1.0 + 写 CHANGELOG
