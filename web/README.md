# InterviewLens Web

Next.js 15 (App Router) + TypeScript + Tailwind v3 + SWR.

## 启动

```bash
cd web
cp .env.example .env.local      # 默认 NEXT_PUBLIC_API_BASE=http://localhost:8000
pnpm install                    # 或 npm install / yarn
pnpm dev                        # 默认 :3000
```

后端先把 `il serve` 跑起来。前端通过 Next.js rewrites `/api/*` → 后端 `:8000/*`，
本地不会遇到 CORS。

## 页面

| 路径 | 用途 |
|---|---|
| `/` | 三栏：公司列表 / 岗位筛选 / 摘要面板 |
| `/search` | 语义搜索题目，关键词高亮，分数 + 相似度展示 |
| `/admin` | 健康检查 + Celery 队列 / DLQ / 节点延迟 / 缓存命中率 |

## 文件树

```
web/
├── package.json
├── tsconfig.json
├── next.config.ts          # /api/* → 后端 rewrites
├── tailwind.config.js
├── postcss.config.js
└── src/
    ├── app/
    │   ├── layout.tsx      # 顶部导航
    │   ├── globals.css     # 主题 + .prose-il markdown 样式
    │   ├── page.tsx        # 首页
    │   ├── search/page.tsx
    │   └── admin/page.tsx
    ├── components/
    │   ├── search-bar.tsx
    │   ├── company-list.tsx
    │   ├── position-filter.tsx
    │   ├── question-card.tsx
    │   └── summary-view.tsx
    └── lib/
        ├── api.ts          # fetch 封装 + 类型
        └── cn.ts           # tailwind classnames helper
```
