# 平板服务接入记录

2026-10-14：在现有 Arch chroot 试运行环境接入 Cloudflare Tunnel、Caddy、Celery 和付费 AI 生成。该部署使用现有数据库副本，不改动 PC 主库。

## 访问和管理

- 公网入口：<https://interview.819266.xyz>；后台：`/admin`。
- PC 经 USB 访问：<http://127.0.0.1:3313>。
- 后台使用管理员 Token 登录，没有新增用户名密码。Token 单独保存在本机 `D:\tmp\InterviewLensRuntime\tablet-trial\admin-token.txt`，仅当前 Windows 用户可读；不进入 Git、页面源码或日志。
- 管理 API 和 AI 生成均要求 Bearer Token。普通用户可以查看已生成的答案，不能匿名触发计费。

启动、停止及检查沿用本机脚本：

```powershell
& D:\tmp\InterviewLensRuntime\tablet-trial\control-trial.ps1 -Action start
& D:\tmp\InterviewLensRuntime\tablet-trial\control-trial.ps1 -Action status
& D:\tmp\InterviewLensRuntime\tablet-trial\control-trial.ps1 -Action stop
```

## 平板上的服务

| 服务 | 仅本机监听端口 | 说明 |
| --- | --- | --- |
| PostgreSQL | 15433 | 原有数据副本，应用使用最小权限角色 |
| Valkey 状态 / 缓存 | 16380 / 16381 | 独立密码，状态与可淘汰缓存分离 |
| FastAPI | 18800 | 唯一 ONNX BGE-M3 模型实例 |
| Next.js | 13013 | 已构建的生产前端 |
| Caddy | 13080 | 网页与 API 路由，覆写可信访问者 IP，限制请求体 |
| cloudflared metrics | 18081 | 仅本机运维，不向公网转发 |

Tunnel `interviewlens-tablet` 通过 HTTP/2 主动连到 Cloudflare，连接数实测为 4；不需要公网 IP 或路由器开放端口。仅指定域名转到 Caddy，其他域名返回 404。内嵌 RPC、深度健康检查及 API 文档在公网入口返回 404。

Celery 使用原生 `solo` 池、并发 1，没有启动 Beat 或自动爬虫。此池不提供 prefork 的硬超时；现有协程桥接 220 秒超时和 HTTP 超时继续生效。`worker.py` 的模型适配器通过带鉴权的本机 `/internal/embed` 调用 API，每次最多 4 条，不在 worker 中再加载一份大模型。

## AI 和追踪

复用现有 DeepSeek 配置，运行模型为 `deepseek-v4-flash`；并发 1、每分钟 30 调用、每日 200 万 token 上限，已有计数不清空。

用户选择继续使用 PC 的 Langfuse v2.95.11。USB 私有反向映射 `平板 127.0.0.1:13014 → PC 127.0.0.1:3014`；网站和后台任务在平板运行，追踪依赖 PC 开机、USB 连接和 PC Langfuse 服务。断开后 AI 可以继续运行，追踪降级并记录警告。失败事件只在有界内存缓冲区中保留，重启会丢失未发出的追踪，不是持久化离线队列。

配置 `LANGFUSE_TRANSPORT=legacy` 才向既有 v2 服务发送 REST ingestion；新服务器使用 `otel`。代码同时兼容 SDK 2 原接口与 SDK 4 observation 接口，正确结束子观察和根观察，并将 provider 的 token usage 映射到对应协议。模板中 bundled Compose 的 v2 服务明确使用 legacy。

## 验收证据

- 真实 Celery 队列任务读到 **17,275** 道题，生成 **1024** 维、范数 **1.0** 的向量。
- 管理生成接口产生一道新答案：题目 **16488**，**1,843 字**，入库版本 **1**；再次请求复用答案。
- PC Langfuse 中查到对应 `answerer.answer`：输入 **186**、输出 **931**，合计 **1,117 token**，包含完整输出与结束时间。
- 实际 SDK 4 内存 exporter 验证根/子 span 的父子关系、输出、usage 和结束；不是只通过宽松 Mock 检查。
- 43 项针对性回归测试通过；加入服务后现场总 PSS 约 **1.07GiB**，系统可用内存约 **1.42GiB**，属于一次采样而非峰值保证。
- 公网 HTTPS 返回帖子数据 200，匿名后台/生成返回 401；深度健康检查和内嵌 RPC 返回 404。真实 Cloudflare IP 的请求保持证书校验。PC 代理曾缓存新子域名的 NXDOMAIN，这与源站故障分开记录。
- 新增答案后的 PostgreSQL 原生备份已复制到 PC 的 `D:\tmp\InterviewLensRuntime\backups\tablet-services-20261014.dump`，大小 **190,138,305 bytes**，SHA-256：`f88391f6dcd5d9151aeeeaac37513b46667e7cb5185d127e6b22840577c610e8`。

运行配置、证书和凭据留在平板 `/opt/interviewlens-trial/private`，权限 600；证据和控制脚本在 PC `D:\tmp\InterviewLensRuntime\tablet-trial`。本目录里的 Caddy 配置和 worker 是可审查的源码，不包含凭据。

本目录 `api.py`、`start_services.py` 和 `stop_services.py` 是已准备好的试运行目录所用的启动脚本快照，部署时对应 `trial_api.py`、`start_trial.py` 和 `stop_trial.py`。它们依赖此前安装的原生组件和 ONNX 模型，不是通用的全新系统安装程序。

## 试运行边界

设备仍是 Android 4.19 内核上的 Arch chroot。PostgreSQL 使用先前验证的私有共享内存兼容库；Valkey 因内核 ARM64 COW 缺陷禁止 fork 快照和 AOF rewrite，后续需停机维护 AOF。量化模型最长 1024 token，超过时明确拒绝而非静默截断；此前 24 条样本 Top-10 与原模型平均重合 92.5%，这不是人工评估准确率。

尚未做整机重启后的自启验收、长期稳定性和恢复演练。因此本次完成服务接入与公网试运行，不等于已消除设备原有的长期生产运行限制。

## 首页导航优化（2026-10-14）

原首页强制动态渲染，服务端先读取公司列表，但只用到列表长度；客户端列表随后又请求同一接口。公司选择的 effect 还会触发服务端导航。首页现在预生成页面骨架，公司目录及计数共享同一 SWR 请求，帖子继续独立加载和更新；公司选择通过 Next.js 支持的原生 history 更新 URL，不再等待一次服务端渲染。首次访问仍需加载实际数据，缓存页面骨架不会冻结帖子内容。

在 **https://interview.819266.xyz/** 的真实浏览器中，以“点击 → 目标页面标题可见”计时，包含自动化接口开销；两组各三次，并非冷启动或完整数据加载时间：

| 切换 | 修改前（ms） | 修改后（ms） |
| --- | --- | --- |
| 最新面经 → 浏览 | 969 / 1281 / 153 | 60 / 67 / 68 |
| 浏览 → 最新面经 | 107 / 56 / 53 | 77 / 50 / 43 |

首页切换中位数由 969ms 降为 67ms。公网响应的 `x-nextjs-cache: HIT` 证明首页已命中 Next.js 预生成结果，Cloudflare 仍返回 `DYNAMIC`，本次没有增加 CDN 缓存规则。独立 HTTPS 请求当时约 1.7–2.2 秒，说明公网链路开销仍然存在，不能将上述切换计时当成首次打开速度。

验证通过：生产构建、TypeScript 检查、公司及岗位筛选、清空公司、公司链接刷新、浏览器前进后退，测试标签页无控制台错误。一次公网首页刷新在 API 日志中只产生一个公司请求、一个帖子请求和一个岗位字典请求。仅替换 web 进程，其余服务保持原进程；旧前端保留在平板 `/opt/interviewlens-trial/web-before-navigation-20261014`，旧版静态资源同时保留，供更新前已打开的标签页使用。

本机复测证据：`D:\tmp\InterviewLensRuntime\tablet-trial\public-navigation-browser-after.json`、`public-navigation-http-after.json` 和 `public-navigation-after.png`。
