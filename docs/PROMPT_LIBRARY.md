# InterviewLens Prompt 库

所有 LLM prompt 在此集中管理，**修改 prompt 必须升 `version`，并触发 `extract_version` 不一致的 posts 重抽**。

## 1. Extractor Prompt（v1）

**用途**：从清洗后的面经文本抽取结构化信息。

**模式**：DeepSeek Function Calling，强制返回如下 schema。

### 1.1 Function Schema

```json
{
  "name": "extract_interview_post",
  "description": "从面经文本中抽取公司、岗位、面试题目等结构化信息",
  "parameters": {
    "type": "object",
    "required": ["companies", "positions", "rounds"],
    "properties": {
      "companies": {
        "type": "array",
        "description": "面经涉及的公司名（原文出现的形式，不要规范化）",
        "items": {"type": "string"}
      },
      "positions": {
        "type": "array",
        "description": "面经涉及的岗位（原文形式）",
        "items": {"type": "string"}
      },
      "level": {
        "type": "string",
        "enum": ["实习", "校招", "社招", "未知"]
      },
      "interview_date": {
        "type": "string",
        "description": "面试时间，YYYY-MM 格式，无法判断填 null",
        "nullable": true
      },
      "rounds": {
        "type": "array",
        "description": "按面试轮次分组的题目",
        "items": {
          "type": "object",
          "required": ["round_no", "questions"],
          "properties": {
            "round_no": {"type": "integer"},
            "round_type": {
              "type": "string",
              "enum": ["技术一面", "技术二面", "技术三面", "HR面", "交叉面", "其他"]
            },
            "questions": {
              "type": "array",
              "items": {
                "type": "object",
                "required": ["content"],
                "properties": {
                  "content": {"type": "string", "description": "题目原文，保持完整"},
                  "category": {
                    "type": "string",
                    "enum": ["算法", "数据结构", "系统设计", "数据库", "操作系统", "网络", "语言基础", "项目", "HR", "其他"]
                  },
                  "answer_brief": {
                    "type": "string",
                    "description": "原帖给出的答案要点；没有则填 null",
                    "nullable": true
                  }
                }
              }
            }
          }
        }
      }
    }
  }
}
```

### 1.2 System Prompt

```
你是面经信息抽取助手。任务：从用户给的面经文本中抽取结构化信息。

铁律：
1. 不臆造内容。原文没说的字段一律填 null 或留空数组。
2. 公司/岗位名保持原文形式，不要主动规范化（这一步交给后续节点）。
3. 题目原文必须完整保留，不要总结、不要改写、不要合并。
4. 如果一段话明显是抒情/吐槽/无关内容，跳过不抽。
5. 答案要点（answer_brief）只在原帖明确给出时填写，不要替原帖编答案。

输出：调用 extract_interview_post 函数，参数严格符合 schema。
```

### 1.3 调用参数

- temperature: 0.1（首次）/ 0.0（重试）
- max_tokens: 4096
- 失败重试：JSON 解析失败 → 降温度 + 加一句"上一次返回不是合法 JSON，请严格输出"

---

## 2. Normalizer Prompt（v1）

**用途**：当 alias_dict 未命中、且 embedding 相似度 < 0.85 时，让 LLM 判断是否是已有 canonical 的别名，或新建 canonical。

```
判断"{alias}"在面经语境下指代的实体。

候选 canonical 列表（按 embedding 相似度排序的 top-5）：
{candidates}

请输出 JSON：
{
  "decision": "match" | "new",
  "canonical_id": <若 match，候选中的 id>,
  "canonical_name": <若 new，建议的规范名>,
  "confidence": 0.0-1.0,
  "reason": "<一句话理由>"
}

判断原则：
- "字节" / "Bytedance" / "ByteDance" → 字节跳动
- "抖音" / "TikTok" 单独出现也算字节跳动
- "鹅厂" → 腾讯；"猪厂" → 网易；"狼厂" → 百度
- "阿里" 默认指阿里巴巴集团；"淘天" / "蚂蚁" 应单独建 canonical
- 岗位"Java 后端" / "服务端" / "后台开发" → 后端开发
- 不确定时 confidence 低于 0.7，宁可新建不要错配
```

---

## 3. Aggregator Prompt（v1）

**用途**：对某 (公司, 岗位, 季度) 桶内 top-100 题目做摘要。

```
你是面试备考助手。基于以下 {n} 道{company}{position}的真实面试题（{period}），
总结高频考点并给出备考建议。

题目列表（含出现频次）：
{questions_with_freq}

输出 markdown，包含：

## 高频考点 Top 10
（按频次排序，每条引用 1-2 道原题作为示例，原题用 > 引用块）

## 重点考察方向
（3-5 个分类总结，例如"分布式锁实现细节"、"JVM GC 调优"）

## 易忽略的偏门题
（出现频次 1-2 但有特点的题目）

## 备考建议
（针对该公司该岗位的针对性建议，3-5 条）

铁律：
1. 所有"高频考点"必须有原题支撑，不要空谈。
2. 不要编造题目；引用原题必须来自给定列表。
3. 备考建议要具体到技术点，不要"多刷算法"这种废话。
```

---

## 4. Scorer 评分规则（非 LLM，纯函数）

```python
def score_post(post) -> int:
    score = 0
    # 题量 (0-30)
    n_questions = sum(len(r.questions) for r in post.rounds)
    score += min(n_questions * 3, 30)

    # 含答案 (0-20)
    n_with_answer = sum(1 for r in post.rounds for q in r.questions if q.answer_brief)
    score += min(n_with_answer * 4, 20)

    # 轮次完整度 (0-20)
    n_rounds = len(post.rounds)
    score += min(n_rounds * 7, 20)

    # 时间衰减 (0-30)
    if post.posted_at:
        months_ago = (now - post.posted_at).days / 30
        if months_ago <= 3:   score += 30
        elif months_ago <= 6: score += 25
        elif months_ago <= 12: score += 15
        elif months_ago <= 24: score += 8
        else: score += 0

    return min(score, 100)
```

---

## 5. Prompt 版本管理

| Prompt | 当前版本 | 更新时间 | 变更说明 |
|---|---|---|---|
| Extractor | v1 | 2026-06-02 | 初版 |
| Normalizer | v1 | 2026-06-02 | 初版 |
| Aggregator | v1 | 2026-06-02 | 初版 |

**升级流程**：
1. 在本文档新增 v(n+1) 章节，保留旧版本可对比
2. 代码 `EXTRACT_PROMPT_VERSION = 2`
3. 启动批量任务：`UPDATE posts SET extract_status='pending' WHERE extract_version < 2`
4. Celery 自动重抽
