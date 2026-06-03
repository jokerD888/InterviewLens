# Day 11 — Next.js 前端骨架（三栏 + 搜索 + 管理）

> 目标：把 D10 的 API 包装成可演示的 UI，简历 README 录 GIF 直接用。

## 0. 这一步带来什么

| 之前 | 现在 |
|---|---|
| 只能 curl / Swagger 看数据 | 浏览器直接看 markdown 摘要 |
| 不知道有多少公司岗位 | 左侧侧边栏自动列出 |
| 想搜题要写 SQL | `/search` 输入关键词回车 |
| 任务监控只能 CLI | `/admin` 实时看队列/worker/缓存 |

## 1. 启动

```bash
cd web
cp .env.example .env.local
pnpm install        # 或 npm install / yarn
pnpm dev            # http://localhost:3000
```

后端 `uv run il serve` 必须先起来（默认 8000）。前端通过 `next.config.ts` 的 rewrites
把 `/api/*` 映射到后端 `:8000/*`，**完美绕过 CORS**。

## 2. 三个页面

### `/` 浏览页
三栏布局：
- 左：公司列表（带 post_count，按数量降序）
- 上：岗位筛选 chips（点公司后自动切换为该公司岗位）
- 右：摘要面板（react-markdown 渲染，自定义 .prose-il 主题）

### `/search` 搜索页
- 顶部搜索框，回车触发
- 结果卡片含：分类标签、轮次、质量分（颜色编码）、相似度百分比、原帖链接
- 关键词在题目中高亮 (`<mark>`)
- 答案要点折叠展开
- 公司/岗位/最低分三个过滤器

### `/admin` 管理页
- 健康检查：pg / pgvector / redis 三盏灯，5 秒自动刷新
- 任务队列：长度 / 活跃 worker / 死信队列计数
- LLM 指标：缓存命中率 / token 总数 / 估算￥ / 各节点平均延迟表

## 3. 关键技术决策

| 维度 | 决策 | 理由 |
|---|---|---|
| 框架 | Next.js 15 App Router | 现代默认，支持 RSC、typedRoutes、自带 rewrites |
| 数据获取 | SWR | 比 react-query 轻量、跑在客户端、自动重试 + revalidate |
| 样式 | Tailwind v3 + 自写主题 | 没装 shadcn 因为单页应用不值，原生 + cn helper 够 |
| Markdown | react-markdown + remark-gfm | 标准答案，支持表格/任务列表 |
| 图标 | lucide-react | 比 heroicons 选择多，跟 shadcn 同源 |
| 主题 | 深色 only | 面试加分；浅色不需要为 demo 项目做 |

## 4. 文件清单（13 个）

```
web/
├── package.json / tsconfig.json / next.config.ts
├── tailwind.config.js / postcss.config.js
├── next-env.d.ts / .env.example / .gitignore / README.md
└── src/
    ├── app/
    │   ├── globals.css     # 主题变量 + markdown 样式
    │   ├── layout.tsx      # 顶部导航
    │   ├── page.tsx        # 首页（三栏）
    │   ├── search/page.tsx
    │   └── admin/page.tsx
    ├── components/         # 5 个：search-bar / company-list / position-filter / question-card / summary-view
    └── lib/api.ts          # fetch 封装 + 全部 TypeScript 类型
```

## 5. 关键设计要点（面试讲故事）

- **next.config.ts rewrites 而不是 fetch 直连后端**：本地 dev 浏览器不需要 CORS 头；生产部署到 Vercel + 自托管后端时只改 `NEXT_PUBLIC_API_BASE` 一个变量
- **SWR `refreshInterval: 5000`** 在 admin 页：实时性足够低成本，比 WebSocket 简单
- **类型从 `lib/api.ts` 单一来源**：所有组件 import `Question`/`Company`/`Summary`，后端 schema 改了改这一个文件
- **关键词高亮用纯 React + regex**：不引第三方 highlight 库，30 行手写够
- **Loading / Error / Empty 三态都有 UI**：摘要为空告诉用户跑哪个命令生成；很多教程级前端缺这个
- **`.prose-il` 自定义而不是 @tailwindcss/typography**：包大、默认样式跟主题不搭；自写 60 行 CSS 完全够
- **位置筛选 chips 而不是下拉**：移动端友好，hover 状态明显

## 6. 验收清单

- [ ] `pnpm dev` 启服务，http://localhost:3000 不白屏
- [ ] 首页左侧公司列表渲染（如果库里没数据，会空着但不报错）
- [ ] 选公司 + 岗位后，右侧摘要面板加载（404 时给提示而不是崩）
- [ ] `/search?q=分布式锁` 关键词搜索能命中题目
- [ ] 关键词在结果卡片中黄色高亮
- [ ] `/admin` 页 5 秒自动刷新数据
- [ ] 关掉后端，前端显示加载失败而不是白屏

## 7. 后端依赖

前端调用的 API 必须在后端跑起来：

```bash
# 终端 1
uv run il serve

# 终端 2
cd web && pnpm dev
```

如果只想 demo UI 没真数据，先填几条 mock：
```bash
uv run il graph "https://www.nowcoder.com/discuss/<某id>"
uv run il aggregate --company X --position Y
```

## 8. 部署示意（D14 会写）

- 前端：Vercel（push GitHub 自动部署）
- 后端：自托管 Docker；Caddy/Nginx 反代到 :8000
- DNS：api.yourdomain.com 反代后端，前端 .env.production 设 `NEXT_PUBLIC_API_BASE=https://api...`

## 9. 下一步（D12 预告）

D12：检索体验打磨 + 数据填充：
- 跑 D9 批量填 200+ 真实面经
- 调 prompt / 调 ScorerWeights
- 添加 SSR 首屏（公司列表 RSC 直出，加快加载）
- 录 30 秒演示 GIF 准备简历用
