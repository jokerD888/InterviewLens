# 补充修复与验收：2026-10-13

分支为 codex/deployment-reliability，基于 d660420；未合并 main、未发布公网。

## 已修复

- 015 迁移在业务 DML 之前取得事务写锁；租约 fence、人工编辑、原地复用与离线审核遵循相同顺序。保留提交与缓存失效原子性，不把模型调用放进写锁事务。
- 租约 owner/expiry/payload 等非展示信息不推进缓存版本，阶段实际变化仍推进。被拒绝的领取和零行插入不会推进版本。
- Caddy 拒绝公网深度就绪探针，包含尾斜线与常见编码形式；内部 ready 与公开 live 继续可用。
- 备份监控核对固定生成时间、文件名、文件大小与 SHA-256；恢复验证时间单独记录，不再借清单 mtime 判断新鲜度。
- 每个源库独立保留最新备份与至少三个完整的已恢复验证备份；完整验证不足三个时保留该库所有文件。不自动删除坏文件、无源库清单、链接或未知文件。
- Docker 浏览器依赖移到源码之前的独立构建阶段，避免源码小改动重新下载 Chromium；API 不继承浏览器依赖。

## 已完成的验证

完整测试集为 **315 passed / 11 skipped**，启用了 PostgreSQL 的隔离 schema 测试。新增真实业务交错测试调用实际 backfill_embeddings 与 Bridge generate_answers，模型与 provider 替换为本地确定性 mock：014 复现 SQLSTATE 40P01，015 两项写入均成功。正常未过期的重复领取被拒绝，续期不失效缓存，业务回滚同时回滚版本。

015 已应用本机主库及隔离恢复库。故障发生前：

- 原库七项数量及帖子/题目/分类三项内容指纹，与迁移前备份完全相同；1,211 帖、17,275 题、17,275 向量。
- 本机首页与帖子接口 200，内部 ready 200。
- 隔离 HTTPS 公共 ready（含尾斜线、编码路径）404，live 200，帖子接口 200，匿名管理接口 401。
- 使用真实隔离备份的监控输出 recent_backup=true，并分别给出生成时间与 restore_verified=true。
- 第一轮 API/worker 构建成功；worker 非 root Chromium about:blank 验证成功，外部请求 0。

## 磁盘故障与恢复（已完成）

最后重新构建时，Windows C 盘剩余空间降到 0。Docker/WSL 报只读文件系统，PostgreSQL 报读取 pg_proc 文件的磁盘 I/O 错误，实际 q=Redis 检索返回 500。此后不能把前述成功记录当成当前服务健康证明。

已停止追加构建与数据库写入；独立核验 D 盘主库备份、隔离备份的 SHA-256 均匹配。未删除数据库卷、重建业务库或启动抓取、Celery、付费生成。最后一轮镜像构建未成功，随后调整了 Docker 构建层，调整后的镜像仍待磁盘恢复后验证。

用户先选择手动清理，随后明确授权将 WSL 从 C 盘迁到 D 盘。没有执行 BGE-M3 缓存迁移；HF_HOME 与用户 HF 凭据保持原位置。

2026-10-13 20:10 左右完成 WSL 原生迁移：先停止现有容器并关闭 WSL，再使用 `wsl --manage Ubuntu-22.04 --move D:\WSL\Ubuntu-22.04`。关闭后的虚拟磁盘为 96,693,387,264 字节，迁移前后大小与 SHA-256 完全一致，注册 BasePath 为 D:\WSL\Ubuntu-22.04，C 盘原 VHD 已移除。校验记录在 `D:\tmp\InterviewLensRuntime\wsl-migration-20261013.json`。WSL 交换文件另配置到 D:\WSL\swap.vhdx，保留原 networkingMode/dnsTunneling/autoProxy，原配置已备份。

恢复并重新验收：

- WSL 根文件系统可读写，原有十个容器恢复运行；C 盘剩余约 91GB，D 盘剩余约 96GB（验收时快照）。
- 原库七项数量及三项内容指纹仍与迁移前备份完全一致；1,211 帖、17,275 题、17,275 向量；迁移记录 15 条，四阶段未完成记录 0。pg_proc 与 pgvector 正常可读。
- 本机首页、帖子列表、内部 ready、实际 `q=Redis` 语义检索均为 200；未再遇到此前磁盘 I/O 错误。
- 调整后的最终 API/worker 镜像均构建成功。两者 uid 为 10001；API 为 CPU PyTorch 且不含浏览器目录；worker Chromium about:blank 启动成功，网络隔离，外部请求 0。
- 在隔离恢复库使用实际 il_app 角色执行题目 UPDATE：缓存版本从 1 变为 2，ROLLBACK 后恢复为 1，验证权限与事务原子性。
- 使用最终 API 镜像重建隔离 API；真实备份监控再次返回 ready、recent_backup=true、restore_verified=true。
- 最终镜像的隔离 HTTPS 首页、帖子、语义搜索、live 均为 200；public ready、尾斜线、两种编码形式均为 404；匿名管理接口为 401。TLS 使用本机测试 CA 验证，未关闭证书验证。

恢复日志为 `wsl-migration-verification.log`、`reliability-post-migration-build.log`、`reliability-post-migration-https.log`，均在 D:\tmp\InterviewLensRuntime。未启动抓取、Celery 或付费模型任务，未发布公网。

日志位于 D:\tmp\InterviewLensRuntime\reliability-followup-*；常规升级步骤见 [可靠性部署说明](deployment-reliability.md)。
