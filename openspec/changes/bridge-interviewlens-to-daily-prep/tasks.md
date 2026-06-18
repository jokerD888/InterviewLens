## 1. daily-interview-prep：导入 API

- [x] 1.1 新增 `backend/app/schemas/bridge.py`：定义 `BulkImportRequest`（cards 列表）和 `BulkImportResponse`（imported/skipped/skipped_reasons）
- [x] 1.2 在 `backend/app/api/cards.py` 新增 `POST /api/cards/bulk-import` 端点：JWT 认证、请求校验、去重检查（按 user_id + question）、写入 cards 表和 card_progress 表
- [x] 1.3 新卡片默认值：`scheduler_state="new"`、`review_count=0`、`next_review_at=今天`、可选 `source_url`；`material_id` 改为 nullable
- [x] 1.4 在 `backend/app/main.py` 注册 card_router 并添加 auth 依赖

## 2. InterviewLens：后端桥接 API

- [x] 2.1 在 `src/interviewlens/config.py` 新增配置项：`daily_prep_api_url` 和 `daily_prep_token`
- [x] 2.2 新增 `src/interviewlens/api/routes_bridge.py`：桥接路由模块
- [x] 2.3 实现 `POST /api/bridge/generate-answers`：接收 question_id 列表，查 questions 表获取内容，逐条调用 DeepSeek 生成参考答案（含 company/position 上下文），返回 {question, generated_answer, importance_score}
- [x] 2.4 实现 `POST /api/bridge/export`：接收确认后的卡片列表，调用 daily-interview-prep 的 `POST /api/cards/bulk-import`（带 Authorization header），返回导入结果
- [x] 2.5 在 `src/interviewlens/api/app.py` 注册 bridge 路由

## 3. InterviewLens：前端交互

- [x] 3.1 在 `web/src/components/question-card.tsx` 增加 checkbox，受控于父组件的选中状态
- [x] 3.2 在 `web/src/app/search/page.tsx` 增加顶部操作栏：已选数量 + "加入八股"按钮（disable when 0）
- [x] 3.3 实现全选/取消全选逻辑
- [x] 3.4 新增答案预览弹窗组件：显示问题列表+AI 生成答案（可编辑 textarea）+ importance_score 显示 + 确认/取消按钮
- [x] 3.5 调 `POST /api/bridge/generate-answers` → 显示预览弹窗 → 用户编辑 → 确认后调 `POST /api/bridge/export` → 显示结果 toast
- [x] 3.6 在 `web/src/lib/api.ts` 新增 bridge API 调用函数

## 4. 集成测试

- [x] 4.1 编写 `tests/test_bridge.py`：测试 generate-answers 和 export 端到端流程（mock daily-interview-prep 响应）
- [x] 4.2 编写 daily-interview-prep 端 `tests/test_bulk_import.py`：测试批量导入、去重、认证
- [ ] 4.3 手动端到端验证：InterviewLens 搜索 → 勾选问题 → 生成答案 → 编辑 → 导入 → 在 daily-interview-prep 中看到新卡片
