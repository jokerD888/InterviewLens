# 爬虫架构演进：从页面抓取到 API 直连

> 记录 `il batch` 默认来源从 Playwright 页面抓取升级到 API 网关直连的过程。

---

## 一、问题发现

首次部署后用户反馈：`il batch --pages 5` 爬回来的内容不对——大量"简历求批""找实习吐槽"等非面经帖子混入。

实际上 5 页扫出 109 个 URL，但内容质量参差不齐，真正的高质量面经占比不高。

---

## 二、根因分析

### 2.1 表面现象

浏览器手动访问 `https://www.nowcoder.com/?type=818_1`，点击"面经"tab 后能看到面经帖子。但同一个 URL 用爬虫抓取，返回的 HTML 里全是首页混流内容。

### 2.2 架构揭秘

```
用户操作：
  浏览器 → GET /?type=818_1 → 服务端返回 SSR HTML（推荐流）
         → 点击"面经"tab → JS 触发 XHR → gw-c.nowcoder.com → 渲染面经

直接爬取：
  HTTP GET /?type=818_1 → 服务端只返回 SSR HTML → 只有推荐流
```

**关键结论：**

- `?type=818_1` 是前端 SPA 路由参数，**服务端不认**。服务端对这个 URL 永远返回首页推荐流。
- 面经内容由前端 JavaScript 异步加载，请求发往独立的 API 网关 `gw-c.nowcoder.com`。
- 两个域名分工：`www.nowcoder.com` 负责 SSR 页面，`gw-c.nowcoder.com` 负责数据 API。
- **爬面经不能走页面，必须直连 API 网关。**

---

## 三、新方案：API 直连

### 3.1 API 端点

```
POST https://gw-c.nowcoder.com/api/sparta/job-experience/experience/job/list
Content-Type: application/json
```

### 3.2 请求头

```json
{
  "content-type": "application/json",
  "origin": "https://www.nowcoder.com",
  "referer": "https://www.nowcoder.com/"
}
```

- `origin` 和 `referer` 用于通过 CORS 校验
- **无需 Cookie**，公开 API

### 3.3 请求体

```json
{
  "companyList": [],
  "jobId": 818,
  "level": 3,
  "order": 3,
  "page": 1,
  "isNewJob": true
}
```

| 参数 | 说明 | 可选值 |
|---|---|---|
| `jobId` | 岗位 ID | `818`=后端, `819`=前端, `820`=测试, `898`=AI |
| `level` | 级别 | `3`=不限, `1`=实习, `2`=校招 |
| `order` | 排序 | `3`=最新, `1`=最热 |
| `page` | 页码 | 从 1 开始 |

### 3.4 响应结构

API 返回 JSON，**每条记录直接包含帖子全文**：

```json
{
  "success": true,
  "data": {
    "total": 2000,
    "records": [
      {
        "extraInfo": { "entityId": "740002863927" },
        "momentData": {
          "title": "tme hr面 已OC",
          "content": "自我介绍\n为什么在百度实习...",
          "createdAt": 1781256161000
        },
        "userBrief": { "nickname": "失速飞机" }
      }
    ]
  }
}
```

### 3.5 帖子 URL 拼接

```
https://www.nowcoder.com/discuss/{entityId}
```

---

## 四、新旧方案对比

| | 旧（Playwright 页面） | 新（API 直连） |
|---|---|---|
| **来源** | `/?type=818_1` 或 `/discuss?type=2` | `gw-c.nowcoder.com/api/...` |
| **内容获取** | 开浏览器 → 等 JS 渲染 → 取 HTML → 清洗 | `POST` → 拿 JSON → 直接落库 |
| **需要 Cookie** | ✅ 必须 | ❌ 不需要 |
| **需要 Playwright** | ✅ | ❌ |
| **速度** | 每篇 5-10 秒（浏览器启动+渲染） | 每页 20 篇 < 2 秒 |
| **内容质量** | 混流，含非面经 | 纯面经（API 按岗位过滤） |
| **断网恢复** | Worker 断连需手动重启 | HTTP 天然可重试 |
| **反爬风险** | 浏览器指纹可能触发验证码 | 纯 HTTP，只需注意请求频率 |

---

## 五、CLI 变更

### 5.1 命令变化

```bash
# 旧（仍可用，但不推荐）
docker compose exec api uv run il batch --pages 5 --source interview

# 新（默认）
docker compose exec api uv run il batch --pages 5
# 等价于 --source api --job backend
```

### 5.2 新增参数 `--job`

```bash
# 后端开发（默认）
docker compose exec api uv run il batch --pages 5 --job backend

# 前端开发
docker compose exec api uv run il batch --pages 3 --job frontend

# 测试开发
docker compose exec api uv run il batch --pages 3 --job test

# 人工智能
docker compose exec api uv run il batch --pages 3 --job ai
```

---

## 六、代码变更清单

| 文件 | 变更 |
|---|---|
| `src/interviewlens/crawler/api_discover.py` | **新增**：API 网关直连发现 + 落库 |
| `src/interviewlens/cli.py` | **修改**：`batch` 默认 `--source api`，新增 `--job` 参数 |

---

## 七、经验教训

1. **SPA 页面不能靠 GET 抓 HTML**：很多现代网站的"内容区"是前端 JS 异步加载的，服务端 HTML 里根本没有目标数据。必须用 DevTools 观察 Network 面板，找到真正的数据 API。

2. **API 不一定需要登录**：虽然牛客页面需要登录才能看面经，但面经数据 API（`gw-c` 网关）是公开的，只要有正确的 `origin`/`referer` 头即可访问。

3. **能调 API 就别开浏览器**：Playwright 对 CPU/内存开销大、速度慢、容易断连。HTTP API 天然可重试、可限流、速度快几十倍。
