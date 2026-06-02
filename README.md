# InterviewLens

> 自用面经聚合 AI 工具：抓取牛客大厂面经 → LLM 结构化抽取 → 公司/岗位归一 → 质量打分 → RAG 摘要

## 文档导航

| 文档 | 内容 |
|---|---|
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | 完整架构、数据模型、Agent 设计、API、部署 |
| [docs/PROMPT_LIBRARY.md](docs/PROMPT_LIBRARY.md) | 所有 LLM prompt 与版本管理规则 |
| [docs/ROADMAP.md](docs/ROADMAP.md) | 14 天 MVP day-by-day 排期 |
| [docs/DAY1_BOOTSTRAP.md](docs/DAY1_BOOTSTRAP.md) | Day 1 一步步把骨架跑起来 |
| [docs/DAY2_CRAWLER.md](docs/DAY2_CRAWLER.md) | Day 2 抓取与清洗使用指南 |
| [docs/DAY3_EXTRACTOR.md](docs/DAY3_EXTRACTOR.md) | Day 3 LLM 结构化抽取使用指南 |
| [docs/DAY4_LANGGRAPH.md](docs/DAY4_LANGGRAPH.md) | Day 4 LangGraph 状态机 + 断点续跑 |
| [docs/DAY5_OBSERVABILITY.md](docs/DAY5_OBSERVABILITY.md) | Day 5 节点级 Langfuse trace + 缓存命中率 + 成本统计 |
| [docs/DAY6_NORMALIZER.md](docs/DAY6_NORMALIZER.md) | Day 6 三级归一（字典→embedding→LLM）+ 自学习 |

## 快速开始（Day 1）

```bash
cp .env.example .env          # 填 DeepSeek key / 牛客 cookie / Langfuse secrets
docker compose up -d          # postgres + redis + langfuse
uv sync                       # 装依赖
uv run playwright install chromium
uv run il doctor              # 健康检查
uv run il seed-aliases        # 灌入种子别名
uv run pytest                 # 跑冒烟测试
```

详细步骤见 [docs/DAY1_BOOTSTRAP.md](docs/DAY1_BOOTSTRAP.md)。

## 技术栈速览

Python 3.13 · uv · Playwright · LangGraph · DeepSeek-V3 · bge-m3 · PostgreSQL 16 + pgvector · Redis · Celery · Langfuse · FastAPI · Next.js 15 · shadcn/ui

## 法律红线

仅供个人/小圈子使用。**严禁将抓取内容二次发布到任何公开站点。** Cookie 写入 `.env`，不得提交 git。

## 状态

- ✅ Day 1：骨架（容器、SQL、ORM、CLI 三件套）
- ✅ Day 2：抓取与清洗（Playwright + trafilatura + `il crawl` / `il show-post`）
- ✅ Day 3：LLM 结构化抽取（DeepSeek Function Calling + Redis 缓存 + Langfuse trace + `il extract` / `il run-pipeline`）
- ✅ Day 4：LangGraph 状态机串联三节点 + 断点续跑（`il graph` / `il resume`）
- ✅ Day 5：节点级 Langfuse trace + 缓存/token 仪表（`il metrics` / `il metrics-reset`）
- ✅ Day 6：Normalizer 节点 — 三级归一 + 自学习字典（`il normalize` / `il aliases`）
- 🚧 Day 7：Scorer 节点（题量/答案/轮次/时间衰减打分）
