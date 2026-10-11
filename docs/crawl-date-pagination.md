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
