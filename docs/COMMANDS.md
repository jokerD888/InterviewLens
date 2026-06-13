# InterviewLens 命令参考

> 所有命令可在本地（`uv run il <cmd>`）或 Docker（`docker compose exec api uv run il <cmd>`）执行。
> 本文档以 **Docker 全栈部署** 为例，本地运行时去掉 `docker compose exec api` 前缀即可。

---

## 目录

- [环境准备](#环境准备)
- [单篇调试](#单篇调试)
- [批量生产](#批量生产)
- [数据管理](#数据管理)
- [监控与排障](#监控与排障)
- [日常增量更新](#日常增量更新)

---

## 环境准备

```bash
# 1. 配置 .env（填入 DeepSeek Key / 牛客 Cookie / Langfuse secrets）
cp .env.example .env && vim .env

# 2. 一键启动全栈（首次会 build 镜像，约 3-5 分钟）
docker compose up -d --build

# 3. 健康检查
docker compose exec api uv run il doctor

# 4. 灌入种子别名（30 家公司 + 15 个岗位）
docker compose exec api uv run il seed-aliases

# 5. （可选）灌入演示数据，立即可看 UI 效果
docker compose exec api uv run il seed-demo
```

浏览器访问：
- 前端：`http://localhost:3000`
- API 文档：`http://localhost:8000/docs`
- Langfuse 面板：`http://localhost:3001`

---

## 单篇调试

验证爬虫和 LLM 抽取是否正常工作。

| 操作 | 命令 |
|---|---|
| **一键全链路**（推荐） | `docker compose exec api uv run il graph "https://www.nowcoder.com/discuss/<id>"` |
| 分步：抓取 + 清洗 | `docker compose exec api uv run il crawl "https://www.nowcoder.com/discuss/<id>"` |
| 分步：LLM 抽取 | `docker compose exec api uv run il extract <post_id>` |
| 查看帖子详情 | `docker compose exec api uv run il show-post <post_id>` |
| 重打分 | `docker compose exec api uv run il rescore <post_id>` |
| 查看质量排行 | `docker compose exec api uv run il top-posts` |

`il graph` 内部自动执行：crawl → clean → extract(LLM) → normalize(归一) → score(打分)。

| 常用选项 | 说明 |
|---|---|
| `--no-headless` | 显示浏览器窗口（调试用） |
| `--no-cache` | 不走 Redis 缓存，强制重新 LLM 调用 |
| `--no-reuse` | 强制重新抓取 HTML（即使库里已有） |
| `--min-chars 200` | 清洗后不足此字数则跳过 |

---

## 批量生产

### Celery 模式（后台并发）

```bash
# 启动 Worker（docker compose up -d 已包含，通常不需要额外操作）
docker compose up -d worker

# 批量入队（扫 N 页列表 → 自动发现 URL → 抓取 → 抽取）
docker compose exec api uv run il batch --pages 5 --source interview

# 查看任务状态
docker compose exec api uv run il task-status <task_id>

# 重跑失败/待处理的帖子
docker compose exec api uv run il resume

# 死信队列（超重试上限的任务）
docker compose exec api uv run il dlq list
docker compose exec api uv run il dlq drain --limit 50
docker compose exec api uv run il dlq clear
```

### Inline 模式（同步，调试用）

```bash
docker compose exec api uv run il batch --pages 2 --inline
```

### 后处理

```bash
# bge-m3 向量化所有题目 → 开启语义搜索
docker compose exec api uv run il backfill-embeddings

# RAG 摘要（单桶）
docker compose exec api uv run il aggregate --company 字节跳动 --position 后端开发 --period 2025Q2

# RAG 摘要（全桶批量）
docker compose exec api uv run il aggregate

# 查看摘要
docker compose exec api uv run il show-summary 字节跳动 后端开发 --period 2025Q2
```

---

## 数据管理

| 操作 | 命令 | 说明 |
|---|---|---|
| **软重置** | `docker compose exec api uv run il reset` | 保留已爬帖子，清空 AI 结果（questions/summaries/aliases），post 回 pending |
| **硬重置** | `docker compose exec api uv run il reset --full` | 帖子也全删，彻底重来 |
| 跳过确认 | `docker compose exec api uv run il reset -y` | 加 `-y` 跳过确认提示 |
| 重跑 embedding + 聚合 | `docker compose exec api uv run il backfill-embeddings && docker compose exec api uv run il aggregate` | 调 prompt 后刷新结果 |
| 查看别名 | `docker compose exec api uv run il aliases` | |
| 归一化测试 | `docker compose exec api uv run il normalize "字节" --type company` | |

### Docker 服务管理

| 操作 | 命令 |
|---|---|
| 停止（保留数据） | `docker compose down` |
| 启动 | `docker compose up -d` |
| 重启 | `docker compose restart` |
| 重建镜像 | `docker compose up -d --build` |
| 销毁数据卷（终极核武） | `docker compose down -v` |
| 查看日志 | `docker compose logs -f api` |
| 进容器调试 | `docker compose exec api bash` |

> `docker compose down -v` 会删除所有数据卷（PostgreSQL / Redis / 模型缓存 / Langfuse），慎用。

---

## 监控与排障

```bash
# 配置信息（敏感值遮罩）
docker compose exec api uv run il info

# 健康检查（PG + Redis + pgvector）
docker compose exec api uv run il doctor

# 缓存命中率 / Token 用量 / 预估花费
docker compose exec api uv run il metrics

# 清零指标计数器
docker compose exec api uv run il metrics-reset

# 搜索性能测试
docker compose exec api uv run il bench-search

# 质量排行（可按公司/岗位过滤）
docker compose exec api uv run il top-posts
docker compose exec api uv run il top-posts --company 字节跳动 --position 后端开发

# 数据库直连
docker compose exec postgres psql -U il -d interviewlens
```

---

## 日常增量更新

每天跑一次的标操：

```bash
# 1. 扫最新面经
docker compose exec api uv run il batch --pages 2 --inline

# 2. 跑完 pending/failed
docker compose exec api uv run il resume

# 3. 更新向量
docker compose exec api uv run il backfill-embeddings

# 4. 更新摘要
docker compose exec api uv run il aggregate
```

---

## 命令速查表

```
┌──────────────────────────────────────────────────────────────────┐
│  il info               查看配置                                  │
│  il doctor             健康检查                                  │
│  il seed-aliases       导入公司/岗位别名                          │
│  il seed-demo          灌入演示数据                               │
│  il reset              软重置（保留帖子，清 AI 结果）              │
│  il reset --full       硬重置（删一切）                            │
│                                                                  │
│  il crawl <url>        抓取单篇                                  │
│  il graph <url>        全链路（抓→洗→抽→归一→打分）               │
│  il extract <id>       LLM 结构化抽取                             │
│  il show-post <id>     查看帖子                                   │
│  il rescore <id>       重新打分                                   │
│  il top-posts          质量排行                                   │
│  il resume             断点续跑（failed/pending）                  │
│                                                                  │
│  il batch --pages N    批量发现+入队（Celery）                     │
│  il batch --inline     批量发现+同步跑                             │
│  il task-status <id>   Celery 任务状态                            │
│  il dlq list/drain     死信队列管理                               │
│                                                                  │
│  il normalize <alias>  别名归一测试                               │
│  il aliases            查看别名词典                               │
│                                                                  │
│  il backfill-embeddings   bge-m3 向量化                           │
│  il aggregate             RAG 摘要生成                            │
│  il show-summary <c> <p>  查看摘要                                │
│                                                                  │
│  il metrics            指标面板                                   │
│  il metrics-reset      清零指标                                   │
│  il bench-search       搜索性能测试                               │
│  il serve              启动 API（Docker 内自动，通常不需手动）      │
└──────────────────────────────────────────────────────────────────┘
```
