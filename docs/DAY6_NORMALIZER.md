# Day 6 — Normalizer 节点（公司/岗位归一化）

> 目标：把 LLM 抽出来的"字节"、"Bytedance"、"抖音"统一映射到 `companies` 表里同一条 canonical 记录，自学习写回字典。

## 0. 这一步带来什么

| 之前 | 现在 |
|---|---|
| extract 出来的 companies 是原文字符串数组 | 自动归一为 canonical_id 列表 |
| 同一公司多个写法导致统计裂开 | 三级归一（字典→embedding→LLM）合并 |
| 字典只有 D1 灌入的 25 + 13 条 | LLM 判定的高置信度别名自动写回 → 字典越用越大 |
| post 没有 company/position 关联 | post_company_position 自动写入 |

## 1. 三级归一策略详解

```
alias 来 → tier 1: alias_dict 直查（O(1) Postgres index）
              ↓ miss
          tier 2: bge-m3 embedding 与所有 canonical 算余弦
              ├─ best ≥ 0.85 → 自动 match，写回字典
              └─ best < 0.85 → 进 tier 3
          tier 3: LLM Function Calling（带 top-5 候选）
              ├─ decision=match & confidence ≥ 0.7 → match，写回字典
              └─ 否则 → 新建 canonical + 同时写回 alias 字典
```

阈值定义在 `normalizer/resolver.py`：
- `EMBED_THRESHOLD_HIGH = 0.85`：自动放行的余弦阈
- `EMBED_THRESHOLD_LOW = 0.55`：低于此分的候选不发给 LLM（避免误导）
- `LLM_MIN_CONFIDENCE = 0.7`：LLM 给的 confidence 低于此值视为不可信

## 2. 第一次跑（首次会下载 bge-m3）

```bash
# bge-m3 ≈ 2.3 GB，第一次启会从 Hugging Face 拉
uv run il graph "https://www.nowcoder.com/discuss/<id>"
```

**怕模型下载慢/翻墙**：设置环境变量走镜像
```
HF_ENDPOINT=https://hf-mirror.com
```
或者临时跳过 normalize 节点：
```bash
uv run il graph <url> --skip-normalize
```

## 3. 单点测试归一化

```bash
# 应该走 tier 1 直查（D1 的种子里已经有「字节」→「字节跳动」）
uv run il normalize "字节"

# 走 tier 2 embedding（"Bytedance" 不在种子里，但与「字节跳动」相似度高）
uv run il normalize "ByteDance"

# 走 tier 3 LLM（生僻别名）
uv run il normalize "今日头条母公司"

# 测岗位
uv run il normalize "Java 服务端开发" --type position
```

输出包含 `source` 字段（alias_dict / embedding / llm / new），让你直观看走的哪一路。

## 4. 看字典

```bash
uv run il aliases --type company --limit 100
uv run il aliases --type position
```

第二次跑同一别名应当 source=alias_dict，证明自学习生效。

## 5. SQL 验证

```sql
-- post 现在有了公司/岗位关联
SELECT po.id, po.title, c.canonical AS company, p.canonical AS position
FROM posts po
JOIN post_company_position pcp ON pcp.post_id = po.id
JOIN companies c ON c.id = pcp.company_id
JOIN positions p ON p.id = pcp.position_id
ORDER BY po.id DESC
LIMIT 20;

-- 字典增长情况
SELECT entity_type, COUNT(*) FROM alias_dict GROUP BY entity_type;

-- 看 LLM 学到了哪些别名（confidence < 1.0 是 LLM 判定的）
SELECT entity_type, alias, canonical_id, confidence
FROM alias_dict
WHERE confidence < 1.0
ORDER BY learned_at DESC LIMIT 20;
```

## 6. 关键设计要点（面试讲故事）

- **三级渐进，成本逐层升**：字典 0.1ms / embedding 10ms / LLM 500ms。命中率高的别名永远走最便宜的路径
- **embedding 阈值双向**：上界 0.85 自动放行，下界 0.55 过滤太离谱的候选不送 LLM，省 token
- **自学习写回**：tier 2/3 命中的别名都写回 `alias_dict`，下次直接走 tier 1。字典越用越聪明
- **canonical_name 不臆造**：tier 4 新建时，如果 LLM 没给 canonical_name 就用原始 alias 作为新 canonical，避免随便起名污染数据
- **bge-m3 选型理由**：1024 维匹配 schema；中英混合最强；CPU 可跑（GPU 自动加速）；HuggingFace 直接下
- **新建 canonical 同时写 alias**：原始 alias 和 LLM 建议的新 canonical 名都进字典，避免下次同样的 alias 又走一次 LLM

## 7. 验收清单

- [ ] `il graph <url>` 输出 company_ids / position_ids 非空
- [ ] `il normalize "字节"` source=alias_dict
- [ ] `il normalize "ByteDance"` source=embedding（首次）
- [ ] 重复跑 `il normalize "ByteDance"` source=alias_dict（自学习生效）
- [ ] `psql ... \dt; SELECT COUNT(*) FROM post_company_position;` > 0
- [ ] `pytest tests/test_embedding.py -v` 全绿

## 8. 性能优化建议（可选）

- 首次加载 bge-m3 慢（约 30s）：`il graph` 第一次跑时模型加载占大头
- 启 batch normalize：未来 D9 Celery 批量时可一次 embed 所有 alias
- 加 embedding 缓存：alias → vector 也可以放 Redis，进一步省 CPU

## 9. 下一步（D7 预告）

D7：Scorer 节点（纯函数四维度打分：题量 / 答案 / 轮次 / 时间衰减）+ 把分数写进 posts.quality_score，
后续 Aggregator 可以按分数过滤垃圾帖。
