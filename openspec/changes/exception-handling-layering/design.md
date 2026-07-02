## Context

InterviewLens 用 LangGraph 状态机跑 `Crawler → Cleaner → Extractor → Normalizer → Scorer` 流水线，离线还有 `aggregator` / `answerer` 两个批量任务。日志用 structlog（processors 已配 `StackInfoRenderer`，但全仓没人传 `exc_info=True`，所以栈从未被渲染）。可观测性（Langfuse trace + Redis 计数器）和缓存（Redis）被设计为"挂了不炸主流程"——这个降级意图是对的。

问题出在执行层：全仓 58 处 `except Exception`，44 处标 `# noqa: BLE001` 压制 ruff。它们模式雷同（`except Exception as exc: log.warning("x.y_failed", err=str(exc))`），把三类本该区别对待的异常一锅端了。

逐文件核查后，58 处可按**异常来源**归入四层：

| 层 | 文件 | 处数 | 当前行为 | 期望行为 |
|---|---|---|---|---|
| A 观测/降级 | observability.py, deepseek(LF span), graph, aggregator.gen, answerer.gen | ~22 | 吞+丢栈 | 吞+**留栈** |
| B 基础设施客户端 | llm/cache.py, deepseek(HTTP), tasks/pipeline(DLQ) | ~6 | 吞所有 | 收紧到异常族 |
| C 数据路径 | resolver, nodes/normalizer, aggregator.pair, answerer.llm, tab_crawler | ~8 | 吞所有（含 bug） | bug 冒泡，仅外部故障降级 |
| D 运维探针/legacy | routes_admin(health/jobs), api_discover | ~11 | 吞+丢栈 | 探针留栈；legacy 评估 |

（A+B+C+D 合计与 58 略有出入，因为部分文件跨层，最终以 tasks.md 逐条为准。）

## Goals / Non-Goals

**Goals:**

- 消灭"bug 伪装成降级"：数据路径（resolver/normalizer/aggregator/answerer）里的 `TypeError`/`AttributeError`/`KeyError` 等逻辑 bug 不再被 `except Exception` 吞掉，能冒泡到 DLQ 或上层
- 保留降级能力：observability、Langfuse span、缓存等基础设施层依然"挂了不炸主流程"
- 保留 traceback：所有保留宽捕获的地方，日志带完整栈（`exc_info=True`），不再只有一行 `err=str(exc)`
- 消除重复模板：44 处 `try/except Exception/log.warning(err=str(exc))` 收敛到一个 `swallow()` helper
- 对外行为不变：API 响应、pipeline 产出、缓存命中/未命中语义、DLQ 推送时机全部不变

**Non-Goals:**

- 不引入新的异常类型层级（不自定义 `InterviewLensError` 基类等）—— YAGNI，用 stdlib + 库自带的异常族即可
- 不改重试/熔断策略（那是 TODO Phase 3 的事）
- 不动 legacy `_legacy_discovery/api_discover.py` 的爬虫逻辑本身，只评估它的异常捕获是否该留
- 不改前端、不改 DB schema、不改 API 路由签名

## Decisions

### 1. 按异常来源分层，而非"逐个收紧"

**决策**：58 处分 A/B/C/D 四层，每层一个统一策略（见 Context 表）。逐个收紧会陷入"每处都要重新判断该捕获什么"的低效，且容易不一致。

**替代方案**：统一收紧成 `except (具体A, 具体B)`。**不采用**——observability 层确实需要宽捕获（Langfuse SDK 的异常类型不固定且无意义），强行收紧反而要 import 一堆不需要的类型。

### 2. 新增 `swallow()` helper 统一降级日志

**决策**：在 `src/interviewlens/errors.py` 新增：

```python
from contextlib import asynccontextmanager, contextmanager

@contextmanager
def swallow(event: str, **fields):
    """降级上下文：异常被吞掉并记录（带完整 traceback）。仅用于基础设施/观测层。"""
    try:
        yield
    except Exception:
        log.warning(event, **fields, exc_info=True)
```

A 层的 22 处 `try/except/log.warning(err=str(exc))` 改写为 `with swallow("metric.incr_cache_failed"):` 之类。统一带 `exc_info=True`。

**为什么是 contextmanager 不是装饰器**：这些 try 块包裹的是单段代码，不是整个函数；contextmanager 更贴合当前用法。

**替代方案**：每处手写 `exc_info=True`。**不采用**——44 处重复，且容易漏。

### 3. 数据路径层（C）：只捕获"外部故障"异常族

**决策**：以 `resolver.py:178` 为样板。当前：

```python
try:
    result = await call_tool(...)
    decision = result.arguments
except Exception as exc:  # noqa: BLE001
    log.warning("normalize.llm_failed", alias=alias, err=str(exc))
    decision = None
```

改为只捕获 LLM 调用可能抛的外部故障族（`httpx.HTTPError`、`RuntimeError` 来自 deepseek 的 "no tool call"/"Invalid JSON"、`asyncio.TimeoutError`），其余（`AttributeError`/`TypeError`/`KeyError`）冒泡：

```python
try:
    result = await call_tool(...)
    decision = result.arguments
except (httpx.HTTPError, asyncio.TimeoutError, RuntimeError) as exc:
    log.warning("normalize.llm_failed", alias=alias, exc_info=True)
    decision = None
```

`aggregator.pair_failed`、`answerer.llm_failed`、`nodes/normalizer` 同理。

**为什么 `RuntimeError` 算外部故障**：deepseek.py 在 "no tool call" / "Invalid JSON" 时主动 `raise RuntimeError`，这是 LLM 输出问题（外部），不是代码 bug。

**替代方案**：自定义 `LLMCallError`。**不采用**——增加类型层级，YAGNI。deepseek 已经用 `RuntimeError` 区分了，沿用即可。

### 4. tab_crawler 的 `except Exception: ... return []`

**决策**：`tab_crawler.py:101/161` 当前吞掉所有异常返回空。这是抓取层，网络/Playwright 故障确实是"外部"的，应捕获 `playwright.async_api.Error` + `httpx.HTTPError` + `asyncio.TimeoutError`，但 `AttributeError`（选择器写错）应冒泡——否则一个坏选择器会静默返回空数据，比直接报错更难发现。

### 5. observability 层（A）：保留宽捕获 + swallow

**决策**：observability 的 12 处保留 `except Exception`（Langfuse/Redis SDK 的异常类型不值得逐个 import），但全部走 `swallow()` 带栈。`# noqa: BLE001` 改为 `# noqa: BLE001  # observability: intentional broad catch`，明确标注"这是刻意的宽捕获"。

** Ponytail 注释规范**：所有保留宽捕获的地方用 `# ponytail:` 注释说明为何不收紧，例如 `# ponytail: broad catch ok — observability must not break the pipeline`。

### 6. routes_admin 的 health/jobs（D 层）

**决策**：health 端点本来就是"尽力探测各组件是否存活"，宽捕获 + 留栈是对的（探测 Redis 时连不上，就该报 `redis_ok=False`）。改用 `swallow()` 带栈即可，不收紧。jobs 端点同理（Celery inspect 可能超时）。

### 7. legacy api_discover.py

**决策**：这是 `_legacy_discovery/` 下的旧代码（被 tab_crawler 取代）。5 处异常中，`request_failed`/`fetch_error` 是爬取循环里的容错（保留），`wait_for_load_state`/`click` 的 `except Exception: pass` 是 UI 交互容错（保留但带栈）。**不投入精力重构逻辑**，只补 `exc_info` + `ponytail:` 注释标注"legacy, replaced by tab_crawler"。如果将来删 legacy 模块，这些一起走。

## Risks / Trade-offs

- **[风险] 收紧后原先被吞的 bug 开始冒泡，导致任务失败率上升** → 这是**期望行为**（暴露而非掩盖）。缓解：C 层改造分批进行，每改一个文件跑一次 `il resume` + 查 DLQ，确认没有大面积误伤。先改 `resolver.py`（单点、影响最大、最有示范价值），验证后再扩散。
- **[风险] `swallow()` 改变了日志字段名**（从 `err=str(exc)` 变成 structlog 的 `exc_info` 渲染） → 任何按 `err=` 字段 grep 日志的脚本会失效。缓解：`swallow()` 里同时保留 `error=str(exc)` 字段，向后兼容。
- **[取舍] 保留 observability 层宽捕获** → 理论上不如精确捕获"干净"，但 Langfuse SDK 的异常类型不固定，强行收紧是假精确。这是诚实的权衡。
- **[取舍] 不引入自定义异常基类** → 未来如果异常类型变多可能需要。但目前 58 处用 stdlib + 库异常族足够覆盖，YAGNI。
