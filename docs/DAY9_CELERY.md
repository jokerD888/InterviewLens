# Day 9 — Celery 批量化 + 列表页爬虫 + 死信队列

> 目标：从单 URL 调试模式升级到"扫一晚跑 1000 篇"的批量模式。

## 0. 这一步带来什么

| 之前 | 现在 |
|---|---|
| `il graph <url>` 一次一个 | `il batch --pages 10` 一键扫 100+ URL |
| URL 要手动收集 | 自动从牛客分类页抓取 |
| 失败要看日志手动排 | 死信队列 (DLQ)，`il dlq list/drain/clear` 操作 |
| 单进程同步 | Celery worker 并发 + 自动重试 |

## 1. 启动 worker

```bash
# 方式 A：本机直接跑（开发推荐）
uv run celery -A interviewlens.tasks.celery_app worker --loglevel=INFO --concurrency=2

# 方式 B：用 docker compose worker（准生产）
docker compose -f docker-compose.yml -f docker-compose.worker.yml up -d worker
docker compose logs -f worker
```

worker 启动后会监听 `redis://localhost:6380/1` 上的任务队列。

## 2. 三种使用模式

```bash
# 模式 1：批量入队（生产）
uv run il batch --pages 5
# 输出 task_id，worker 会异步扫 5 页 → 提取所有 URL → 每个 URL 派一个 crawl_url 任务

# 模式 2：inline 同步跑（调试，没 worker 也能用）
uv run il batch --pages 1 --inline
# 在当前进程跑完所有 URL，看每条结果

# 模式 3：单条入队
uv run python -c "from interviewlens.tasks import crawl_url; crawl_url.delay('https://www.nowcoder.com/discuss/123')"
```

## 3. 看任务状态

```bash
# 用入队时打印的 task_id
uv run il task-status 7c4f2e90-a8b1-...

# state: PENDING | STARTED | SUCCESS | FAILURE | RETRY
```

## 4. 死信队列（DLQ）

任务超过 max_retries 后会进 Redis list `il:dlq:{task_name}`，便于人工排查。

```bash
# 查看 DLQ 内容
uv run il dlq list
uv run il dlq list --task-name il.aggregate_pair

# 重新入队（drain 把 N 条 pop 出来变成新任务）
uv run il dlq drain --limit 100

# 清空（确认问题已修复后）
uv run il dlq clear --task-name il.crawl_url
```

## 5. 任务清单与重试策略

| 任务 | max_retries | 退避 | 失败入 DLQ |
|---|---|---|---|
| `il.crawl_url` | 3 | 指数 5-120s + jitter | ✅ |
| `il.enqueue_listing` | 0 | - | ❌（仅派发） |
| `il.aggregate_pair` | 2 | 指数 10-300s | ✅ |

`acks_late=True`：worker 处理完才 ack；如果 worker 中途挂掉，任务会被 redelivered。
`worker_max_tasks_per_child=50`：每 50 任务回收 worker 子进程，避免 Playwright 内存泄漏积累。

## 6. 性能调优

```bash
# 提高并发（默认 2，CPU 核心数 - 1 是好起点）
uv run celery -A interviewlens.tasks.celery_app worker --concurrency=4

# 拆分 queue 让重活轻活分开（高级用法）
# 例如：crawl 和 aggregate 分队，互不阻塞
```

`task_soft_time_limit=240s` / `task_time_limit=300s`：单任务超 4 分钟先发软警告，5 分钟硬杀。
Playwright 偶尔卡死或牛客特别慢的页面会被这层兜底救回来。

## 7. SQL 验证

```sql
-- 抓取进度
SELECT extract_status, COUNT(*) FROM posts GROUP BY extract_status;

-- 看抓取速度（最近 1 小时）
SELECT date_trunc('minute', fetched_at) AS minute, COUNT(*)
FROM posts
WHERE fetched_at > NOW() - INTERVAL '1 hour'
GROUP BY minute ORDER BY minute;

-- 哪些 URL 失败了
SELECT id, source_url, extract_error FROM posts
WHERE extract_status = 'failed'
ORDER BY fetched_at DESC LIMIT 20;
```

## 8. 关键设计要点（面试讲故事）

- **Celery 任务 sync 包 async**：Celery worker 是同步执行模型，但我们的 graph/playwright 都是 async。`_run_async` 桥接两者，避免重写整个代码库
- **enqueue_listing 自己也是 task**：列表页发现也耗时，用 task 化让它能被中央调度，不阻塞主进程
- **DLQ 用 Redis list 而不是新表**：临时性数据放 Redis 简单；要持久化可以加一张表
- **acks_late + reject_on_worker_lost**：避免任务进了 worker 又被吃掉的情况，重启 worker 也不丢
- **prefetch_multiplier=1**：Playwright 启动慢，预取多了空 worker 等不必要；让任务均匀分布
- **inline 模式**：调试时不想启 worker，加个 `--inline` flag 在当前进程跑，便于 IDE 断点
- **max_tasks_per_child=50**：Playwright/Chromium 长跑会内存泄漏；定期回收 worker 子进程是经典做法

## 9. 验收清单

- [ ] worker 启动后 `il batch --pages 1` 返回 task_id
- [ ] `docker compose logs worker` 看到 worker 开始处理任务
- [ ] 跑 30 分钟后 SQL 查 posts 表新增 30+ 条
- [ ] 故意停掉 postgres 一会儿再重启，看到任务被 RETRY 而不是 FAILURE
- [ ] 把某条 URL 改成无效的，3 次重试后进入 `il dlq list`
- [ ] `il dlq drain` 把 DLQ 任务重新入队
- [ ] `pytest tests/test_discover.py -v` 全 4 个测试绿

## 10. 一晚跑 1000 篇示例

```bash
# 1. 启 worker
uv run celery -A interviewlens.tasks.celery_app worker --concurrency=4 --loglevel=INFO &

# 2. 扫 30 个列表页（每页约 30 条 → ~900 URL）
uv run il batch --pages 30

# 3. 第二天起来看
uv run il metrics                         # 缓存命中率/token 成本/节点延迟
docker exec il-postgres psql -U il -d interviewlens -c "SELECT COUNT(*) FROM posts;"
uv run il dlq list                        # 看哪些 URL 卡住了
uv run il top-posts --limit 20            # 看高分帖
uv run il aggregate                       # 全公司全岗位摘要
```

## 11. 下一步（D10 预告）

D10：FastAPI 接口层 —— 把库里的数据通过 REST 暴露给前端：
- `/companies` / `/positions` 列表
- `/posts/search?q=&company=&position=` 语义检索（pgvector）
- `/summaries/{company_id}/{position_id}` 摘要
- `/admin/jobs` 任务面板
