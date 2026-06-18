# AI 解答功能设计

日期：2026-06-18
状态：已批准设计，待写实现计划

## 背景与目标

绝大多数面经只有问题、没有答案。本功能为 `questions` 表的题目离线预生成 AI 解答，
按题目难度自适应长度（简单题 2-3 句、复杂题展开），以 Markdown 存储，前端默认折叠、
点击展开，并提供「展开所有答案」批量按钮。

## 关键决策

| 维度 | 选择 | 理由 |
|---|---|---|
| 生成时机 | **离线预生成 + 存库** | 用户体验优先，读库即时展示；复用 aggregator 的离线模式 |
| 难度自适应 | **prompt 内让 AI 自判断** | 一次调用搞定，不做难度预分类两步法 |
| 调用粒度 | **每题独立调用 DeepSeek** | 批量总结会导致单题回答过浅——这正是要解决的问题 |
| 输出格式 | **Markdown** | 与摘要走同一套 react-markdown 渲染，支持代码块/列表 |
| 生成范围 | **仅高质量帖的题**（所属帖 quality_score >= 30） | 跳过低质题省 token |
| 展示位置 | **摘要页题目清单 + 搜索结果卡片** | 两处都用同一 `Question` 数据结构 |

## 数据存储

`questions` 表新增两列（仿照 posts.extract_version 的版本门控模式）：

```sql
-- sql/002_answer_ai.sql
ALTER TABLE questions ADD COLUMN IF NOT EXISTS answer_ai TEXT;
ALTER TABLE questions ADD COLUMN IF NOT EXISTS answer_ai_version INT NOT NULL DEFAULT 0;
```

- `answer_ai`：AI 生成的 Markdown 答案，NULL 表示尚未生成
- `answer_ai_version`：生成时写入的 prompt 版本号；改 prompt 时 bump 配置值即可让旧答案被重算
- 不动现有 `answer_brief`（原帖答案要点），两者独立并存

同步更新 `src/interviewlens/db/models.py` 的 `Question` 类加这两个字段。

## 配置

`config.py` 新增：
- `answer_prompt_version: int = 1` — 改 answerer prompt 时 bump，门控重算

复用现有 `deepseek_model_chat`。

## 生成逻辑（离线）

新模块 `src/interviewlens/answerer/answerer.py`，结构仿照 `aggregator/aggregator.py`：

### 选题查询
- 所属帖 `extract_status = 'done'` 且 `quality_score >= min_quality`(默认 30)
- 且 `answer_ai IS NULL OR answer_ai_version < :current_version`
- 可选 `--company/--position` 过滤（JOIN post_company_position）
- 可选 `--limit N` 限制本次条数
- `--regenerate` 时忽略 NULL/version 条件，强制全部重算

### 生成
- 每题独立调 `client.chat.completions.create`，`temperature=0.3`，`max_tokens=1500`
- 复用 `llm/cache.py`：`make_cache_key(namespace="answer", payload={"content": q.content}, version=answer_prompt_version)`，相同题目跨帖命中缓存不重复调用
- 命中缓存仍写库（缓存只省 LLM 调用，不省 DB 写入）
- 并发 `asyncio.Semaphore(5)`，与 aggregator 一致
- token 用量经 `incr_tokens` 计入 observability
- 单题失败只记 log 跳过，不中断整批（仿 aggregate_all 的 _one 容错）

### 返回
`AnswerOutcome` dataclass：generated / cache_hit / skipped / failed 计数。

## Prompt

`llm/prompts.py` 新增 `ANSWERER_SYSTEM` + `build_answerer_messages(content, category)`：

铁律：
1. **难度自适应**：简单概念题 2-3 句直接讲透，不堆字；复杂题分点展开，可用代码块/对比表，但不灌水
2. 输出纯 Markdown（标题、列表、代码块、**强调**），与摘要排版统一
3. 超纲或题目本身信息不足无法作答时直说，不编造
4. 面向面试备考，讲清原理与考点，不要泛泛而谈

## API

### Schema
`QuestionOut`（schemas.py）新增 `answer_ai: str | None = None`。
`web/src/lib/api.ts` 的 `Question` type 同步加 `answer_ai: string | null`。

### 路由
两处 SQL 各加 `q.answer_ai` 到 SELECT，无需新增端点：
- `routes_summary.py` 的 `list_raw_questions`
- `routes_search.py` 的 `search`

（search 用 `QuestionOut(**dict(r))` 自动映射，加列即可；summary 显式构造，需补字段。）

## CLI

`cli.py` 新增 `answer` 命令：

```
uv run il answer [--company X] [--position Y] [--limit N] [--regenerate] [--min-quality 30]
```

调用 `answerer.run_answers(...)`，打印 outcome 统计。

## 前端

### 共用组件
新建 `web/src/components/answer-block.tsx`：
- 折叠组件，默认收起，点击展开
- `expandAll` prop 受控：父组件传 true/false 覆盖本地状态
- 展开后用 `react-markdown` + `remark-gfm` 渲染 `answer_ai`
- `answer_ai` 为 null 时不渲染任何入口

### 接入点
1. **`summary-view.tsx` 的 `RawQuestionList`**：
   - 每条 `<li>` 在 `answer_brief` 下方加 `<AnswerBlock>`
   - 列表顶部加「展开所有答案」按钮，控制一个 `expandAll` state 传给所有子项

2. **`question-card.tsx` 的 `QuestionCard`**：
   - 在「原帖答案要点」details 旁加 `<AnswerBlock>`
   - 搜索结果页（`search/page.tsx`）列表顶部加「展开所有答案」按钮

UI 风格沿用现有：font-mono 小标签、折叠箭头用 lucide ChevronDown/Right、Markdown 复用 `.prose-il` 样式。

## 测试

- `tests/test_answerer.py`：选题查询过滤逻辑（mock session）、缓存键稳定性、单题失败不中断整批
- 复用现有 pytest-asyncio 模式

## 不做（YAGNI）

- 按需实时生成（已选离线）
- 难度预分类两步法（prompt 内判断）
- Redis 之外额外缓存层
- Celery 异步队列（直接 CLI 同步跑，量不大）
