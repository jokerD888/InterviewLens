# InterviewLens 项目审查（2026-10-13）

审查基线：main / 0b3ac4d。范围为当前采集入口、LangGraph 流水线、归一化、岗位分类、聚合、向量检索、Celery、API 和前端。此次仅做审查并新增报告，未修改业务代码、未处理待抽取帖子、未调用付费 LLM、未恢复牛客采集。数据库检查为只读；数据库测试使用独立临时 schema。

判断：现有技术栈可以继续使用。优先修复聚合读列错误、异步任务取消和阶段恢复，再打通新数据索引链路。部署前还需要修补前端依赖和后台接口安全。没有依据要求把当前规模的项目拆成微服务或更换数据库。

## 验证结果与当前数据

- 后端全量 pytest：230 通过、2 失败、11 跳过、1 个既有未等待协程警告。启用了隔离 PostgreSQL 补采测试；未开启会操作业务行的岗位分类集成测试和额外数据库时间测试。
- 前端 TypeScript：`tsc --noEmit --incremental false` 通过。这不代表生产构建或端到端交互全部通过；本次没有做漏洞攻击、生产负载或浏览器全流程测试。
- PostgreSQL：1211 篇帖子，801 篇 `done`、410 篇 `pending`；10080 道题，现有题目均有向量且版本为 2；10010 道题已有 AI 答案；435 份摘要。
- 118 篇 `done` 帖子没有公司关联。这可能包含原文未提供公司名称的帖子，不能仅据此认定为归一化失败。
- 12 篇帖子同时关联多个公司和多个旧岗位；需要检查真实公司—岗位配对，而不能把这个数字直接当作错误数量。
- 本次新增的 245 篇正文仍待抽取，因此没有新增对应题目与向量。现有题目向量完整，不代表新增正文已经可以语义检索。

优先级说明：P0 为有对外可达部署时应立即处理的严重安全项；P1 为错误输出、任务一致性或部署保护问题；P2 为后续可靠性与数据质量问题。没有实测的业务污染不作既成事实描述。

## 1. 聚合 SQL 结果按旧列顺序读取 — P1，已实库复现

位置：[aggregator.py:144](D:/code/Resume/个人github项目/InterviewLens/src/interviewlens/aggregator/aggregator.py:144)、[aggregator.py:174](D:/code/Resume/个人github项目/InterviewLens/src/interviewlens/aggregator/aggregator.py:174)。

SQL 实际选择的是 `id, post_id, content, category, answer_brief, content_score, source_url`，Python 仍把第二列当题干，并将后面的字段整体错读。

只读调用当前 `_fetch_candidate_questions(top_n=1)` 返回了：`content` 为整数、`source_url` 为整数、`content_score` 为 None，并且缺少 `post_id`。若最后一行的答案要点是普通文本，`int(rows[-1][4])` 还会触发 ValueError；如果答案为空，则分页游标误用 0，可能提前结束。

影响：聚合输入、分页、题次/篇次和引用来源都可能错误。现有 435 份摘要不能据此全部认定已污染，需追溯生成版本；但应先修复再重跑当前聚合代码。

建议：用 `mappings()` 和具名字段读取，显式传递 `post_id`；加入真实 PostgreSQL 选数→分页→聚类→统计测试。现有聚类测试多直接构造字典，未覆盖 SQL 行到字典的转换。

## 2. 抽取后续阶段缺少可恢复状态 — P1，故障注入复现

位置：[extractor.py:78](D:/code/Resume/个人github项目/InterviewLens/src/interviewlens/agent/nodes/extractor.py:78)、[normalizer.py:50](D:/code/Resume/个人github项目/InterviewLens/src/interviewlens/agent/nodes/normalizer.py:50)、[recovery.py](D:/code/Resume/个人github项目/InterviewLens/src/interviewlens/agent/recovery.py)。

Extractor 写完题目就提交 `extract_status=done`，之后才归一化和评分。故障注入让 normalizer 抛异常后，已经写入的状态仍为 done。部分实体解析失败时，normalizer 还会记录日志后继续，以成功解析的子集替换旧关联。

`extract_status` 表示“抽取完成”本身可以成立；问题是没有独立的归一化/评分完成状态或持久任务，`resume_failed(pending,failed)` 无法补做这些后续阶段。读接口又用 done 判断可展示，可能出现题目已出现、公司关联不完整的状态。

建议：分别记录抽取、归一化、评分、索引阶段的状态与失败原因；支持从失败阶段恢复。完成抽取后原子写入后续任务记录，避免进程在两阶段间退出时丢失任务。不要为修复归一化而重新支付一次抽取费用。

## 3. Celery 软超时未取消后台协程 — P1，模拟复现

位置：[pipeline.py:74](D:/code/Resume/个人github项目/InterviewLens/src/interviewlens/tasks/pipeline.py:74)、[celery_app.py:29](D:/code/Resume/个人github项目/InterviewLens/src/interviewlens/tasks/celery_app.py:29)。

后台 bridge 默认等 600 秒，Celery 软/硬超时分别为 240/300 秒。桥接只在 TimeoutError 时执行 `future.cancel()`，软超时异常 SoftTimeLimitExceeded 不在此分支。

用抛出 SoftTimeLimitExceeded 的 future 做故障注入，异常传出，但 `future.cancel` 没有调用。该模拟验证了取消遗漏，未进行真实 prefork worker 超时攻击或长任务压测。实际软超时是否触发也与 worker pool/平台有关。

影响：在支持软超时的 worker 中，Celery 开始重试后，旧协程可能继续消耗模型额度或写库，直到完成或进程被硬杀。

建议：让桥接截止时间小于 Celery 软超时；捕获软超时及调用方中断，取消协程并等待有界清理；同时为同一帖子处理加入任务占用与幂等写入，不能只依赖 cancel 防重。

## 4. 前端依赖存在已披露严重漏洞 — 对外可达时 P0，版本已核实

位置：[package.json:15](D:/code/Resume/个人github项目/InterviewLens/web/package.json:15)。

package.json 与实际 node_modules 均为 Next.js 15.0.3、React 19.0.0，项目使用 App Router。该组合在官方公布的 RSC 漏洞受影响范围内，包含无需认证的远程代码执行风险。这里只核对版本与官方影响范围，没有执行攻击，也没有发现被入侵的证据。

依据：[Next.js 官方 RSC 安全公告](https://nextjs.org/blog/CVE-2025-66478)、[React 官方公告及后续更新](https://react.dev/blog/2025/12/03/critical-security-vulnerability-in-react-server-components)。

建议：升级到受支持且覆盖后续安全补丁的版本，更新 lockfile，验证生产构建、App Router 与反向代理。不要只升级到第一份公告的最低修复版本，因为随后还有额外修补。仅本机不可对外访问会缩小暴露面，但不会改变版本受影响的事实。

## 5. 管理、生成与导出接口缺少统一鉴权 — P1，模拟请求复现

位置：[routes_admin.py:17](D:/code/Resume/个人github项目/InterviewLens/src/interviewlens/api/routes_admin.py:17)、[routes_bridge.py:22](D:/code/Resume/个人github项目/InterviewLens/src/interviewlens/api/routes_bridge.py:22)。

岗位编辑器有本机来源检查，但其他 admin 路由、AI 答案生成、对外导出未加同等保护。用远端地址的 TestClient、mock 掉真实 `.delay()` 后，无认证 POST `/admin/ingest` 返回 200 并调用了入队函数。

影响取决于服务可达性：若开放前端代理、局域网或公网，可被非管理员触发抓取、费用支出、死信清空或导出操作。当前 CORS 全放开也没有提供权限保护。

建议：统一管理员认证与授权，生成接口加并发/频率约束、幂等键和费用预算。费用保护是 LLM 维度；不恢复用户已取消的采集每日100次上限。权限需要后端强制执行，而不只隐藏按钮。

## 6. 抓取域名白名单使用子串判断 — P1，模拟复现

位置：[playwright_runner.py:128](D:/code/Resume/个人github项目/InterviewLens/src/interviewlens/crawler/playwright_runner.py:128)。

`"nowcoder.com" in host` 会放行 `nowcoder.com.attacker.invalid`。用 mock 抓取器验证该域名确实进入 `_do_fetch`；没有访问这个域名。协议、跳转后地址和页面子资源也没有统一入口限制。

这会扩大不受信任站点与内网请求的风险，尤其与未鉴权的手动抓取接口组合。不能据此宣称已发生 Cookie 泄漏或内网攻击。

建议：限定 https 和确切允许的牛客主机/帖子路径，校验重定向目标；限制不必要的浏览器外部请求。已有 metadata_api 的严格路径校验可作为统一入口规则的一部分。

## 7. 摘要 HTML 渲染缺少净化 — P1，危险输出已复现

位置：[summary-view.tsx:85](D:/code/Resume/个人github项目/InterviewLens/web/src/components/summary-view.tsx:85)、[prompts.py:146](D:/code/Resume/个人github项目/InterviewLens/src/interviewlens/llm/prompts.py:146)。

摘要页面启用 rehypeRaw，没有 HTML sanitize。后端虽用结构化 JSON 生成 Markdown，但 topic、建议、原题等字符串仍直接插入 Markdown，因此“结构化输出”不等于“安全 HTML”。

用项目安装的 ReactMarkdown/rehypeRaw 做静态渲染，iframe 的 srcDoc 内含 script 时仍输出该 iframe，且没有 sandbox。这里只验证危险结构未过滤，未在浏览器执行脚本；是否被额外部署层 CSP 限制未核实。AnswerBlock 没有开启 rehypeRaw，不应将该问题泛化到所有答案组件。

建议：去掉 raw HTML，或仅净化放行用于计数的 sub 等少量标签；禁止 iframe、脚本、表单和危险属性。对后端自由文本做恰当转义，CSP 作为附加保护。

## 8. 日常流水线被采集暂停阻断，而且没有索引阶段 — P1/P2，代码与现状相符

位置：[daily.py:45](D:/code/Resume/个人github项目/InterviewLens/src/interviewlens/tasks/daily.py:45)、[embedding/backfill.py](D:/code/Resume/个人github项目/InterviewLens/src/interviewlens/embedding/backfill.py)。

daily_update 在采集返回非 complete 时直接退出，后续不会处理已有 pending。当前它调用的旧 tab 来源已经 pagination_repeated 暂停，因此常规 daily 调用会停在这里。即便采集成功，后续只有抽取→聚合→答案，没有题目向量构建；搜索和聚合又过滤缺少当前版本向量的题目。

已有10080道题的向量均完整，这个问题主要影响今后新增题目。当前410篇 pending 包含本轮新增245篇，不能将它们计入可检索题目。

建议：采集、处理既有正文、索引与聚合应有独立调度与状态。采集受分页边界阻断时，仍可处理已经安全保存的数据；按新增/变更题目做增量嵌入，然后刷新聚合和缓存。状态统计应区分“尝试处理”与“成功完成”，不能只用返回列表长度当成功数。

## 9. 公司×岗位笛卡尔积仍会制造未经证明的配对 — P1/P2，设计风险

位置：[repositories.py:205](D:/code/Resume/个人github项目/InterviewLens/src/interviewlens/db/repositories.py:205)、[schema.py](D:/code/Resume/个人github项目/InterviewLens/src/interviewlens/llm/schema.py)。

当前抽取结构提供 companies、positions 两个独立数组，replace_post_links 将两者全组合。比如原文分别讨论 A 公司后端和 B 公司客户端，也会关联成 A 客户端、B 后端。搜索用 EXISTS 已解决重复行占据 Top-K，但不能修复配对语义错误。

更深的问题是题目只挂在 post 下，整篇多家公司/岗位的汇总帖中，每道题会继承帖子全部标签。实库12篇多公司且多岗位只证明这种情况存在，尚未逐篇判断错误归属。

建议：增加“单次面试/面试经历”层，记录该次公司、岗位 profile、轮次与所属题目；不能确定时保留未明确归属，而不是自动生成所有配对。旧数据迁移要保留原始证据。

## 10. 并查集聚类存在真实的代表题漂移 — P2，实库向量复现

位置：[aggregator.py:287](D:/code/Resume/个人github项目/InterviewLens/src/interviewlens/aggregator/aggregator.py:287)。

算法允许 A≈B、B≈C 的连通分量合并，不能保证 A≈C。用实库最大合格桶中的255道题及已有向量进行离线聚类，得到207簇；有2个成员与其代表题的相似度低于0.92，其中最低0.865。

例子：`vector 扩容流程是什么？` 与 `vector 什么情况下扩容？` 被放入同一4题簇，代表题相似度为0.865。它们讨论同一技术但提问角度不同。该结果证明链式漂移真实存在，不能据此推算全库误合并率，也不能断言任何宽主题归并都错。

建议：明确“同一考点”和“可复用同一答案的同义题”两种聚类目标；若用于题目去重，要求成员与代表题达到阈值，或使用更严格的簇内约束。建立真实正负题对、簇纯度与召回评测。保留同簇原题，不让主题频次代替问题细节。

## 11. 多入口的发布时间、限速和异常处理没有统一 — P2，代码确认

位置：[orchestrator.py:49](D:/code/Resume/个人github项目/InterviewLens/src/interviewlens/crawler/orchestrator.py:49)、[playwright_runner.py:147](D:/code/Resume/个人github项目/InterviewLens/src/interviewlens/crawler/playwright_runner.py:147)、[pipeline.py:126](D:/code/Resume/个人github项目/InterviewLens/src/interviewlens/tasks/pipeline.py:126)。

generic FetchResult 已带 published_ms，但 crawl_one 写库时仍未传 posted_at，新帖仍可能丢失已取得的日期。通用 fetch 路径也未像 bounded 路径一样调用响应状态/验证码守卫。Celery crawl_url 各自创建 fetcher，使用实例限速器，不共享可见补采的 PostgreSQL 互斥及跨批次限速。

后果：用户以为“统一限速、停止条件和日期修复”适用于所有入口，实际只有部分路径成立。多个 worker 还可能将单个实例的请求速率叠加。

建议：统一“请求守卫→提取元数据→保存正文”的服务入口；各调度器只负责调度，共用站点限速与停止状态。各入口明确遵守当前用户配置的数量策略，避免手动和任务路径有不同的隐藏限制。

## 12. 死信重放在发布失败时可能丢任务 — P2，失败路径可推导

位置：[pipeline.py:230](D:/code/Resume/个人github项目/InterviewLens/src/interviewlens/tasks/pipeline.py:230)。

dlq_drain 先 LPOP，再 `.delay()`。发布失败时，已弹出的条目没有补回；未知 task_name 也会消耗条目而不重放。此次没有操作真实死信队列。

建议：先移到 processing 列表，成功发布后确认删除，失败恢复；或者持久任务表/Outbox。记录每条重放成功与失败，不只统计弹出数量。

## 13. 客户端生命周期与测试契约存在问题 — P2，测试失败已记录

位置：[app.py:25](D:/code/Resume/个人github项目/InterviewLens/src/interviewlens/api/app.py:25)、[observability.py:69](D:/code/Resume/个人github项目/InterviewLens/src/interviewlens/observability.py:69)、[test_answerer.py:76](D:/code/Resume/个人github项目/InterviewLens/tests/test_answerer.py:76)。

两个失败分别是：

1. test_generate_one_none_on_api_failure：测试 mock get_client 抛 RuntimeError，而当前生成函数只把 APIError/TimeoutError 转成 None。测试与收窄异常的实现约定不一致，不能据此声称真实的 OpenAI APIError 未被处理。
2. test_summary_404_when_missing：多次 TestClient 生命周期复用全局 async Redis 连接，引发 Event loop is closed。API lifespan 只 warm 模型，没有关闭并清空 Redis/HTTP/DB 客户端。这个失败发生于多事件循环测试环境，不能直接推广为当前单事件循环服务每个请求都会失败。

建议：统一客户端创建与关闭生命周期，worker fork 时检查所有跨进程资源；测试隔离外部 Redis 并清理单例。明确“外部故障降级、逻辑错误抛出”的异常契约，再更新对应测试，避免靠扩大 except 隐藏缺陷。

## 14. 同一帖子处理缺少显式领取/版本控制 — P2，并发设计风险

位置：[recovery.py](D:/code/Resume/个人github项目/InterviewLens/src/interviewlens/agent/recovery.py)、[repositories.py:133](D:/code/Resume/个人github项目/InterviewLens/src/interviewlens/db/repositories.py:133)。

resume 查询 pending/failed 后没有将记录原子领取为处理中；Celery、人工恢复和另一批恢复可能同时选中同一帖子。replace_questions 先读取旧题再同步写入，没有同一 post 的处理占用，保存 profile 时的锁也晚于题目快照读取。

可能出现重复模型调用、两份初次题目集合、旧任务覆盖新结果。这次未做真实并发写入压测，属于代码路径可推导的风险，不能声称数据库当前已有这类重复。

建议：持久任务租约或 SKIP LOCKED 领取、按 post 的处理锁、内容版本与乐观写入校验；明确崩溃后何时可以重新领取。LLM 请求结束前后都要检查任务版本，重试使用幂等键。

## 后续优化，不建议先做大规模重构

1. **统一四维分类与旧岗位摘要。** 前端方向过滤和人工纠正基于 post_position_profiles；旧聚合仍基于 Position 和 post_company_position。人工改“后端→客户端”不会自动修正旧摘要分桶。逐步让新摘要使用稳定类别/方向标识，原始岗位名作为证据保留；无需把待审核提示重新显示给用户。
2. **区分历史补采和最新增量。** 当前保存历史 cursor 很合理，但暂停来源不再扫最新页。独立记录最新增量起点和历史覆盖状态；按时间窗报告已发现、已抓、已抽取和可检索数量。服务端重复页不能视为该日期之后没有帖子。
3. **改善缓存与费用可追溯性。** AI 答案缓存只包含题干和 prompt version，未含 category/model；改模型或分类可能复用旧答案。interactive 写入后应刷新对应读取缓存。别名 Tier1 固定返回 confidence=1，也会丢掉实际低置信映射的含义；保存/返回实际来源和置信，不强制增加用户端审核流程。
4. **控制 LLM 并发和重试。** 离线答案并发硬编码100，网页生成最多50题逐个等待；改为可配置额度与后台任务进度。call_tool 对任意 Exception 重试，并可能叠加 SDK 重试；区分429/暂时网络故障、无效输入、校验失败和程序错误，统计所有计费调用，而不是只有最终成功输出。
5. **把检索和聚合效果做成评测。** 当前直接余弦 Top-K 缺少与关键词检索的对照；先用真实查询评测 Recall@K 和结果相关性，再判断是否需要词法+向量混合召回。聚类精确两两比较仍为 O(n²d)，现阶段桶规模有限；只有实测成为瓶颈时才考虑近邻候选建图。
6. **保留可重处理的原始证据。** bounded 采集主要保存 cleaned_text 和列表记录，缺少完整原始页面快照；后续改清洗规则或证明正文来源时可能只能重新访问原站。统一保存必要的正文原始响应、抓取时间、内容哈希和解析版本，避免把业务需求绑定在浏览器再次可访问上。

## 建议修复顺序

1. 若服务对外可达，首先升级受影响依赖并保护管理/生成接口；本机开发也应尽快完成。
2. 修复聚合行映射，增加 SQL 到业务对象的真实数据库回归，再核验现有摘要。
3. 修复 Celery 软超时取消、任务领取与阶段恢复。
4. 打通已有正文→抽取→增量嵌入→聚合→缓存刷新链路，给当前 pending 做可见的分批处理。
5. 调整公司—岗位—问题归属模型，完成代表题约束和真实聚类评测。
6. 再根据实测做缓存、模型加载、批处理和查询性能优化。

无需推倒重来的部分：PostgreSQL+pgvector、URL唯一约束、EXISTS 搜索过滤、固定11类/四个正交维度、人工分类的乐观并发、重抽保留旧题派生数据、分区断点与重复页审计都值得保留。它们已有实际作用；目前最欠缺的是模块之间的完整性约束、恢复能力和回归覆盖。

## 本机复现脚本

- [project_audit_probe.py](D:/tmp/InterviewLensRuntime/project_audit_probe.py)：只读实库聚合选数、实库向量聚类漂移、mock Celery软超时。
- [project_audit_boundary_probe.py](D:/tmp/InterviewLensRuntime/project_audit_boundary_probe.py)：mock 管理接口入队、域名白名单及 normalizer 失败后的状态，不请求外部站点、不调用付费模型。
- HTML 净化问题通过本机 react-dom/server + ReactMarkdown + rehypeRaw 静态渲染验证，未做浏览器脚本执行。

以上复现和只读检查没有证明项目完全无其他问题；本报告明确列出本轮发现及验证边界，下一轮应优先覆盖修复后的真实端到端链路。
