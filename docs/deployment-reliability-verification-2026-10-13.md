# 可靠性修复验收（2026-10-13）

本轮修复位于 `codex/deployment-reliability`，基线 main `90314ff`。这是本机与隔离生产副本验收，没有发布到云服务器。

## 已完成

- 存活/就绪分开；就绪验证模型状态、数据库 schema 014、pgvector >=0.8、状态 Redis，依赖失败或长期卡住推理时返回 503。
- 初始化、迁移、业务账号分离；应用无 SUPERUSER/CREATEDB/CREATEROLE、建表或缓存/迁移元数据写入权限。生产 API 不接收 bootstrap/迁移密码。
- 数据库名统一配置，恢复切库后的备份跟随实际 API 目标；备份清单记录源库。独立恢复与校验通过。
- 缓存版本随业务事务更新，包含数据库名；回滚同时回滚版本，Redis 故障不丢失失效事件。
- 公共公司/岗位篇数与 Feed 可见性统一。字节当前可展示计数为 144。
- 网页与离线强制重新生成绕过旧答案缓存；费用/并发限制继续生效。
- 后台读取 broker DB 和优先级队列；DLQ 继续读取状态 DB。
- 缓存向量检查 1024 维、有限值和归一化范数，坏数据作为 miss。
- Feed 只发元数据和摘要，展开时分页读取题目；先分页帖子，再聚合关联，避免多关联与全量题解传输。
- 生产服务日志轮转；提供就绪/备份监控与显式配置的失败通知、保守的备份保留工具。
- Linux 官方 CPU Torch 2.13 与 API/worker 镜像拆分；API 不安装 Chromium/CUDA。SSR 访客 IP 经过 Caddy 覆盖、Web 透传与内部 peer 校验，不共享一个 Web IP 配额桶。
- 提供只读索引召回/延迟评测，以及独立标注集的分类准确率/维度 micro-F1 工具。

## 实测

| 验证 | 结果 |
|---|---|
| 启用 PostgreSQL 的完整测试集 | 304 passed / 11 skipped；之后新增 SSR 回归并与关联用例共 39 项通过，新增用例 1 项，累计 305 项通过 |
| Linux API/Web/worker 构建 | 通过；worker 非 root Chromium 打开 about:blank，外部请求 0 |
| API 镜像 inspect Size | 454,694,721 bytes，约 434 MiB；此前约 3.46 GiB，模型卷另计 |
| 浏览器后台验收 | 公开导航、匿名拒绝、错误/正确凭据、恢复校验、会话失效、退出通过；业务操作 0 |
| 浏览器 Feed | 展开前题目请求 0；展开后请求 1，加载首篇 11 道题 |
| 私有 CA HTTPS | 证书链检查通过；真实域名 ACME 未执行 |
| SSR 限流与伪造 IP 头 | API 与首页 SSR 同一访客桶增加 2；用户伪造私有头未建立其指定 IP 桶 |
| CPU 未缓存搜索 | 最后样本约 1.10 秒，Top-100 返回 100 项；不作为云服务器延迟承诺 |
| HNSW vs 精确检索 | 20 样本 @20，ef_search=200：ID recall 0.96，处理距离并列的 recall 0.99；字节过滤样本二者 0.99 |
| CPU/GPU 向量兼容 | 最长三道题重算，各 3×1024，余弦约 1.0；未重建或删除原库向量 |
| 生产 Python 依赖审计 | 127 个第三方包记录，已知漏洞 0；本项目源码不计为 PyPI 审计对象，未执行全量 OS 渗透测试 |
| 数据保留 | 1,211 帖、17,275 题、17,275 向量，处理检查点未完成数 0 |

数据库角色实测：il_app / il_migrate 均非超级用户、不可建库/建角色；il_app 能写业务表，不能建表或 UPDATE il_read_revision。独立副本执行 no-op 业务 UPDATE 后版本增长；ROLLBACK 后版本恢复，COMMIT 后版本增长。

## 备份与运行

迁移前新增真实主库备份：`D:\tmp\InterviewLensRuntime\backups\interviewlens-20261013T081540Z-00ecb3.dump`。

切到恢复库后生成的新备份：`D:\tmp\InterviewLensRuntime\reliability-backups\interviewlens-20261013T080927Z-6bca92.dump`。再恢复到 `restore_reliability_verify` 后，帖子、题目、分类内容指纹及七项数据数量与来源相同。没有清理旧备份。

本机 runtime 已切换为有限权限业务账号并应用 014；本机 API/Web 已启动，地址 `http://127.0.0.1:3013`。本机使用原 GPU 环境；生产隔离副本使用 CPU。没有开启爬虫、Celery 处理或实际付费生成，保留原 Cookie/管理员凭据/预算状态。

隔离生产测试项目是 `il-reliability-20261013`，入口只绑定回环 3180/3543；它使用恢复副本，与本机主库分开。仓库被忽略的 `.env.production` 是 localhost 验收配置，不能直接复制作为公网配置。SQL、服务部署和日志均为新方案，实际服务器仍须按 [升级说明](deployment-reliability.md) 创建自己的私有配置。

## 验收边界

一次停止隔离 Redis 服务的故障演练被自动审批拒绝，仅返回 `blocked by policy`；改用独立进程的不可用 Redis 连接，实测就绪 503、存活 200，没有停止 Redis 服务。数据库/模型失败以及卡住推理由隔离回归场景覆盖。

未配置云服务器、真实 DNS/公网证书、异机加密备份目标或真实告警 webhook，也未对没有独立人工标签的全库宣称分类准确率。相关代码与流程已提供，这些外部资源仍需真实部署环境。

原始日志、召回 JSON、向量兼容结果和审计记录在 `D:\tmp\InterviewLensRuntime\reliability-*`，私有备份与配置不进入 Git。
