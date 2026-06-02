# Day 4 — LangGraph 状态机串联

> 目标：把 D2 + D3 的散装代码升级成显式状态机，支持断点续跑、节点级日志、未来易扩展。

## 0. 这一步带来什么

| 之前（D2/D3） | 现在（D4） |
|---|---|
| `crawl_one()` + `extract_post()` 两段函数手动拼 | LangGraph StateGraph 自动调度 |
| 失败要手写脚本扫库重试 | `il resume` 一行命令重跑所有 failed/pending |
| 看哪步死了要翻 log | `current_node` 字段 + 节点级 structlog event |
| 加新节点要改胶水代码 | `add_node` + `add_edge` 一行接进来 |

## 1. 跑一遍

```bash
# 推荐：一键跑（D4 主入口）
uv run il graph "https://www.nowcoder.com/discuss/<id>"

# 第一次调试可以 headful + 不复用旧数据
uv run il graph "https://www.nowcoder.com/discuss/<id>" --no-headless --no-reuse
```

输出含：post_id / title / chars / cache_hit / token 用量；skip 时 yellow Panel；error 时 red Panel。

## 2. 复用机制

`il graph` 默认 `reuse_existing=True`：如果 URL 在库里已经 `cleaned_text` 非空，直接跳过 Crawler+Cleaner，从 Extractor 开始。
- 想强制重抓 HTML：`--no-reuse`
- 想强制重抽 LLM：`--no-cache`（清掉 Redis 那条）

## 3. 断点续跑

```bash
# 把 extract_status 是 failed / pending 的 post 全部重跑一遍（默认 50 条）
uv run il resume

# 只跑 failed
uv run il resume --statuses failed --limit 100

# 强制不走 LLM 缓存
uv run il resume --no-cache
```

`il resume` 共用一个 Playwright 浏览器实例，省去每条 URL 启动浏览器的 1-2 秒开销。

## 4. 节点级日志查看

```bash
LOG_LEVEL=DEBUG uv run il graph <url>
```

每节点发两条事件：
- `node.start node=crawler post_id=...`
- `node.done  node=crawler post_id=... bytes=...`

skip / failed 路径有专门 event：
- `node.crawler.reuse`（命中已有数据）
- `node.cleaner.skipped_short`（清洗后太短）
- `node.extractor.failed`（LLM 异常）

## 5. 路由规则

```
START → crawl → clean ┬→ extract → END
                      └→ END (when skip_reason set)
```

唯一的条件分支在 cleaner 之后：cleaned_text < 200 字 → 直接终止。
extractor 内部失败时不抛异常出 graph，而是把 `skip_reason='extract_failed'` 写进 state，让上层 CLI 决定 exit code。

## 6. SQL 验证状态机正常推进

```sql
-- 各状态分布
SELECT extract_status, COUNT(*) FROM posts GROUP BY extract_status;

-- 看最近一条失败的 post 错在哪
SELECT id, extract_status, extract_error, extract_version
FROM posts
WHERE extract_status = 'failed'
ORDER BY fetched_at DESC LIMIT 5;
```

## 7. 验收清单

- [ ] `il graph <url>` 输出 graph result 表，post_id 非空
- [ ] 重复跑 `il graph <同一 url>` 命中 reuse + cache_hit=yes
- [ ] 故意停 docker postgres 后跑 graph，应看到 errors 字段
- [ ] 把某条 post 的 extract_status 手动改成 'failed'，跑 `il resume`，看到该条被重跑
- [ ] `pytest tests/test_graph_routing.py -v` 全绿

## 8. 设计要点（面试讲故事用）

- **TypedDict + total=False**：每节点只写自己的 key，LangGraph 自动浅合并，避免节点之间互踩
- **节点纯函数**：`(state) -> partial state`，不在节点内做 side effect 之外的状态转移
- **复用 fetcher**：在 graph 外创建 Playwright，注入到节点，避免单机一晚启 1000 次浏览器
- **断点续跑用 DB 状态而非 LangGraph checkpoint**：业务级幂等比框架级 checkpoint 更可靠（Redis/容器掉了状态也不丢）
- **路由函数是普通 Python**：易测试、易解释，不用 LCEL 那套 DSL

## 9. 下一步（D5 预告）

D5：接 Langfuse + 加每节点 trace span，给 LLM 调用打 prompt/response/usage 详细记录；
启 Redis 缓存仪表（命中率统计）。然后 D6 才是 Normalizer 节点。
