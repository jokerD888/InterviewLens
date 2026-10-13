# 本轮可靠性修复与验收

## 从旧生产配置升级

生成器升级仅补充 APP_DB_PASSWORD、MIGRATION_DB_PASSWORD、WORKER_IMAGE、DATABASE_NAME，保留已有 PostgreSQL/Redis/管理员密钥：

```bash
python3 scripts/init_production.py --upgrade
docker compose --env-file deploy/.env.production -f deploy/compose.production.yml build api web
docker compose --env-file deploy/.env.production -f deploy/compose.production.yml up -d postgres redis redis-cache
docker compose --env-file deploy/.env.production -f deploy/compose.production.yml run --rm provision
```

已有 013 数据库无版本表时，先备份和在独立库恢复核对，再 baseline；该操作仅登记 001～013，即使当前发行版包含 014：

```bash
docker compose --env-file deploy/.env.production -f deploy/compose.production.yml run --rm migrate python -m interviewlens.db.migrate baseline
docker compose --env-file deploy/.env.production -f deploy/compose.production.yml up --force-recreate migrate
docker compose --env-file deploy/.env.production -f deploy/compose.production.yml up -d api web caddy
```

首次空库不执行 baseline。provision 是超级用户初始化边界；il_migrate 拥有业务 schema、无超级用户和建角色权限；il_app 仅有业务 DML 和序列权限，无建表/超级用户权限，不可改写迁移和缓存版本元数据。API 和 worker 不接收 bootstrap/迁移密码。恢复新库后重新 provision 收养恢复对象的所有权与权限。

## 原子缓存版本

014 新增 il_read_revision；业务表写入通过同事务触发器更新版本，回滚不更新。缓存读取以数据库版本命名，写入使用查询前捕获的版本。Redis 故障不能丢失提交对应的失效事件；版本读取失败时跳过缓存。旧缓存随 TTL 过期。

单个版本行会短暂串行化写入；当前读多写少的单机配置采用此方案。扩大处理 worker 前应测试写入争用，不直接横向复制模型。数据库语句/锁等待有上限，HNSW 使用 200 候选和严格顺序迭代扫描；生产要求 pgvector >=0.8。缓存版本包含当前数据库名，切换恢复库不会复用其他库的同版本缓存。

## 公共数据与后台

公司/岗位目录统一使用 Feed 的可见性条件，不把零题或未完成处理帖子计入公共篇数。Feed 不返回完整题解，前端展开时请求 `/posts/{id}/questions?limit=50&offset=0`；后端最多 100 条，顺序稳定。列表的 questions 保留为空数组兼容旧响应结构，新前端按需读取。

强制重新生成在网页与离线 answerer 中都绕过答案缓存读取，成功后回写；日预算/重复调用/并发保护继续生效。坏向量缓存校验维度、有限值与非零范数，作为 miss。队列面板使用 broker DB 和优先级列表，DLQ 使用状态 DB。

## 就绪、备份与告警

`/health/live` 仅证明进程存活；`/health/ready` 在 2 秒内检查当前 schema、状态 Redis、已加载模型状态，失败 503；不在探针中重载模型，不返回私有信息。Compose 依赖 ready。Docker healthy/unhealthy 不是自动恢复保证，需要持续监控和告警。所有生产服务使用有上限的 local 日志轮转。

Caddy 对 API 和 Web 均覆盖私有客户端 IP 头，Web 的 SSR 透传该头，API 只信任配置的内部 Caddy/Web socket peer。这样首页 SSR 不会把全部访问者算进 Web 容器的同一限流桶；不信任普通访问者提供的头，也不在公网暴露 Web 的宿主端口。

备份默认读取 Compose 的实际 API 数据库；明确指定不同库会被拒绝。使用 `--container` 时必须明确提供 `backup --database NAME`。备份前后变化会保留文件但退出失败，不能视为验收成功。副本恢复成功后清单记录 restore_verified_at；服务代码、模型卷、Redis 状态和 Langfuse 库仍须按原部署文档单独保护。

`python3 scripts/production_ops.py prune --directory /var/backups/interviewlens` 默认仅预览；加 `--apply` 才删除过期的生成文件对。至少保留 14 日、最近 3 份通过恢复演练的备份和最新备份；未累积 3 份验证备份时完全不清理。不执行递归删除，不处理符号链接或目录外文件。本轮没有清理你的任何备份。

将 deploy 中的 backup、monitor、alert service/timer 安装到 `/etc/systemd/system`。监控每分钟检查 ready 与当前库最近 26 小时内的稳定备份；实际安装时先完成首次备份，再启用 timer。

```bash
sudo install -d -m 700 /etc/InterviewLens
# 创建 root 专属 /etc/InterviewLens/alert.env，内容为 IL_ALERT_WEBHOOK_URL=https://YOUR_OPERATOR_WEBHOOK
sudo chmod 600 /etc/InterviewLens/alert.env
sudo systemctl daemon-reload
sudo systemctl enable --now interviewlens-backup.timer interviewlens-monitor.timer
```

没有配置真实 webhook 时不会宣称告警已送达；通知仅由操作员明确配置的服务调用。真实域名证书、云服务器、防火墙、异机加密备份和告警账户需要目标环境。本机测试不等同于这些外部资源已经部署。

## 质量与召回评测

`PYTHONPATH=src python scripts/evaluate_retrieval.py --samples 20 --k 20` 用已存向量比较 HNSW 与精确 SQL 检索；加 `--company 字节跳动` 单独评估过滤场景。报告 ID recall 和距离阈值 recall，区分距离并列产生的 ID 差异；不调用模型或改业务数据。

`PYTHONPATH=src python scripts/evaluate_profiles.py --labels PRIVATE_LABELS.json` 对独立人工标注输出一级分类准确率和技术方向/领域/技能 micro-F1，缺失记录和重复标签直接拒绝。不得把现有模型输出复制为标签，再声称达到真实准确率。人工标注涉及私有证据时放在 Git 之外；未提供标注集时不声称完成全库语义质量评估。
