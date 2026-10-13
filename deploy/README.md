# 公网部署与恢复

首发范围：岗位方向浏览、最新面经、语义检索、原帖来源和已有答案。历史摘要只在后台核对，生成与导出也只在后台。不要将开发 Compose 或本机 Next dev 暴露到公网。

## 服务器准备

使用 Linux、Docker Engine 和 Compose v2。建议从至少 4 vCPU / 16 GiB RAM / 80 GiB 可用磁盘开始，按实测调整：本配置为 CPU BGE-M3 保留 6 GiB 内存；同时开启处理 worker 还需额外资源。当前锁定依赖包含 CUDA 包，因此镜像下载和构建较大；CPU 实际运行不需要 GPU。只支持一个 API 容器、一个 Uvicorn 进程，不能直接扩容复制模型；多实例需要独立推理服务及统一并发控制。

把仓库放在 `/opt/InterviewLens`，准备域名 A/AAAA 记录、正确系统时间、防火墙只放行 80/443，以及只允许管理 IP 的 SSH。Caddy 直接面对访问者，自动申请/续期证书。尚未配置 CDN/额外反向代理；不能直接相信它们传来的 IP 头。管理允许范围使用实际管理员公网 IP `/32` 或 VPN CIDR，不使用 `0.0.0.0/0`。

```bash
cd /opt/InterviewLens
python3 scripts/init_production.py --domain interviews.example.com --email owner@example.com --admin-network YOUR_PUBLIC_IP/32 --release YOUR_GIT_SHA
docker compose --env-file deploy/.env.production -f deploy/compose.production.yml config --quiet
docker compose --env-file deploy/.env.production -f deploy/compose.production.yml build api web
```

初始化脚本生成 `.env.production` 和 Redis 密码哈希 ACL；不会打印凭据或覆盖已有配置。使用 Linux 文件权限保护部署目录（私有配置 0600，private 目录 0700）；Windows 上准备时要另行配置 NTFS ACL。密钥不要放进 Git、镜像、构建参数或聊天记录。管理员凭据是文件中的 `ADMIN_API_TOKEN`，只通过 `/admin` 登录使用；没有默认用户名和密码。

## 首次启动与数据导入

```bash
docker compose --env-file deploy/.env.production -f deploy/compose.production.yml up -d postgres redis redis-cache
docker compose --env-file deploy/.env.production -f deploy/compose.production.yml run --rm model-download
docker compose --env-file deploy/.env.production -f deploy/compose.production.yml up -d api web caddy
```

`migrate` 按 001～013 的版本顺序执行并记录 SHA-256，每份迁移和版本登记在同一事务内。既有数据卷不会依赖 PostgreSQL init 目录重新执行。发现修改过的迁移、版本断档或数据库比代码新时停止；只新增下一份迁移，不修改已发布 SQL。

如果导入已有的 InterviewLens dump，先把文件复制到 PostgreSQL 容器，用 `pg_restore --single-transaction --exit-on-error --no-owner --no-acl` 导入一个**空的目标数据库**，不要给现有库使用 `--clean`。先在独立 `restore_...` 库演练，核对数据和应用查询。013 的旧库没有迁移版本表，确认恢复演练后执行：

```bash
docker compose --env-file deploy/.env.production -f deploy/compose.production.yml run --rm migrate python -m interviewlens.db.migrate baseline
docker compose --env-file deploy/.env.production -f deploy/compose.production.yml run --rm migrate python -m interviewlens.db.migrate status
```

`baseline` 仅登记通过结构检查的 013 旧库；不会重算、删除或填造数据。空库直接 `apply`。本机 10-04 原始包已经落后，应使用本次最新备份。HF 模型卷可提前从已下载的 BGE-M3 缓存复制，保证 UID 10001 可读写；API 默认离线，未准备模型时语义检索不可用，浏览仍可用。发布验收必须实测一次未缓存的语义检索，不能只看首页健康探针。

## 后台与更新

公开服务只映射 80/443。数据库、两个 Redis、API 和 Web 都无宿主机端口映射。管理页面、管理 API、Bridge 全部路径别名、历史摘要均受 Caddy IP 限制；后端继续验证 Bearer 凭据。匿名语义检索每 IP 每分钟 12 次，普通接口 120 次；超限 429，保护存储不可用 503，模型忙 503，超时 504，均可稍后重试。API 进程最多运行一个语义编码任务，超时不提前释放名额。

默认不启动采集和处理 worker，也不自动触发网站请求或付费调用。确需处理时先私下配置 DeepSeek 凭据、确认每日 token 预算，再开启 `--profile processing`。Langfuse 使用 `--profile observability`，自己的数据库、NEXTAUTH_SECRET、SALT 均随机生成，控制台只绑定服务器回环端口 3001，通过 SSH 隧道访问。创建项目后将服务端项目密钥写入私有环境文件。处理与可观测性分别启动；没有 Langfuse 项目密钥时不应声称调用已经追踪。

## 备份与恢复演练

```bash
python3 scripts/production_ops.py backup --directory /var/backups/interviewlens
python3 scripts/production_ops.py restore --file /var/backups/interviewlens/EXACT_FILE.dump --database restore_drill_20261013
```

脚本生成 custom dump、SHA-256 和计数清单，通过 Docker 文件复制，避免 PowerShell 重定向破坏二进制。恢复只接受新的 `restore_...` 库，拒绝覆盖，校验文件 hash，单事务恢复，再核对帖子、题目、向量、摘要和关联数量。备份时暂停写入任务，清单 `counts_stable=false` 说明前后统计有变化，需停写后重做验收，不能视为核对成功。

将 `.service/.timer` 放到 `/etc/systemd/system` 并执行 `systemctl enable --now interviewlens-backup.timer`；每日 03:00 备份，关机漏跑后补执行。检查 `systemctl status interviewlens-backup.service`、`journalctl -u interviewlens-backup.service` 并接入自己的失败通知。保留至少 14 日和最近 3 次已验证版本；磁盘与保留空间由运维监控，脚本不会自行删除唯一可恢复的数据。将备份**加密后复制到服务器之外**，私有环境/ACL、模型下载信息、证书卷也单独加密保留，定期校验并做异机演练。仓库提供流程，但没有替你创建云存储账户或上传私有数据。

Redis 的任务/预算状态在独立持久卷并采用 `noeviction`；缓存可丢弃且采用 `allkeys-lru`。数据库恢复不应重置当天预算、重放旧任务或自动启动 worker。灾难导致状态卷丢失时先保持 worker/付费功能关闭，保守恢复预算再开放。若启用 Langfuse，还需为它的 PostgreSQL 单独备份，主业务 dump 不包含该库。

## 发布、重启与回滚

1. 保存当前 Git SHA、镜像标签/digest、部署环境和备份清单（私有副本）。验收新镜像后推送/保留，不能只保留可被覆盖的 `latest`。
2. 停止写入 worker，生成一份最新备份并在独立库恢复核对。
3. 把 `.env.production` 的 `APP_IMAGE/WEB_IMAGE` 改为已构建的新版本，运行 `up -d api web caddy`；迁移服务每次版本升级需 `up --force-recreate migrate` 并确认成功后启动应用。
4. 检查首页 SSR、公司点击、最新面经展开、真实未缓存语义检索、匿名后台 403/401、管理员登录、非法参数 422、限流 429。重启 API/Web 后再确认同一批数据可读取。
5. 仅应用改动且无不兼容迁移时，把两个镜像标签改回记录的旧版本，`up -d --no-deps api web`，**不要用旧代码重跑 migrate**。
6. 不兼容数据库变更使用已验证备份恢复到新的库，核对后切换数据库 URL，再启动对应旧镜像；不要自动执行破坏性的 down migration，也不要删除生产卷。回滚到备份会损失备份之后的写入，因此保持停写并人工核对差异。

本发布只有 API/UI 和运维工具改动，无业务表结构变化，保留原数据；后续迁移须在恢复副本先做升级与回滚演练。

## 来源与历史数据限制

公开列表只返回已抽取的题目、分类维度和必要来源信息，不返回整段抓取文本、SSR 登录上下文、内部证据 quote/input_hash/origin。后台人工分类仍可查看证据并修改分类。`scripts/audit_public_archives.py` 只读检查并输出受影响 ID，不输出正文或登录用户字段；原始档案保留私下调查。缺少作者正文的存档不猜测补全。

435 份旧摘要保留在后台、标记历史，未重新调用付费模型；本首发不以它们代表最新数据。分类归属不明确的记录仍采用保守筛选，不自动把模糊归属当成精确公司/岗位配对。
