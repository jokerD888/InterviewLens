# InterviewLens 架构设计文档

> 自用面经聚合工具：抓取牛客大厂面经 → LLM 结构化抽取 → 公司/岗位归一 → 质量打分 → RAG 摘要。

## 0. 项目定位与边界

| 维度 | 决策 |
|---|---|
| 用户 | 仅自用 / 小圈子（≤5 人），不对公开互联网开放 |
| 数据 | 爬取牛客面经，自负风险；**严禁二次发布到任何公开站点** |
| 体量 | 单机部署，预期 10w-100w 条面经，全程跑得动 pgvector |
| 模型 | 调 DeepSeek API，不自部署；本地仅跑 embedding（bge-m3） |
| 目标 | 既是工具，也是简历项目；侧重 Agent 编排与可观测性 |

## 1. 系统架构总览

### 1.1 分层架构

```
┌─────────────────────────────────────────────────────────────┐
│  Frontend (Next.js 15 + shadcn/ui + Tailwind)               │
│  公司列表 │ 岗位筛选 │ 摘要面板 │ 语义搜索框                  │
└──────────────────────────┬──────────────────────────────────┘
                           │ REST/JSON
┌──────────────────────────▼──────────────────────────────────┐
│  API Layer (FastAPI + SQLModel + async)                     │
│  /companies  /positions  /posts/search  /summaries          │
└──────────────────────────┬──────────────────────────────────┘
                           │ 同进程调用
┌──────────────────────────▼──────────────────────────────────┐
│  Service Layer                                              │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────────┐   │
│  │ AgentService │  │SearchService │  │SummaryService    │   │
│  │(LangGraph)   │  │(pgvector RAG)│  │(分桶+缓存)        │   │
│  └──────┬───────┘  └──────┬───────┘  └────────┬─────────┘   │
└─────────┼─────────────────┼───────────────────┼─────────────┘
          │ Celery task     │ asyncpg            │
┌─────────▼─────────────────▼───────────────────▼─────────────┐
│  Infrastructure                                             │
│  Celery │ PostgreSQL16+pgvector │ Redis │ Langfuse │ DeepSeek│
└─────────────────────────────────────────────────────────────┘
```

### 1.2 关键技术选型（与决策理由）

| 组件 | 选型 | 备选 | 选择理由 |
|---|---|---|---|
| 语言 | Python 3.13 | Go | LangGraph/Playwright 生态成熟，单机够用 |
| 包管理 | `uv` | poetry / pip | 2025 年事实标准，速度碾压 |
| 浏览器自动化 | Playwright | Selenium / rod | 异步 API 友好，反检测一般够用 |
| LLM | DeepSeek-V4 | Qwen2.5 / GPT-4o | 中文+长上下文+成本（百万 token < 10 元） |
| Embedding | bge-m3 | text2vec / GTE | 中英混合最强，1024 维，CPU 可跑 |
| 编排 | LangGraph | LangChain / LlamaIndex | 状态机式，断点续跑，面试讲故事好讲 |
| 向量库 | pgvector | Qdrant / Milvus | 与关系数据同库 join，省运维 |
| 任务队列 | Celery | RQ / arq / Dramatiq | 生态最成熟，监控完善 |
| 可观测 | Langfuse | LangSmith / Phoenix | 自部署免费，trace LLM 链路 |
| 前端 | Next.js 15 (App Router) | Vite + React | SSR + 路由零配置，shadcn 直接接 |

## 2. 数据模型（PostgreSQL Schema）

### 2.1 ER 关系

主要实体包括 `companies`、`positions`、`posts`、`questions`、`post_company_position`（关联表）、`summaries`、`company_aliases` 和 `position_aliases`。

```
companies ──┐                             ┌── positions
            │                             │
            └──< post_company_position >──┘
                       │
                       │
                     posts ───────< questions(embedding)
                       │
            summaries (按 company×position×period 聚合)

company_aliases (公司别名 → companies.id，自学习)
position_aliases (岗位别名 → positions.id，自学习)
```

### 2.2 完整建表 SQL

```sql
-- 启用 pgvector
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pg_trgm;  -- 模糊匹配兜底

-- 公司主表
CREATE TABLE companies (
    id           BIGSERIAL PRIMARY KEY,
    canonical    TEXT NOT NULL UNIQUE,         -- 规范名: "字节跳动"
    industry     TEXT,                          -- 互联网/金融/...
    embedding    vector(1024),                  -- canonical 名称向量
    embedding_model TEXT,
    embedding_version INT,
    created_at   TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX idx_companies_embedding ON companies
    USING hnsw (embedding vector_cosine_ops);

-- 岗位主表
CREATE TABLE positions (
    id           BIGSERIAL PRIMARY KEY,
    canonical    TEXT NOT NULL UNIQUE,         -- "后端开发"
    category     TEXT,                          -- 后端/前端/算法/测试...
    embedding    vector(1024),                  -- canonical 名称向量
    embedding_model TEXT,
    embedding_version INT,
    created_at   TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX idx_positions_embedding ON positions
    USING hnsw (embedding vector_cosine_ops);

-- 面经原文
CREATE TABLE posts (
    id              BIGSERIAL PRIMARY KEY,
    source_url      TEXT NOT NULL UNIQUE,
    title           TEXT,
    raw_html        TEXT,                       -- 原始 HTML（断点重抽用）
    cleaned_text    TEXT,                       -- trafilatura 清洗后
    posted_at       TIMESTAMPTZ,                -- 牛客上的发布时间
    interview_date  DATE,                       -- 抽取的面试月份，保存为当月 1 号
    fetched_at      TIMESTAMPTZ DEFAULT NOW(),
    content_score   INT,                        -- 0-70，稳定内容完整度
    content_score_version INT DEFAULT 1,
    content_scored_at TIMESTAMPTZ,
    quality_score   INT,                        -- 迁移兼容字段，不参与新逻辑
    extract_status  TEXT DEFAULT 'pending',     -- pending/done/failed/skipped
    extract_error   TEXT,
    extract_version INT DEFAULT 0               -- prompt 版本，重抽时 +1
);
CREATE INDEX idx_posts_status ON posts(extract_status);
CREATE INDEX idx_posts_posted ON posts(posted_at DESC);

-- 一篇面经可能涉及多家公司多岗位（少数情况）
CREATE TABLE post_company_position (
    post_id      BIGINT NOT NULL REFERENCES posts(id) ON DELETE CASCADE,
    company_id   BIGINT NOT NULL REFERENCES companies(id),
    position_id  BIGINT NOT NULL REFERENCES positions(id),
    PRIMARY KEY (post_id, company_id, position_id)
);

-- 题目（核心检索单元）
CREATE TABLE questions (
    id           BIGSERIAL PRIMARY KEY,
    post_id      BIGINT NOT NULL REFERENCES posts(id) ON DELETE CASCADE,
    round_no     INT,                           -- 第几轮，1/2/3/HR
    content      TEXT NOT NULL,
    category     TEXT,                          -- 算法/系统设计/八股/项目/HR
    answer_brief TEXT,                          -- 用户/原帖给的答案要点
    answer_ai    TEXT,
    answer_ai_version INT NOT NULL DEFAULT 0,
    embedding    vector(1024),                  -- bge-m3
    embedding_model TEXT,
    embedding_version INT,
    created_at   TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX idx_questions_embedding ON questions
    USING hnsw (embedding vector_cosine_ops);
CREATE INDEX idx_questions_post ON questions(post_id);

-- 摘要表（公司×岗位×季度，预计算）
CREATE TABLE summaries (
    id           BIGSERIAL PRIMARY KEY,
    company_id   BIGINT NOT NULL REFERENCES companies(id),
    position_id  BIGINT NOT NULL REFERENCES positions(id),
    period       TEXT NOT NULL,                 -- "2025Q2"
    content_md   TEXT NOT NULL,                 -- markdown 格式高频考点
    sample_count INT,                           -- 实际送入聚合的原始题目数
    input_fingerprint TEXT,                     -- 输入与聚合参数的 SHA-256 缓存指纹
    updated_at   TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (company_id, position_id, period)
);

-- 公司别名（自学习；真实外键）
CREATE TABLE company_aliases (
    id            BIGSERIAL PRIMARY KEY,
    alias         TEXT NOT NULL,
    company_id    BIGINT NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    confidence    REAL DEFAULT 1.0,             -- LLM 学到的低分；人工标注 1.0
    learned_at    TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (alias)
);
CREATE INDEX idx_company_alias_canonical ON company_aliases(company_id);

-- 岗位别名（自学习；真实外键）
CREATE TABLE position_aliases (
    id            BIGSERIAL PRIMARY KEY,
    alias         TEXT NOT NULL,
    position_id   BIGINT NOT NULL REFERENCES positions(id) ON DELETE CASCADE,
    confidence    REAL DEFAULT 1.0,
    learned_at    TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (alias)
);
CREATE INDEX idx_position_alias_canonical ON position_aliases(position_id);
```

别名表拆开后，`company_id` / `position_id` 可以声明真实外键，不再依赖 `entity_type + canonical_id` 的多态引用。canonical embedding 由迁移后的回填命令生成，Normalizer 的 embedding tier 使用 pgvector HNSW Top-K，不再在应用层读取并重新编码全部 canonical 名称。

### 2.3 设计要点

- **`extract_version`**：prompt 改版后扫表把 `version < 当前` 的全部重抽，避免历史数据污染。
- **`post_company_position` 多对多**：少数面经会同时讲多家公司，不要一对一卡死。
- **`embedding` 放在 `questions` 而非 `posts`**：搜索粒度是题目，不是整篇。
- **canonical embedding 放在 `companies` / `positions`**：归一化只需对候选 canonical 做向量近邻查询。
- **`summaries` 预计算**：摘要由 Aggregator 离线生成，Web 直查不再调 LLM。
- **HNSW 索引**：题目搜索和 canonical 召回都在 PostgreSQL 内完成；当前仓库没有真实压测，不承诺固定延迟。

## 3. Agent 流水线详解（LangGraph）

### 3.1 状态机定义

```python
class PipelineState(TypedDict):
    url: str
    raw_html: str | None
    cleaned_text: str | None
    extracted: dict | None       # {company, position, questions: [...]}
    normalized: dict | None      # {company_id, position_id, ...}
    content_score: int | None
    content_score_version: int
    errors: list[str]
    skip_reason: str | None      # 早退原因（重复/过短）
```

### 3.2 节点职责

| 节点 | 输入 | 输出 | 副作用 |
|---|---|---|---|
| **Crawler** | `url` | `raw_html` | 写 `posts.raw_html`；URL 已存在则早退 |
| **Cleaner** | `raw_html` | `cleaned_text` | 写 `posts.cleaned_text`；< 200 字早退 |
| **Extractor** | `cleaned_text` | `extracted` JSON | DeepSeek Function Calling，强制 schema |
| **Normalizer** | `extracted` | `normalized` ids | 查实体别名表 → pgvector Top-K → miss 调 LLM → 写回对应别名表 |
| **Scorer** | `extracted` | `content_score` | 写稳定内容分；freshness 在查询时根据 `posted_at` 动态计算 |
| **Aggregator** | （离线触发） | `summaries.content_md` | 按 (c,p,period) 分桶后跑 |

说明：抽取结果中的招聘层级 `ExtractedPost.level`（实习/校招/社招/未知）目前只在抽取结果和 CLI 展示中使用，未持久化到规范岗位表；`positions` 只表示岗位实体本身。

### 3.3 流水线时序

```
URL 入队 → Celery worker
  │
  ├─ Crawler (Playwright async)              → posts(raw)
  ├─ Cleaner (trafilatura)                   → posts(cleaned)
  ├─ Extractor (DeepSeek Function Calling)
  │    ├─ Redis cache check (key=hash(text))
  │    └─ miss → LLM 调用 → 缓存 + 落库
  ├─ Normalizer
  │    ├─ company_aliases / position_aliases 直查命中 → 返回 id
  │    └─ miss → bge-m3 查询 canonical embedding 的 Top-K
  │              ├─ ≥ 0.85 → 同一实体，写回对应别名表
  │              └─ < 0.85 → LLM 判定 → 新建 canonical
  ├─ Scorer (规则函数，纯本地)
  └─ 写 questions + post_company_position
      └─ embedding 异步任务（避免阻塞主流水线）

定时任务（每天 03:00）：
  Aggregator 扫描有新数据的 (c,p,period) 桶
  → 分页读取桶内全部合格题目（可用 top_n 显式限流）
  → NumPy 分块计算余弦相似度，阈值建图并用 Union-Find 去重
  → 只把按真实频次排序的 Top-M 代表簇交给 DeepSeek
  → DeepSeek 总结成 markdown
  → 写 summaries
```

### 3.4 容错与可观测

- **Redis 缓存 key**：`extract:{sha256(cleaned_text)}:{prompt_version}`
- **重试策略**：Crawler 网络错误 3 次指数退避；Extractor 由 `call_tool` 做最多 3 次重试；Aggregator 对 API/网络错误做最多 3 次传输重试，对空/非法/不符合业务 schema 的输出追加 1 次纠正提示重试（第二次降温度到 0）
- **Langfuse**：每个节点开 span，Extractor 记录 token 数、耗时、prompt 版本
- **断点续跑**：Celery 任务幂等，按 `posts.extract_status` 重新调度未完成节点

## 4. API 设计

| Method | Path | 描述 |
|---|---|---|
| GET | `/companies` | 公司列表（按面经数排序） |
| GET | `/companies/{id}/positions` | 该公司所有岗位 |
| GET | `/posts/search?q=&company=&position=` | 语义搜索（pgvector） |
| GET | `/summaries/{company_id}/{position_id}?period=` | 取摘要 |
| POST | `/admin/crawl` | 提交 URL 列表入队（自用，无鉴权） |
| GET | `/admin/jobs` | Celery 任务状态 |

## 5. 部署与运行

### 5.1 目录结构

```
InterviewLens/
├── docker-compose.yml          # postgres + redis + langfuse
├── .env.example
├── pyproject.toml              # uv 管理
├── docs/
│   ├── ARCHITECTURE.md         # 本文档
│   ├── PROMPT_LIBRARY.md       # 所有 prompt 版本管理
│   └── ROADMAP.md              # 14 天排期
├── sql/
│   ├── 001_init.sql            # 初始 schema
│   ├── 002-006_*.sql           # 历史增量迁移
│   └── 007_database_integrity.sql # 当前完整性与向量元数据迁移
├── src/interviewlens/
│   ├── __init__.py
│   ├── config.py               # pydantic-settings
│   ├── db/                     # SQLModel 模型 + asyncpg 连接
│   ├── crawler/                # Playwright 抓取
│   ├── agent/                  # LangGraph 节点
│   │   ├── state.py
│   │   ├── nodes/
│   │   │   ├── crawler.py
│   │   │   ├── cleaner.py
│   │   │   ├── extractor.py
│   │   │   ├── normalizer.py
│   │   │   ├── scorer.py
│   │   │   └── aggregator.py
│   │   └── graph.py            # 组装 StateGraph
│   ├── llm/                    # DeepSeek 客户端 + 缓存装饰器
│   ├── embedding/              # bge-m3 加载
│   ├── tasks/                  # Celery tasks
│   └── api/                    # FastAPI 路由
├── web/                        # Next.js 前端
└── tests/
```

### 5.2 docker-compose 关键服务

- `postgres:16` 带 pgvector 镜像（`pgvector/pgvector:pg16`）
- `redis:7-alpine`
- `langfuse/langfuse:2`（含自带 Postgres，可独立）

## 6. 风险登记表

| 风险 | 影响 | 缓解 |
|---|---|---|
| 牛客封号/封 IP | 抓取中断 | 单线程 1-2 req/s + 随机 sleep；备用账号 |
| Cookie 过期 | 抓取失败 | 启动健康检查；过期写 Slack/邮件提醒 |
| LLM 输出 schema 漂移 | 入库脏数据 | Extractor/Aggregator 均做 Pydantic 校验；失败不写入摘要，由任务边界重试或进入死信队列 |
| 别名误归一 | 数据污染 | 低置信度 alias 标记 `confidence < 0.9`，定期人工抽检 |
| 摘要幻觉 | 误导面试准备 | Aggregator 强制引用题目原文，不让 LLM 自由发挥 |

## 7. 后续迭代方向（v2+）

- 答案生成：对未带答案的题目用 LLM + 检索补答案
- 趋势分析：按时间维度统计某公司高频考点变化
- 个性化推荐：用户上传简历，按技能 gap 推荐重点准备方向
- 浏览器插件：在牛客页面悬浮显示"该题最近考过 N 次"
