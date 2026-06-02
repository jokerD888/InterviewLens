# Day 7 — Scorer 节点（四维度质量打分）

> 目标：给每个 post 打一个 0-100 的质量分，垃圾帖一眼识别，未来 Aggregator 可以按分数过滤。

## 0. 这一步带来什么

| 之前 | 现在 |
|---|---|
| posts 表 quality_score 永远是 NULL | Scorer 节点写入 0-100 分数 |
| 不知道哪些是水帖 | `il top-posts` 一眼看高分帖 |
| 改打分规则要重跑全流程 | `il rescore --all` 不调 LLM 直接重打 |

## 1. 评分公式（4 个独立桶 + 总分上限 100）

| 维度 | 权重 | 计算 | 饱和点 |
|---|---|---|---|
| **题量** | 30 | 题目数 × 3 | 10 题（30）|
| **答案** | 20 | 含 answer_brief 的题数 × 4 | 5 题（20） |
| **轮次** | 20 | 轮次数 × 7 | 3 轮（21→cap 20） |
| **新鲜度** | 30 | ≤3月→30 / ≤6月→25 / ≤12月→15 / ≤24月→8 / >24月→0 | 3 个月内满分 |

权重在 `scoring/scorer.py` 里 `ScorerWeights` dataclass，未来想 A/B 改一行就行。
posted_at 缺失时新鲜度为 0（**故意惩罚**，不让没日期的旧帖排过有日期的新帖）。

## 2. 跑一次看分数

```bash
uv run il graph "https://www.nowcoder.com/discuss/<id>"
```

graph result 表新增两行：
```
quality_score    : 78
score_breakdown  : q=30 a=12 r=14 t=22
```

## 3. 不调 LLM 重打分

改了 `ScorerWeights` 默认值后，**不需要**重抓 / 重抽 LLM，直接：
```bash
uv run il rescore 5            # 重打单条
uv run il rescore --all        # 全表重打
```

`rescore` 从 `questions` 表反向拼出 extracted 结构，然后跑 score_extracted。0 token 消耗。

## 4. 看排行榜

```bash
# 全局 top 20
uv run il top-posts

# 指定公司岗位
uv run il top-posts --company 字节跳动 --position 后端开发 --limit 50

# 单看某岗位
uv run il top-posts --position 算法工程师
```

## 5. SQL 验证

```sql
-- 分数分布直方图
SELECT
  CASE
    WHEN quality_score >= 80 THEN '80-100 hardcore'
    WHEN quality_score >= 60 THEN '60-79 solid'
    WHEN quality_score >= 40 THEN '40-59 average'
    WHEN quality_score >= 20 THEN '20-39 thin'
    ELSE '0-19 noise'
  END AS bucket,
  COUNT(*) AS cnt
FROM posts
WHERE quality_score IS NOT NULL
GROUP BY bucket
ORDER BY MIN(quality_score) DESC;

-- 找潜在水帖看眼真实内容
SELECT id, quality_score, title, source_url
FROM posts
WHERE quality_score < 20 AND extract_status = 'done'
ORDER BY quality_score
LIMIT 10;
```

## 6. 设计要点（面试讲故事）

- **四维度独立桶**：每个维度独立饱和，避免某一维度刷爆压过其他维度
- **题量饱和点 10**：与其奖励"我罗列了 50 道题"，不如鼓励"我至少写了 10 道"，超过价值递减
- **答案权重比题量小**：因为大部分牛客面经不写答案，刚性要求会让 80% 的帖子被冤枉
- **新鲜度独立打分而不是衰减系数**：分桶给值（30/25/15/8/0）比指数衰减更可解释，调阈值方便
- **无日期惩罚 0 而不是平均**：让未知发布时间的旧帖天然下沉
- **rescore 不调 LLM**：questions 表存了完整结构化数据，反推 extracted 就够，**调权重 0 成本**
- **ScorerWeights dataclass + 默认值**：未来加 A/B 实验、按公司不同权重，改 instance 就行

## 7. 验收清单

- [ ] `il graph <url>` 输出 quality_score 和 score_breakdown
- [ ] 两条对比帖，水帖（1 轮 2 题无答案）应 < 20，硬核帖（4 轮 12 题带答案）应 = 100
- [ ] `il rescore <id>` 与 graph 输出分数一致
- [ ] `il top-posts --limit 5` 列出最高分前 5
- [ ] 改 `ScorerWeights` 后 `il rescore --all` 全表更新
- [ ] `pytest tests/test_scorer.py -v` 全 6 个测试绿

## 8. 下一步（D8 预告）

D8：Aggregator —— 按公司×岗位×季度分桶，跑 pgvector RAG 取 top-100 题目，
DeepSeek 总结成 markdown，写入 summaries 表。这之后整个 LangGraph 流程就完整了。
