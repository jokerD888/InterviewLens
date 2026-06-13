# TODO

## 🔧 已修复的 Bug（记录，供参考）

| # | 问题 | 文件 | 修复方式 |
|---|------|------|----------|
| 1 | 循环导入：`embedding` / `llm` / `crawler` 三个包内部 `..self` 自引用 | `embedding/backfill.py` `llm/orchestrator.py` `crawler/orchestrator.py` | 改为模块内直接 `from .xxx import` |
| 2 | `created_at` / `fetched_at` 等列 NOT NULL 但 ORM 默认 None | `db/models.py` | 改为 `default_factory=_now` + `server_default` |
| 3 | `seed_demo.py` / `repositories.py` / `aggregator.py` 使用 `datetime.now(timezone.utc)`（带时区）写入无时区列 | 对应文件 | 改为 `.replace(tzinfo=None)` |
| 4 | `deepseek-v4-flash` 默认思考模式不支持 function calling | `llm/deepseek.py` | `call_tool()` 增加 `extra_body={"thinking": {"type": "disabled"}}` |
| 5 | aggregator SQL 中 `None` 参数类型无法被 asyncpg 推断 | `aggregator/aggregator.py` | `:period IS NULL` → `CAST(:period AS TEXT) IS NULL` |

---

## 📝 待做

### Prompt 调优
- [ ] **MCP / Skills 等 AI Agent 术语识别**：提取阶段的 `EXTRACTOR_SYSTEM` prompt 缺少 AI Agent 领域术语表，导致这类新兴概念被归类为「其他」或产生幻觉。建议：
  - 在 `question.category` 增加一个 `AI工具/Agent` 分类
  - 或在 prompt 中补充术语指南（MCP → 协议类, Skills → 工具类）
  - 参考项目文档 `docs/DAY13_INGESTION_TUNING.md`

### 数据质量
- [ ] 清理器 `clean_html` 对牛客新页面模板的清洗效果待验证（`test_cleaner.py::test_clean_extracts_main_text` 断言失败，可能因 trafilatura 版本变化）
- [ ] 列表页 `discover_from_listing` 匹配规则可能需要适配牛客页面更新（`test_discover.py::test_extract_classic_discuss` 断言失败）

### 配置
- [ ] Langfuse 密钥补全（`.env` 中仍是占位符，仅影响 trace 可视化，不影响功能）
- [ ] Docker Compose 文件移除以弃用的 `version` 属性警告

### 功能增强
- [ ] A/B Prompt 测试（Day 13 文档）
- [ ] Scorer 质量分调优（Day 13 文档）
- [ ] 部署方案（Day 14 文档）
