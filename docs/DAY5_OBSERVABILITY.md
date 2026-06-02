# Day 5 — 可观测性（Langfuse trace + 缓存命中率 + token 成本）

> 目标：把每次 graph 跑变成"可解剖"的 trace；用 Redis 计数把缓存命中率和钱花在哪一目了然。

## 0. 这一步带来什么

| 之前 | 现在 |
|---|---|
| 只有 LLM 一个 generation span | 每节点都有 span，能看耗时分布 |
| 不知道缓存命中率 | `il metrics` 一行查 |
| 不知道 token 总花费 | 累计统计 + 按 DeepSeek 价格估 ¥ |
| Langfuse trace 各跑各的 | 整个 pipeline 一个 trace，三节点挂下面 |

## 1. 启用 Langfuse

```bash
# 1. 容器已在 D1 起好，访问 http://localhost:3001 注册账号
# 2. 创建一个 project（名字随意）
# 3. Settings → API Keys → 新建一对 key
# 4. 把 pk-xxx / sk-xxx 填到 .env：
LANGFUSE_PUBLIC_KEY=pk-...
LANGFUSE_SECRET_KEY=sk-...
LANGFUSE_HOST=http://localhost:3001
```

未配置也没关系：所有 trace 调用静默跳过，pipeline 照跑不误。

## 2. 跑一次 graph，看 trace

```bash
uv run il graph "https://www.nowcoder.com/discuss/<id>"
```

打开 http://localhost:3001 → Tracing：能看到一条 `il.pipeline` trace，展开后是：
```
il.pipeline                   2.3s
├── crawler                  1100ms
├── cleaner                    50ms
└── extractor                1150ms
    └── deepseek.tool_call   1100ms  in:1500 out:480
```

每个节点 span 带 `input` 元数据（URL、html 字节数、cleaned 字符数等），LLM generation 还带完整 messages + 输出 + token usage。

## 3. 看缓存命中率与花费

```bash
uv run il metrics
```

输出三张表：
- **LLM cache**：hits / misses / total / hit_rate
- **Tokens & cost**：prompt / completion / total + 估算 ¥（默认 DeepSeek-V3 1元/2元 per million）
- **Per-node latency**：每个节点跑了多少次、平均 ms

调价：
```bash
uv run il metrics --price-in 1.5 --price-out 3.0
```

## 4. 重置统计

```bash
uv run il metrics-reset
```

适合阶段性对比（例如调 prompt 前后的 token 差异）。

## 5. 实战玩法

**一晚跑 100 篇看命中率**
```bash
for url in $(your_url_list.txt); do
  uv run il graph "$url"
done
uv run il metrics
```

第一晚会看到 hit_rate=0%（全 miss），第二天再跑应该接近 100%（同一 URL 全命中缓存）。

**调 prompt 前后对比**
```bash
uv run il metrics-reset
# 跑 50 篇
uv run il batch ...
uv run il metrics > before.txt

# 改 EXTRACT_PROMPT_VERSION=2，再跑 50 篇
uv run il metrics > after.txt
diff before.txt after.txt
```

**找瓶颈节点**
看 `Per-node latency` 表，如果 crawler 平均 5000ms 远高于其他，说明 Playwright 启动慢或网慢；如果 extractor 慢，可能是 DeepSeek 排队。

## 6. 设计要点（面试讲故事）

- **trace 在 graph 顶层创建，节点接收 trace 参数**：所有 span 同 trace_id，Web UI 一棵树展开看，不用拼 trace_id
- **Langfuse 软依赖**：缺 SDK / 缺 key / Web 挂了 → 全部静默 no-op，不影响业务
- **node_span context manager**：把 Langfuse span + Redis duration 打点合并进同一个 with 块，节点代码只多一行
- **cost 估算单独一个方法**：未来要按月份/项目分账时直接复用
- **metrics 走 Redis 不走数据库**：高频写入不污染 PG；用 INCR/HINCRBY 原子操作避免竞争

## 7. 验收清单

- [ ] `il graph <url>` 跑完，Langfuse Web UI 能看到一条 `il.pipeline` trace 含 3 个 node span
- [ ] `il metrics` 显示 hit / miss 总数和 token 总数
- [ ] 重复跑同一 URL，hit_rate 接近 100%
- [ ] `il metrics-reset` 后再 `il metrics` 显示全 0
- [ ] `pytest tests/test_metrics.py -v` 全绿

## 8. 下一步（D6 预告）

D6 加 Normalizer 节点：公司/岗位归一化（alias_dict 直查 → bge-m3 embedding 相似度 → LLM 兜底自学习）。
