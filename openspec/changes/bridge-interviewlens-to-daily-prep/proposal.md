## Why

InterviewLens 能爬取大量面经并提取问题，但这些问题绝大多数没有答案（answer_brief 为空或只有一句），用户看完问题后无法系统化记忆。daily-interview-prep 有完整的 AI 卡牌生成和 Ebbinghaus 遗忘曲线复习系统，但内容来源单一（用户上传 PDF/Markdown）。两个系统打通后，用户可以在 InterviewLens 中浏览面经发现高频问题，一键生成答案并导入每日八股进行科学复习，形成"发现 → 理解 → 记忆"的完整学习闭环。

## What Changes

- **InterviewLens 前端**：面经问题搜索/浏览页面增加勾选框、"加入八股"按钮、答案预览与编辑弹窗
- **InterviewLens 后端**：新增桥接 API（bridge）调用 DeepSeek 为选中问题生成参考答案，生成后调用 daily-interview-prep 的导入接口
- **daily-interview-prep 后端**：新增 `POST /api/cards/bulk-import` 接口接收外部卡片导入，自动分配重要性评分并加入学习队列
- **daily-interview-prep 前端**：无改动（导入的卡片直接出现在 Home 待复习卡片中）

## Capabilities

### New Capabilities

- `bridge-export`: InterviewLens 端桥接能力——批量选中问题、调用 AI 生成答案、用户确认后导出到 daily-interview-prep
- `bridge-import`: daily-interview-prep 端桥接能力——接收外部卡片批量导入，验证认证、去重、写入卡片表和用户进度表

### Modified Capabilities

无（两个项目各自现有功能不变）

## Impact

- **InterviewLens**：
  - `src/interviewlens/api/`：新增 `routes_bridge.py`（桥接 API 路由）
  - `web/src/components/question-card.tsx`：增加复选框和操作按钮
  - `web/src/app/search/`：增加批量操作工具栏和答案预览弹窗
  - `src/interviewlens/config.py`：新增 daily-interview-prep API 地址和 JWT token 配置项
- **daily-interview-prep**：
  - `backend/app/api/cards.py`：新增 `POST /api/cards/bulk-import` 端点
  - `backend/app/schemas/`：新增导入请求/响应的 Pydantic schema
- **依赖**：无新依赖，复用现有 DeepSeek API 和 httpx
- **认证**：InterviewLens 通过配置项持有 daily-interview-prep 的 JWT token，代用户调用导入 API
