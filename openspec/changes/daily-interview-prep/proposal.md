## Why

面试八股知识点繁多、碎片化，用户缺少科学的复习调度和评估机制。纯手动背效率低，容易遗忘。借AI自动拆解资料生成学习卡片，结合艾宾浩斯遗忘曲线和主动回忆驱动每日推送，系统性提升学习效率。

## What Changes

- 新增PWA前端：提供资料上传、每日卡片复习、进度统计三大界面
- 新增Python后端服务：用户认证、资料解析(PDF/Markdown)、AI卡片生成、艾宾浩斯调度、Web Push推送
- 集成DeepSeek/通义千问API：八股重要性评分、QA卡片正反面生成
- 实现艾宾浩斯+主动回忆调度引擎：固定每日配额(新卡+复习卡)，根据用户自评正确/错误调整下次复习间隔
- 实现手机端Web Push通知提醒

## Capabilities

### New Capabilities

- `user-auth`: 用户注册、登录、JWT认证
- `material-upload`: 上传八股资料(PDF/Markdown)，后端解析提取文本
- `ai-card-generation`: AI分析资料内容，按面试频率评分，生成正反面记忆卡片(问题/答案)
- `review-scheduler`: 艾宾浩斯遗忘曲线调度引擎，计算每日复习配额，根据用户回忆结果调整间隔
- `daily-push`: 每日固定时间推送复习卡片到PWA，支持Web Push通知
- `progress-tracking`: 学习进度统计，展示掌握率、连续打卡天数、卡片状态分布

### Modified Capabilities

<!-- 无现有spec，不作修改 -->

## Impact

- 技术栈：Python (FastAPI) + PostgreSQL + PWA (Vue/React) + DeepSeek API
- 部署：单服务架构，无需微服务
- 依赖：PDF解析库(pymupdf/pypdf)、Markdown解析库、Web Push VAPID密钥
