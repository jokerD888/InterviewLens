## 1. 项目脚手架

- [x] 1.1 初始化Python项目：FastAPI + SQLAlchemy + Alembic + 项目目录结构
- [x] 1.2 初始化Vue 3 + Vite + Vant UI PWA项目，配置Service Worker和manifest.json
- [x] 1.3 编写Docker Compose：FastAPI + PostgreSQL + Nginx
- [x] 1.4 配置环境变量管理（.env），定义DB连接、JWT密钥、AI API Key、VAPID密钥

## 2. 用户认证 (user-auth)

- [ ] 2.1 实现User模型和数据库迁移
- [x] 2.2 实现注册接口 POST /api/auth/register
- [x] 2.3 实现登录接口 POST /api/auth/login，返回JWT
- [x] 2.4 实现JWT认证中间件，保护后续API
- [x] 2.5 PWA登录/注册页面

## 3. 资料上传 (material-upload)

- [x] 3.1 实现Material模型和数据库迁移
- [x] 3.2 实现PDF文本解析（pymupdf/pypdf）
- [x] 3.3 实现Markdown文本解析
- [x] 3.4 实现上传接口 POST /api/materials
- [x] 3.5 实现资料列表接口 GET /api/materials
- [x] 3.6 实现删除接口 DELETE /api/materials/{id}
- [x] 3.7 PWA上传页面（文件选择 + 上传进度 + 资料列表）

## 4. AI卡片生成 (ai-card-generation)

- [x] 4.1 实现Card模型和数据库迁移
- [x] 4.2 实现AI服务抽象基类和DeepSeek实现
- [x] 4.3 实现卡片生成服务：分块文本 → 调用AI → 解析JSON → 存储卡片
- [x] 4.4 实现材料处理状态机（uploaded → processing → completed/failed）
- [x] 4.5 PWA材料详情页，展示卡片生成状态和卡片列表

## 5. 艾宾浩斯调度引擎 (review-scheduler)

- [x] 5.1 实现CardProgress模型和数据库迁移
- [x] 5.2 实现调度核心：间隔序列 [1,2,4,7,15,30]，推进/重置逻辑
- [x] 5.3 实现每日配额计算API GET /api/daily-cards（到期复习+新卡填充）
- [x] 5.4 实现复习提交接口 POST /api/reviews（记住/忘了 + 更新进度）
- [x] 5.5 PWA卡片复习页面：正面问题 + 翻转看答案 + 自评按钮（记住/忘了）

## 6. 推送通知 (daily-push)

- [x] 6.1 实现Web Push订阅管理接口 POST/DELETE /api/push-subscription
- [x] 6.2 实现定时推送任务（APScheduler/cron），查询到期用户并推送
- [x] 6.3 PWA注册Service Worker，处理push事件和通知点击
- [x] 6.4 PWA今日卡片页面（复习卡片队列 + 翻转交互）

## 7. 学习进度统计 (progress-tracking)

- [x] 7.1 实现进度统计接口 GET /api/progress
- [x] 7.2 实现连续打卡天数计算逻辑
- [x] 7.3 实现复习日历接口 GET /api/progress/history
- [x] 7.4 PWA统计面板页面（掌握率环形图 + 打卡日历 + 卡片状态分布）

## 8. 种子数据与测试

- [x] 8.1 准备3套内置八股种子卡片（Java基础、Spring、操作系统各20张）
- [x] 8.2 编写后端核心API的单元测试
- [x] 8.3 端到端测试：注册→上传→生成卡片→复习→统计
