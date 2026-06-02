# Day 3 — Extractor (DeepSeek Function Calling)

> 目标：把 D2 抓回来的 `cleaned_text` 喂给 DeepSeek，吐结构化 JSON 写进 `questions` 表。

## 0. 前置

- D1 / D2 跑通：`posts` 表里至少有一条 `extract_status='pending'` 且 `cleaned_text` 不为空的记录
- `.env` 里 `DEEPSEEK_API_KEY` 已填真实 key（去 `platform.deepseek.com` 拿）
- Langfuse key 可以暂时不填（启动会自动跳过 trace），但建议填了，能在 Web UI 看 prompt + token + 耗时

## 1. 单条抽取

```bash
# 用 D2 抓回来的 post_id（默认走 Redis 缓存）
uv run il extract 1

# 不走缓存（调试 prompt 时用）
uv run il extract 1 --no-cache
```

输出三段：
1. **元数据表**：companies / positions / level / interview_date / rounds 数 / questions 插入数 / cache_hit / token 消耗 / model
2. **每轮一个 Panel**：列出该轮所有题目，按 `[分类] 题目` 格式

## 2. 端到端管线（D2 + D3 一气呵成）

```bash
uv run il run-pipeline "https://www.nowcoder.com/discuss/<id>"
uv run il run-pipeline "https://www.nowcoder.com/discuss/<id>" --no-headless
```

抓 → 清 → 抽 → 入库一步到位，最后绿色 panel 给你总结。

## 3. SQL 验证

```sql
-- 看 post 状态
SELECT id, title, extract_status, extract_version FROM posts;

-- 看抽出的题目
SELECT round_no, round_type, category, left(content, 80)
FROM questions
WHERE post_id = 1
ORDER BY round_no, id;
```

## 4. 缓存机制

- Redis key：`il:llm:extract:v{prompt_version}:{sha256(cleaned_text)}`
- TTL：30 天
- 升级 prompt → 改 `EXTRACT_PROMPT_VERSION` → 同一文本会重新调 LLM，**旧缓存自动失效**
- 强制刷新某次：`il extract <id> --no-cache`，会跳过读缓存但仍会写新缓存

## 5. Langfuse 接入

- `.env` 里填 `LANGFUSE_PUBLIC_KEY` + `LANGFUSE_SECRET_KEY`（去 http://localhost:3001 创建项目拿）
- 每次抽取自动产生一条 trace，包含：
  - 输入 messages（system + user）
  - LLM 完整响应
  - usage（prompt/completion/total tokens）
  - 重试次数（attempt 元数据）
  - prompt 版本号

未配置 Langfuse 时不影响运行，trace 静默跳过。

## 6. 典型问题与处理

| 现象 | 原因 / 处理 |
|---|---|
| `RuntimeError: LLM returned no tool call` | 极少见，DeepSeek 没按 `tool_choice=required` 走；自动重试 1 次温度降到 0 |
| `RuntimeError: Invalid JSON in tool args` | tools schema 改坏了；检查 `EXTRACT_FUNCTION_SCHEMA` 里 enum 是否包含 None |
| `pydantic ValidationError: round_no` | LLM 编出来轮次 > 20；检查 cleaned_text 是不是把多篇拼一起了 |
| `OPENAI authentication failed` | `DEEPSEEK_API_KEY` 写错或欠费 |
| 第二次抽 token 数变 0 | cache_hit=true，正常，省钱 |
| extract_status 一直 pending | LLM 失败了，看 `posts.extract_error` 字段 |

## 7. 成本估算（DeepSeek-V3）

- 单条面经 cleaned_text 平均 1500 tokens 输入
- 输出 JSON 约 600 tokens
- 单条调用成本：约 0.001-0.002 元
- 1000 条全跑下来 < 5 元
- 命中缓存 → 0 元

## 8. 验收清单

- [ ] `il extract <post_id>` 输出元数据表 + 每轮题目预览
- [ ] `il run-pipeline <url>` 跑完返回绿色 panel
- [ ] SQL 看到 questions 表新增数据
- [ ] 重跑 `il extract` 同一 id 显示 cache_hit=yes
- [ ] `pytest tests/test_schema.py tests/test_cache_key.py -v` 全绿
- [ ] Langfuse Web UI 看到 trace（如已配置）

## 9. 下一步（D4 预告）

D4 把 Crawler / Cleaner / Extractor 三个节点用 LangGraph StateGraph 编排起来，
失败可断点续跑，节点级追踪进 Langfuse。
