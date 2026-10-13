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

## 当前环境阻塞

最后重新构建时，Windows C 盘剩余空间降到 0。Docker/WSL 报只读文件系统，PostgreSQL 报读取 pg_proc 文件的磁盘 I/O 错误，实际 q=Redis 检索返回 500。此后不能把前述成功记录当成当前服务健康证明。

已停止追加构建与数据库写入；独立核验 D 盘主库备份、隔离备份的 SHA-256 均匹配。未删除数据库卷、重建业务库或启动抓取、Celery、付费生成。最后一轮镜像构建未成功，随后调整了 Docker 构建层，调整后的镜像仍待磁盘恢复后验证。

缓存迁移脚本位于 D:\tmp\InterviewLensRuntime\relocate-project-model-cache.ps1，限定迁移本项目使用的 BGE-M3 缓存（19 文件，约 4.6GB），逐文件核对大小和 SHA-256，核验明确源/目标路径后才释放 C 盘原缓存，并将本项目 runtime-env.ps1 的 HF_HOME 指向 D 盘。不迁移用户 HF 凭据。

迁移缓存及重启 Ubuntu-22.04 的用户确认尚待回复；重启会影响该发行版内全部 Linux/Docker 进程。恢复后必须重新验证磁盘、数据库状态、业务数量/指纹、内部探针、公开检索与最终镜像。此时不宣称运行恢复或公网发布完成。

日志位于 D:\tmp\InterviewLensRuntime\reliability-followup-*；常规升级步骤见 [可靠性部署说明](deployment-reliability.md)。
