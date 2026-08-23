# InterviewLens

InterviewLens 是一个面向个人秋招准备的面经知识库：把牛客等来源的非结构化面经抓取下来，抽取为公司、岗位、面试轮次和问题，统一实体名称，建立可检索的数据层，再生成公司 × 岗位 × 时间段的面试重点摘要。

它不是一个通用爬虫或聊天机器人，而是一条“采集 → 结构化 → 归一 → 检索 → 聚合”的数据管线。

## 能做什么

| 能力 | 当前实现 |
|---|---|
| 单篇面经处理 | Playwright 抓取、正文清洗、LLM 结构化抽取 |
| 实体归一 | alias 字典 → embedding 相似度 → LLM 兜底，并将结果写回字典 |
| 内容评分 | `content_score` 衡量题量、答案完整度和面试轮次，范围 0～70 |
| 动态推荐 | 根据原始发布时间 `posted_at` 计算 freshness，推荐场景使用 `ranking_score` |
| 语义搜索 | 题目级 embedding + PostgreSQL pgvector/HNSW |
| 面经聚合 | 按公司、岗位、季度或全部数据聚类去重，统计真实出现频次，再由 LLM 生成 Markdown 摘要 |
| 摘要可靠性 | JSON mode + `json-repair` + `AggregatorResult` Pydantic 校验，题目引用回查输入，失败有限重试且不落坏数据 |
| 批量处理 | Celery Worker、失败恢复、重试和 DLQ |
| 可观测性 | Langfuse trace、Redis 缓存、Token 用量和节点耗时统计 |
| 使用入口 | CLI、FastAPI REST API、Next.js Web 界面 |

## 核心流程

```text
牛客面经 URL
    │
    ▼
Crawler       Playwright 抓取原文
    │
    ▼
Cleaner       去噪、提取正文、短文本过滤
    │
    ▼
Extractor     DeepSeek Function Calling → 公司/岗位/轮次/问题
    │
    ▼
Normalizer    company_aliases / position_aliases → pgvector → LLM 兜底
    │
    ▼
Scorer        计算稳定 content_score 并写入数据库
    │
    ├──────────────► pgvector 语义搜索
    │
    └──────────────► Aggregator 聚类去重 → LLM 摘要 → summaries
```

LangGraph 中是五个节点：`crawl → clean → extract → normalize → score`。Aggregator 和 Answerer 是图外的离线任务，不属于 LangGraph 主链。

## 评分模型

项目没有把“内容质量”和“时间新鲜度”永久混成一个数据库字段：

```text
content_score = quantity(30) + answers(20) + rounds(20)       # 稳定，持久化
freshness_score = f(posted_at, as_of)                         # 动态，查询时计算
ranking_score = content_score + freshness_score                # 只用于推荐排序
```

- `content_score` 用于 Aggregator 和 Answerer 的内容完整度门槛。
- 时间线按照 `posted_at` 排序。
- 推荐列表才使用 `content_score + freshness_score`。
- `fetched_at` 只表示系统抓取时间，不能替代原始发布时间 `posted_at`。
- `quality_score` 仍保留为迁移兼容字段，新逻辑不再依赖它。

## 技术栈

- Python 3.13、uv、Typer
- LangGraph、DeepSeek API、Pydantic、tenacity
- Playwright、trafilatura
- PostgreSQL 16、pgvector、pg_trgm
- Redis、Celery
- FastAPI、Next.js 15、TypeScript、Tailwind
- Langfuse

## 快速启动：Docker 全栈

### 1. 准备配置

```bash
cp .env.example .env
```

至少填写：

- `DEEPSEEK_API_KEY`
- `NOWCODER_COOKIE`（需要抓取受限页面时）
- Langfuse 的密钥（如果需要追踪）

`.env` 不应提交到 Git。

### 2. 启动服务

```bash
docker compose up -d --build
```

首次启动会创建 PostgreSQL、Redis、Langfuse、API、Celery Worker 和 Web 服务，并下载 Python/embedding 依赖，可能需要较长时间。

### 3. 初始化和检查

```bash
docker compose exec api uv run il doctor
docker compose exec api uv run il seed-aliases
docker compose exec api uv run il backfill-canonical-embeddings
docker compose exec api uv run il backfill-embeddings  # 007 后刷新题目向量元数据
```

如果只想立即查看界面，可以导入演示数据：

```bash
docker compose exec api uv run il seed-demo
```

访问地址：

- Web：<http://localhost:3013>
- API 文档：<http://localhost:8000/docs>
- Langfuse：<http://localhost:3001>

### 已有数据库的迁移

`sql/001_init.sql` 只会在 PostgreSQL 数据卷首次创建时自动执行。已有数据库需要按顺序执行尚未执行的迁移（下面两种导入方式二选一）：

```bash
# macOS / Linux
docker compose exec -T postgres psql -U il -d interviewlens < sql/003_content_score.sql
docker compose exec -T postgres psql -U il -d interviewlens < sql/004_split_aliases_canonical_embeddings.sql
docker compose exec -T postgres psql -U il -d interviewlens < sql/005_summary_input_fingerprint.sql
docker compose exec -T postgres psql -U il -d interviewlens < sql/006_drop_unused_position_level.sql
docker compose exec -T postgres psql -U il -d interviewlens < sql/007_database_integrity.sql
# PowerShell
Get-Content sql/003_content_score.sql | docker compose exec -T postgres psql -U il -d interviewlens
Get-Content sql/004_split_aliases_canonical_embeddings.sql | docker compose exec -T postgres psql -U il -d interviewlens
Get-Content sql/005_summary_input_fingerprint.sql | docker compose exec -T postgres psql -U il -d interviewlens
Get-Content sql/006_drop_unused_position_level.sql | docker compose exec -T postgres psql -U il -d interviewlens
Get-Content sql/007_database_integrity.sql | docker compose exec -T postgres psql -U il -d interviewlens
docker compose exec api uv run il rescore --all
docker compose exec api uv run il seed-aliases
docker compose exec api uv run il backfill-canonical-embeddings
docker compose exec api uv run il backfill-embeddings
```

迁移不会直接复制旧的 `quality_score`，因为旧分数可能已经包含时间衰减，无法无损还原为内容分。
`004` 会把旧 `alias_dict` 按实体类型迁移到 `company_aliases` 和 `position_aliases`，同时为 `companies` / `positions` 增加向量列和 HNSW 索引；迁移前会检查孤儿 canonical 引用，发现异常时整笔事务回滚。
`005` 为 `summaries` 增加 Aggregator 输入指纹列；已有摘要指纹为空，会在下一次聚合时自动重算并补齐。
`006` 删除 `positions.level` 预留字段。招聘层级目前只存在于单篇面经的抽取结果（`ExtractedPost.level`）中，尚未持久化；它不属于规范岗位实体，原字段没有业务读写。
`007` 增加 `interview_date`、embedding 模型/版本元数据、关系复合索引和数据完整性约束；迁移中的约束先以 `NOT VALID` 保护新写入，清理旧数据后再执行 `VALIDATE CONSTRAINT`。
执行 `007` 后应重新运行两类 embedding 回填；查询只接受当前 `embedding_model + embedding_version`，避免混用不同模型生成的向量。

## 常用工作流

### 处理单篇面经

```bash
# 全链路：抓取 → 清洗 → 抽取 → 归一 → 内容评分
docker compose exec api uv run il graph "https://www.nowcoder.com/discuss/<id>"

# 查看帖子和处理结果
docker compose exec api uv run il show-post <post_id>
```

需要分步调试时，可以分别使用：

```bash
docker compose exec api uv run il crawl "<url>"
docker compose exec api uv run il extract <post_id>
docker compose exec api uv run il normalize "字节" --type company
```

### 批量采集和恢复

```bash
# 从列表页抓取，并把帖子写入数据库
docker compose exec api uv run il tab-crawl --pages 2 --save-db

# 让 LangGraph 处理刚写入的 pending 帖子
docker compose exec api uv run il resume

# 查看或处理死信队列
docker compose exec api uv run il dlq list
docker compose exec api uv run il dlq drain --limit 50
```

如果需要 Celery 后台处理单个 URL，可以调用 `POST /admin/ingest`；批量任务和 DLQ 由 Worker 执行。

### 向量搜索和聚合摘要

```bash
# 给题目生成 embedding
docker compose exec api uv run il backfill-embeddings

# 给公司/岗位 canonical 名称生成 embedding，供归一化的 pgvector Top-K 查询使用
docker compose exec api uv run il backfill-canonical-embeddings

# 聚合一个公司/岗位/季度
docker compose exec api uv run il aggregate \
  --company 字节跳动 --position 后端开发 --period 2025Q2

# 聚合全部有数据的公司/岗位组合
docker compose exec api uv run il aggregate

# 查看摘要
docker compose exec api uv run il show-summary 字节跳动 后端开发 --period 2025Q2
```

### 内容分与推荐

```bash
# 从 questions 表重算稳定内容分，不调用 LLM
docker compose exec api uv run il rescore --all

# 推荐列表：content_score + 动态 freshness
docker compose exec api uv run il top-posts --limit 20

# Aggregator/Answerer 的内容分门槛，两个参数名都兼容
docker compose exec api uv run il aggregate --min-content-score 30
docker compose exec api uv run il answer --min-content-score 30
```

日常增量更新也可以直接使用：

```bash
docker compose exec api uv run il daily-update
```

## REST API

主要接口如下，完整定义可直接查看 `/docs`：

| 接口 | 用途 |
|---|---|
| `GET /companies` | 公司列表 |
| `GET /companies/{id}/positions` | 公司下的岗位统计 |
| `GET /positions` | 岗位列表 |
| `GET /posts` | 按发布时间排序的面经 Feed |
| `GET /posts/{id}` | 面经详情及评分信息 |
| `GET /posts/search?q=...` | 题目级语义搜索 |
| `GET /summaries` | 已生成摘要列表 |
| `GET /summaries/{company}/{position}` | 查看公司/岗位摘要 |
| `GET /summaries/{company}/{position}/questions` | 查看原始问题 |
| `GET /admin/health` | PostgreSQL、Redis、pgvector 健康检查 |
| `GET /admin/jobs` | Celery 队列、Worker 和 DLQ 状态 |
| `GET /admin/metrics` | 缓存、Token、节点耗时统计 |
| `POST /admin/ingest` | 将单个 URL 放入 Celery 队列 |

## 数据模型

核心表：

- `posts`：原始面经、发布时间、抓取时间、抽取状态和稳定内容分。
- `questions`：面试问题、答案要点、AI 答案和题目 embedding。
- `companies` / `positions`：规范化公司和岗位，以及 canonical embedding。
- `post_company_position`：面经与公司/岗位的关联。
- `company_aliases` / `position_aliases`：带真实外键的实体别名复用映射。
- `summaries`：Aggregator 生成的预计算摘要。

向量和关系数据都放在 PostgreSQL 中，搜索时可以同时做实体过滤和向量相似度查询，避免额外维护一套向量数据库。

## 目录结构

```text
src/interviewlens/
├── agent/          # LangGraph 状态和五个节点
├── crawler/        # 单篇、列表和增量抓取
├── normalizer/     # entity alias/pgvector/LLM 实体归一
├── scoring/        # content_score、freshness 和 ranking 计算
├── aggregator/     # embedding 聚类去重和 LLM 摘要
├── answerer/       # 离线生成题目 AI 答案
├── api/            # FastAPI 路由和响应模型
├── db/             # SQLModel 模型、Session 和 Repository
└── tasks/          # Celery 任务和每日更新流程

sql/
├── 001_init.sql             # 初始 schema
├── 002_answer_ai.sql        # AI 答案字段
├── 003_content_score.sql    # 内容分迁移
├── 004_split_aliases_canonical_embeddings.sql  # 别名拆表与 canonical 向量迁移
├── 005_summary_input_fingerprint.sql           # Aggregator 输入指纹
├── 006_drop_unused_position_level.sql          # 删除未使用的岗位 level 字段
└── 007_database_integrity.sql                  # 约束、复合索引和字段元数据

web/                         # Next.js 前端
tests/                       # 单元测试和行为测试
docs/                        # 架构、命令和各模块设计文档
```

## 本地开发

安装 Python 依赖后：

```bash
uv sync
uv run playwright install chromium
uv run pytest
uv run ruff check src tests
```

开发环境可以使用热重载配置：

```bash
docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d
```

常用命令和排障步骤见 [docs/COMMANDS.md](docs/COMMANDS.md)。

## 文档导航

- [架构与数据模型](docs/ARCHITECTURE.md)
- [命令参考](docs/COMMANDS.md)
- [Crawler 演进](docs/CRAWLER_EVOLUTION.md)
- [LLM 抽取可靠性](docs/LLM_EXTRACTION_RELIABILITY.md)
- [实体归一](docs/DAY6_NORMALIZER.md)
- [评分与动态时效](docs/DAY7_SCORER.md)
- [Aggregator 摘要](docs/DAY8_AGGREGATOR.md)
- [FastAPI 接口](docs/DAY10_API.md)
- [前端说明](docs/DAY11_FRONTEND.md)
- [Prompt 库](docs/PROMPT_LIBRARY.md)

## 当前边界

- 这是个人/小规模使用的工具，没有登录鉴权和多租户设计。
- 抓取依赖目标站点页面结构、访问权限和 Cookie，站点改版可能导致解析失败。
- LLM 抽取、摘要和本地 embedding 都有时间、算力或 API 成本。
- 当前仓库没有真实大规模压测数据，不对百万级数据量或固定 P95 延迟作承诺。
- 抓取内容仅用于个人学习和检索，必须遵守目标网站服务条款与适用法律，不要把原始面经再次公开发布。

## License

MIT
