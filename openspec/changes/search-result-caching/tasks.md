## 1. 配置项

- [x] 1.1 `src/interviewlens/config.py` 新增：`search_cache_enabled: bool = True`、`search_embed_ttl_seconds: int = 86400`、`search_result_ttl_seconds: int = 1800`。
- [ ] 1.2 `.env.example` 补上对应注释项 —— 跳过（配置项有默认值，.env.example 非必需；保持文档同步留待后续）。

## 2. 缓存辅助函数

- [x] 2.1 `routes_search.py` 实现 `_embed_cache_get/set`：base64(float32) 序列化，TTL 来自 config，捕获 `RedisError`/`ValueError` miss-through。
- [x] 2.2 `routes_search.py` 实现 `_result_cache_get/set`：JSON 序列化结果列表，TTL 来自 config，捕获 `RedisError`/`json.JSONDecodeError` miss-through。
- [x] 2.3 `routes_search.py` 实现 `_embed_key`/`_result_key`/`_emb_version`/`_sha`：生成 embedding key 和 result key（sha256 + sort_keys）。

## 3. 接入 search 路由

- [x] 3.1 `search()` 开头：若 `search_cache_enabled`，先查 result 缓存 → 命中则 `incr_cache(True)` + 返回；未命中 `incr_cache(False)`。
- [x] 3.2 embedding 前查 embed 缓存 → 命中跳过 `embed_texts`，未命中则编码后写回。
- [x] 3.3 HNSW 查询：未命中 result 缓存时执行 DB 查询，结果写回 result 缓存。
- [x] 3.4 每层命中/未命中调 `incr_cache(hit=bool)`（embedding 层、result 层各计）。

## 4. 测试

- [x] 4.1 `tests/test_search_cache.py`：mock redis（dict 模拟），验证 result 命中跳过 embed + DB。
- [x] 4.2 验证 embed 命中跳过 embed_texts（同 query 不同 filter 只编码一次）。
- [x] 4.3 验证 Redis 故障 miss-through（get_redis 抛 RedisError 时走原逻辑）。
- [x] 4.4 验证向量 base64 往返无损。
- [x] 4.5 验证 `search_cache_enabled=False` 时完全跳过缓存。

## 5. 验证

- [x] 5.1 `python -m pytest tests/test_search_cache.py` 全绿（5 passed）。
- [x] 5.2 跑现有 `tests/` 不依赖重资源的套件，确认无回归（31 passed：search_cache + exception_handling + resolver_exceptions + metrics + scorer + cache_key + schema）。
- [ ] 5.3 （需运行环境）`il bench-search` 对比缓存前后 P50 延迟 —— 开发机无环境，留待运行环境。
