# search-cache specification

## Purpose

为 `GET /posts/search` 增加 Redis 两层缓存（query embedding + 完整结果），消除热门 query 的重复编码和重复 HNSW 查询。对外 API 契约不变。

## Cache Layers

### Layer 1 — Query Embedding Cache

- **Key**: `il:search:embed:v{EMB_VER}:{sha256(q).hex()}`
- **Value**: `base64(float32 bytes)` of the 1024-dim vector
- **TTL**: `search_embed_ttl_seconds` (default 86400 = 24h)
- **Scope**: only depends on query text + embedding model version; shared across all filter combinations

### Layer 2 — Search Result Cache

- **Key**: `il:search:result:v{EMB_VER}:{sha256(canonical_filters).hex()}`
  - `canonical_filters = json.dumps({q, company, position, min_quality, limit}, sort_keys=True)`
- **Value**: JSON array of `QuestionOut` dicts
- **TTL**: `search_result_ttl_seconds` (default 1800 = 30min)
- **Scope**: full query + filters

`EMB_VER` = `settings.embedding_model` (the model id/path). Changing the model invalidates all keys.

## Behavioral Requirements

### REQ-1: Embedding cache reuses across filters

Same query text with different `company`/`position`/`min_quality`/`limit` hits the embedding cache once; `embed_texts` is called at most once per query text per TTL window.

### REQ-2: Result cache short-circuits embed + DB

A result-cache hit returns immediately without calling `embed_texts` or executing the HNSW SQL.

### REQ-3: Redis failure is transparent (miss-through)

Any `redis.RedisError` (connection lost, timeout) or deserialization error (`ValueError` on bad base64, `json.JSONDecodeError`) in cache read/write → treated as miss → falls through to the original embed + DB path. The search endpoint never returns an error due to cache failure.

### REQ-4: No API contract change

Request parameters, response shape (`list[QuestionOut]`), filter semantics, ordering — all identical with and without cache. The cache is purely a latency optimization.

### REQ-5: Cache can be disabled

`settings.search_cache_enabled = False` skips all cache reads/writes; the endpoint behaves exactly as before this change.

### REQ-6: Hit/miss counted in existing metrics

Each layer's hit and miss calls `observability.incr_cache(hit=bool)`. `il metrics` cache_hit_rate reflects search cache effectiveness. No new metric keys.

### REQ-7: Vector round-trip is lossless

float32 → bytes → base64 → bytes → float32 reproduces the original vector bit-for-bit. No precision loss in the cached embedding.

## Constraints

- No new runtime dependencies. Vector serialization uses stdlib (`base64`) + `numpy`.
- Reuse `observability.get_redis()` (async singleton, `decode_responses=True`).
- No active invalidation on the write path — TTL only.
- Cache read/write exception handling follows the Layer B pattern from `exception-handling-layering` (catch concrete exception families, miss-through).
