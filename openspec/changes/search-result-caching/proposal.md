## Why

`GET /posts/search` 当前每次请求都做两件重复且昂贵的事：

1. **重算 query embedding**：`routes_search.py:32` 每次 `await embed_texts([q])`。bge-m3 CPU 编码单条约 30–50ms，但热门搜索词（"分布式锁""JVM GC""JVM 内存模型"）会被反复搜索——同一个 query 的 embedding 完全可复用，现在零缓存。
2. **重跑 HNSW 查询**：相同的 `(query, company, position, min_quality, limit)` 组合每次都直查 pgvector，结果在数据不变期间（仅爬取时才可能新增题目）完全一致。

两段都没有缓存。TODO 3.2 已识别此问题但未实现。这是读路径性能优化的最高 ROI 项：热门 query 命中后，响应从「编码+DB查询 ~50-150ms」降到「Redis 一次 GET ~1ms」。

## What Changes

在 `routes_search.py` 的 `search()` 加两层 Redis 缓存，复用已有的 async redis（`observability.get_redis()`）：

- **query embedding 缓存**：key = `il:search:embed:v{emb_ver}:{sha256(q)}`，value = 向量的紧凑序列化（base64 的 float32 bytes），TTL 24h。命中则跳过 `embed_texts`。
- **搜索结果缓存**：key = `il:search:result:v{emb_ver}:{sha256(q + filters)}`，value = 结果列表 JSON，TTL 30min。命中则直接返回，跳过 embedding + HNSW。

失效策略（渐进式，先做最小可行）：
- 纯 TTL 驱动。embedding 24h、result 30min。爬取新增题目后，老结果最多滞后 30min——对个人工具可接受。
- 不做主动 invalidate（避免在写入路径加耦合）。TODO 3.2 原设想"Crawler/Normalizer 写入时主动删 key"暂不做，YAGNI——30min TTL 足够。

降级：Redis 不可用时，缓存层全部 miss-through 到原逻辑（embed + DB），搜索功能不受影响。复用刚做完的异常分层——缓存读取走 B 层（捕获 `redis.RedisError`），不炸主流程。

## Capabilities

### Modified Capabilities

- `semantic-search`: `GET /posts/search` 在 embedding 计算和 HNSW 查询前各加一层 Redis 缓存。对外 API 契约（请求参数、响应结构、过滤语义）完全不变；仅响应延迟在缓存命中时下降。

### New Capabilities

无（不新增独立模块，缓存逻辑内联在路由里，复用现有 redis 基础设施）。

## Impact

- **改动文件**：
  - `src/interviewlens/api/routes_search.py`：`search()` 内加 embedding 缓存 + 结果缓存两层；新增 `_embed_cache_get/set`、`_result_cache_get/set` 辅助函数。
  - `src/interviewlens/config.py`：新增 `search_embed_ttl_seconds`（默认 86400）、`search_result_ttl_seconds`（默认 1800）、`search_cache_enabled`（默认 True，可关）。
- **复用**：`observability.get_redis()`（async redis 单例）、`embedding.embed_texts`、`hashlib.sha256`。
- **依赖**：无新依赖。向量序列化用 stdlib（`base64` + `numpy.tobytes`/`frombuffer`）。
- **观测**：缓存命中/未命中走现有 `incr_cache(hit/miss)` 计数器（已有，`il metrics` 可看命中率），不新增指标。
- **测试**：新增 `tests/test_search_cache.py`——验证 embedding 缓存命中跳过 embed_texts、结果缓存命中跳过 DB、Redis 故障时 miss-through、TTL/序列化正确性。用 monkeypatch 替换 embed_texts 和 session.execute，不依赖真实 Redis/pgvector（mock redis）。
- **风险**：向量 base64 序列化的精度（float32 → bytes → float32 无损 ✅）；缓存 key 的 filter 序列化稳定性。
