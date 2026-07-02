## Context

`GET /posts/search?q=...&company=...&position=...&min_quality=...&limit=...` 是前端搜索页的核心读路径。当前每次请求：

1. `qvec = await embed_texts([q])` — bge-m3 CPU 编码，单条 ~30–50ms，加载过模型后纯推理。
2. 拼 SQL，`ORDER BY q.embedding <=> CAST(:vec AS vector) LIMIT :limit` — pgvector HNSW 查询，单条 ~10–100ms（取决于 limit 和过滤）。

数据特性：题目只在爬取时新增，且爬取是低频（TODO 计划每天凌晨一次）。所以搜索结果在 30min 窗口内几乎稳定不变。热门 query 被反复搜索时，重复编码 + 重复 HNSW 是纯浪费。

Redis 已就绪：`settings.redis_url` 配置好，`observability.get_redis()` 提供 async 单例（`aioredis.from_url`，`decode_responses=True`）。`redis>=5.2` 是依赖。

刚完成的异常分层（`exception-handling-layering`）已经把缓存读取归入 B 层——捕获 `redis.RedisError` 降级 miss-through，不炸主流程。本方案直接套用。

## Goals / Non-Goals

**Goals:**

- 热门 query 的 embedding 复用（24h TTL，prompt/embedding 模型不变期间完全可复用）
- 热门 `(query, filters)` 的完整结果复用（30min TTL）
- Redis 故障时透明降级，搜索功能不受影响
- 不改 API 契约、不改 DB schema、不引入新依赖
- 复用现有 `incr_cache` 命中率指标

**Non-Goals:**

- 不做主动缓存失效（写入路径不感知缓存）—— 30min TTL 足够，YAGNI
- 不缓存 `/posts/{post_id}`（单帖查询，DB 主键 lookup 已经很快，无 ROI）
- 不引入 Redis JSON/向量专用序列化库 —— stdlib base64 够用
- 不做缓存预热 —— 冷启动靠 TTL 自然填满

## Decisions

### 1. 两层缓存，各自独立 TTL

**决策**：embedding 层（24h）和 result 层（30min）分开。embedding 比 result 长寿，因为 embedding 只依赖 query 文本 + 模型版本，而 result 依赖 query + filters + 数据。

**替代方案**：只缓存 result（含 embedding）。**不采用**——不同 filter 组合（同 query 不同 company）会重复触发 embed_texts，浪费编码。分两层让 embedding 跨 filter 复用。

### 2. 向量序列化：base64(float32 bytes)

**决策**：

```python
import base64, numpy as np
# encode
blob = base64.b64encode(qvec[0].astype(np.float32).tobytes()).decode("ascii")
# decode
arr = np.frombuffer(base64.b64decode(blob), dtype=np.float32)
```

float32 → bytes → float32 **无损往返**（bge-m3 输出本就是 float32）。1024 维 = 4096 bytes → base64 ≈ 5.5KB，Redis 存储无压力。

**替代方案**：JSON `[0.0123, -0.0456, ...]`。**不采用**——1024 个 float 的 JSON 约 12KB+，且 `json.loads` 后还要转 np.array，比 base64 慢且大。

### 3. 缓存 key 设计

```
il:search:embed:v{EMB_VER}:{sha256(q).hex()}              # embedding
il:search:result:v{EMB_VER}:{sha256(canonical_filters).hex()}  # result
```

- `EMB_VER` = `settings.embedding_model` 的稳定哈希或显式版本号。改模型时 bump → 旧 key 自然失效。当前用 `settings.embedding_model` 字符串本身做版本（bge-m3 路径变了 key 就变）。
- result 的 filters 用 `json.dumps({q, company, position, min_quality, limit}, sort_keys=True)` 再 sha256，保证 key 稳定且不受参数顺序影响。

### 4. 复用 `observability.get_redis()`，不自建客户端

**决策**：用 `from ..observability import get_redis`。它已是 async 单例 + `decode_responses=True`。

**注意**：`decode_responses=True` 意味着 `r.get()` 返回 str。embedding 的 base64 blob 是 ascii str ✅；result 的 JSON 是 str ✅。一致，无需额外处理。

### 5. 降级：B 层异常族，miss-through

**决策**：所有缓存读写包在 `try/except (aioredis.RedisError, ...)` 里，任何 Redis 故障 → 当作 miss，走原逻辑（embed + DB）。复用刚做完的异常分层模式：

```python
async def _embed_cache_get(key):
    try:
        r = get_redis()
        blob = await r.get(key)
        return np.frombuffer(base64.b64decode(blob), dtype=np.float32) if blob else None
    except (aioredis.RedisError, ValueError):  # ValueError: bad base64
        return None  # miss-through
```

`search_cache_enabled=False` 时完全跳过缓存（配置开关，调试用）。

### 6. 命中率指标复用现有 `incr_cache`

**决策**：embedding 命中/未命中、result 命中/未命中各调一次 `incr_cache(hit=bool)`。`il metrics` 的 cache_hit_rate 会自然反映搜索缓存效果。不新增单独指标——YAGNI，混在一起也能看出趋势。

## Risks / Trade-offs

- **[风险] 30min 内新增题目不出现** → 缓存命中时返回老结果。个人工具 + 每日爬取频率，可接受。若需更及时，调小 `search_result_ttl_seconds`。
- **[风险] 向量序列化损坏** → `_embed_cache_get` 捕获 `ValueError`（bad base64）当 miss，重新编码。不会返回错误数据。
- **[风险] filter 序列化不稳定** → 用 `json.dumps(sort_keys=True)` 保证 key 稳定。已覆盖。
- **[取舍] 不做主动失效** → 写入路径零耦合，但牺牲了时效性。30min TTL 是诚实的权衡。如果将来爬取变高频，再考虑 Crawler 写入后 `DELETE il:search:result:*`（用 SCAN，慢但低频）。
- **[取舍] embedding 版本用模型路径字符串** → 若模型文件原地更新（同路径不同权重），key 不变会返回老 embedding。bge-m3 实践中不会原地更新，可接受。若担心，加显式 `embedding_cache_version` 配置项手动 bump。
