## Context

**InterviewLens**（Python 3.13 + FastAPI + PostgreSQL + Next.js）爬取牛客大厂面经，LLM 抽取结构化问题存入 `questions` 表。`questions.answer_brief` 字段绝大多数情况下为 `NULL` 或一句话摘要。

**daily-interview-prep**（Python 3.12 + FastAPI + SQLite + Vue 3 PWA）是 AI 卡牌记忆工具。用户上传资料 → DeepSeek 生成 Q&A 卡片 → Ebbinghaus 遗忘曲线调度复习。卡片存入 `cards` 表，用户进度存入 `card_progress` 表。

两系统各自独立运行，通过 HTTP API 互调。本设计聚焦 InterviewLens 端发起导入的完整数据流。

## Goals / Non-Goals

**Goals:**
- InterviewLens 前端支持浏览面经问题时勾选、批量选中
- 对选中问题通过 DeepSeek 生成完整参考答案
- 用户可预览、编辑答案后确认导入
- 确认后调用 daily-interview-prep API，卡片写入对方 SQLite 并自动进入学习队列
- InterviewLens 持有 daily-interview-prep 的 JWT token，代用户认证

**Non-Goals:**
- 不在 daily-interview-prep 前端加任何新功能
- 不修改两系统的现有数据模型和 API
- 不实现双向同步（卡片修改不回写 InterviewLens）
- 不实现 real-time 推送，本方案是用户主动触发的批量导入

## Decisions

### 1. 桥接由 InterviewLens 后端中转

**决策**：InterviewLens 后端新增 `/api/bridge/` 路由组，前端调 bridge API，后端调 DeepSeek 生成答案 + 调用 daily-interview-prep 导入 API。

**替代方案**：前端直接调 daily-interview-prep API。**不采用**——前端不应持有 DeepSeek API Key，且跨域调用两个后端在 CORS 和认证上更复杂。

### 2. AI 答案生成在 InterviewLens 端完成

**决策**：生成答案的 prompt 和逻辑放在 InterviewLens 的 bridge 路由中，不经过 daily-interview-prep 的 card_generator。原因：
- daily-interview-prep 的 card_generator 设计为从大段资料中生成多张卡片，而桥接场景是"已有明确问题，只需生成答案"
- 专用 prompt 可生成更精准的答案（可传入 company/position 上下文）
- 用户在 InterviewLens 端可预览编辑答案后再确认导入

**替代方案**：调 daily-interview-prep 已有的 card_generator。**不采用**——card_generator 的 PROMPT 要求输入大段文本资料生成多张卡片，与"单问题单答案"场景不匹配。

### 3. 导入 API 设计：POST /api/cards/bulk-import

**决策**：在 daily-interview-prep 新增一个专用导入端点。

请求体：
```json
{
  "cards": [
    {
      "question": "请解释 JVM 内存模型",
      "answer": "JVM 内存模型分为线程共享的堆和方法区...",
      "importance_score": 4
    }
  ]
}
```

响应：
```json
{
  "imported": 3,
  "skipped": 1,
  "skipped_reasons": ["问题重复: '请解释 JVM 内存模型'"]
}
```

- 导入时按 `(user_id, question)` 去重，重复问题跳过
- 新卡片的 `scheduler_state = "new"`, `review_count = 0`, `next_review_at = today`
- `importance_score` 由用户指定（InterviewLens 端生成答案时可附上评分）

### 4. 认证方式：服务器间 Token（Server-to-Server）

**决策**：InterviewLens 后端通过配置项持有 daily-interview-prep 用户的 JWT token。调用导入 API 时，在 Authorization header 中传入。

```python
# InterviewLens config.py
daily_prep_api_url: str = "http://localhost:8000/api"
daily_prep_token: str = "eyJ..."
```

**替代方案**：实现 OAuth 授权流程。**不采用**——过度复杂，两个自用项目不需要标准授权协议。用户手动从 daily-interview-prep 获取 token 填入 InterviewLens 的环境变量即可。

### 5. 前端交互设计

**InterviewLens 前端改动**：

1. 问题搜索 `/search` 页面：每个 `QuestionCard` 加 checkbox
2. 顶部操作栏：已选 N 个问题，按钮"加入八股"（未选禁用）
3. 点击后弹窗：显示每个问题的 AI 生成答案，可编辑，显示预估 time/score
4. 确认按钮：调 bridge API 最终导入
5. 结果提示：成功 X 个，跳过 Y 个

### 6. 导入的问题不会回写 InterviewLens

**决策**：导入到 daily-interview-prep 后，不在 InterviewLens 的 `questions.answer_brief` 中记录已导入状态。两系统各自维护自己的数据完整性。

## Risks / Trade-offs

- **[风险] 两系统数据库脱节**：InterviewLens 的 question 和 daily-interview-prep 的 card 之间没有关联。同一问题可能被多次导入。→ **缓解**：导入 API 按 `(user_id, question)` 去重，防止同用户重复导入同一问题。如需追踪，可在 daily-interview-prep 的 cards 表加 `source_url` 字段存储面经来源链接。
- **[风险] Token 泄露**：InterviewLens 的 `.env` 中明文存储 daily-interview-prep 的 JWT。→ **缓解**：JWT 本身有过期时间，且两个服务部署在同一内网，外部不可达。
- **[风险] 答案质量差**：AI 生成的答案可能不准确。→ **缓解**：提供编辑预览环节，用户可在确认前修改答案。后续可加入答案评分反馈机制。
- **[取舍] 不双向同步**：用户修改了 daily-interview-prep 中的答案，不会回写 InterviewLens。这是刻意设计，保持两系统解耦。
