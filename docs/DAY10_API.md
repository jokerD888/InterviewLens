# Day 10 — FastAPI REST 接口

> 目标：把库里数据通过 REST 暴露出去，给 Day 11 的 Next.js 前端用，也给将来的 mobile / 浏览器插件用。

## 0. 这一步带来什么

| 之前 | 现在 |
|---|---|
| 只有 CLI 能查数据 | REST 接口随便接 |
| 没有公开文档 | OpenAPI 自动生成在 `/docs` |
| 没有任务面板 | `/admin/jobs` 看队列/DLQ/worker |
| 没有健康检查 | `/admin/health` 适合 docker healthcheck |

## 1. 启动

```bash
# 一行启服务（CLI 包装的 uvicorn）
uv run il serve --reload

# 或直接 uvicorn
uv run uvicorn interviewlens.api.app:app --reload --port 8000
```

启动后默认在 http://127.0.0.1:8000：
- **Swagger UI**：http://127.0.0.1:8000/docs
- **ReDoc**：http://127.0.0.1:8000/redoc

## 2. 路由清单

| Method | Path | 用途 |
|---|---|---|
| GET | `/` | 元信息 + 端点目录 |
| GET | `/companies` | 公司列表（默认带 post_count，按数量降序） |
| GET | `/companies/{id}/positions` | 该公司下所有岗位 + 统计 |
| GET | `/positions` | 岗位列表（带统计） |
| GET | `/posts/search?q=&company=&position=&min_quality=&limit=` | pgvector 语义检索题目 |
| GET | `/posts/{id}` | 帖子详情（带 companies/positions 关联）|
| GET | `/summaries?company=&position=&period=` | 摘要列表 |
| GET | `/summaries/{company}/{position}?period=2025Q2` | 单条摘要 |
| GET | `/admin/health` | docker healthcheck 用，状态码总是 200，body 看 status |
| GET | `/admin/jobs` | Celery 队列长度 / DLQ / 活跃 worker |
| GET | `/admin/metrics` | 缓存命中率 / token 累计 / 节点延迟 |
| POST | `/admin/ingest` | 入队一个 URL，返回 task_id |
| GET | `/admin/dlq/{task_name}` | 看 DLQ |
| DELETE | `/admin/dlq/{task_name}` | 清空 DLQ |

## 3. 重头戏：语义搜索

```bash
# 默认 top-20，无过滤
curl 'http://localhost:8000/posts/search?q=分布式锁怎么实现'

# 按公司岗位过滤
curl 'http://localhost:8000/posts/search?q=JVM%20GC&company=字节跳动&position=后端开发&limit=10'

# 只看高分帖
curl 'http://localhost:8000/posts/search?q=ZSet&min_quality=60'
```

返回：
```json
[
  {
    "id": 4123,
    "post_id": 456,
    "round_no": 1,
    "round_type": "技术一面",
    "content": "Redis 分布式锁的实现，Redisson 是怎么做的？",
    "category": "数据库",
    "answer_brief": "...",
    "quality_score": 78,
    "source_url": "https://www.nowcoder.com/discuss/...",
    "similarity": 0.872
  }
]
```

`similarity = 1 - cosine_distance`，越接近 1 越相关。

## 4. 摘要查询

```bash
# 单条
curl 'http://localhost:8000/summaries/字节跳动/后端开发?period=2025Q2'

# 全部
curl 'http://localhost:8000/summaries?limit=50'
```

## 5. 任务面板

```bash
curl http://localhost:8000/admin/jobs
```

```json
{
  "queues": {"celery": 12},
  "dlq": {"il:dlq:il.crawl_url": 3},
  "workers": ["celery@host-1"]
}
```

前端 D11 会做一个简单 dashboard 接这个。

## 6. 关键设计要点（面试讲故事）

- **lifespan 预热 bge-m3**：不预热的话第一个 `/posts/search` 会卡 30 秒。lifespan 在 worker 启动时同步 load 一次，后续无延迟
- **依赖注入 `get_session`**：FastAPI 经典模式；测试时 `app.dependency_overrides[get_session] = ...` 一行搞定 mock
- **pgvector 用 `<=>` 而不是 `<#>`**：`<=>` 是 cosine distance（已归一化场景），`<#>` 是 negative inner product；选错了排序方向会反
- **手动拼 vec_str 而不是 ORM 列绑定**：pgvector 在 SQLAlchemy 里参数绑定有点 quirky；直接 CAST text 最稳
- **`/admin/jobs` 是 sync endpoint**：Celery `inspect.active()` 阻塞 RPC，async 包了反而难看
- **CORS allow_origins=["\*"]**：本地开发友好；生产改白名单
- **路由按业务分文件**：taxonomy / search / summary / admin，每个文件 100-150 行，便于维护和讲故事

## 7. 用 httpx 跑一遍测试

```bash
# 启服务
uv run il serve &

# 简单冒烟
curl -s http://localhost:8000/admin/health | jq
curl -s http://localhost:8000/companies?limit=5 | jq
curl -s 'http://localhost:8000/posts/search?q=Redis&limit=3' | jq

# pytest（用 TestClient + mock session，不需要真 DB）
uv run pytest tests/test_api.py -v
```

## 8. 验收清单

- [ ] `uv run il serve --reload` 起得来
- [ ] http://localhost:8000/docs 能打开 Swagger
- [ ] `/companies` 返回非空数组
- [ ] `/posts/search?q=分布式锁` 返回带 similarity 的题目
- [ ] `/summaries/{c}/{p}` 找不到时 404 不是 500
- [ ] `/admin/health` 返回 status=ok
- [ ] `pytest tests/test_api.py -v` 全 3 个测试绿

## 9. 下一步（D11 预告）

D11：Next.js 15 前端骨架 —— 三栏布局（左公司列表 / 中岗位筛选 / 右摘要面板），shadcn/ui 组件，调今天的 API。
