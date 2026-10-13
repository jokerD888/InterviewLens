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
| `/admin` | 独立管理登录；验证成功后显示健康检查、队列、岗位分类管理等 |

公共导航只显示浏览、最新面经和检索，不提供后台入口。管理员直接访问 `/admin`，
使用后端 `.env` 中的 `ADMIN_API_TOKEN` 登录；刷新后重新向后端验证，退出后清空本次后台缓存。
管理接口（包括直接访问 API）仍由后端 `require_admin` 鉴权，隐藏导航不承担安全防护。
后台页面设置 `noindex, nofollow`；这只控制搜索引擎收录，不代表访问控制。

公网部署应使用 HTTPS，并限制后台及其 API 的访问范围（例如反向代理的 IP 白名单或受控管理网络）。
管理凭据不得写入 `NEXT_PUBLIC_*` 或前端源码。当前仍使用单管理员凭据，本次改动不包含完整的用户账号或多管理员权限系统。
权限控制原则参考 [OWASP Authorization Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/Authorization_Cheat_Sheet.html)。

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
