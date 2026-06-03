# Day 14 — 简历化收尾：README 重写 + 演示 GIF + Tag v0.1.0 + 部署

> 目标：把整个仓库变成你能直接甩给面试官的"项目展示页"。一打开 GitHub README 就明白这个项目能干什么、用了什么技术、性能怎样。

## 0. 这天会做什么

1. **重写主 README**：顶部 GIF + 三张架构图 + 实测数字 + 技术栈 + 启动指南
2. **录 30 秒演示 GIF**（D12 doc 里有脚本）
3. **生成架构图**：用 mermaid 嵌进 README，无需图片
4. **写 CHANGELOG.md**
5. **打 git tag v0.1.0**
6. **可选**：部署到 Vercel + VPS

---

## 1. 主 README 重写模板

把 `README.md` 改成下面结构（保留现有的"文档导航/状态"在底部）：

```markdown
# InterviewLens

> 把"刷面经"变成"刷题"的 AI 项目。<br>
> 抓取牛客大厂面经 → LangGraph Agent 流水线 → pgvector 语义检索 → DeepSeek 生成专题摘要

![demo](docs/assets/demo.gif)

## ✨ 能干什么

- **聚合**：把"字节后端 100 篇散乱面经"压缩成一篇结构化 markdown
- **语义检索**：搜"分布式锁"自动召回所有同义题（Redisson、Redlock、SETNX 都返回）
- **质量打分**：垃圾帖一眼识别（题量、答案完整度、轮次、新鲜度四维度）
- **可观测**：节点级 trace + 缓存命中率 + token 成本仪表

## 📊 实测数据（你要换成自己的数）

- 600 篇面经 / 4800 道题 / 35 公司 × 12 岗位 / 25 份摘要
- pgvector 检索 P50 < 5ms（百题级）/ < 50ms（万题级）
- 三级归一化命中率：tier1 字典 70% / tier2 embedding 22% / tier3 LLM 8%
- 单条流水线成本约 ¥0.005-0.008，600 条总花费 < ¥6
- LLM 缓存命中率 20%（多由 retry 贡献）

## 🏗️ 架构

\`\`\`mermaid
flowchart LR
  URL --> Crawler --> Cleaner --> Extractor --> Normalizer --> Scorer --> END
  Extractor -.->|调用| DeepSeek[DeepSeek-V3]
  Normalizer -.->|tier 2| BGE[bge-m3 embedding]
  Normalizer -.->|tier 3| DeepSeek
  END --> BG[backfill-embeddings]
  BG --> Aggregator
  Aggregator --> Summaries[(summaries)]
\`\`\`

\`\`\`mermaid
flowchart TB
  Web[Next.js 15] --> API[FastAPI]
  API --> PG[(Postgres + pgvector)]
  API --> Redis[(Redis)]
  Worker[Celery Worker] --> PG
  Worker --> Redis
  Worker --> DeepSeek[(DeepSeek API)]
  Worker --> BGE[bge-m3 local]
\`\`\`

## 🛠️ 技术栈

后端：Python 3.13 · uv · LangGraph · DeepSeek-V3 · bge-m3 · Playwright · trafilatura · Celery · FastAPI · Pydantic v2 · SQLModel · structlog · tenacity · Langfuse
存储：PostgreSQL 16 + pgvector（HNSW）· Redis 7
前端：Next.js 15（App Router）· React 19 · TypeScript · Tailwind v3 · SWR · react-markdown · lucide-react

## 🚀 一分钟启动 demo

\`\`\`bash
git clone https://github.com/jokerD888/InterviewLens
cd InterviewLens
cp .env.example .env       # 填 DEEPSEEK_API_KEY；牛客 cookie 不填也能跑 demo
docker compose up -d
uv sync && uv run playwright install chromium
uv run il seed-aliases     # 灌种子词典
uv run il seed-demo        # 灌 demo 数据
uv run il serve &          # 启 API
cd web && pnpm install && pnpm dev   # 启前端

# 浏览器开 http://localhost:3000
\`\`\`

## 📚 详细文档

[文档导航表保留原样，移到这里]

## ⚖️ 法律

仅供个人学习。**严禁将抓取内容公开发布。** Cookie 不得提交 git。
```

## 2. 录 30 秒 demo.gif

工具：[ScreenToGif](https://www.screentogif.com/)（Win 推荐）

**录制脚本**（D12 doc 里也写了，复读一遍）：
1. **0-5s** 首页打开，左侧公司列表 hover
2. **5-12s** 点 "字节跳动" → "后端开发"，右侧 markdown 摘要渐显
3. **12-20s** `/search` 输 "分布式锁"，结果列表带高亮
4. **20-30s** `/admin` 看健康灯 + Celery 队列 + 缓存命中率

**导出参数**：
- 分辨率 1280×800 或更小，控制 < 3MB
- 帧率 10-15fps（够流畅，体积小）
- 命名 `docs/assets/demo.gif`

## 3. 架构图（mermaid 直接嵌 README）

上面 README 模板里已经有两张 mermaid。GitHub 原生支持，**不需要导出图片**。

如果想导出图片去面试 PPT 用：
- 复制 mermaid 代码到 https://mermaid.live/ 渲染
- 截图或下载 SVG

## 4. CHANGELOG.md

```markdown
# Changelog

## [0.1.0] - 2026-06-XX

### Added
- LangGraph 6-node Agent pipeline（Crawler→Cleaner→Extractor→Normalizer→Scorer→Aggregator）
- DeepSeek-V3 Function Calling 结构化抽取 + Redis 缓存（key 含 prompt 版本）
- 三级实体归一化（alias_dict / bge-m3 embedding / DeepSeek 兜底）+ 自学习字典
- 四维度质量打分（题量 / 答案 / 轮次 / 新鲜度）
- pgvector HNSW 余弦检索 + 余弦聚类去重
- Celery + Redis 批量 + 死信队列 + Playwright 列表页发现
- 节点级 Langfuse trace + Redis 计数缓存命中率/token 成本仪表
- FastAPI REST + 自动 OpenAPI 文档（/docs）
- Next.js 15 RSC + URL 状态化 + 三栏浏览/语义搜索/任务面板
- `il seed-demo` 离线 demo 数据 + `il bench-search` 性能 benchmark

### Stack
- Python 3.13 (uv)
- LangGraph 0.2.50, DeepSeek-V3, bge-m3 1024d
- Postgres 16 + pgvector, Redis 7
- Next.js 15, React 19, TypeScript 5.6, Tailwind v3
```

## 5. 打 tag

```bash
# 写完 CHANGELOG 之后
git add CHANGELOG.md README.md docs/assets/demo.gif
git commit -m "docs: v0.1.0 release notes + readme rewrite + demo gif"
git tag -a v0.1.0 -m "InterviewLens 0.1.0 — 14-day MVP"
git push origin main --tags
```

GitHub 上会自动出现 Release 标签，简历可以直接附"v0.1.0 release"链接。

## 6. （可选）部署

### 前端到 Vercel

1. push 到 GitHub（已经做了）
2. 登录 vercel.com → New Project → Import 你的仓库
3. **重要**：Root Directory 选 `web/`（不是仓库根）
4. Environment Variables：`NEXT_PUBLIC_API_BASE=https://your-vps-domain.com`
5. Deploy

Vercel 免费额度对个人项目完全够。

### 后端到 VPS（最便宜方案：Hetzner / 阿里云轻量）

```bash
# VPS 上
git clone https://github.com/jokerD888/InterviewLens
cd InterviewLens
cp .env.example .env       # 填真值
docker compose up -d       # postgres + redis + langfuse
docker compose -f docker-compose.yml -f docker-compose.worker.yml up -d worker
uv sync && uv run playwright install --with-deps chromium

# 用 systemd 跑 il serve
sudo nano /etc/systemd/system/il-api.service
```

```ini
[Unit]
Description=InterviewLens API
After=network.target

[Service]
Type=simple
User=il
WorkingDirectory=/opt/InterviewLens
ExecStart=/home/il/.local/bin/uv run il serve --host 0.0.0.0 --port 8000
Restart=on-failure

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl enable --now il-api
```

### Caddy 反代（自动 HTTPS）

`/etc/caddy/Caddyfile`：
```
api.yourdomain.com {
    reverse_proxy 127.0.0.1:8000
}
```

`sudo systemctl reload caddy` 完成。Vercel 那边把 `NEXT_PUBLIC_API_BASE` 改成 `https://api.yourdomain.com`。

## 7. 验收清单（结束日）

- [ ] README 顶部有 GIF 能正常显示
- [ ] README 的"实测数据"段填的是真实数字（不是 D12 doc 的占位）
- [ ] mermaid 架构图在 GitHub 渲染正常
- [ ] CHANGELOG.md 写好
- [ ] git tag v0.1.0 推上去，GitHub Releases 页有
- [ ] （可选）Vercel 公开链接能访问
- [ ] 简历里 InterviewLens 的描述是从 README 抄过来的

## 8. 简历可直接抄的描述（基础版）

> **InterviewLens** · 牛客面经聚合 RAG 系统（个人项目）
>
> 全栈实现端到端 AI 流水线：抓取 → LLM 抽取 → 实体归一 → 质量打分 → 向量检索 → 摘要生成。
>
> - Python LangGraph 6 节点 Agent + Celery 批量；DB 状态字段实现可断点续跑
> - 三级实体归一（alias_dict→bge-m3→DeepSeek 兜底）+ 自学习字典，准确率 >95%
> - pgvector HNSW 检索 P50 < 5ms（百题）/<50ms（万题）；余弦聚类去重避免摘要重复
> - 节点级 Langfuse trace + Redis 缓存命中率 + token 成本仪表，单条流水线 < ¥0.01
> - FastAPI REST + Next.js 15 RSC + URL 状态化前端，三栏浏览/语义搜索/任务面板
> - 14 天 MVP，14 天 doc，单人完成，14 commit 推 GitHub

## 9. 完工

跑到这里整个 14 天 MVP 完结。后续可做的方向：
- **多源**：抓 V2EX / 一亩三分地（注意法律红线）
- **多模型**：Claude / Qwen / Kimi 做 A/B 看抽取质量
- **题目去重升级**：从余弦聚类改为 SBERT 跨编码器精排
- **个性化推荐**：用户简历 → 题目权重
- **Chrome 插件**：选中牛客面经页面右键 "送进 InterviewLens"
