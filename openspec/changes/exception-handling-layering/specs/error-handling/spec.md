# error-handling specification

## Purpose

定义 InterviewLens 全仓异常捕获、记录、传播的分层规则。目标：降级能力不丢，但 bug 不再被伪装成降级，且所有降级日志保留 traceback。

## Layers

异常处理按**异常来源**分四层，每层一个统一策略。

### Layer A — Observability / Degradation

观测与降级路径（Langfuse trace/span、Redis 计数器、generation.end）。这些组件"挂了不该炸主流程"。

- **策略**：保留 `except Exception` 宽捕获，但必须带 `exc_info=True` 保留栈。
- **实现**：统一用 `errors.swallow(event, **fields)` 上下文管理器，禁止再手写 `try/except/log.warning(err=str(exc))`。
- **标注**：每处保留的宽捕获附 `# ponytail: broad catch ok — observability must not break the pipeline`。

### Layer B — Infrastructure Clients

基础设施客户端（Redis 缓存、DeepSeek HTTP、Celery DLQ push）。

- **策略**：`except Exception` 收紧到具体异常族：
  - Redis：`redis.RedisError`（+ `json.JSONDecodeError` 给读路径）
  - DeepSeek HTTP：`httpx.HTTPError`、`asyncio.TimeoutError`
  - Celery 任务顶层边界：保留 `except Exception`（任务边界本就该兜底 + 推 DLQ），但补 `exc_info=True`
- 真 bug（`AttributeError`/`TypeError`/`KeyError`）冒泡。

### Layer C — Data Paths

数据路径（resolver、normalizer node、aggregator pair、answerer、tab_crawler）。这是"bug 伪装成降级"风险最高的层。

- **策略**：只捕获"外部故障"异常族：
  - LLM 调用：`(httpx.HTTPError, asyncio.TimeoutError, RuntimeError)`（`RuntimeError` 来自 deepseek 的 "no tool call"/"Invalid JSON"，属外部输入问题）
  - 抓取：`(playwright.async_api.Error, httpx.HTTPError, asyncio.TimeoutError)`
- **关键**：`TypeError`/`AttributeError`/`KeyError` 等逻辑 bug **必须冒泡**，不降级。
- 降级时仍保留"一个失败不影响其他"的语义（如 normalizer node 里一个 alias 失败继续处理下一个），但限定到外部故障。

### Layer D — Ops Probes / Legacy

运维探针（health/jobs/dlq 端点）和 legacy 爬虫。

- **策略**：探针本就是"尽力探测"，保留宽捕获 + `swallow()` 带栈。legacy 模块不重构逻辑，只补 `exc_info` + 标注 `# ponytail: legacy, replaced by tab_crawler`。

## The `swallow()` helper

```python
# src/interviewlens/errors.py
from contextlib import asynccontextmanager, contextmanager
from .logging import log

@contextmanager
def swallow(event: str, **fields):
    """Swallow an exception, log it WITH traceback. Infrastructure/observability only."""
    try:
        yield
    except Exception:
        log.warning(event, **fields, error=..., exc_info=True)

@asynccontextmanager
async def aswallow(event: str, **fields):
    """Async variant."""
    try:
        yield
    except Exception:
        log.warning(event, **fields, error=..., exc_info=True)
```

- 保留 `error=str(exc)` 字段向后兼容现有 grep 脚本。
- **只用于 A/D 层**。B/C 层用具体异常族，不用 `swallow`。

## Behavioral Requirements

### REQ-1: Traceback preserved on all degradation

任何被吞掉的异常，日志必须包含完整 traceback（structlog 的 `exc_info=True`）。不再出现只有 `err=str(exc)` 单行的降级日志。

### REQ-2: Logic bugs surface in data paths

在 Layer C（resolver/normalizer/aggregator/answerer/tab_crawler）中，`TypeError`、`AttributeError`、`KeyError` 等逻辑 bug 不被捕获，冒泡到 Celery 任务边界 → 进入 DLQ，而非静默降级。

### REQ-3: External degradation still degrades

LLM 超时、Redis 断连、Playwright 网络错误等外部故障，依然走降级路径（返回 None / 空列表 / 跳过该 alias），主流程不中断。

### REQ-4: No behavior change to external surface

API 响应结构、pipeline 最终产出、缓存命中/未命中语义、DLQ 推送时机——全部不变。本规格只改异常如何被捕获/记录/传播。

### REQ-5: Broad catches are annotated

任何保留 `except Exception` 的地方（A/D 层），必须附 `# ponytail:` 注释说明为何不收紧。`# noqa: BLE001` 保留但搭配说明性注释。

## Constraints

- 不引入自定义异常基类（YAGNI）。
- 不改重试/熔断策略。
- 不改 DB schema、API 路由签名、前端。
- 无新运行时依赖。
