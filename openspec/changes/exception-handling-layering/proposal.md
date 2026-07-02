## Why

当前代码库有 58 处 `except Exception`（其中 44 处用 `# noqa: BLE001` 主动压制了 ruff 的"捕获过宽"警告）。问题不在"降级"本身——observability 挂了不该炸主流程，降级是对的；问题在 **58 处一刀切、模式雷同**，没有区分三类异常：

1. **基础设施降级**（Langfuse / Redis 偶发故障）—— 应吞掉 + 降级，但当前丢了 traceback
2. **可预期的业务异常**（JSON 解析失败、HTTP 超时、asyncpg 死锁）—— 应精确捕获具体类型
3. **真 bug**（`AttributeError` / `TypeError` / `KeyError`）—— 当前也被一并吞掉，假装成"降级"

两个具体危害：

- **traceback 丢失**：几乎所有 `except Exception as exc` 都只 `log.warning(..., err=str(exc))`，把异常压成一行字符串。structlog 的 processors 里已经配了 `StackInfoRenderer`，但没人传 `exc_info=True`，所以栈信息从未被记录。生产排查时只知道"哪挂了"，不知道"为什么、在哪一行"。
- **bug 伪装成降级**：例如 `resolver.py:178` 的 LLM 调用失败被 `except Exception` 兜住后走 tier4 建新 canonical。如果一个 `TypeError`（代码 bug）混在里面，会静默地往数据库塞重复 canonical 公司名，日志只显示 `normalize.llm_failed`，数据脏了都不知道。

## What Changes

按**异常来源分层**重写这 58 处捕获，而非"逐个收紧"：

- **A. 观测/降级层**（observability.py、deepseek.py 的 Langfuse span、aggregator/answerer 的 generation.end）：保留宽捕获（这些确实"挂了无所谓"），但统一补 `exc_info=True` 留栈，并抽取一个 `_swallow` helper 消除重复模板。
- **B. 基础设施客户端层**（llm/cache.py、deepseek.py 的 HTTP 调用、tasks/pipeline.py 的 DLQ push）：把 `except Exception` 收紧成具体异常族（`redis.RedisError`、`httpx.HTTPError`、`json.JSONDecodeError`），让真 bug 冒泡。
- **C. 数据路径层**（resolver.py、agent/nodes/normalizer.py、aggregator.py 的 pair_failed、answerer.py 的 llm_failed）：区分"外部依赖故障"（降级）和"逻辑 bug"（冒泡）。resolver 的 LLM 失败只捕获 HTTP/超时族，`TypeError` 等不再被吞。
- **D. CLI/运维探针层**（routes_admin.py 的 health/jobs、api_discover.py 的 legacy 爬虫）：health 端点本就是"尽力探测"，保留宽捕获但补栈；legacy 爬虫单独评估。
- **新增辅助**：`logging.py` 或新模块加一个 `swallow(context, exc_info=True)` 上下文管理器，统一降级日志格式，消灭 44 处重复的 `try/except/log.warning` 模板。

## Capabilities

### Modified Capabilities

- `error-handling`: 异常处理从"无差别宽捕获 + 丢栈"升级为"按层分流 + 保留 traceback + 真 bug 冒泡"。不改任何对外行为（API 响应、pipeline 产出、缓存语义全部不变），只改异常如何被捕获、记录、传播。

### New Capabilities

无。

## Impact

- **改动的模块**（按 58 处分布）：
  - `src/interviewlens/observability.py`（12 处，A 层）
  - `src/interviewlens/llm/deepseek.py`（7 处，A+B 层混合）
  - `src/interviewlens/api/routes_admin.py`（6 处，D 层）
  - `src/interviewlens/crawler/_legacy_discovery/api_discover.py`（5 处，D 层，legacy）
  - `src/interviewlens/tasks/pipeline.py`（3 处，B 层）
  - `src/interviewlens/llm/cache.py`（2 处，B 层）
  - `src/interviewlens/crawler/tab_crawler.py`（2 处，C 层）
  - `src/interviewlens/answerer/answerer.py`（2 处，C 层）
  - `src/interviewlens/aggregator/aggregator.py`（2 处，C 层）
  - `src/interviewlens/agent/nodes/normalizer.py`（2 处，C 层）
  - `src/interviewlens/agent/graph.py`（2 处，A 层）
  - `src/interviewlens/normalizer/resolver.py`（1 处，C 层，重点）
  - `src/interviewlens/llm/orchestrator.py`、`db/session.py`、`crawler/playwright_runner.py`、`crawler/job_list_crawler.py`、`crawler/cleaner.py`、`api/routes_bridge.py`、`api/app.py`、`agent/recovery.py`、`agent/nodes/extractor.py`（各 1 处，逐个归类）
- **新增**：`src/interviewlens/errors.py`（或挂到 `logging.py`）—— `swallow()` 降级 helper
- **依赖**：无新依赖，复用 structlog 已有的 `StackInfoRenderer`
- **测试**：新增 `tests/test_exception_handling.py`，验证三层行为：降级层留栈、客户端层捕获具体异常族、数据路径层的 bug 能冒泡
- **风险**：收紧捕获后，原先被静默吞掉的 bug 可能开始冒泡并导致任务失败。这是**期望行为**（暴露而非掩盖），但需配合 DLQ 验证不产生大面积误伤
