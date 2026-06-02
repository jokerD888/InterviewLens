# InterviewLens 14 天 MVP Roadmap

> 起算日：2026-06-02（周二）。每天投入 2-3 小时。

## Milestone 1 · 单点跑通（D1-D3）

### Day 1（6/2 周二）—— 项目骨架
- [ ] `uv init interviewlens` + 锁定 Python 3.13
- [ ] `pyproject.toml` 加依赖：fastapi sqlmodel asyncpg pgvector celery redis playwright trafilatura openai langgraph langfuse pydantic-settings httpx
- [ ] `docker-compose.yml`：postgres（pgvector/pgvector:pg16）+ redis7
- [ ] `.env.example` 列全 LLM key / DB url / cookie
- [ ] `sql/001_init.sql` 跑通建表
- **验收**：`docker compose up -d` + `psql` 能列出 7 张表

### Day 2 —— 抓取与清洗
- [ ] `crawler/playwright_runner.py`：注入 cookie，单 URL 抓 HTML
- [ ] `crawler/cleaner.py`：trafilatura 转纯文本
- [ ] CLI：`python -m interviewlens.crawl <url>` → 入 `posts` 表
- **验收**：psql 查到一条记录，`cleaned_text` 非空

### Day 3 —— Extractor
- [ ] `llm/deepseek.py`：异步客户端，带 Redis 缓存装饰器
- [ ] `agent/nodes/extractor.py`：实现 Function Calling，prompt 来自 `PROMPT_LIBRARY.md`
- [ ] Pydantic 模型校验 LLM 输出
- [ ] CLI：`python -m interviewlens.extract <post_id>`
- **验收**：`questions` 表多出 N 条；Langfuse 看得到调用

---

## Milestone 2 · Agent 流水线（D4-D8）

### Day 4 —— LangGraph 编排
- [ ] `agent/state.py`：`PipelineState` TypedDict
- [ ] `agent/graph.py`：StateGraph 串 Crawler → Cleaner → Extractor
- [ ] 每节点失败写 `errors` 字段，整体可重入

### Day 5 —— 缓存与可观测
- [ ] Langfuse 自部署 docker-compose 加进来
- [ ] `llm/cache.py`：装饰器 + key=hash(prompt)+prompt_version
- [ ] 跑 5 个相同 URL，确认第二次起从缓存命中

### Day 6 —— Normalizer
- [ ] `embedding/bge_m3.py`：sentence-transformers 加载（fp16 节省内存）
- [ ] 手写 `data/seed_aliases.yaml` 种子词典（30+ 大厂别名）
- [ ] `agent/nodes/normalizer.py`：alias_dict 直查 → embedding 相似度 → LLM 兜底
- **验收**："字节"、"Bytedance"、"抖音"全部归一到同一 company_id

### Day 7 —— Scorer
- [ ] `agent/nodes/scorer.py`：纯函数实现 `PROMPT_LIBRARY.md` 第 4 节规则
- [ ] 单元测试覆盖 5 种典型样本
- **验收**：水帖 ≤ 30 分，硬核帖 ≥ 70 分

### Day 8 —— Aggregator
- [ ] `agent/nodes/aggregator.py`：分桶 + pgvector top-100 召回 + DeepSeek 总结
- [ ] 写入 `summaries` 表
- [ ] CLI：`python -m interviewlens.aggregate --company 字节跳动 --position 后端开发 --period 2025Q2`
- **验收**：输出 markdown 包含高频考点 + 引用原题

---

## Milestone 3 · 批量与 Web（D9-D12）

### Day 9 —— Celery 批量
- [ ] `tasks/crawl_task.py`：包装 LangGraph 为 Celery 任务
- [ ] `crawler/list_page.py`：抓牛客分类列表页提取面经 URL（限速 1.5 req/s）
- [ ] 一键 `python -m interviewlens.batch --pages 10` 入队 100 条
- **验收**：worker 日志能看到 100 条任务

### Day 10 —— FastAPI
- [ ] `api/companies.py` `/companies` `/positions`
- [ ] `api/search.py` `/posts/search` 走 pgvector + 公司岗位过滤
- [ ] `api/summary.py` `/summaries/{c}/{p}`
- [ ] OpenAPI docs 走通

### Day 11 —— Next.js 骨架
- [ ] `pnpm create next-app web --ts --tailwind --app`
- [ ] shadcn/ui init + 装 Sidebar / Card / Input / Badge
- [ ] 三栏布局：左公司 / 中岗位筛选 / 右摘要

### Day 12 —— 检索体验
- [ ] 顶部搜索框，回车走 `/posts/search`，结果列表带 quality_score 徽标
- [ ] 点击题目展开看原帖链接 + 答案要点
- [ ] 关键词高亮

---

## Milestone 4 · 打磨与简历化（D13-D14）

### Day 13 —— 真实数据 + 调优
- [ ] 跑 500-1000 篇真实数据
- [ ] 看 Langfuse 找最贵的 prompt，做提示词压缩
- [ ] 修典型 schema 漂移 case；补别名词典
- **验收**：单条端到端成本 ≤ 0.05 元；P95 延迟 ≤ 30s

### Day 14 —— README + 简历化
- [ ] README：项目背景 / 架构图（用 ARCHITECTURE.md 那张）/ Quick Start / 亮点
- [ ] 录 30s 演示 GIF：搜索"分布式锁" → 看到字节后端高频考点
- [ ] 推上 GitHub，仓库描述写清晰

---

## 简历亮点（可直接抄进简历）

> **InterviewLens · 面经聚合 Agent**
> 基于 LangGraph 实现 6 节点状态机流水线（Crawler/Cleaner/Extractor/Normalizer/Scorer/Aggregator），处理 1000+ 篇牛客面经。
>
> - 用 DeepSeek-V3 Function Calling 强制 JSON schema 抽取，配合 Redis 缓存命中率 >85%，单条端到端成本 ≤ 0.05 元
> - 别名归一采用"词典 + bge-m3 embedding 相似度 + LLM 兜底"三级策略，自学习写回词典；公司/岗位归一准确率 ≥ 95%
> - PostgreSQL pgvector HNSW 索引支持百万级题目语义检索，P95 召回 < 50ms
> - Langfuse 全链路 trace + Celery 任务幂等 + LangGraph 断点续跑，支持 prompt 版本管理与历史数据重抽
