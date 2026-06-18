## Context

面试八股学习工具，PWA手机端为主。用户上传PDF/Markdown资料，AI拆解为正反面记忆卡片，按艾宾浩斯遗忘曲线+主动回忆模式每日推送固定配额。现有仓库为空项目，从零搭建。无遗留系统约束。

## Goals / Non-Goals

**Goals:**
- 完整MVP：资料上传→AI拆解→每日卡片推送→自评反馈→统计面板
- PWA支持离线访问和Web Push通知
- 艾宾浩斯调度引擎：默认间隔序列 [1,2,4,7,15,30] 天，用户自评"忘了"→重置为1天，"记住了"→进阶下一级
- 固定每日配额：新卡N张+复习卡M张（可配置，默认N=10, M=20）
- AI按面试频率给卡片打分(1-5)，高分优先推送给用户

**Non-Goals:**
- 不支持多用户协作、社群功能
- 不做iOS/Android原生App
- 不实现卡片间的依赖关系/知识图谱
- 不支持用户手动创建卡片（MVP阶段）
- 不做复杂的NLP语义匹配判题——用户自评即可

## Decisions

### 1. 后端框架：FastAPI

选择FastAPI而非Flask/Django。原因：异步支持好（AI API调用耗时），自动OpenAPI文档，Pydantic数据校验天然适合卡片/用户模型。

### 2. PWA前端：Vue 3 + Vite + Vant UI

选择Vue 3 + Vant UI（移动端组件库）而非React Native。原因：PWA即可覆盖手机端，Vant提供成熟的移动端卡片/日历/进度组件，Vue生态对单人开发更友好。

### 3. 数据库：PostgreSQL + SQLAlchemy

PostgreSQL适合卡片复习状态的复杂查询（按用户+到期日+评分多维度筛选）。SQLAlchemy (async) 与FastAPI集成成熟。

### 4. AI服务：插件式设计

```
┌──────────────────────┐
│   CardGeneratorABC   │  ← 抽象基类
├──────────────────────┤
│  DeepSeekGenerator   │  ← DeepSeek实现
│  QwenGenerator       │  ← 通义千问实现
└──────────────────────┘
```

两个关键Prompt：
- **资料→卡片**: 传入全文，返回JSON数组 `[{question, answer, importance_score}]`
- **批量生成**: 一次调用生成最多20张卡片，减少API开销

### 5. 艾宾浩斯调度引擎

```python
# 核心数据结构
CARD_STATES = {
    "new": -1,      # 未学习
    "level_0": 1,   # 第0次复习后间隔1天
    "level_1": 2,   # 间隔2天
    "level_2": 4,   # 间隔4天
    "level_3": 7,   # 间隔7天
    "level_4": 15,  # 间隔15天
    "level_5": 30,  # 间隔30天
    "mastered": -2  # 已掌握，不再推送
}
```

每日配额逻辑：`到期复习卡(M张)` + `新卡片填充(直到总配额)`。复习卡先于新卡推送。

### 6. Web Push：VAPID + Service Worker

使用 `pywebpush` 后端生成推送，PWA注册Service Worker接收。需要用户授权通知权限。降级方案：定时刷新页面也能看到今日卡片。

### 7. 部署策略

单机Docker Compose部署：FastAPI容器 + PostgreSQL容器 + Nginx反向代理。PWA静态文件由Nginx直接serve。

## Risks / Trade-offs

- **Risk**: AI生成卡片质量不稳定，某些资料拆解出的QA对不精准 → 前端展示"来源段落"，用户可反馈低质量卡片，后续版本加审核
- **Risk**: 用户不上传资料就无法使用 → MVP提示用户上传示例资料，内置几套热门八股卡片作为种子
- **Risk**: Web Push在iOS上支持有限（iOS 16.4+才支持，需添加到主屏幕） → PWA内部有"今日待复习"红点提醒作为降级
- **Trade-off**: 用户自评而非AI判题，可能作弊 → MVP阶段接受，自评"主动回忆"本身有学习效果
- **Trade-off**: 卡片只按时间+级别调度，不按知识点关联 → 简单但有效，后续可加标签系统
