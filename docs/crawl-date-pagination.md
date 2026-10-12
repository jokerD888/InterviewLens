# 发布时间与历史分页修复

## 根因与验证

- 动态帖用 momentData.createdAt，讨论帖用 contentData.createTime。旧 tab 提取与队列日期过滤只读取前者，所以讨论帖入库但日期为 NULL。
- 通用 crawler node 保存 raw_html 时没有向 upsert_raw_post 传入发布时间，因此旧页面采集也会缺日期。页面相对时间、题目中日期、评论时间均不能替代原帖发布日期。
- 旧 job/list 把 level 错当招聘类型，并使用旧岗位编号。2026-10-11 当前官方前端及 selector 表明：level 是岗位树深度；全部为 jobId=-1/level=1，后端为 jobId=11200/level=2，算法/AI 为 11240/level=2。
- 实测接口可能返回不同 current、很大的 totalPage，却给不同请求页返回相同帖子。不能把这种响应当成历史已经爬完，也不能持续增加页码空转。

## 行为

新增 sql/010_crawl_scan_audit.sql，先应用 009 再应用 010。页面身份集合的指纹、扫描日期边界按来源和页码持久化。相同页的重访允许；不同页返回同一集合（含换序）时停止并暂停，原因 pagination_repeated，保持 completed=false，不推进断点。只有有效空页会记录自然结束。新一轮已结束扫描会清理该来源的旧指纹。

backfill-crawl --listing job 使用当前 job/list 参数，并按 jobId/level 保存独立断点，避免与旧 tab 来源混用。来源共用数据库互斥锁，队列 URL 全局唯一；已存在正文不会被重新覆盖。仍保留原来的详情日预算、限速及异常暂停。

例：

```powershell
# 当前岗位树的后端历史批次：一批最多30次详情请求
python -m interviewlens.cli backfill-crawl --listing job --job-id 11200 --job-level 2 --since 2026-07-08
python -m interviewlens.cli backfill-status --listing job --job-id 11200 --job-level 2
```

正确筛选参数使历史分区可配置，但代码无法取消服务器本身的窗口限制。遇到重复页需保留“该区间未验证”的结果，不能宣称七八月份已覆盖。不能通过反复 resume-paused 继续撞同一分页边界。

job/list 导出不再因两页被日期范围过滤而提前结束；依靠原始页身份判断重复，输出尾部包含 stop_reason 和 complete。默认列表请求间隔10秒加1–10秒随机量，序列执行。

## 日期修复

```powershell
# 不访问网站的预览
python -m interviewlens.cli repair-post-dates
# 只利用已保存原始记录修复
python -m interviewlens.cli repair-post-dates --apply
# 仍然缺日期时，最多30次准确元数据请求，11–20秒间隔，无自动重试
python -m interviewlens.cli repair-post-dates --apply --fetch-missing --max-requests 30
```

修复只填写 posted_at IS NULL，按原始记录或官方详情接口精确时间保存证据到 crawl_date_repairs。不修改正文、题目、答案、向量、抽取状态；同一修复可重复执行。不会用 editTime/showTime，亦不会猜测旧快照的年份。详情响应必须与所请求的帖子 ID/UUID 对应；身份不符、登录拒绝、限流或请求异常立即停止并报告剩余数量。已删除/仅作者可见的帖子单独记入 crawl_date_unavailable，保留 NULL，不猜日期，后续自动修复不再访问这些帖子。元数据修复与批采共享互斥锁，单次上限最多150次，默认30次，执行中打印进度，不后台无限重试。

新采集统一解析两种记录的发布时间。通用页面 crawler 从同一详情接口获取发布日期，保留已有日期；浏览器时区固定 Asia/Shanghai。缺少原始记录和日期的详情会保持 NULL，并明确作为未解决项。

页面列表备用发现路径也检测重复 URL 集合并停止，同时补齐内嵌 JSON 中相对帖子链接的提取，避免静默漏掉该类链接。

旧页面快照还有时区风险：本次对52份已恢复精确日期的快照抽查，43份正文时间与 UTC 时钟一致，没有一份与北京时间分钟完全一致。当前官方前端的正文时间文字取自 contentData.showTime 并经本地时间格式化，剩余9份未能与原始发布时间匹配，不能用页面日期替代接口 createTime。新浏览器固定北京时间，数据库写入仍以原始 epoch 转成 UTC。

验证：最终相关测试90项通过、10项因条件未启用跳过，包含“不识别的列表记录不能推进历史断点”的数据库验证。已有验收测试产生一个未等待 sleep 协程的警告；此次未修改该测试。

## 本机执行结果（2026-10-11）

- 010 新增审计表已应用；原采集断点 next_page=12、completed=false，未重置冷却、预算或队列。
- 共966篇帖子，原缺失日期189篇，已恢复185篇：保存的原始记录66篇、官方详情元数据119篇。剩余4篇接口返回不可见，保留NULL并持久化跳过记录。仅修改空 posted_at；题目、题解、向量和抽取状态未改动。
- 日期恢复后，仍无已知发布日期记录的区间为5月23–24日、7月16日–9月19日、10月5–11日。这不是“已确认网站当天无帖子”，仍需验证来源覆盖。
- 使用当前有效参数 jobId=11200、level=2、order=3 实测第100与200页：两页均20条，帖子身份集合 SHA256 完全相同（3499cebec2f5004b0498fbaca3fe849627b4a572144bba34a02d5a8e281e4d12），日期边界均为北京时间2026-09-17 15:31:41至20:38:23。客户端已处理重复分页，但不能修改服务端历史窗口；后续补采需要更细的有效岗位/公司分区或另一个历史入口。
- 用户已取消ARW，采用普通Git流程；修复代码及新启动入口将一起并入main。

## 可见连续采集入口（2026-10-12）

从主项目运行，不再使用旧 hourly-backfill worktree 的启动命令：

```powershell
& .\scripts\start_visible_backfill.ps1
# 只执行一批：
& .\scripts\start_visible_backfill.ps1 -Once
# 旧tab遇到分页边界后，改用新版全部岗位列表；保留7月8日起点：
& .\scripts\start_visible_backfill.ps1 -Listing job -JobId -1 -JobLevel 1 -Since '2026-07-08'
```

连续模式明确设置 continuous=true、cooldown=0、daily=null，取消批间长休息和每日数量上限（2026-10-12按用户要求调整）。每批最多30次详情请求（包括日期元数据请求），每日请求数继续记录，不清零已有计数。列表、详情和日期请求串行使用同一个限速器；相邻请求最少10秒加1–10秒随机间隔，限速器在批次之间保留。普通CLI定时批次仍保持一小时冷却和显式日预算。

控制台逐条显示列表页、详情URL和保存进度，日志位于本机 LOCALAPPDATA/InterviewLens/visible-backfill。已入库URL不会再进入待抓队列；队列URL全局唯一。为应对列表插入和排序变动仍会重访最多两页，这不等于重复请求已入库正文。遇到重复页、鉴权/限流、异常、已有任务占锁或无进展立即停止，不自动清除暂停、不重置断点、不无限重试。Ctrl+C可停止。

本次新入口相关回归验证74项通过，包含真实PostgreSQL重复页/队列/预算检查、连续批次异常停止及日期请求计入每批上限。

2026-10-12：旧tab在第21页返回已见集合，暂停时总库1113篇，当日新增147篇。只读探测新版job/list全部岗位与后端第一页面均为20条有效记录、全部未入库，日期覆盖10月11–12日。切换新版来源从新断点开始，全局正文URL去重继续生效，旧暂停保留；不能据第一页探测推断全部历史可覆盖。启动入口支持上述岗位与起点参数。遇到采集守卫停止时Python返回退出码2，便于区分成功批次与受阻运行。
