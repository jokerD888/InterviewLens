# Day 1 启动指南

> 目标：搭好"地基"——容器跑起来、库建好、CLI 能跑通 doctor 检查、种子词典灌进库。

## 0. 前置检查（5 分钟）

```bash
# Docker Desktop 必装
docker --version && docker compose version

# uv 必装（包管理器，2025 年 Python 项目事实标准）
# Windows PowerShell:
#   irm https://astral.sh/uv/install.ps1 | iex
# 或 winget install astral-sh.uv
uv --version
```

## 1. 复制环境变量并填值

```bash
cp .env.example .env
```

至少填 3 项：
- `DEEPSEEK_API_KEY`：去 platform.deepseek.com 拿
- `LANGFUSE_NEXTAUTH_SECRET` / `LANGFUSE_SALT`：执行 `openssl rand -hex 32` 各跑一次
- `NOWCODER_COOKIE`：登录 nowcoder.com 后 F12 → Application → Cookies → 复制全部 → 拼成 `key1=v1; key2=v2`

## 2. 启动容器

```bash
docker compose up -d
docker compose ps             # 三个容器全 Up，langfuse 第一次启会久点
docker compose logs postgres  # 看到 "database system is ready to accept connections"
```

验证 SQL 跑通：
```bash
docker exec -it il-postgres psql -U il -d interviewlens -c "\dt"
# 应列出 7 张表 + 1 个视图
```

## 3. 安装 Python 依赖

```bash
uv sync
uv run playwright install chromium
```

## 4. 跑通三件事

```bash
# 4.1 看配置加载情况（敏感字段已 mask）
uv run il info

# 4.2 健康检查（连 PG + Redis）
uv run il doctor

# 4.3 灌入种子别名词典
uv run il seed-aliases
```

`seed-aliases` 跑完后验证：
```bash
docker exec -it il-postgres psql -U il -d interviewlens \
  -c "SELECT entity_type, COUNT(*) FROM alias_dict GROUP BY entity_type;"
# 应该看到 company / position 各几十条
```

## 5. 跑测试

```bash
uv run pytest -v
```

## 6. Langfuse 首次设置

打开 http://localhost:3001 → 注册账号（本地任意） → 创建 project → 拿到 public/secret key →
回填 `.env` 的 `LANGFUSE_PUBLIC_KEY` / `LANGFUSE_SECRET_KEY` → 重新 `uv run il info` 确认。

## 7. Day 1 完成检查清单

- [ ] `docker compose ps` 三个 healthy
- [ ] `psql ... \dt` 看到 7 张表
- [ ] `uv run il doctor` 全 OK
- [ ] `uv run il seed-aliases` 写入成功
- [ ] `uv run pytest` 绿
- [ ] Langfuse 能登录

完事就直接进 Day 2，明天写 Playwright 抓单条面经。

## 故障速查

| 现象 | 原因 / 处理 |
|---|---|
| `psycopg2.OperationalError` | 端口冲突，把 .env 里 `POSTGRES_PORT` 改成 5434 之类，重启 docker |
| `ModuleNotFoundError: pgvector` | `uv sync` 没装全，重跑一次 |
| `il doctor` 报 "vector extension missing" | 没用对镜像，确认是 `pgvector/pgvector:pg16` |
| Playwright 报缺浏览器 | `uv run playwright install chromium` 没跑 |
| Langfuse 起不来 | 内存吃紧，确认 Docker Desktop 给了 ≥ 4 GB |
