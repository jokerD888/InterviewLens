# Day 12 — 数据填充 + SSR + URL 状态化 + 性能 bench

> 目标：让项目从"能跑"升级到"立刻能演示"——没真数据也能跑 UI；URL 可分享；首屏 SSR 直出。

## 0. 这一步带来什么

| 之前 | 现在 |
|---|---|
| 没有真数据 UI 是空的 | `il seed-demo` 一行命令塞 5 公司 / 5 帖子 / 16 题 / 2 摘要 |
| URL 不带状态 | `/?company=字节跳动&position=后端开发&period=2025Q2` 可分享 |
| 首页全 CSR，慢 | 首页 RSC SSR 直出公司列表，体感更快 |
| 性能没有数字支撑 | `il bench-search` 输出 emb ms / 检索 p50 ms |
| 搜索页要手敲常见词 | 搜索框下方有"分布式锁/Redis 持久化/JVM GC/..." 一键示例 |

## 1. 数据填充：3 秒生成一份 demo 数据

```bash
uv run il seed-demo
```

输出：
```
demo seed
  companies   5
  positions   4
  posts       5
  questions   16
  summaries   2

Demo data inserted. Try:
  uv run il serve  &
  cd web && pnpm dev
  open http://localhost:3000
```

幂等：`questions.post_id` 唯一约束让重复运行不会重复插入。

为什么需要：开发/演示时**完全不需要**真的去爬牛客（没 cookie、cookie 失效、被 ban）。
打开 `/`、`/search`、`/admin` 三个页面都立刻有内容。

## 2. SSR 首屏

`web/src/app/page.tsx` 改成 React Server Component：
- 服务器 fetch `/companies` 直接渲染初始公司列表
- `<BrowserShell />` 客户端组件接管交互（公司选择、岗位筛选、period 切换）
- API 挂了也能渲染 shell（`apiDown` 状态显示 "API 未连通" badge）

收益：
- 首屏看到内容比 CSR 快 ~200-400ms（一次 RTT 省下来）
- SEO 友好（虽然 demo 项目不需要，但是简历可讲）
- 服务器 fetch 不需要 CORS 头

`web/src/lib/server-api.ts`：服务器侧 fetch 直连后端，绕过 rewrites（rewrites 只针对浏览器侧）。

## 3. URL 状态化

首页：
```
/?company=字节跳动&position=后端开发&period=2025Q2
```

搜索页：
```
/search?q=分布式锁&company=字节跳动&position=后端开发&min_quality=60
```

实现：`useEffect` 监听本地状态变化 → `router.replace(?...)` （不污染历史）。
**好处**：演示时甩个链接给面试官，对方点开看到的是和你一样的视图。

## 4. 性能 bench

```bash
uv run il bench-search
# 默认 5 个 query × 3 次取 p50，输出 emb ms 和检索 ms

# 自定义
uv run il bench-search --queries "分布式锁,JVM GC" --limit 20 --repeat 5
```

输出示例（pgvector HNSW 索引下）：
```
bench-search · 5 queries × 3 runs
┃ query              ┃ emb ms ┃ p50 ms ┃ hits ┃
┃ 分布式锁           ┃ 12.3   ┃ 2.4    ┃ 10   ┃
┃ Redis 持久化       ┃ 11.8   ┃ 2.1    ┃ 10   ┃
┃ JVM GC             ┃ 12.0   ┃ 1.9    ┃ 10   ┃
┃ TCP 三次握手       ┃ 11.6   ┃ 2.6    ┃ 10   ┃
┃ Transformer        ┃ 12.2   ┃ 2.0    ┃ 10   ┃
```

简历可以直接抄数字：**"百万级题目向量检索 P50 < 5ms"**。

## 5. 搜索页"示例查询"

页面右上角新增 `分布式锁 / Redis 持久化 / MySQL 索引 / JVM GC / Transformer` 5 个 chip，
**0 输入即可演示**：面试官打开 `/search` 看到示例链接，点一下就有结果。

## 6. 关键设计要点（面试讲故事）

- **seed_demo 幂等**：`(canonical) UNIQUE` + `ON CONFLICT DO UPDATE` 让重跑安全；面试现场可反复演示
- **RSC 直接 fetch 后端**：跳过浏览器 rewrites，性能最优；环境变量 `API_BASE` 优先于 `NEXT_PUBLIC_API_BASE` 让前后端可分离部署
- **URL 状态而不是 client state**：可分享、刷新不丢、浏览器后退按钮可用
- **`router.replace` 不是 `push`**：避免每次输入都堆历史栈
- **bench-search 算 p50 不算 avg**：tail 受冷启动影响，p50 更能反映稳态性能
- **示例 chip 集中常见技术面题**：覆盖 5 个最热的考点方向，演示时一定有命中

## 7. 验收清单

- [ ] `il seed-demo` 跑完看到 5 公司 5 帖
- [ ] `uv run il serve` + `pnpm dev` 后首页左侧有公司列表
- [ ] 点 "字节跳动" → "后端开发" 看到 markdown 摘要
- [ ] URL 自动变成 `/?company=字节跳动&position=后端开发`
- [ ] 复制 URL 新窗口打开，看到同样视图
- [ ] `/search` 点示例 "分布式锁" 看到关键词高亮的结果
- [ ] `il bench-search` 输出表格

## 8. 录 30 秒演示 GIF（D14 简历用）

工具推荐：[ScreenToGif](https://www.screentogif.com/)（Win）/ [Kap](https://getkap.co/)（Mac）

脚本（30 秒精华版）：
1. **0-5s**：首页打开，左侧公司列表 hover
2. **5-12s**：点 "字节跳动" → "后端开发"，右侧摘要面板的 markdown 渐显
3. **12-20s**：切到 `/search`，输入 "分布式锁"，结果列表带关键词高亮
4. **20-30s**：切到 `/admin`，看健康灯 / Celery 队列 / 缓存命中率 5 秒刷新

输出为 GIF 或 mp4，<2MB 优先（GitHub README 加载快）。

## 9. 下一步（D13 预告）

D13：跑真实数据 + prompt 调优：
- `il batch --pages 30` 跑一晚抓 ~900 帖
- 看 `il metrics` 找瓶颈
- 调 EXTRACT_PROMPT_VERSION，做 A/B 比较
- `il rescore --all` 不动 LLM 试不同 ScorerWeights
