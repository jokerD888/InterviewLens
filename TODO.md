# InterviewLens TODO

> 当前状态：D1–D12 + feed/bridge/answerer/tab_crawler 代码均已完成（见近期 commit），D13–D14 仅文档就绪。目标：真实数据验证 → 生产部署上线。
>
> **代码侧就绪核对（2026-07-02）**：`il batch` / `backfill-embeddings` / `aggregate` / `rescore --all` / `answer --regenerate` / `tab-crawl` / `import-crawl` / `clear-embeddings` CLI 全在；`aggregate_all` 函数已存在（CLI 在用，但尚未包成 Celery 任务）；`/admin/ingest` 可单条触发爬取。阻塞点仅在"真去跑 + 填数字"。

---

## 🔧 已修复的 Bug（记录，供参考）

| # | 问题 | 文件 | 修复方式 |
|---|------|------|----------|
| 1 | 循环导入：`embedding` / `llm` / `crawler` 三个包内部 `..self` 自引用 | `embedding/backfill.py` `llm/orchestrator.py` `crawler/orchestrator.py` | 改为模块内直接 `from .xxx import` |
| 2 | `created_at` / `fetched_at` 等列 NOT NULL 但 ORM 默认 None | `db/models.py` | 改为 `default_factory=_now` + `server_default` |
| 3 | `seed_demo.py` / `repositories.py` / `aggregator.py` 使用 `datetime.now(timezone.utc)`（带时区）写入无时区列 | 对应文件 | 改为 `.replace(tzinfo=None)` |
| 4 | DeepSeek 默认思考模式不支持 function calling | `llm/deepseek.py` | `call_tool()` 增加 `extra_body={"thinking": {"type": "disabled"}}`（原 TODO 笔误写成 `deepseek-v4-flash`，该型号不存在，已修正） |
| 5 | aggregator SQL 中 `None` 参数类型无法被 asyncpg 推断 | `aggregator/aggregator.py` | `:period IS NULL` → `CAST(:period AS TEXT) IS NULL` |

---

## Phase 1：真实数据验证（原 D13，预计 1-2 天）

### 1.1 批量跑真实数据

- [ ] 更新 `.env` 中的 `NOWCODER_COOKIE`（从浏览器重新复制）
- [ ] 启动 Celery Worker：`uv run celery -A interviewlens.tasks.celery_app worker --concurrency=2 --loglevel=INFO`
- [ ] 先跑 3 页试水：`uv run il batch --pages 3`
- [ ] 确认无大面积失败后放量：`uv run il batch --pages 30`
- [ ] 监控：`uv run il metrics` + 查 `posts.extract_status` 分布
- [ ] 跑完后：`uv run il backfill-embeddings` → `uv run il aggregate`

**验收标准**：posts `extract_status='done'` ≥ 200，questions ≥ 1500 且全有 embedding，summaries ≥ 10

### 1.2 Prompt 调优 & Scorer 调优

- [ ] 在 5 个样本上 A/B 测试 `EXTRACT_PROMPT_VERSION=2`
- [ ] 调整 `ScorerWeights` 权重，`il rescore --all` 后验证排序合理性
- [ ] 检查 `il aliases --type company --limit 200`，补漏归一失败 case
- [ ] 视情况微调 `EMBED_THRESHOLD_HIGH`（当前 0.85）

**验收标准**：`il top-posts --limit 10` 排序符合直觉，DLQ 长度 < 总抓取数 5%

### 1.3 录制实测指标

- [ ] 执行 `docs/DAY13_INGESTION_TUNING.md` 第 6 节的 SQL 查询，记录真实数字
- [ ] `uv run il bench-search` 记录 P50 延迟
- [ ] 将真实数字填入 README 的"实测数据"段

---

## Phase 2：简历化收尾（原 D14，预计 1 天）

- [ ] 重写 README（用 `docs/DAY14_RESUME_AND_RELEASE.md` 模板 + Phase 1 真实数字）
- [ ] 添加 mermaid 架构图到 README
- [ ] 录 30s 演示 GIF → `docs/assets/demo.gif`
- [ ] 写 `CHANGELOG.md`
- [ ] `git tag -a v0.1.0` + push

---

## Phase 3：生产部署（预计 1-2 天）

### 3.1 读路径缓存——消除重复 DB 查询

> **问题**：`/companies`、`/positions`、`/summaries` 每次请求都直查 DB，数据变化极慢（仅爬取时才可能新增）。

**方案**：在 FastAPI 层加 Redis 缓存，TTL 驱动失效。

```python
# 伪代码示意
@router.get("/companies")
async def list_companies():
    cache_key = "il:api:companies"
    cached = await redis.get(cache_key)
    if cached:
        return json.loads(cached)
    rows = await db.execute(...)
    await redis.set(cache_key, json.dumps(rows), ex=3600)  # 1 小时过期
    return rows
```

失效时机：Crawler/Normalizer 写入新 company/position 时主动删除对应缓存 key。

- [x] `/companies` 结果缓存到 Redis，TTL 1 小时
- [x] `/companies/{id}/positions` 结果缓存到 Redis
- [x] `/summaries/{c}/{p}` 结果缓存到 Redis（含 `/summaries` 列表 + `/positions`，复用 `api/cache.py`）
- [ ] 写入路径（Crawler/Normalizer/Aggregator）主动 invalidate 相关缓存 —— **暂不做**，纯 TTL（1h）对每日爬取频率足够，YAGNI
- [ ] Admin 面板加一个"刷新缓存"按钮 —— **暂不做**，可 `redis-cli FLUSHDB` 或等 TTL 自然过期

### 3.2 搜索结果缓存——热门搜索词命中率极高

> **问题**："分布式锁""JVM GC"等高频搜索词每次都重新编码 query + 跑 HNSW。query embedding 完全可复用。

**方案**：按 `sha256(query)` 缓存 query embedding，按 `sha256(query + filters)` 缓存完整搜索结果。

```python
# 伪代码示意
embed_key = "il:search:embed:" + sha256(query)
vec = await redis.get(embed_key)
if not vec:
    vec = await embed_texts([query])
    await redis.set(embed_key, vec, ex=86400)  # query embedding 24h 有效

result_key = "il:search:result:" + sha256(query + str(filters))
cached = await redis.get(result_key)
if cached:
    return json.loads(cached)
rows = await db.execute(...)
await redis.set(result_key, json.dumps(rows), ex=1800)  # 结果 30min 有效
```

- [x] query embedding 缓存（key=sha256(query)+emb 版本, TTL 24h，base64 float32 序列化）
- [x] HNSW 搜索结果缓存（key=sha256(query+filters), TTL 30min）

### 3.3 bge-m3 模型单例——避免多进程重复加载

> **问题**：用 `gunicorn --workers 4` 启动 FastAPI 时，4 个 worker 各加载一份 bge-m3（~1.1GB），共 4.4GB。VPS 内存直接爆炸。

**方案**：用 `gunicorn --preload` 让 master 先加载模型，worker fork 后共享同一块内存页。

```bash
gunicorn -w 4 -k uvicorn.workers.UvicornWorker \
  --preload \                          # ← 关键参数
  interviewlens.api.app:app
```

`--preload` 的限制：代码必须在 import 时就能安全执行（不能有在 fork 后才初始化的 DB 连接池）。

> **当前实现**（2026-07-02 核对）：`embedding/bge_m3.py` 用模块级 `_model` 全局 + `asyncio.Lock` 做**懒加载**——首次 `await get_model()` 才加载，`api/app.py` 的 `lifespan` 里调一次预热。**这是 fork-safe 的**：worker fork 后各自首次请求才加载，master 不跑 lifespan。
>
> **为什么不能照搬原 TODO 的"移到模块级 import"**：`get_model()` 是 async（`asyncio.to_thread` 包了同步的 `SentenceTransformer` 构造）。模块级 import 时同步加载会破坏当前 fork-safe 的懒加载，且 master 进程加载的 torch/sentence-transformers 对象 fork 到 worker 后状态不一定干净（CUDA 上下文尤其危险）。**原方案方向对但做法错，已修正。**

**正确方案**：`gunicorn --preload` 让 master 在 fork 前执行 app 模块顶层代码；在 `bge_m3.py` 加一个**同步预热入口**，在 app 模块顶层调用——master 加载一次，fork 后各 worker 共享同一块内存页（copy-on-write，只要不写就不复制）。

```python
# src/interviewlens/embedding/bge_m3.py 追加同步预热入口
def preload_model() -> None:
    """Synchronous pre-load for gunicorn --preload. Loads once in master, shared via CoW."""
    global _model
    if _model is not None:
        return
    device = _resolve_device()
    log.info("embed.preload", model=settings.embedding_model, device=device)
    from sentence_transformers import SentenceTransformer
    _model = SentenceTransformer(settings.embedding_model, device=device)
```

```python
# src/interviewlens/api/app.py 顶层（lifespan 之外）
from ..embedding import preload_model
preload_model()   # master 进程执行一次；fork 后 worker 共享
```

**注意点**：
- 必须 `device="cpu"`。CUDA 上下文 fork 后会损坏——若 VPS 有 GPU，preload 后改用 worker 内重新加载，或干脆 CPU 推理（bge-m3 CPU 编码单条 <50ms，搜索场景够用）。
- `session_scope()` 的 async engine 是 lazy 的（首次 `get_session()` 才建池），master 在 `--preload` 时不碰 DB，fork-safe。✅ 无需改动。
- fork 后若 worker **写入** `_model` 会触发 CoW 内存复制——只要 `get_model()` 里 `if _model is not None: return _model` 短路生效就不重载。当前代码满足。✅

- [ ] `embedding/bge_m3.py` 加 `preload_model()` 同步入口
- [ ] `api/app.py` 顶层调一次 `preload_model()`
- [ ] 压测验证 4 worker 时内存用量 ≈ 1 份模型而非 4 份（`ps aux --sort=-rss | grep gunicorn`）

### 3.4 Celery Beat 定时调度——替代手动 `il batch`

> **问题**：当前爬取全靠手动跑 `il batch`，生产环境需要每天凌晨自动执行。

**方案**：写 Celery Beat schedule 配置。

```python
# src/interviewlens/tasks/celery_app.py 追加
from celery.schedules import crontab

celery_app.conf.beat_schedule = {
    "crawl-daily": {
        "task": "il.enqueue_listing",
        "schedule": crontab(hour=4, minute=0),     # 每天凌晨 4 点
        "kwargs": {"pages": 30, "skip_normalize": False},
    },
    "aggregate-daily": {
        "task": "il.aggregate_pair",
        "schedule": crontab(hour=5, minute=30),    # 5:30，等爬取跑完
        "kwargs": {"company": "", "position": ""}, # 需改为 aggregate_all 逻辑
    },
}
```

**注意**：`aggregate_pair` 一次只处理一个 (company, position) 对，目前没有"遍历所有活跃桶"的 Celery 任务。需要：
- [ ] 写一个 `aggregate_all_active_buckets` 任务（扫所有有 posts 的 company×position 组合，逐个调用 `aggregate_one`）
- [ ] 或用 Celery Beat 的 chord/chain 模式 fan-out

- [ ] 新增 `aggregate_all_active_buckets` Celery 任务（替代手动 `il aggregate`）
- [ ] 配置 Celery Beat schedule（crawl 04:00、aggregate 05:30）
- [ ] 新增 `docker-compose.beat.yml` 或把 beat 并入 worker compose
- [ ] 加一个"立即触发"的 Admin API（`POST /admin/trigger-crawl`）

### 3.5 读写资源隔离——避免爬取拖慢用户查询

> **问题**：凌晨爬取时大量写 DB，如果正好有用户搜索，性能互相干扰。

**方案（渐进式，按需升级）**：

| 层级 | 手段 | 复杂度 |
|------|------|--------|
| 连接池隔离 | Worker 用独立的 `pool_size`（小），FastAPI 用另一个（大） | 低 |
| 限流 | FastAPI 搜索接口加 `slowapi` 或 nginx `limit_req_zone` | 低 |
| 读写分离 | pg 主从复制，Worker 写主库，FastAPI 搜索读从库 | 中（VPS 一般不搞） |

**最小可行方案**：连接池隔离 + 搜索限流即可。

```python
# config 里拆两个 pool size
# Worker 侧: pool_size=3, max_overflow=5
# API 侧:   pool_size=10, max_overflow=20
```

- [ ] Worker 和 API 使用不同 DB 连接池大小

### 3.6 生产化 FastAPI 部署

- [ ] 用 gunicorn + uvicorn workers 替代 `il serve`
- [ ] 写 `systemd` service 文件（模板见 Day 14 doc）
- [ ] nginx/Caddy 反代 + HTTPS
- [ ] 前端部署到 Vercel（Root Directory = `web/`）
- [ ] 环境变量在 Vercel 控制台设置 `NEXT_PUBLIC_API_BASE`

---

## Phase 4：持续优化（长期，按需做）

- [ ] 单条 URL 抓取成功率监控（每日巡检 DLQ）
- [ ] Cookie 过期检测 → 自动通知（邮件/微信/钉钉 webhook）
- [ ] 多数据源（V2EX 面经区、一亩三分地）
- [ ] 题目去重升级：余弦聚类 → SBERT 跨编码器精排
- [ ] 个性化推荐：用户上传简历 → 按技能 gap 推荐准备方向
- [ ] Chrome 浏览器插件：在牛客页面悬浮显示"该题最近考过 N 次"

---

## 任务依赖关系

```
Phase 1 (真实数据) ──→ Phase 2 (简历化) ──→ Phase 3 (部署) ──→ Phase 4 (迭代)
                              │
                              └── 也可以 Phase 1 完成后先部署再装修 README
```

Phase 3 内部的依赖：
```
3.3 bge-m3 单例 ─┐
3.6 生产化部署 ──┤
                  ├── 必须先做（部署到 VPS 时一起搞定）
3.1 读路径缓存 ──┤
3.2 搜索缓存 ────┘
3.4 Celery Beat ─── 可以部署后单独补
3.5 资源隔离 ────── 小规模不用急，DLQ 堆积了再搞
```
