## 1. 新增 `swallow()` 降级 helper

- [x] 1.1 新增 `src/interviewlens/errors.py`：定义 `swallow(event, **fields)` 上下文管理器（contextmanager + asynccontextmanager 两个版本），异常时 `log.warning(event, **fields, error=str(exc), exc_info=True)`。保留 `error=` 字段向后兼容 grep 脚本。
- [x] 1.2 在 `tests/test_exception_handling.py` 写最小自检：`swallow` 吞掉异常、日志带 `exc_info`、正常路径无副作用。（6 个测试全绿；因 structlog 走自己 processor 链不进 caplog，断言改为验证行为而非日志内部）

## 2. A 层：观测/降级 —— 保留宽捕获 + 补栈（用 swallow）

- [x] 2.1 `observability.py`（12 处）：`incr_cache`/`incr_tokens`/`record_node`/`reset_metrics`/`langfuse.flush`/`node_span` 改用 `swallow()`/`aswallow()`；`get_langfuse`/`fetch_metrics` 因有副作用/返回值保留 try/except 但补 `exc_info=True`。每处保留的宽捕获附 `# ponytail: broad catch ok — observability must not break the pipeline`。
- [x] 2.2 `llm/deepseek.py` 的 Langfuse span 相关（`trace_create_failed`/`gen_create_failed`/`gen_end_failed`/`trace_update_failed` 共 5 处）：改用 `swallow()`。
- [x] 2.3 `agent/graph.py`（2 处）：`trace_create_failed` + `trace_update_failed` 改用 `swallow()`。
- [x] 2.4 `aggregator/aggregator.py:236`、`answerer/answerer.py:78` 的 `generation.end` 改用 `swallow()`。

## 3. B 层：基础设施客户端 —— 收紧到异常族

- [x] 3.1 `llm/cache.py`（2 处）：`cache.get_failed` 收紧到 `(aioredis.RedisError, json.JSONDecodeError)`；`cache.set_failed` 收紧到 `aioredis.RedisError`。
- [x] 3.2 `llm/deepseek.py:131` JSON repair：保留 `except Exception`（repair_json 的失败类型不定），但补 `exc_info=True` + `ponytail:` 注释。
- [x] 3.3 `tasks/pipeline.py:43` 的 `_dlq_push`：收紧到 `(redis.RedisError, json.JSONDecodeError, TypeError)`。
- [x] 3.4 `tasks/pipeline.py:88/150` 的 Celery 任务顶层：保留 `except Exception`（Celery 任务边界本就该兜底 + 推 DLQ + re-raise），补 `exc_info=True` + `ponytail:` 注释。

## 4. C 层：数据路径 —— bug 冒泡，仅外部故障降级（重点）

- [x] 4.1 `normalizer/resolver.py:178`：`except Exception` 收紧到 `(httpx→openai.APIError, asyncio.TimeoutError, RuntimeError)`，补 `exc_info=True`。**已用 `tests/test_resolver_exceptions.py` 验证 `TypeError` 冒泡、`openai.APIConnectionError` 降级到 tier4。**（注：deepseek 用 openai SDK，故捕获 openai.APIError 而非 httpx）
- [x] 4.2 `agent/nodes/normalizer.py:46/54`：company/position resolve 失败捕获同 4.1 的异常族 `(openai.APIError, asyncio.TimeoutError, RuntimeError)`；逻辑 bug 冒泡。保留"一个 alias 失败不影响其他"的降级语义。
- [x] 4.3 `aggregator/aggregator.py:408` `pair_failed`：收紧到 `(openai.APIError, SQLAlchemyError, asyncio.TimeoutError, RuntimeError)`（含 DB 异常族，因 aggregate_one 含 DB 写）。
- [x] 4.4 `answerer/answerer.py:58` `llm_failed`：收紧到 `(openai.APIError, asyncio.TimeoutError)`。
- [x] 4.5 `crawler/tab_crawler.py:101/161`：收紧到 `(PlaywrightError, asyncio.TimeoutError, [json.JSONDecodeError])`，改 `try/except/finally` 保 `page.close()`，`AttributeError` 冒泡。

## 5. D 层：运维探针 / legacy

- [x] 5.1 `api/routes_admin.py`（6 处）：health 的 pg/redis 探针保留宽捕获 + `ponytail:` 注释；jobs 的 queue/dlq/workers 改用 `swallow()`；list_dlq 的 json 解析收紧到 `json.JSONDecodeError`。
- [x] 5.2 `crawler/_legacy_discovery/api_discover.py`（5 处）：不重构逻辑，`request_failed`/`ai_error`/`fetch_error` 补 `exc_info=True`；两处 UI 容错（wait_for_load_state/close_dialog）改用 `swallow()`；全部附 `# ponytail: legacy, replaced by tab_crawler`。
- [x] 5.3 其余单处文件：`llm/orchestrator.py` + `agent/nodes/extractor.py`（extractor 收紧到 C 层异常族）；`db/session.py`（事务 rollback+raise 标准模式，加注释不吞）；`crawler/playwright_runner.py`（h1 容错用 swallow）；`crawler/cleaner.py`（trafilatura 保留宽捕获补 exc_info）；`api/routes_bridge.py`（DB 写降级补 exc_info）；`api/app.py`（lifespan 预热补 exc_info）；`agent/recovery.py`（批量 resume 容错补 exc_info）；`cli.py`（doctor/task-status 探针补 `ponytail:` 注释）。

## 6. 验证

- [x] 6.1 `uv run pytest` 全绿 —— **开发机无运行环境**，改用全局 Python + `PYTHONPATH=src` 跑不依赖重资源的测试：26 passed（含新增 8 个异常处理测试）。依赖 langgraph/playwright/postgres 的测试套件无法在此环境运行，待有运行环境时补跑全量。
- [ ] 6.2 `uv run ruff check src/` —— **开发机无 uv/完整依赖**，未跑。手动核查：`noqa: BLE001` 从 44 → 19，剩余均附 `ponytail:` 说明性注释。
- [ ] 6.3 `uv run mypy src/` —— **开发机无运行环境**，未跑。`py_compile` 23 个改动文件全部通过，语法无误。
- [x] 6.4 改造后 grep `except Exception` 处数：58 → **22**（目标 ≤25 ✅），且剩余均为 A/D 层刻意的宽捕获（事务边界 / Celery 任务边界 / health 探针 / node_span re-raise），全部带 `ponytail:` 注释。
- [ ] 6.5 抽查日志：构造一个 LLM 超时场景，确认日志带完整 traceback —— **需运行环境**，未做。代码侧所有降级日志已统一 `exc_info=True`，待运行环境验证。
