# Day 2 — 抓取与清洗

> 目标：跑一条命令把任意牛客面经页抓回来，清洗成纯文本，落库。

## 0. 前置

D1 已经跑完（容器在跑、`il doctor` 全 OK、表已建、别名词典已灌）。
`.env` 里 **必须填好** `NOWCODER_COOKIE`，否则只能拿到登录页。

## 1. 装浏览器（如还没装）

```bash
uv run playwright install chromium
```

## 2. 找一篇真实面经 URL

打开 https://www.nowcoder.com/discuss → 任选一篇大厂面经 → 复制地址栏 URL。

格式通常长这样：
```
https://www.nowcoder.com/discuss/123456789
https://www.nowcoder.com/feed/main/detail/abc123
```

## 3. 抓取（开 headful 看效果）

```bash
uv run il crawl "https://www.nowcoder.com/discuss/<id>" --no-headless
```

第一次推荐 `--no-headless`，能直观看到浏览器自动开页：
- 注入了 cookie → 直接是登录态
- 页面渲染完成后被静默抓取 → 浏览器自动关闭
- 终端看到 cleaned 字符数和 post_id

后续日常用 headless：
```bash
uv run il crawl "https://www.nowcoder.com/discuss/<id>"
```

## 4. 看入库结果

```bash
uv run il show-post 1
```

输出包含：
- 元数据表：source_url / title / fetched_at / extract_status (= pending) / cleaned_chars
- 清洗后的文本前 800 字预览

直接 SQL 验证：
```bash
docker exec -it il-postgres psql -U il -d interviewlens \
  -c "SELECT id, title, char_length(cleaned_text), extract_status FROM posts;"
```

## 5. 验收清单

- [ ] `il crawl <url>` 终端 panel 是绿色（非 yellow skipped）
- [ ] `cleaned_chars` ≥ 200
- [ ] `il show-post <id>` 看到面经题目原文（不是登录页 / 验证码 / 空白）
- [ ] 重复跑 `il crawl <同一url>` 不报 unique 错误（upsert 逻辑生效）
- [ ] `pytest tests/test_cookie.py tests/test_cleaner.py -v` 全绿

## 6. 调速建议

`.env` 里：
```
CRAWLER_RATE_PER_SEC=1.5      # 单纯节流，每秒最多 1.5 次
CRAWLER_JITTER_MIN=2.0        # 每次 acquire 后额外随机 sleep 2-5s
CRAWLER_JITTER_MAX=5.0
CRAWLER_MAX_RETRIES=3
```

被 ban 的几乎都是并发开太大 + 没 jitter。当前默认值跑通宵安全。

## 7. 常见问题

| 现象 | 原因 / 处理 |
|---|---|
| 抓回来 cleaned_chars < 100 → skipped | cookie 失效或过期，重新拿 |
| Playwright 报 `Timeout 30000ms` | 网络慢，或牛客让 JS 验证；`--no-headless` 看一眼 |
| 抓回来全是登录引导页 | cookie 没生效，检查 `.env` 里有没有空行 / 引号问题 |
| `psycopg.OperationalError` | 容器没起，`docker compose ps` 检查 |
| 重复 URL 报错 | 不应该，`upsert_raw_post` 已处理；如真报错把日志贴给我 |

## 8. 下一步（D3 预告）

D3 接 DeepSeek，把 `cleaned_text` 喂给 Function Calling，吐出结构化 JSON 写入 questions 表。
